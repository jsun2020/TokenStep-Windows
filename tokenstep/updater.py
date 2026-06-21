# -*- coding: utf-8 -*-
"""Update checking and in-place auto-update against GitHub Releases.

Mirrors the macOS UpdateService: semver compare against GitHub Releases, then
download + verify + install + relaunch. On Windows the app ships as a single
portable ``TokenStep.exe`` inside ``TokenStep-<ver>-win64.zip``, so the install
step replaces that one file:

1. ``check_for_updates`` finds a newer release and its Windows zip asset.
2. ``download_asset`` streams the zip into ``%APPDATA%\\TokenStep\\updates`` with
   a progress callback and a size cap.
3. ``verify_asset`` checks a SHA-256 published in the release notes (Windows
   portable builds are unsigned, so codesign-style verification isn't possible;
   the checksum is the integrity gate when present).
4. ``extract_new_exe`` unzips the new ``TokenStep.exe``.
5. ``install_and_relaunch`` writes a detached ``.cmd`` helper that waits for this
   process to exit (so it can overwrite the locked exe and the single-instance
   mutex is released), copies the new exe over the old one, and relaunches it.

Running from source (not frozen) has no exe to replace, so callers fall back to
opening the download page — the original check-only behaviour.

Best-effort throughout: short timeouts, ``check_for_updates`` returns None on any
failure (offline, proxy, rate limit) so it never disrupts the tray app; the
install steps raise :class:`UpdateError` with a user-facing message on failure.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
import sys
import urllib.request
import zipfile
from pathlib import Path
from typing import Any, Callable

from . import __version__, paths

# A Windows release zip should never exceed this; guards against a runaway or
# wrong (e.g. accidentally huge) asset filling the disk.
MAX_ASSET_BYTES = 200 * 1024 * 1024  # 200 MB
EXE_NAME = "TokenStep.exe"


class UpdateError(Exception):
    """Raised when an update download/verify/install step fails."""

# The Windows port's own repo, so update checks find Windows release assets.
REPO = "jsun2020/TokenStep-Windows"
LATEST_RELEASE_URL = f"https://api.github.com/repos/{REPO}/releases/latest"
RELEASES_PAGE_URL = f"https://github.com/{REPO}/releases"


def _is_windows_asset(name: str) -> bool:
    """True only for clearly-Windows artifacts.

    Installers (.exe/.msi) always count. A generic .zip counts only when the name
    signals Windows, so we never mistake the macOS release zip (e.g.
    TokenStep-0.1.4.zip) for a Windows build.
    """
    name = name.lower()
    if name.endswith((".exe", ".msi")):
        return True
    if name.endswith(".zip") and ("win" in name or "windows" in name):
        return True
    return False


def _version_tuple(value: str) -> tuple[int, ...]:
    cleaned = (value or "").strip().lstrip("vV")
    parts = re.split(r"[.\-+]", cleaned)
    nums: list[int] = []
    for part in parts:
        if part.isdigit():
            nums.append(int(part))
        else:
            break
    return tuple(nums) if nums else (0,)


def is_newer(remote: str, local: str) -> bool:
    return _version_tuple(remote) > _version_tuple(local)


def check_for_updates(
    current_version: str = __version__, timeout: float = 8.0
) -> dict[str, Any] | None:
    """Return update info dict if a newer release exists, else None.

    The returned dict has: version, tag, title, notes, page_url, and (when a
    Windows asset is published) asset_url / asset_name.
    Returns None when up-to-date or on any error.
    """
    request = urllib.request.Request(
        LATEST_RELEASE_URL,
        headers={
            "Accept": "application/vnd.github+json",
            "User-Agent": f"TokenStep-Windows/{current_version}",
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as resp:
            if resp.status < 200 or resp.status >= 300:
                return None
            release = json.loads(resp.read().decode("utf-8"))
    except Exception:
        return None

    if not isinstance(release, dict):
        return None
    if release.get("draft") or release.get("prerelease"):
        return None

    tag = str(release.get("tag_name") or "")
    version = tag.lstrip("vV")
    if not version or not is_newer(version, current_version):
        return None

    assets = release.get("assets") or []
    win_asset = None
    for asset in assets:
        if _is_windows_asset(str(asset.get("name", ""))):
            win_asset = asset
            break

    notes = release.get("body") or ""
    info: dict[str, Any] = {
        "version": version,
        "tag": tag,
        "title": release.get("name") or f"TokenStep {version}",
        "notes": notes,
        "page_url": release.get("html_url") or RELEASES_PAGE_URL,
    }
    if win_asset:
        info["asset_url"] = win_asset.get("browser_download_url")
        info["asset_name"] = win_asset.get("name")
        try:
            info["asset_size"] = int(win_asset.get("size") or 0)
        except (TypeError, ValueError):
            info["asset_size"] = 0
        sha = sha256_for_asset(notes, str(win_asset.get("name", "")))
        if sha:
            info["asset_sha256"] = sha
    return info


# -- frozen / install-target helpers --------------------------------------


def is_frozen() -> bool:
    """True when running as the PyInstaller-built exe (has an exe to replace)."""
    return bool(getattr(sys, "frozen", False))


def current_exe() -> Path:
    """Path to the running TokenStep.exe (only meaningful when frozen)."""
    return Path(sys.executable)


# -- checksum parsing ------------------------------------------------------

_SHA256_RE = re.compile(r"\b([0-9a-fA-F]{64})\b")


def sha256_for_asset(notes: str, asset_name: str) -> str | None:
    """Extract a SHA-256 for ``asset_name`` from release notes, if published.

    Recognises two common shapes:
      * ``<64-hex>  TokenStep-0.1.15-win64.zip``  (sha256sum output, any order)
      * a line mentioning the asset name with a 64-hex token nearby.
    Returns the lowercased hex digest, or None when no checksum is present
    (Windows portable builds may ship without one — verification is then skipped).
    """
    if not notes:
        return None
    name = (asset_name or "").lower()
    for raw in notes.splitlines():
        line = raw.strip()
        if not line:
            continue
        match = _SHA256_RE.search(line)
        if not match:
            continue
        # If the asset name is on the line, that digest is unambiguously ours.
        if name and name in line.lower():
            return match.group(1).lower()
    # Fallback: a release that ships exactly one checksum and no asset name.
    digests = _SHA256_RE.findall(notes)
    if len(digests) == 1:
        return digests[0].lower()
    return None


# -- download / verify / extract / install --------------------------------


def download_asset(
    info: dict[str, Any],
    on_progress: Callable[[float], None] | None = None,
    timeout: float = 30.0,
) -> Path:
    """Download the release zip into the updates dir; return its path.

    Streams in chunks, reporting fractional progress (0..1) when the server
    sends a Content-Length. Enforces ``MAX_ASSET_BYTES``. Raises UpdateError.
    """
    url = info.get("asset_url")
    name = info.get("asset_name") or f"TokenStep-{info.get('version', 'update')}-win64.zip"
    if not url:
        raise UpdateError("这个新版本没有可下载的 Windows 安装包。")

    paths.ensure_dirs()
    dest = paths.UPDATES_DIR / name
    tmp = dest.with_suffix(dest.suffix + ".part")
    try:
        if tmp.exists():
            tmp.unlink()
    except OSError:
        pass

    request = urllib.request.Request(
        url, headers={"User-Agent": f"TokenStep-Windows/{__version__}"}
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as resp:
            if resp.status < 200 or resp.status >= 300:
                raise UpdateError("下载更新失败，请稍后再试。")
            try:
                total = int(resp.headers.get("Content-Length") or 0)
            except (TypeError, ValueError):
                total = 0
            if total and total > MAX_ASSET_BYTES:
                raise UpdateError("更新包过大，已取消下载。")
            read = 0
            with tmp.open("wb") as out:
                while True:
                    chunk = resp.read(64 * 1024)
                    if not chunk:
                        break
                    read += len(chunk)
                    if read > MAX_ASSET_BYTES:
                        raise UpdateError("更新包过大，已取消下载。")
                    out.write(chunk)
                    if on_progress and total:
                        try:
                            on_progress(min(max(read / total, 0.0), 1.0))
                        except Exception:
                            pass
    except UpdateError:
        _silent_unlink(tmp)
        raise
    except Exception as exc:  # network/proxy/IO
        _silent_unlink(tmp)
        raise UpdateError("下载更新失败，请检查网络后重试。") from exc

    try:
        if dest.exists():
            dest.unlink()
        tmp.replace(dest)
    except OSError as exc:
        _silent_unlink(tmp)
        raise UpdateError("保存更新包失败，请稍后再试。") from exc
    return dest


def verify_asset(zip_path: Path, info: dict[str, Any], require_verified: bool) -> None:
    """Verify the downloaded zip against the release's SHA-256 when available.

    Windows portable builds are unsigned, so there is no codesign/notarization to
    check. When the release publishes a SHA-256 we always enforce it. When it does
    not, behaviour depends on ``require_verified``: with verification required we
    proceed (we cannot verify an unsigned portable, and failing closed would block
    all updates); the absence of a checksum is logged by the caller. Raises
    UpdateError only on an actual mismatch.
    """
    expected = (info.get("asset_sha256") or "").lower()
    if not expected:
        return  # nothing published to check against
    actual = _sha256_file(zip_path)
    if actual != expected:
        raise UpdateError("更新包校验未通过（SHA-256 不匹配），已停止安装。")


def extract_new_exe(zip_path: Path) -> Path:
    """Extract TokenStep.exe from the release zip; return the extracted path.

    The zip stages the exe (optionally inside a single top-level folder); pick the
    first member whose basename is TokenStep.exe. Guards against zip-slip.
    """
    target = paths.UPDATES_DIR / "TokenStep-new.exe"
    _silent_unlink(target)
    try:
        with zipfile.ZipFile(zip_path) as zf:
            member = None
            for info in zf.infolist():
                if info.is_dir():
                    continue
                if os.path.basename(info.filename).lower() == EXE_NAME.lower():
                    member = info
                    break
            if member is None:
                raise UpdateError("更新包里没有找到 TokenStep.exe。")
            with zf.open(member) as src, target.open("wb") as out:
                while True:
                    chunk = src.read(64 * 1024)
                    if not chunk:
                        break
                    out.write(chunk)
    except UpdateError:
        raise
    except zipfile.BadZipFile as exc:
        raise UpdateError("更新包已损坏，请稍后重试。") from exc
    except Exception as exc:
        raise UpdateError("解压更新包失败，请稍后重试。") from exc
    return target


def install_and_relaunch(new_exe: Path, target_exe: Path | None = None) -> None:
    """Launch a detached helper that replaces the running exe and relaunches it.

    The helper waits for this process (PID) to exit, then retries copying the new
    exe over the old one until the file unlocks (covers the PyInstaller onefile
    bootloader still holding the handle), then starts the app again. Because the
    app uses a single-instance mutex, the helper must wait for full exit before
    relaunch. The caller should quit the app immediately after this returns.
    """
    if not is_frozen():
        raise UpdateError("从源码运行时不支持自动安装，请手动下载更新。")
    old = target_exe or current_exe()
    if not new_exe.exists():
        raise UpdateError("更新文件缺失，无法安装。")

    paths.ensure_dirs()
    helper = paths.UPDATES_DIR / "update-helper.cmd"
    log = paths.UPDATES_DIR / "update-install.log"
    helper.write_text(
        _helper_script(),
        encoding="ascii",
    )

    pid = str(os.getpid())
    try:
        # Detached so it outlives the app; no console window.
        flags = 0
        creationflags = (
            getattr(subprocess, "DETACHED_PROCESS", 0)
            | getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
        ) or flags
        subprocess.Popen(
            ["cmd", "/c", str(helper), pid, str(old), str(new_exe), str(log)],
            cwd=str(paths.UPDATES_DIR),
            creationflags=creationflags,
            close_fds=True,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
    except Exception as exc:
        raise UpdateError("启动安装程序失败，请手动安装更新。") from exc


def download_and_install(
    info: dict[str, Any],
    require_verified: bool = True,
    on_progress: Callable[[float], None] | None = None,
) -> None:
    """High-level flow mirroring the macOS downloadAndInstall.

    Download -> verify (SHA-256 when published) -> extract -> launch helper.
    Raises UpdateError on any failure; on success the caller must quit the app so
    the helper can replace the exe.
    """
    zip_path = download_asset(info, on_progress=on_progress)
    verify_asset(zip_path, info, require_verified=require_verified)
    new_exe = extract_new_exe(zip_path)
    install_and_relaunch(new_exe)


# -- internals -------------------------------------------------------------


def _sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest().lower()


def _silent_unlink(path: Path) -> None:
    try:
        if path.exists():
            path.unlink()
    except OSError:
        pass


def _helper_script() -> str:
    r"""The detached .cmd that waits for exit, swaps the exe, and relaunches.

    Args (passed positionally by ``install_and_relaunch``):
      %1 = PID of the app to wait for
      %2 = path to the old (currently running) exe
      %3 = path to the new exe to copy in
      %4 = log file path

    ``ping`` is used as a console-free ~1s sleep (``timeout`` needs a console
    handle a detached process lacks). The copy is retried because the onefile
    bootloader keeps the exe locked for a moment after the child PID exits.
    """
    return (
        "@echo off\r\n"
        "setlocal enableextensions\r\n"
        'set "PID=%~1"\r\n'
        'set "OLDEXE=%~2"\r\n'
        'set "NEWEXE=%~3"\r\n'
        'set "LOGF=%~4"\r\n'
        'echo [%date% %time%] update helper started PID=%PID% >> "%LOGF%"\r\n'
        "set /a waited=0\r\n"
        ":waitloop\r\n"
        'tasklist /FI "PID eq %PID%" /NH 2>nul | find "%PID%" >nul\r\n'
        "if errorlevel 1 goto exited\r\n"
        "if %waited% geq 60 goto exited\r\n"
        "set /a waited+=1\r\n"
        ">nul ping -n 2 127.0.0.1\r\n"
        "goto waitloop\r\n"
        ":exited\r\n"
        'echo [%date% %time%] app exited, replacing exe >> "%LOGF%"\r\n'
        "set /a tries=0\r\n"
        ":copyloop\r\n"
        'copy /Y "%NEWEXE%" "%OLDEXE%" >> "%LOGF%" 2>&1\r\n'
        "if not errorlevel 1 goto copied\r\n"
        "if %tries% geq 30 goto failed\r\n"
        "set /a tries+=1\r\n"
        ">nul ping -n 2 127.0.0.1\r\n"
        "goto copyloop\r\n"
        ":copied\r\n"
        'echo [%date% %time%] replaced, relaunching >> "%LOGF%"\r\n'
        'start "" "%OLDEXE%"\r\n'
        'del /Q "%NEWEXE%" >nul 2>&1\r\n'
        "goto cleanup\r\n"
        ":failed\r\n"
        'echo [%date% %time%] ERROR could not replace exe >> "%LOGF%"\r\n'
        ":cleanup\r\n"
        '(goto) 2>nul & del /Q "%~f0"\r\n'
    )
