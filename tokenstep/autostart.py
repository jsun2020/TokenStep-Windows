# -*- coding: utf-8 -*-
"""Windows autostart via the per-user Run registry key.

Adds HKCU\\Software\\Microsoft\\Windows\\CurrentVersion\\Run\\TokenStep so the
tray app launches at login. Works for both the frozen .exe build and the
dev (pythonw + script) layout.
"""
from __future__ import annotations

import os
import sys

try:
    import winreg
except ImportError:  # non-Windows, for import safety
    winreg = None  # type: ignore[assignment]

RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
VALUE_NAME = "TokenStep"


def _launch_command() -> str:
    if getattr(sys, "frozen", False):
        return f'"{sys.executable}"'
    # Dev layout: prefer pythonw.exe (no console window) running the entry script.
    exe_dir = os.path.dirname(sys.executable)
    pythonw = os.path.join(exe_dir, "pythonw.exe")
    interpreter = pythonw if os.path.exists(pythonw) else sys.executable
    script = os.path.abspath(
        os.path.join(os.path.dirname(__file__), os.pardir, "tokenstep_app.py")
    )
    return f'"{interpreter}" "{script}"'


def is_enabled() -> bool:
    if winreg is None:
        return False
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY) as key:
            value, _ = winreg.QueryValueEx(key, VALUE_NAME)
            return bool(value)
    except FileNotFoundError:
        return False
    except OSError:
        return False


def set_enabled(enable: bool) -> None:
    if winreg is None:
        return
    with winreg.CreateKey(winreg.HKEY_CURRENT_USER, RUN_KEY) as key:
        if enable:
            winreg.SetValueEx(key, VALUE_NAME, 0, winreg.REG_SZ, _launch_command())
        else:
            try:
                winreg.DeleteValue(key, VALUE_NAME)
            except FileNotFoundError:
                pass


def toggle() -> bool:
    new_state = not is_enabled()
    set_enabled(new_state)
    return is_enabled()
