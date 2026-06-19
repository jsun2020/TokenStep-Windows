# -*- coding: utf-8 -*-
"""Filesystem locations for TokenStep on Windows.

Mirrors the macOS layout (~/Library/Application Support/TokenStep) using the
Windows equivalent: %APPDATA%\\TokenStep.
"""
from __future__ import annotations

import os
from pathlib import Path

APP_NAME = "TokenStep"


def _appdata_root() -> Path:
    base = os.environ.get("APPDATA")
    if base:
        return Path(base) / APP_NAME
    # Fallback for unusual environments.
    return Path.home() / "AppData" / "Roaming" / APP_NAME


ROOT = _appdata_root()
DATA_DIR = ROOT / "data"
DATA_JSON = DATA_DIR / "usage.json"
DASHBOARD_HTML = ROOT / "dashboard.html"
CONFIG_DIR = ROOT / "config"
SETTINGS_JSON = CONFIG_DIR / "settings.json"
PRICING_JSON = CONFIG_DIR / "pricing.json"
CACHE_DIR = ROOT / "cache"
COLLECTOR_CACHE_JSON = CACHE_DIR / "collector-cache.json"
LOGS_DIR = ROOT / "logs"
ERROR_LOG = LOGS_DIR / "tokenstep.log"


def ensure_dirs() -> None:
    for directory in (DATA_DIR, CONFIG_DIR, CACHE_DIR, LOGS_DIR):
        directory.mkdir(parents=True, exist_ok=True)
