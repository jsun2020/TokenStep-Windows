# -*- coding: utf-8 -*-
"""Self-contained tests for the auto-updater pure logic.

No pytest dependency (the project ships dependency-light): run directly with
    python -m tests.test_updater
or
    python tests/test_updater.py
Exits non-zero on the first failed assertion.
"""
from __future__ import annotations

import hashlib
import io
import os
import sys
import zipfile
from pathlib import Path

# Allow running as a bare script (python tests/test_updater.py).
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from tokenstep import updater  # noqa: E402


def test_version_compare() -> None:
    assert updater.is_newer("0.1.15", "0.1.14")
    assert updater.is_newer("0.2.0", "0.1.99")
    assert not updater.is_newer("0.1.14", "0.1.14")
    assert not updater.is_newer("0.1.13", "0.1.14")
    # v-prefix and noise tolerated.
    assert updater.is_newer("v0.1.15", "0.1.14")


def test_windows_asset_detection() -> None:
    assert updater._is_windows_asset("TokenStep-0.1.15-win64.zip")
    assert updater._is_windows_asset("Setup.exe")
    assert updater._is_windows_asset("installer.msi")
    # A bare zip without a Windows marker must NOT match (mac release zip).
    assert not updater._is_windows_asset("TokenStep-0.1.15.zip")
    assert not updater._is_windows_asset("TokenStep-0.1.15.dmg")


def test_sha256_parsing_with_asset_name() -> None:
    digest = "a" * 64
    notes = f"""## TokenStep for Windows v0.1.15

### SHA-256
```
{digest}  TokenStep-0.1.15-win64.zip
```
"""
    got = updater.sha256_for_asset(notes, "TokenStep-0.1.15-win64.zip")
    assert got == digest, got


def test_sha256_single_digest_fallback() -> None:
    digest = "b" * 64
    notes = f"checksum: {digest}"
    # No asset name on a matching line, but exactly one digest in the notes.
    assert updater.sha256_for_asset(notes, "whatever.zip") == digest


def test_sha256_absent_returns_none() -> None:
    assert updater.sha256_for_asset("no checksum here", "x.zip") is None
    assert updater.sha256_for_asset("", "x.zip") is None
    # Two digests, neither tied to the asset name -> ambiguous -> None.
    notes = f"{'c' * 64}\n{'d' * 64}"
    assert updater.sha256_for_asset(notes, "x.zip") is None


def test_verify_asset(tmp: Path) -> None:
    payload = b"hello tokenstep"
    f = tmp / "pkg.zip"
    f.write_bytes(payload)
    sha = hashlib.sha256(payload).hexdigest()

    # Matching checksum passes.
    updater.verify_asset(f, {"asset_sha256": sha}, require_verified=True)
    # No checksum published -> skipped (no raise), even when verification required.
    updater.verify_asset(f, {}, require_verified=True)
    # Mismatch always raises.
    try:
        updater.verify_asset(f, {"asset_sha256": "f" * 64}, require_verified=False)
    except updater.UpdateError:
        pass
    else:
        raise AssertionError("mismatched sha256 should raise UpdateError")


def test_extract_new_exe(tmp: Path, monkeypatch) -> None:
    # Point the updater's UPDATES_DIR at the temp dir.
    monkeypatch_updates_dir(tmp)
    zip_path = tmp / "TokenStep-0.1.15-win64.zip"
    with zipfile.ZipFile(zip_path, "w") as zf:
        zf.writestr("TokenStep-0.1.15-win64/TokenStep.exe", b"MZnewbinary")
        zf.writestr("TokenStep-0.1.15-win64/README.md", b"readme")
    out = updater.extract_new_exe(zip_path)
    assert out.exists()
    assert out.read_bytes() == b"MZnewbinary"


def test_extract_missing_exe_raises(tmp: Path) -> None:
    monkeypatch_updates_dir(tmp)
    zip_path = tmp / "bad.zip"
    with zipfile.ZipFile(zip_path, "w") as zf:
        zf.writestr("README.md", b"no exe here")
    try:
        updater.extract_new_exe(zip_path)
    except updater.UpdateError:
        pass
    else:
        raise AssertionError("missing TokenStep.exe should raise UpdateError")


def test_helper_script_shape() -> None:
    script = updater._helper_script()
    # Console-free sleep (a detached process has no console for `timeout`).
    assert "ping -n 2 127.0.0.1" in script
    assert "timeout" not in script
    # Waits, copies, relaunches, self-deletes.
    assert "tasklist" in script
    assert 'copy /Y "%NEWEXE%" "%OLDEXE%"' in script
    assert 'start "" "%OLDEXE%"' in script
    assert 'del /Q "%~f0"' in script
    # CRLF line endings for cmd.exe.
    assert "\r\n" in script
    # Pure ASCII (CLAUDE.md: no non-ASCII in shell literals on Windows).
    script.encode("ascii")


# -- tiny harness ----------------------------------------------------------


class _Monkey:
    def __init__(self) -> None:
        self._undo = []

    def setattr(self, obj, name, value):
        self._undo.append((obj, name, getattr(obj, name)))
        setattr(obj, name, value)

    def undo(self):
        for obj, name, old in reversed(self._undo):
            setattr(obj, name, old)
        self._undo.clear()


_ACTIVE_MONKEY: _Monkey | None = None


def monkeypatch_updates_dir(tmp: Path) -> None:
    assert _ACTIVE_MONKEY is not None
    _ACTIVE_MONKEY.setattr(updater.paths, "UPDATES_DIR", tmp)


def _run() -> int:
    import inspect
    import tempfile

    global _ACTIVE_MONKEY
    tests = [
        (name, fn)
        for name, fn in sorted(globals().items())
        if name.startswith("test_") and callable(fn)
    ]
    failed = 0
    for name, fn in tests:
        params = inspect.signature(fn).parameters
        monkey = _Monkey()
        _ACTIVE_MONKEY = monkey
        try:
            with tempfile.TemporaryDirectory() as d:
                kwargs = {}
                if "tmp" in params:
                    kwargs["tmp"] = Path(d)
                if "monkeypatch" in params:
                    kwargs["monkeypatch"] = monkey
                fn(**kwargs)
            print(f"PASS {name}")
        except Exception as exc:  # noqa: BLE001
            failed += 1
            print(f"FAIL {name}: {exc!r}")
        finally:
            monkey.undo()
            _ACTIVE_MONKEY = None
    print(f"\n{len(tests) - failed}/{len(tests)} passed")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(_run())
