# -*- coding: utf-8 -*-
"""Update checking against GitHub Releases.

Mirrors the macOS UpdateService check logic (semver compare against GitHub
Releases) against this Windows port's own repo, but is **check-only** on Windows:
it never silently downloads or installs an .exe. If
a newer release exists it surfaces a notification and a link to the download page,
leaving the actual install to the user. This is the safe Windows equivalent of the
Mac auto-updater.

Best-effort: short timeout, returns None on any failure (offline, proxy, rate
limit) so it never disrupts the tray app.
"""
from __future__ import annotations

import json
import re
import urllib.request
from typing import Any

from . import __version__

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

    info: dict[str, Any] = {
        "version": version,
        "tag": tag,
        "title": release.get("name") or f"TokenStep {version}",
        "notes": release.get("body") or "",
        "page_url": release.get("html_url") or RELEASES_PAGE_URL,
    }
    if win_asset:
        info["asset_url"] = win_asset.get("browser_download_url")
        info["asset_name"] = win_asset.get("name")
    return info
