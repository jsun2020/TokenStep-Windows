# -*- coding: utf-8 -*-
"""Tests for the CC Switch Proxy data source and history-window cutoff.

No pytest dependency. Run with:
    python -m tests.test_collector_ccswitch
    python tests/test_collector_ccswitch.py
"""
from __future__ import annotations

import datetime as dt
import os
import sqlite3
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from tokenstep import collector  # noqa: E402

# Full schema CC Switch exposes (we only need the required subset, but build the
# realistic table so the schema check passes).
_COLUMNS = [
    "request_id",
    "app_type",
    "provider_id",
    "model",
    "request_model",
    "pricing_model",
    "input_tokens",
    "output_tokens",
    "cache_read_tokens",
    "cache_creation_tokens",
    "total_cost_usd",
    "status_code",
    "created_at",
    "data_source",
]


def _make_db(path: Path, rows: list[dict]) -> None:
    con = sqlite3.connect(path)
    cols_sql = ", ".join(f"{c}" for c in _COLUMNS)
    con.execute(f"create table proxy_request_logs ({cols_sql})")
    placeholders = ", ".join("?" for _ in _COLUMNS)
    for r in rows:
        con.execute(
            f"insert into proxy_request_logs ({', '.join(_COLUMNS)}) values ({placeholders})",
            tuple(r.get(c) for c in _COLUMNS),
        )
    con.commit()
    con.close()


def _row(**kw) -> dict:
    base = {
        "request_id": "r1",
        "app_type": "claude",
        "provider_id": "p1",
        "model": "claude-sonnet",
        "request_model": "claude-sonnet",
        "pricing_model": "claude-sonnet",
        "input_tokens": 100,
        "output_tokens": 50,
        "cache_read_tokens": 0,
        "cache_creation_tokens": 0,
        "total_cost_usd": 0.0,
        "status_code": 200,
        "created_at": 1_700_000_000,  # epoch seconds
        "data_source": "proxy",
    }
    base.update(kw)
    return base


def test_tool_name_mapping() -> None:
    assert collector._cc_switch_tool_name("claude") == "Claude Code via CC Switch"
    assert collector._cc_switch_tool_name("codex") == "Codex via CC Switch"
    assert collector._cc_switch_tool_name("gemini") == "Gemini via CC Switch"
    assert collector._cc_switch_tool_name("CLAUDE") == "Claude Code via CC Switch"
    assert collector._cc_switch_tool_name("qwen") == "qwen via CC Switch (experimental)"
    assert collector._cc_switch_tool_name(None) == "unknown via CC Switch (experimental)"
    assert collector._cc_switch_tool_name("") == "unknown via CC Switch (experimental)"


def test_missing_db_is_graceful() -> None:
    records, meta = collector.collect_cc_switch_proxy(Path("Z:/nope/cc-switch.db"))
    assert records == []
    assert meta["status"] == "missing_db"


def test_schema_mismatch(tmp: Path) -> None:
    db = tmp / "bad.db"
    con = sqlite3.connect(db)
    con.execute("create table proxy_request_logs (request_id, created_at)")
    con.commit()
    con.close()
    records, meta = collector.collect_cc_switch_proxy(db)
    assert records == []
    assert meta["status"] == "schema_mismatch"


def test_basic_collection_and_filters(tmp: Path) -> None:
    db = tmp / "cc.db"
    _make_db(
        db,
        [
            _row(request_id="ok1", app_type="claude", input_tokens=100, output_tokens=50,
                 total_cost_usd=0.25),
            _row(request_id="ok2", app_type="codex", input_tokens=10, output_tokens=0,
                 cache_read_tokens=5, total_cost_usd=0.01),
            # filtered: non-proxy data_source
            _row(request_id="x1", data_source="aggregated"),
            # filtered: error status
            _row(request_id="x2", status_code=500),
            # filtered: zero tokens
            _row(request_id="x3", input_tokens=0, output_tokens=0,
                 cache_read_tokens=0, cache_creation_tokens=0),
        ],
    )
    records, meta = collector.collect_cc_switch_proxy(db)
    assert meta["status"] == "ok", meta
    assert len(records) == 2, [r["tool"] for r in records]
    by_tool = {r["tool"]: r for r in records}
    assert "Claude Code via CC Switch" in by_tool
    assert "Codex via CC Switch" in by_tool
    claude = by_tool["Claude Code via CC Switch"]
    assert claude["usage"]["total_tokens"] == 150
    assert claude["cost"] == 0.25
    assert claude["source"] == "cc-switch-proxy"
    codex = by_tool["Codex via CC Switch"]
    assert codex["usage"]["total_tokens"] == 15
    assert codex["usage"]["cache_read_input_tokens"] == 5


def test_schema_variant_without_pricing_model_or_data_source(tmp: Path) -> None:
    # Matches the real Windows CC Switch schema (no pricing_model, no data_source).
    cols = [
        "request_id", "provider_id", "app_type", "model", "request_model",
        "input_tokens", "output_tokens", "cache_read_tokens", "cache_creation_tokens",
        "total_cost_usd", "status_code", "created_at",
    ]
    db = tmp / "variant.db"
    con = sqlite3.connect(db)
    con.execute(f"create table proxy_request_logs ({', '.join(cols)})")
    con.execute(
        f"insert into proxy_request_logs ({', '.join(cols)}) values ({', '.join('?' for _ in cols)})",
        ("r1", "p1", "claude", "claude-sonnet", "claude-sonnet",
         200, 80, 0, 0, "0.5", 200, 1_700_000_000),
    )
    con.commit()
    con.close()
    records, meta = collector.collect_cc_switch_proxy(db)
    assert meta["status"] == "ok", meta
    assert len(records) == 1
    rec = records[0]
    assert rec["tool"] == "Claude Code via CC Switch"
    assert rec["usage"]["total_tokens"] == 280
    assert rec["cost"] == 0.5
    assert rec["model"] == "claude-sonnet"


def test_created_at_milliseconds(tmp: Path) -> None:
    db = tmp / "ms.db"
    # 1_700_000_000_000 ms == 1_700_000_000 s; both must bucket to the same day.
    _make_db(
        db,
        [
            _row(request_id="s", created_at=1_700_000_000),
            _row(request_id="m", created_at=1_700_000_000_000),
        ],
    )
    records, _ = collector.collect_cc_switch_proxy(db)
    days = {r["date"] for r in records}
    assert len(records) == 2
    assert len(days) == 1, days


def test_aggregate_honors_record_cost() -> None:
    records = [
        {
            "date": "2026-06-21",
            "timestamp": None,
            "tool": "Claude Code via CC Switch",
            "model": "claude-sonnet",
            "usage": {**collector.empty_usage(), "input_tokens": 1000, "total_tokens": 1000},
            "cost": 1.23,  # explicit billed cost
        }
    ]
    out = collector.aggregate(records, collector.DEFAULT_PRICING)
    assert out["totals"]["cost"] == 1.23
    assert out["totals"]["tokens"] == 1000


def test_source_file_cutoff_and_too_old(tmp: Path) -> None:
    # 180-day history -> cutoff ~181 days ago.
    cutoff = collector.source_file_cutoff(180)
    assert cutoff is not None
    now = time.time()
    # ~181 days in seconds, with a margin.
    assert (now - cutoff) > 179 * 86400
    assert (now - cutoff) < 183 * 86400

    old = tmp / "old.jsonl"
    new = tmp / "new.jsonl"
    old.write_text("{}\n", encoding="utf-8")
    new.write_text("{}\n", encoding="utf-8")
    # Backdate `old` to 200 days ago.
    old_ts = now - 200 * 86400
    os.utime(old, (old_ts, old_ts))
    assert collector._too_old(str(old), cutoff) is True
    assert collector._too_old(str(new), cutoff) is False
    # No cutoff -> never too old.
    assert collector._too_old(str(old), None) is False


def test_date_from_epoch_variants() -> None:
    collector.configure_timezone("Asia/Shanghai")
    secs = collector.date_from_epoch(1_700_000_000)
    millis = collector.date_from_epoch(1_700_000_000_000)
    assert secs == millis
    assert collector.date_from_epoch(None) is None
    assert collector.date_from_epoch("not-a-number") is None
    assert collector.date_from_epoch("1700000000") == secs


def test_settings_retain_all_history_roundtrip() -> None:
    from tokenstep import settings as settings_mod

    assert settings_mod.DEFAULTS["retain_all_history"] is False
    assert settings_mod.normalize({})["retain_all_history"] is False
    assert settings_mod.normalize({"retain_all_history": True})["retain_all_history"] is True
    # Non-bool coerced.
    assert settings_mod.normalize({"retain_all_history": 1})["retain_all_history"] is True


def test_retain_all_history_disables_cutoff() -> None:
    # collect_all should pass modified_since=None when retain_all_history is on,
    # and a real cutoff when off. Capture what each file collector receives.
    captured: dict[str, object] = {}

    def fake_codex(cache, live_paths, modified_since=None):
        captured["codex"] = modified_since
        return [], {"status": "ok", "files": 0, "records": 0}

    def fake_claude(cache, live_paths, modified_since=None):
        captured["claude"] = modified_since
        return [], {"status": "ok", "files": 0, "records": 0}

    def fake_cc(database=None):
        return [], {"status": "missing_db", "files": 0, "records": 0}

    saved = (
        collector.collect_codex,
        collector.collect_claude_code,
        collector.collect_cc_switch_proxy,
        collector.load_cache,
        collector.save_cache,
    )
    collector.collect_codex = fake_codex
    collector.collect_claude_code = fake_claude
    collector.collect_cc_switch_proxy = fake_cc
    collector.load_cache = lambda: {"version": collector.CACHE_VERSION, "files": {}}
    collector.save_cache = lambda cache: None
    try:
        collector.collect_all({"retain_all_history": True, "history_days": 180})
        assert captured["codex"] is None, captured
        assert captured["claude"] is None, captured

        collector.collect_all({"retain_all_history": False, "history_days": 180})
        assert captured["codex"] is not None
        assert captured["claude"] is not None
    finally:
        (
            collector.collect_codex,
            collector.collect_claude_code,
            collector.collect_cc_switch_proxy,
            collector.load_cache,
            collector.save_cache,
        ) = saved


def _run() -> int:
    import inspect

    tests = [
        (n, f) for n, f in sorted(globals().items())
        if n.startswith("test_") and callable(f)
    ]
    failed = 0
    for name, fn in tests:
        needs_tmp = "tmp" in inspect.signature(fn).parameters
        try:
            if needs_tmp:
                with tempfile.TemporaryDirectory() as d:
                    fn(tmp=Path(d))
            else:
                fn()
            print(f"PASS {name}")
        except Exception as exc:  # noqa: BLE001
            failed += 1
            print(f"FAIL {name}: {exc!r}")
    print(f"\n{len(tests) - failed}/{len(tests)} passed")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(_run())
