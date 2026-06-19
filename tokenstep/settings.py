# -*- coding: utf-8 -*-
"""User settings (daily goal, refresh interval, history window, timezone).

Matches the macOS TokenStepSettings model so the same settings.json shape works
across platforms.
"""
from __future__ import annotations

import json
from typing import Any

from . import paths

DEFAULTS: dict[str, Any] = {
    "daily_goal_tokens": 100_000_000,
    "refresh_interval_seconds": 60,
    "history_days": 180,
    "timezone": "Asia/Shanghai",
    # Update checking (mirrors the macOS settings shape).
    "auto_update_enabled": True,
    "ask_before_downloading_updates": True,
    "require_verified_updates": True,
    "skipped_update_version": None,
}

VALID_INTERVALS = {0, 60, 300, 900}
_BOOL_KEYS = ("auto_update_enabled", "ask_before_downloading_updates", "require_verified_updates")


def normalize(raw: dict[str, Any] | None) -> dict[str, Any]:
    out = dict(DEFAULTS)
    if isinstance(raw, dict):
        for key in DEFAULTS:
            if key in raw and raw[key] is not None:
                out[key] = raw[key]
            elif key == "skipped_update_version" and key in raw:
                out[key] = raw[key]  # explicit null allowed
    try:
        out["daily_goal_tokens"] = max(1_000_000, int(out["daily_goal_tokens"]))
    except Exception:
        out["daily_goal_tokens"] = DEFAULTS["daily_goal_tokens"]
    if out["refresh_interval_seconds"] not in VALID_INTERVALS:
        out["refresh_interval_seconds"] = 60
    try:
        out["history_days"] = min(365, max(7, int(out["history_days"])))
    except Exception:
        out["history_days"] = DEFAULTS["history_days"]
    if not isinstance(out["timezone"], str) or not out["timezone"]:
        out["timezone"] = DEFAULTS["timezone"]
    for key in _BOOL_KEYS:
        out[key] = bool(out[key])
    sv = out.get("skipped_update_version")
    out["skipped_update_version"] = sv if (sv is None or isinstance(sv, str)) else None
    return out


def load() -> dict[str, Any]:
    try:
        with paths.SETTINGS_JSON.open("r", encoding="utf-8") as f:
            return normalize(json.load(f))
    except Exception:
        return dict(DEFAULTS)


def save(settings: dict[str, Any]) -> dict[str, Any]:
    paths.ensure_dirs()
    data = normalize(settings)
    tmp = paths.SETTINGS_JSON.with_suffix(".json.tmp")
    tmp.write_text(
        json.dumps(data, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8"
    )
    tmp.replace(paths.SETTINGS_JSON)
    return data
