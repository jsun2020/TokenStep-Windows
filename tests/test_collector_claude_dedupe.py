# -*- coding: utf-8 -*-
"""Tests for Claude Code per-response token dedup (macOS 0.1.32 parity).

Claude Code writes each assistant content block (thinking, text, every tool_use)
on its own JSONL line, all sharing one message.id and identical usage totals.
Counting each line double-counts tokens, so we keep one record per response and
prefer the completed one (carries stop_reason).

No pytest dependency. Run with:
    python -m tests.test_collector_claude_dedupe
    python tests/test_collector_claude_dedupe.py
"""
from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from tokenstep import collector  # noqa: E402


def _line(
    uuid: str,
    message_id: str | None,
    timestamp: str,
    model: str | None,
    stop_reason: str | None,
    inp: int,
    out: int,
    cache_read: int,
) -> str:
    usage = {
        "input_tokens": inp,
        "output_tokens": out,
        "cache_read_input_tokens": cache_read,
    }
    message: dict = {"usage": usage}
    if message_id is not None:
        message["id"] = message_id
    if model is not None:
        message["model"] = model
    if stop_reason is not None:
        message["stop_reason"] = stop_reason
    obj = {
        "type": "assistant",
        "uuid": uuid,
        "timestamp": timestamp,
        "message": message,
    }
    return json.dumps(obj, ensure_ascii=False)


# Six lines = three responses: two assistant blocks share msg_same_response,
# two share msg_tool_batch, and two legacy lines (no message.id) share a uuid.
_FIXTURE = [
    _line("block-thinking", "msg_same_response", "2026-06-21T08:00:00Z",
          "claude-opus-4-20250514", None, 10, 3, 100),
    _line("block-text", "msg_same_response", "2026-06-21T08:00:01Z",
          "claude-opus-4-20250514", "end_turn", 10, 3, 100),
    _line("tool-1", "msg_tool_batch", "2026-06-21T08:01:00Z",
          "claude-opus-4-20250514", None, 7, 2, 200),
    _line("tool-2", "msg_tool_batch", "2026-06-21T08:01:01Z",
          "claude-opus-4-20250514", None, 7, 2, 200),
    _line("legacy-1", None, "2026-06-21T08:02:00Z", None, "end_turn", 1, 1, 0),
    _line("legacy-1", None, "2026-06-21T08:02:01Z", None, "end_turn", 1, 1, 0),
]


def _run_collect(tmp: Path) -> tuple[list[dict], dict]:
    """Point collect_claude_code at a temp ~/.claude/projects and run it."""
    root = tmp / ".claude" / "projects" / "proj"
    root.mkdir(parents=True, exist_ok=True)
    (root / "session.jsonl").write_text("\n".join(_FIXTURE), encoding="utf-8")

    original_home = collector.Path.home
    try:
        collector.Path.home = staticmethod(lambda: tmp)  # type: ignore[assignment]
        cache = {"version": collector.CACHE_VERSION, "files": {}}
        live: set[str] = set()
        return collector.collect_claude_code(cache, live)
    finally:
        collector.Path.home = original_home  # type: ignore[assignment]


def test_dedup_keeps_one_record_per_response(tmp: Path) -> None:
    records, meta = _run_collect(tmp)
    assert meta["status"] == "ok", meta
    # Three distinct responses survive (not six lines).
    assert len(records) == 3, [r["model"] for r in records]


def test_dedup_token_totals_not_double_counted(tmp: Path) -> None:
    records, _ = _run_collect(tmp)
    agg = collector.aggregate(records, collector.load_pricing())

    # msg_same_response = 113, msg_tool_batch = 209, legacy = 2  -> 324
    assert agg["totals"]["tokens"] == 324, agg["totals"]
    daily = agg["daily"]
    assert len(daily) == 1, daily
    assert daily[0]["date"] == "2026-06-21"
    assert daily[0]["tools"]["Claude Code"] == 324, daily[0]["tools"]


def test_dedup_prefers_stop_reason_and_model(tmp: Path) -> None:
    records, _ = _run_collect(tmp)
    agg = collector.aggregate(records, collector.load_pricing())
    models = {m["model"]: m["tokens"] for m in agg["models"]}
    # The kept opus records sum to 322; the model-less legacy line -> "unknown".
    assert models.get("claude-opus-4-20250514") == 322, models
    assert models.get("unknown") == 2, models


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
