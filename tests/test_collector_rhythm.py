# -*- coding: utf-8 -*-
"""Tests for the daily rhythm computation (hourly buckets + pattern classifier).

macOS 0.1.42 parity: ports RhythmAccumulator / DailyRhythm / RhythmTag from the
Swift collector. Verifies bucketing from per-record timestamps and the 10-way
pattern classifier (double-peak, night-agent, one-shot, quiet-day, etc.).

No pytest dependency. Run with:
    python -m tests.test_collector_rhythm
    python tests/test_collector_rhythm.py
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from tokenstep import collector  # noqa: E402


def _hourly(pairs: dict[int, int]) -> list[int]:
    buckets = [0] * 24
    for hour, tokens in pairs.items():
        buckets[hour] = tokens
    return buckets


def test_buckets_and_peak_from_records() -> None:
    collector.configure_timezone("UTC")
    records = [
        {"timestamp": "2026-06-22T09:00:00Z", "date": "2026-06-22",
         "usage": {"total_tokens": 100}},
        {"timestamp": "2026-06-22T09:30:00Z", "date": "2026-06-22",
         "usage": {"total_tokens": 50}},
        {"timestamp": "2026-06-22T17:00:00Z", "date": "2026-06-22",
         "usage": {"total_tokens": 300}},
        # zero-token and timestamp-less records are ignored
        {"timestamp": "2026-06-22T03:00:00Z", "date": "2026-06-22",
         "usage": {"total_tokens": 0}},
        {"timestamp": None, "date": "2026-06-22", "usage": {"total_tokens": 999}},
    ]
    rhythms = collector.compute_rhythms(records)
    assert len(rhythms) == 1, rhythms
    r = rhythms[0]
    assert r["buckets"][9] == 150, r["buckets"]
    assert r["buckets"][17] == 300, r["buckets"]
    assert r["total_tokens"] == 450, r
    assert r["peak_hour"] == 17, r
    assert r["peak_tokens"] == 300, r


def test_double_peak_classification() -> None:
    # Two strong peaks >= 4 hours apart -> 双峰推进型.
    r = collector.compute_daily_rhythm(
        "2026-06-22", _hourly({9: 2800, 10: 1200, 13: 800, 17: 2845, 18: 1000})
    )
    assert r["primary_tag"] == "double_peak", r
    assert r["title"] == "双峰推进型", r
    assert r["peak_hour"] == 17, r


def test_one_shot_classification() -> None:
    # A single hour holding >= 50% of the day's tokens -> 一波流型.
    r = collector.compute_daily_rhythm("2026-06-22", _hourly({14: 9000, 15: 500}))
    assert r["primary_tag"] == "one_shot", r


def test_night_agent_classification() -> None:
    # Heavy contiguous late-night usage (no second far-apart peak) -> 夜间 Agent 型.
    r = collector.compute_daily_rhythm(
        "2026-06-22", _hourly({21: 2000, 22: 3000, 23: 3000})
    )
    assert r["primary_tag"] == "night_agent", r


def test_quiet_day_for_empty() -> None:
    r = collector.compute_daily_rhythm("2026-06-22", [0] * 24)
    assert r["primary_tag"] == "quiet_day", r
    assert r["total_tokens"] == 0, r
    assert r["peak_hour"] is None, r
    assert r["longest_streak"] == 0, r


def test_night_share_uses_raw_buckets() -> None:
    # 夜间占比 = (21-23 + 0-2) / total over RAW buckets. Here 2000 of 10000 -> 20%.
    r = collector.compute_daily_rhythm(
        "2026-06-22", _hourly({22: 1000, 1: 1000, 14: 8000})
    )
    assert abs(r["night_share"] - 0.20) < 1e-9, r["night_share"]


def test_active_hours_threshold_and_streak() -> None:
    # threshold = max(total*0.03, peak*0.30); tiny buckets below it are not active.
    r = collector.compute_daily_rhythm(
        "2026-06-22", _hourly({9: 1000, 10: 1000, 11: 1000, 20: 5})
    )
    # peak 1000 -> threshold = max(90.15, 300) = 300; the hour with 5 is below it.
    assert r["active_hours"] == 3, r
    assert r["longest_streak"] == 3, r
    assert r["first_active_hour"] == 9, r
    assert r["last_active_hour"] == 11, r


def test_yesterday_rhythm_fallback() -> None:
    # An empty snapshot still yields a renderable quiet-day rhythm for yesterday.
    r = collector.yesterday_rhythm({"rhythms": []})
    assert r["primary_tag"] == "quiet_day", r
    assert r["buckets"] == [0] * 24, r


def _runner() -> int:
    tests = [
        (n, f) for n, f in sorted(globals().items())
        if n.startswith("test_") and callable(f)
    ]
    failed = 0
    for name, fn in tests:
        try:
            fn()
            print(f"PASS {name}")
        except Exception as exc:  # noqa: BLE001
            failed += 1
            print(f"FAIL {name}: {exc!r}")
    print(f"\n{len(tests) - failed}/{len(tests)} passed")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(_runner())
