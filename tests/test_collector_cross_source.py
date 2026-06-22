# -*- coding: utf-8 -*-
"""Tests for cross-source dedup and Codex archived-session exclusion.

macOS 0.1.42 parity:
  * Native log records (Claude Code / Codex) and CC Switch proxy records can
    describe the SAME request when traffic is routed through the proxy. The proxy
    copy is dropped (native kept, enriched with the proxy's real billed cost).
    Gemini-via-proxy has no native source, so it is always kept.
  * archived_sessions are excluded from Codex collection (they may hold restored
    logs with rewritten timestamps that would inflate totals).

No pytest dependency. Run with:
    python -m tests.test_collector_cross_source
    python tests/test_collector_cross_source.py
"""
from __future__ import annotations

import datetime as dt
import json
import sqlite3
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from tokenstep import collector  # noqa: E402

_PROXY_COLUMNS = [
    "request_id",
    "provider_id",
    "app_type",
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


def _epoch(iso: str) -> int:
    """Epoch seconds for an ISO-8601 (Z) timestamp."""
    return int(dt.datetime.fromisoformat(iso.replace("Z", "+00:00")).timestamp())


def _make_proxy_db(path: Path, rows: list[dict]) -> None:
    con = sqlite3.connect(path)
    con.execute(f"create table proxy_request_logs ({', '.join(_PROXY_COLUMNS)})")
    placeholders = ", ".join("?" for _ in _PROXY_COLUMNS)
    for r in rows:
        con.execute(
            f"insert into proxy_request_logs ({', '.join(_PROXY_COLUMNS)}) "
            f"values ({placeholders})",
            tuple(r.get(c) for c in _PROXY_COLUMNS),
        )
    con.commit()
    con.close()


def _proxy_row(**kw) -> dict:
    base = {
        "request_id": None,
        "provider_id": "p",
        "app_type": "claude",
        "model": "claude-opus-4-20250514",
        "request_model": "claude-opus-4-20250514",
        "pricing_model": "claude-opus-4-20250514",
        "input_tokens": 0,
        "output_tokens": 0,
        "cache_read_tokens": 0,
        "cache_creation_tokens": 0,
        "total_cost_usd": "0.0",
        "status_code": 200,
        "created_at": 0,
        "data_source": "proxy",
    }
    base.update(kw)
    return base


def _claude_native_line(
    *, uuid: str, message_id: str, timestamp: str, model: str,
    stop_reason: str, inp: int, out: int, cache_read: int,
    request_id: str, session_id: str,
) -> str:
    obj = {
        "type": "assistant",
        "uuid": uuid,
        "timestamp": timestamp,
        "requestId": request_id,
        "sessionId": session_id,
        "message": {
            "id": message_id,
            "model": model,
            "stop_reason": stop_reason,
            "usage": {
                "input_tokens": inp,
                "output_tokens": out,
                "cache_read_input_tokens": cache_read,
            },
        },
    }
    return json.dumps(obj, ensure_ascii=False)


def _codex_native_lines(*, session_id: str, model: str, timestamp: str,
                        inp: int, out: int, cache_read: int) -> list[str]:
    return [
        json.dumps({"type": "session_meta", "timestamp": timestamp,
                    "payload": {"id": session_id}}),
        json.dumps({"type": "turn_context", "timestamp": timestamp,
                    "payload": {"model": model}}),
        json.dumps({"type": "event_msg", "timestamp": timestamp,
                    "payload": {"type": "token_count", "info": {"last_token_usage": {
                        "input_tokens": inp,
                        "output_tokens": out,
                        "cache_read_input_tokens": cache_read,
                    }}}}),
    ]


# --------------------------------------------------------------------------- #
# Codex archived-session exclusion
# --------------------------------------------------------------------------- #


def test_codex_excludes_archived_sessions(tmp: Path) -> None:
    collector.configure_timezone("Asia/Shanghai")
    live = tmp / ".codex" / "sessions" / "2026" / "06" / "22"
    archived = tmp / ".codex" / "archived_sessions" / "2026" / "06" / "22"
    live.mkdir(parents=True, exist_ok=True)
    archived.mkdir(parents=True, exist_ok=True)
    (live / "live.jsonl").write_text(
        "\n".join(_codex_native_lines(session_id="live", model="gpt-5",
                                      timestamp="2026-06-22T05:00:00Z",
                                      inp=80, out=40, cache_read=0)),
        encoding="utf-8",
    )
    (archived / "archived.jsonl").write_text(
        "\n".join(_codex_native_lines(session_id="archived", model="gpt-5",
                                      timestamp="2026-06-22T05:00:00Z",
                                      inp=600_000_000, out=300_000_000, cache_read=0)),
        encoding="utf-8",
    )

    original_home = collector.Path.home
    try:
        collector.Path.home = staticmethod(lambda: tmp)  # type: ignore[assignment]
        records, meta = collector.collect_codex({"version": collector.CACHE_VERSION,
                                                 "files": {}}, set())
    finally:
        collector.Path.home = original_home  # type: ignore[assignment]

    assert meta["status"] == "ok", meta
    assert len(records) == 1, records
    assert records[0]["usage"]["total_tokens"] == 120, records[0]["usage"]


# --------------------------------------------------------------------------- #
# Cross-source dedup: Claude (exact request-id match) + gemini residual
# --------------------------------------------------------------------------- #


def _collect_claude_native(tmp: Path, line: str) -> list[dict]:
    root = tmp / ".claude" / "projects" / "proj"
    root.mkdir(parents=True, exist_ok=True)
    (root / "session.jsonl").write_text(line, encoding="utf-8")
    original_home = collector.Path.home
    try:
        collector.Path.home = staticmethod(lambda: tmp)  # type: ignore[assignment]
        records, _ = collector.collect_claude_code(
            {"version": collector.CACHE_VERSION, "files": {}}, set()
        )
    finally:
        collector.Path.home = original_home  # type: ignore[assignment]
    return records


def test_claude_proxy_dedup_and_gemini_residual(tmp: Path) -> None:
    collector.configure_timezone("Asia/Shanghai")
    ts = "2026-06-21T08:00:00Z"
    native = _collect_claude_native(
        tmp,
        _claude_native_line(
            uuid="dedupe-claude-1", message_id="msg-dedupe-claude-1",
            timestamp=ts, model="claude-opus-4-20250514", stop_reason="end_turn",
            inp=10, out=3, cache_read=100,
            request_id="req-claude-1", session_id="session-claude-1",
        ),
    )

    db = tmp / "cc.db"
    _make_proxy_db(db, [
        _proxy_row(request_id="req-claude-1", app_type="claude",
                   input_tokens=10, output_tokens=3, cache_read_tokens=100,
                   total_cost_usd="0.12", created_at=_epoch(ts)),
        _proxy_row(request_id="req-claude-2", app_type="claude",
                   input_tokens=20, output_tokens=4,
                   total_cost_usd="0.24", created_at=_epoch(ts) + 60),
        _proxy_row(request_id="req-gemini-1", app_type="gemini",
                   model="gemini-2.5-pro", request_model="gemini-2.5-pro",
                   pricing_model="gemini-2.5-pro",
                   input_tokens=5, output_tokens=1,
                   total_cost_usd="0.06", created_at=_epoch(ts) + 120),
    ])
    proxy, _ = collector.collect_cc_switch_proxy(db)

    dedup = collector.deduplicate_cross_source(native, proxy)
    assert dedup["raw_proxy"] == 3, dedup
    assert dedup["kept_proxy"] == 2, dedup
    assert dedup["deduped_proxy"] == 1, dedup

    agg = collector.aggregate(dedup["records"], collector.DEFAULT_PRICING)
    assert agg["totals"]["tokens"] == 143, agg["totals"]
    # 0.12 (enriched onto native) + 0.24 (kept claude) + 0.06 (gemini) = 0.42
    assert agg["totals"]["cost"] == 0.42, agg["totals"]
    tools = agg["daily"][0]["tools"]
    assert tools["Claude Code"] == 113, tools
    assert tools["Claude Code via CC Switch"] == 24, tools
    assert tools["Gemini via CC Switch"] == 6, tools


# --------------------------------------------------------------------------- #
# Cross-source dedup: Codex (strong usage match -> all_deduped)
# --------------------------------------------------------------------------- #


def _collect_codex_native(tmp: Path, lines: list[str]) -> list[dict]:
    root = tmp / ".codex" / "sessions" / "2026" / "06" / "21"
    root.mkdir(parents=True, exist_ok=True)
    (root / "session.jsonl").write_text("\n".join(lines), encoding="utf-8")
    original_home = collector.Path.home
    try:
        collector.Path.home = staticmethod(lambda: tmp)  # type: ignore[assignment]
        records, _ = collector.collect_codex(
            {"version": collector.CACHE_VERSION, "files": {}}, set()
        )
    finally:
        collector.Path.home = original_home  # type: ignore[assignment]
    return records


def test_codex_proxy_dedup_all_deduped(tmp: Path) -> None:
    collector.configure_timezone("Asia/Shanghai")
    ts = "2026-06-21T09:00:00Z"
    native = _collect_codex_native(
        tmp,
        _codex_native_lines(session_id="codex-session-1", model="gpt-5.4",
                            timestamp=ts, inp=30, out=5, cache_read=10),
    )
    assert len(native) == 1, native

    db = tmp / "cc.db"
    _make_proxy_db(db, [
        _proxy_row(request_id="proxy-codex-strong-match", app_type="codex",
                   model="gpt-5.4", request_model="gpt-5.4", pricing_model="",
                   input_tokens=30, output_tokens=5, cache_read_tokens=10,
                   total_cost_usd="0.45", created_at=_epoch(ts)),
    ])
    proxy, meta = collector.collect_cc_switch_proxy(db)

    dedup = collector.deduplicate_cross_source(native, proxy)
    assert dedup["raw_proxy"] == 1, dedup
    assert dedup["kept_proxy"] == 0, dedup
    assert dedup["deduped_proxy"] == 1, dedup

    annotated = collector._annotate_cc_switch_meta(meta, dedup)
    assert annotated["status"] == "all_deduped", annotated

    agg = collector.aggregate(dedup["records"], collector.DEFAULT_PRICING)
    assert agg["totals"]["tokens"] == 45, agg["totals"]
    assert agg["totals"]["cost"] == 0.45, agg["totals"]
    tools = agg["daily"][0]["tools"]
    assert tools["Codex"] == 45, tools
    assert tools.get("Codex via CC Switch", 0) == 0, tools


def test_non_overlapping_proxy_records_are_all_kept(tmp: Path) -> None:
    # No native records -> nothing to dedup; every proxy record survives.
    collector.configure_timezone("Asia/Shanghai")
    ts = "2026-06-21T10:00:00Z"
    db = tmp / "cc.db"
    _make_proxy_db(db, [
        _proxy_row(request_id="a", app_type="claude", input_tokens=100,
                   output_tokens=50, total_cost_usd="0.10", created_at=_epoch(ts)),
        _proxy_row(request_id="b", app_type="codex", model="gpt-5.4",
                   request_model="gpt-5.4", pricing_model="gpt-5.4",
                   input_tokens=10, output_tokens=0, cache_read_tokens=5,
                   total_cost_usd="0.01", created_at=_epoch(ts)),
    ])
    proxy, _ = collector.collect_cc_switch_proxy(db)
    dedup = collector.deduplicate_cross_source([], proxy)
    assert dedup["kept_proxy"] == 2, dedup
    assert dedup["deduped_proxy"] == 0, dedup


def _runner() -> int:
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
    raise SystemExit(_runner())
