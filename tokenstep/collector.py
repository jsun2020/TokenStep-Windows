# -*- coding: utf-8 -*-
"""Token usage collector.

Ported from the macOS TokenStep Python collector. The reading logic is already
cross-platform (Path.home(), glob, sqlite); this module adapts the inputs/outputs
to the Windows %APPDATA% layout and exposes helper functions for the tray app.

Privacy: only usage metadata (date, model, client name, token counts) is read.
Code, prompts, and conversation content are never read or stored.
"""
from __future__ import annotations

import datetime as dt
import glob
import json
import os
import sqlite3
import traceback
from collections import defaultdict
from pathlib import Path
from typing import Any

from . import paths

# Bump when the cached record shape changes, to invalidate old caches.
# v2 matches macOS 0.1.14 (CollectorCache.currentVersion = 2): forces a one-time
# re-parse so cached numbers align with the current collector logic.
CACHE_VERSION = 2

# Green "step" identity, matching the macOS SwiftUI app
# (tokenGreen / tokenGreenDark, GitHub-contribution greens).
TOOL_COLORS = {
    "Codex": "#2DA44E",
    "Claude Code": "#216E39",
    # CC Switch proxy sources (macOS 0.1.20+). Distinct green/teal shades so they
    # show up in the per-tool daily breakdown; unknown app types fall back to the
    # default color and still count toward totals.
    "Claude Code via CC Switch": "#1A7F4B",
    "Codex via CC Switch": "#3FB950",
    "Gemini via CC Switch": "#2C8C7C",
}

DEFAULT_PRICING: dict[str, Any] = {
    "notes": "Rough local estimates only. Edit these numbers for bill-like cost tracking.",
    "default_total_usd_per_1m": 1.0,
    "tools": {
        "Codex": {"total_usd_per_1m": 1.0},
        "Claude Code": {"total_usd_per_1m": 3.0},
    },
    "models": {
        "gpt-5.5": {
            "openai_input_usd_per_1m": 5.0,
            "openai_cached_input_usd_per_1m": 0.5,
            "openai_output_usd_per_1m": 30.0,
        },
        "gpt-5.4": {
            "openai_input_usd_per_1m": 2.5,
            "openai_cached_input_usd_per_1m": 0.25,
            "openai_output_usd_per_1m": 15.0,
        },
        "gpt-5": {"total_usd_per_1m": 1.0},
        "gpt-5-codex": {"total_usd_per_1m": 1.0},
        "claude-opus": {
            "input_usd_per_1m": 15.0,
            "output_usd_per_1m": 75.0,
            "cache_creation_usd_per_1m": 18.75,
            "cache_read_usd_per_1m": 1.5,
        },
        "claude-sonnet": {
            "input_usd_per_1m": 3.0,
            "output_usd_per_1m": 15.0,
            "cache_creation_usd_per_1m": 3.75,
            "cache_read_usd_per_1m": 0.3,
        },
        "glm": {"total_usd_per_1m": 0.2},
        "minimax": {"total_usd_per_1m": 0.2},
    },
}

# Timezone resolved at collect time from settings (with a safe fallback).
_TZ_NAME = "Asia/Shanghai"
_LOCAL_TZ: dt.tzinfo = dt.timezone(dt.timedelta(hours=8))


def configure_timezone(name: str | None) -> None:
    """Set the local timezone used for day-bucketing.

    Windows has no IANA tz database, so ZoneInfo may be unavailable. Fall back to
    a fixed UTC+8 offset (Asia/Shanghai) when the named zone cannot be resolved.
    """
    global _TZ_NAME, _LOCAL_TZ
    name = name or "Asia/Shanghai"
    _TZ_NAME = name
    try:
        from zoneinfo import ZoneInfo  # noqa: PLC0415

        _LOCAL_TZ = ZoneInfo(name)
    except Exception:
        _LOCAL_TZ = dt.timezone(dt.timedelta(hours=8))


# ---------------------------------------------------------------------------
# Parsing helpers
# ---------------------------------------------------------------------------


def parse_iso(ts: str | None) -> dt.datetime | None:
    if not ts:
        return None
    try:
        if ts.endswith("Z"):
            ts = ts[:-1] + "+00:00"
        parsed = dt.datetime.fromisoformat(ts)
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=dt.timezone.utc)
        return parsed.astimezone(_LOCAL_TZ)
    except Exception:
        return None


def date_from_iso(ts: str | None) -> str | None:
    parsed = parse_iso(ts)
    return parsed.date().isoformat() if parsed else None


def date_from_epoch(seconds: int | float | str | None) -> str | None:
    if seconds is None:
        return None
    try:
        value = float(seconds)
    except (TypeError, ValueError):
        return None
    # Some sources store epoch milliseconds; scale down (matches macOS
    # dayString(fromEpoch:) — anything past year ~2286 in seconds is really ms).
    if value > 10_000_000_000:
        value /= 1_000.0
    try:
        return dt.datetime.fromtimestamp(value, _LOCAL_TZ).date().isoformat()
    except Exception:
        return None


def empty_usage() -> dict[str, int]:
    return {
        "input_tokens": 0,
        "output_tokens": 0,
        "cache_creation_input_tokens": 0,
        "cache_read_input_tokens": 0,
        "reasoning_output_tokens": 0,
        "total_tokens": 0,
    }


def normalize_usage(raw: dict[str, Any] | None) -> dict[str, int]:
    usage = empty_usage()
    if not isinstance(raw, dict):
        return usage
    aliases = {
        "input": "input_tokens",
        "output": "output_tokens",
        "cached": "cache_read_input_tokens",
        "thoughts": "reasoning_output_tokens",
        "total": "total_tokens",
        "input_tokens": "input_tokens",
        "output_tokens": "output_tokens",
        "cache_creation_input_tokens": "cache_creation_input_tokens",
        "cache_read_input_tokens": "cache_read_input_tokens",
        "cached_input_tokens": "cache_read_input_tokens",
        "reasoning_output_tokens": "reasoning_output_tokens",
        "total_tokens": "total_tokens",
    }
    for key, value in raw.items():
        mapped = aliases.get(key)
        if not mapped:
            continue
        try:
            usage[mapped] += int(value or 0)
        except Exception:
            pass
    if usage["total_tokens"] <= 0:
        usage["total_tokens"] = (
            usage["input_tokens"]
            + usage["output_tokens"]
            + usage["cache_creation_input_tokens"]
            + usage["cache_read_input_tokens"]
            + usage["reasoning_output_tokens"]
        )
    return usage


def add_usage(a: dict[str, int], b: dict[str, int]) -> dict[str, int]:
    for key, value in b.items():
        a[key] = a.get(key, 0) + int(value or 0)
    return a


def model_key(model: str | None) -> str:
    value = (model or "unknown").strip()
    return value if value else "unknown"


# ---------------------------------------------------------------------------
# Pricing
# ---------------------------------------------------------------------------


def load_pricing() -> dict[str, Any]:
    if paths.PRICING_JSON.exists():
        try:
            with paths.PRICING_JSON.open("r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return DEFAULT_PRICING


def ensure_pricing_file() -> None:
    """Write the default pricing table on first run so users can edit it."""
    if paths.PRICING_JSON.exists():
        return
    paths.ensure_dirs()
    try:
        paths.PRICING_JSON.write_text(
            json.dumps(DEFAULT_PRICING, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
    except Exception:
        pass


def match_pricing_model(pricing: dict[str, Any], model: str) -> dict[str, Any] | None:
    models = pricing.get("models", {})
    lower = model.lower()
    if model in models:
        return models[model]
    for key, value in models.items():
        if lower.startswith(key.lower()) or key.lower() in lower:
            return value
    return None


def estimate_cost(usage: dict[str, int], tool: str, model: str, pricing: dict[str, Any]) -> float:
    rates = match_pricing_model(pricing, model)
    if not rates:
        rates = pricing.get("tools", {}).get(tool)
    if not rates:
        rates = {"total_usd_per_1m": pricing.get("default_total_usd_per_1m", 0)}

    # OpenAI-style per-part pricing (mirrors macOS openAICostByParts, used for
    # Codex GPT-5.x). OpenAI reports input_tokens *inclusive* of cached reads, so
    # cached tokens are subtracted from input and billed at the cached rate.
    if "openai_input_usd_per_1m" in rates:
        cached = max(0, usage.get("cache_read_input_tokens", 0))
        uncached_input = max(0, usage.get("input_tokens", 0) - cached)
        cache_creation = usage.get("cache_creation_input_tokens", 0)
        output = usage.get("output_tokens", 0) + usage.get("reasoning_output_tokens", 0)
        return (
            (uncached_input + cache_creation) / 1_000_000 * float(rates.get("openai_input_usd_per_1m", 0))
            + cached / 1_000_000 * float(rates.get("openai_cached_input_usd_per_1m", 0))
            + output / 1_000_000 * float(rates.get("openai_output_usd_per_1m", 0))
        )

    if "total_usd_per_1m" in rates:
        return usage.get("total_tokens", 0) / 1_000_000 * float(rates.get("total_usd_per_1m", 0))

    total = 0.0
    total += usage.get("input_tokens", 0) / 1_000_000 * float(rates.get("input_usd_per_1m", 0))
    total += usage.get("output_tokens", 0) / 1_000_000 * float(rates.get("output_usd_per_1m", 0))
    total += usage.get("cache_creation_input_tokens", 0) / 1_000_000 * float(
        rates.get("cache_creation_usd_per_1m", rates.get("input_usd_per_1m", 0))
    )
    total += usage.get("cache_read_input_tokens", 0) / 1_000_000 * float(
        rates.get("cache_read_usd_per_1m", 0)
    )
    total += usage.get("reasoning_output_tokens", 0) / 1_000_000 * float(
        rates.get("reasoning_usd_per_1m", rates.get("output_usd_per_1m", 0))
    )
    return total


# ---------------------------------------------------------------------------
# Incremental file cache
#
# Parsing every JSONL log on each refresh is wasteful (hundreds of MB). We cache
# the parsed records per file, keyed by path + size + mtime, and only re-parse a
# file when it changes. Mirrors the macOS collector's collector-cache.json.
# ---------------------------------------------------------------------------


def _file_meta(path: str) -> tuple[int, float] | None:
    try:
        st = os.stat(path)
        return int(st.st_size), float(st.st_mtime)
    except OSError:
        return None


def source_file_cutoff(history_days: int) -> float | None:
    """Epoch seconds before which log files are too old to scan.

    Mirrors macOS sourceFileCutoffDate: today - max(7, history_days + 1) days.
    Files last modified before this are skipped (and their cache entries pruned),
    so refreshes don't re-walk months of stale logs. Returns None on bad input
    (scan everything).
    """
    try:
        days = max(7, int(history_days) + 1)
    except (TypeError, ValueError):
        return None
    cutoff = dt.datetime.now(_LOCAL_TZ) - dt.timedelta(days=days)
    return cutoff.timestamp()


def _too_old(path: str, cutoff: float | None) -> bool:
    """True when the file's mtime is older than the cutoff (so we should skip it)."""
    if cutoff is None:
        return False
    meta = _file_meta(path)
    if not meta:
        return False  # let the normal read path handle missing/unreadable files
    return meta[1] < cutoff


def load_cache() -> dict[str, Any]:
    try:
        with paths.COLLECTOR_CACHE_JSON.open("r", encoding="utf-8") as f:
            cache = json.load(f)
        if (
            isinstance(cache, dict)
            and cache.get("version") == CACHE_VERSION
            and isinstance(cache.get("files"), dict)
        ):
            return cache
    except Exception:
        pass
    return {"version": CACHE_VERSION, "files": {}}


def save_cache(cache: dict[str, Any]) -> None:
    try:
        paths.ensure_dirs()
        tmp = paths.COLLECTOR_CACHE_JSON.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(cache, ensure_ascii=False), encoding="utf-8")
        tmp.replace(paths.COLLECTOR_CACHE_JSON)
    except Exception:
        pass


def cached_records(cache: dict[str, Any], path: str, tool: str) -> list[dict[str, Any]] | None:
    meta = _file_meta(path)
    if not meta:
        return None
    entry = cache["files"].get(path)
    if (
        entry
        and entry.get("tool") == tool
        and entry.get("size") == meta[0]
        and abs(float(entry.get("mtime", -1.0)) - meta[1]) < 0.001
    ):
        return entry.get("records") or []
    return None


def store_records(cache: dict[str, Any], path: str, tool: str, records: list[dict[str, Any]]) -> None:
    meta = _file_meta(path)
    if not meta:
        return
    cache["files"][path] = {
        "tool": tool,
        "size": meta[0],
        "mtime": meta[1],
        "records": records,
    }


# ---------------------------------------------------------------------------
# Data sources
# ---------------------------------------------------------------------------


def collect_codex(
    cache: dict[str, Any], live_paths: set[str], modified_since: float | None = None
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    home = Path.home()
    candidates: list[str] = []
    for pattern in [
        str(home / ".codex" / "sessions" / "**" / "*.jsonl"),
        str(home / ".codex" / "archived_sessions" / "*.jsonl"),
    ]:
        candidates.extend(glob.glob(pattern, recursive=True))

    paths_list = [p for p in sorted(set(candidates)) if not _too_old(p, modified_since)]
    records: list[dict[str, Any]] = []
    seen: set[tuple[Any, ...]] = set()

    for path in paths_list:
        live_paths.add(path)
        cached = cached_records(cache, path, "Codex")
        if cached is not None:
            records.extend(cached)
            continue

        file_records: list[dict[str, Any]] = []
        session_id = Path(path).stem
        current_model = "unknown"
        event_index = 0
        try:
            with open(path, "r", encoding="utf-8") as f:
                for line in f:
                    try:
                        obj = json.loads(line)
                    except Exception:
                        continue
                    payload = obj.get("payload") if isinstance(obj, dict) else None
                    if obj.get("type") == "session_meta" and isinstance(payload, dict):
                        session_id = payload.get("id") or session_id
                    if obj.get("type") == "turn_context" and isinstance(payload, dict):
                        current_model = model_key(payload.get("model") or current_model)
                    if obj.get("type") != "event_msg" or not isinstance(payload, dict):
                        continue
                    if payload.get("type") != "token_count":
                        continue
                    info = payload.get("info") or {}
                    usage = normalize_usage(info.get("last_token_usage"))
                    if usage["total_tokens"] <= 0:
                        continue
                    event_index += 1
                    timestamp = obj.get("timestamp")
                    day = date_from_iso(timestamp)
                    if not day:
                        continue
                    dedupe_key = (session_id, timestamp, event_index, usage["total_tokens"])
                    if dedupe_key in seen:
                        continue
                    seen.add(dedupe_key)
                    file_records.append(
                        {
                            "date": day,
                            "timestamp": timestamp,
                            "tool": "Codex",
                            "model": current_model,
                            "usage": usage,
                            "source": "codex-rollout",
                        }
                    )
        except Exception:
            # Don't cache a partial/failed read; try again next refresh.
            continue

        store_records(cache, path, "Codex", file_records)
        records.extend(file_records)

    if records:
        return records, {"status": "ok", "files": len(paths_list), "records": len(records)}

    fallback_records = collect_codex_from_threads()
    return fallback_records, {
        "status": "fallback_threads" if fallback_records else "missing",
        "files": len(paths_list),
        "records": len(fallback_records),
    }


def collect_codex_from_threads() -> list[dict[str, Any]]:
    home = Path.home()
    db_candidates = [
        home / ".codex" / "state_5.sqlite",
        home / ".codex" / "sqlite" / "state_5.sqlite",
    ]
    db_path = next((p for p in db_candidates if p.exists()), None)
    if not db_path:
        return []

    records: list[dict[str, Any]] = []
    try:
        con = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
        cur = con.cursor()
        for created_at, model, tokens_used in cur.execute(
            "select created_at, model, tokens_used from threads where tokens_used > 0"
        ):
            day = date_from_epoch(created_at)
            if not day:
                continue
            usage = empty_usage()
            usage["total_tokens"] = int(tokens_used or 0)
            records.append(
                {
                    "date": day,
                    "timestamp": None,
                    "tool": "Codex",
                    "model": model_key(model),
                    "usage": usage,
                    "source": "codex-threads",
                }
            )
        con.close()
    except Exception:
        return []
    return records


def collect_claude_code(
    cache: dict[str, Any], live_paths: set[str], modified_since: float | None = None
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    candidates = glob.glob(
        str(Path.home() / ".claude" / "projects" / "**" / "*.jsonl"), recursive=True
    )
    paths_list = [p for p in sorted(candidates) if not _too_old(p, modified_since)]
    records: list[dict[str, Any]] = []
    seen: set[str] = set()

    for path in paths_list:
        live_paths.add(path)
        cached = cached_records(cache, path, "Claude Code")
        if cached is not None:
            records.extend(cached)
            continue

        file_records: list[dict[str, Any]] = []
        try:
            with open(path, "r", encoding="utf-8") as f:
                for line_no, line in enumerate(f, 1):
                    try:
                        obj = json.loads(line)
                    except Exception:
                        continue
                    if obj.get("type") != "assistant":
                        continue
                    message = obj.get("message")
                    if not isinstance(message, dict):
                        continue
                    usage = normalize_usage(message.get("usage"))
                    if usage["total_tokens"] <= 0:
                        continue
                    day = date_from_iso(obj.get("timestamp"))
                    if not day:
                        continue
                    unique = obj.get("uuid") or f"{path}:{line_no}"
                    if unique in seen:
                        continue
                    seen.add(unique)
                    file_records.append(
                        {
                            "date": day,
                            "timestamp": obj.get("timestamp"),
                            "tool": "Claude Code",
                            "model": model_key(message.get("model")),
                            "usage": usage,
                            "source": "claude-jsonl",
                        }
                    )
        except Exception:
            # Don't cache a partial/failed read; try again next refresh.
            continue

        store_records(cache, path, "Claude Code", file_records)
        records.extend(file_records)

    return records, {
        "status": "ok" if records else "missing",
        "files": len(paths_list),
        "records": len(records),
    }


def _cc_switch_tool_name(app_type: str | None) -> str:
    """Map a CC Switch app_type to a display tool name (mirrors macOS)."""
    value = (app_type or "unknown").strip()
    normalized = value.lower()
    if normalized == "claude":
        return "Claude Code via CC Switch"
    if normalized == "codex":
        return "Codex via CC Switch"
    if normalized == "gemini":
        return "Gemini via CC Switch"
    label = value if value else "unknown"
    return f"{label} via CC Switch (experimental)"


def _cc_switch_db_path() -> Path | None:
    """Locate the CC Switch SQLite DB across Mac- and Windows-style locations."""
    candidates = [Path.home() / ".cc-switch" / "cc-switch.db"]
    for env in ("APPDATA", "LOCALAPPDATA"):
        base = os.environ.get(env)
        if base:
            candidates.append(Path(base) / "cc-switch" / "cc-switch.db")
    return next((p for p in candidates if p.exists()), None)


# The token + bucketing columns we genuinely need. CC Switch's schema varies
# across versions/platforms (e.g. the Windows build omits pricing_model and
# data_source that macOS 0.1.28 assumes), so we require only the essentials and
# adapt the query to whatever optional columns are present.
_CC_SWITCH_REQUIRED_COLUMNS = {
    "app_type",
    "input_tokens",
    "output_tokens",
    "cache_read_tokens",
    "cache_creation_tokens",
    "status_code",
    "created_at",
}


def _cc_switch_query(available: set[str]) -> str:
    """Build the proxy_request_logs query for the columns that actually exist."""
    # Prefer pricing_model, then model, then request_model — whichever exist.
    model_cols = [c for c in ("pricing_model", "model", "request_model") if c in available]
    if model_cols:
        model_expr = (
            "coalesce("
            + ", ".join(f"nullif({c}, '')" for c in model_cols)
            + ", 'unknown') as display_model"
        )
    else:
        model_expr = "'unknown' as display_model"

    cost_expr = (
        "cast(coalesce(nullif(total_cost_usd, ''), '0') as real) as total_cost_usd"
        if "total_cost_usd" in available
        else "0.0 as total_cost_usd"
    )

    # Only filter on data_source when CC Switch records it.
    data_source_clause = (
        "coalesce(data_source, 'proxy') = 'proxy' and "
        if "data_source" in available
        else ""
    )
    order = "order by created_at, request_id" if "request_id" in available else "order by created_at"

    return f"""
    select
        created_at,
        app_type,
        {model_expr},
        coalesce(input_tokens, 0) as input_tokens,
        coalesce(output_tokens, 0) as output_tokens,
        coalesce(cache_read_tokens, 0) as cache_read_tokens,
        coalesce(cache_creation_tokens, 0) as cache_creation_tokens,
        {cost_expr}
    from proxy_request_logs
    where {data_source_clause}status_code >= 200
        and status_code < 300
        and (
            coalesce(input_tokens, 0)
            + coalesce(output_tokens, 0)
            + coalesce(cache_read_tokens, 0)
            + coalesce(cache_creation_tokens, 0)
        ) > 0
    {order}
    """


def collect_cc_switch_proxy(
    database: Path | None = None,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Read CC Switch proxy usage from its SQLite log (macOS 0.1.20+ parity).

    CC Switch routes Claude/Codex/Gemini traffic through a local proxy and logs
    per-request token counts. We read the proxy_request_logs table read-only and
    map each successful, non-empty request to a usage record. The query adapts to
    the installed CC Switch schema (optional pricing_model / data_source /
    total_cost_usd columns). Returns (records, source_meta); never raises
    (missing/locked DB -> empty + status).
    """
    db_path = database or _cc_switch_db_path()
    if not db_path or not db_path.exists():
        return [], {"status": "missing_db", "files": 0, "records": 0}

    try:
        con = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True, timeout=2.0)
    except Exception:
        return [], {"status": "unreadable_db", "files": 1, "records": 0}

    try:
        con.row_factory = sqlite3.Row
        try:
            cols = con.execute("pragma table_info(proxy_request_logs)").fetchall()
        except Exception:
            return [], {"status": "schema_unreadable", "files": 1, "records": 0}
        if not cols:
            return [], {"status": "missing_table", "files": 1, "records": 0}
        available = {row["name"] for row in cols}
        if not _CC_SWITCH_REQUIRED_COLUMNS.issubset(available):
            return [], {"status": "schema_mismatch", "files": 1, "records": 0}

        try:
            rows = con.execute(_cc_switch_query(available)).fetchall()
        except Exception:
            return [], {"status": "query_failed", "files": 1, "records": 0}

        records: list[dict[str, Any]] = []
        for row in rows:
            day = date_from_epoch(row["created_at"])
            if not day:
                continue
            usage = empty_usage()
            usage["input_tokens"] = int(row["input_tokens"] or 0)
            usage["output_tokens"] = int(row["output_tokens"] or 0)
            usage["cache_read_input_tokens"] = int(row["cache_read_tokens"] or 0)
            usage["cache_creation_input_tokens"] = int(row["cache_creation_tokens"] or 0)
            usage["total_tokens"] = (
                usage["input_tokens"]
                + usage["output_tokens"]
                + usage["cache_read_input_tokens"]
                + usage["cache_creation_input_tokens"]
            )
            if usage["total_tokens"] <= 0:
                continue
            try:
                cost = float(row["total_cost_usd"] or 0.0)
            except (TypeError, ValueError):
                cost = 0.0
            records.append(
                {
                    "date": day,
                    "timestamp": None,
                    "tool": _cc_switch_tool_name(row["app_type"]),
                    "model": model_key(row["display_model"]),
                    "usage": usage,
                    "source": "cc-switch-proxy",
                    # CC Switch logs the real billed cost; aggregate() uses it
                    # verbatim instead of estimating from the pricing table.
                    "cost": cost,
                }
            )
    finally:
        try:
            con.close()
        except Exception:
            pass

    return records, {
        "status": "ok" if records else "missing_proxy_rows",
        "files": 1,
        "records": len(records),
    }


# ---------------------------------------------------------------------------
# Aggregation
# ---------------------------------------------------------------------------


def aggregate(records: list[dict[str, Any]], pricing: dict[str, Any]) -> dict[str, Any]:
    daily_map: dict[str, dict[str, Any]] = defaultdict(
        lambda: {"date": "", "tools": {}, "total_tokens": 0, "cost": 0.0}
    )
    tool_map: dict[str, dict[str, Any]] = defaultdict(lambda: {"usage": empty_usage(), "cost": 0.0})
    model_map: dict[tuple[str, str], dict[str, Any]] = defaultdict(
        lambda: {"usage": empty_usage(), "cost": 0.0}
    )

    for record in records:
        tool = record["tool"]
        model = record["model"]
        usage = record["usage"]
        # Use the source-reported cost when present (e.g. CC Switch logs the real
        # billed amount); otherwise estimate from the local pricing table.
        if record.get("cost") is not None:
            cost = float(record["cost"])
        else:
            cost = estimate_cost(usage, tool, model, pricing)
        day = record["date"]

        daily = daily_map[day]
        daily["date"] = day
        daily["tools"][tool] = daily["tools"].get(tool, 0) + usage["total_tokens"]
        daily["total_tokens"] += usage["total_tokens"]
        daily["cost"] += cost

        add_usage(tool_map[tool]["usage"], usage)
        tool_map[tool]["cost"] += cost

        add_usage(model_map[(tool, model)]["usage"], usage)
        model_map[(tool, model)]["cost"] += cost

    total_tokens = sum(v["usage"]["total_tokens"] for v in tool_map.values())
    total_cost = sum(v["cost"] for v in tool_map.values())
    active_days = len([d for d in daily_map.values() if d["total_tokens"] > 0])

    daily_rows = []
    for day in sorted(daily_map):
        row = daily_map[day]
        tools = {tool: int(row["tools"].get(tool, 0)) for tool in TOOL_COLORS}
        daily_rows.append(
            {
                "date": day,
                "tools": tools,
                "total_tokens": int(row["total_tokens"]),
                "cost": round(float(row["cost"]), 4),
            }
        )

    tool_rows = []
    for tool, item in sorted(
        tool_map.items(), key=lambda kv: kv[1]["usage"]["total_tokens"], reverse=True
    ):
        tokens = item["usage"]["total_tokens"]
        tool_rows.append(
            {
                "tool": tool,
                "tokens": int(tokens),
                "percent": round(tokens / total_tokens * 100, 2) if total_tokens else 0,
                "cost": round(float(item["cost"]), 4),
                "color": TOOL_COLORS.get(tool, "#64748b"),
            }
        )

    model_rows = []
    for (tool, model), item in sorted(
        model_map.items(), key=lambda kv: kv[1]["usage"]["total_tokens"], reverse=True
    ):
        tokens = item["usage"]["total_tokens"]
        model_rows.append(
            {
                "tool": tool,
                "model": model,
                "tokens": int(tokens),
                "percent": round(tokens / total_tokens * 100, 2) if total_tokens else 0,
                "cost": round(float(item["cost"]), 4),
                "color": TOOL_COLORS.get(tool, "#64748b"),
            }
        )

    return {
        "generated_at": dt.datetime.now(_LOCAL_TZ).isoformat(timespec="seconds"),
        "timezone": _TZ_NAME,
        "totals": {
            "tokens": int(total_tokens),
            "cost": round(float(total_cost), 2),
            "active_days": active_days,
        },
        "daily": daily_rows,
        "tools": tool_rows,
        "models": model_rows,
    }


def collect_all(settings: dict[str, Any] | None = None) -> dict[str, Any]:
    if settings:
        configure_timezone(settings.get("timezone"))
    history_days = int((settings or {}).get("history_days", 180) or 180)
    cutoff = source_file_cutoff(history_days)
    pricing = load_pricing()
    cache = load_cache()
    live_paths: set[str] = set()
    codex_records, codex_meta = collect_codex(cache, live_paths, modified_since=cutoff)
    claude_records, claude_meta = collect_claude_code(
        cache, live_paths, modified_since=cutoff
    )
    cc_switch_records, cc_switch_meta = collect_cc_switch_proxy()
    # Drop cache entries for files no longer scanned (deleted or aged past the
    # history window) — matches the macOS collector's livePaths pruning.
    cache["files"] = {p: e for p, e in cache["files"].items() if p in live_paths}
    save_cache(cache)
    records = codex_records + claude_records + cc_switch_records
    result = aggregate(records, pricing)
    result["sources"] = {
        "Codex": codex_meta,
        "Claude Code": claude_meta,
        "CC Switch Proxy": cc_switch_meta,
    }
    return result


# ---------------------------------------------------------------------------
# Output / IO helpers
# ---------------------------------------------------------------------------


def _dashboard_phrase(progress: float) -> str:
    if progress >= 1:
        return "今天已经走满"
    if progress >= 0.65:
        return "快到一个亿了"
    if progress >= 0.3:
        return "节奏不错"
    return "刚开始热身"


def build_dashboard_view(data: dict[str, Any], settings: dict[str, Any] | None = None) -> dict[str, Any]:
    """Derive the 'Today' hero metrics for the dashboard (mirrors macOS TodayView).

    The daily goal is a setting, not part of the usage snapshot, so it is injected
    here along with today's progress and the goal-met day count.
    """
    goal = 100_000_000
    if settings:
        try:
            goal = max(1, int(settings.get("daily_goal_tokens", goal)))
        except Exception:
            goal = 100_000_000
    today = today_row(data)
    today_tokens = int(today.get("total_tokens", 0))
    progress = (today_tokens / goal) if goal > 0 else 0.0
    totals = data.get("totals", {}) or {}
    return {
        "goal": goal,
        "today_tokens": today_tokens,
        "today_cost": float(today.get("cost", 0.0)),
        "today_date": today.get("date", ""),
        "progress": progress,
        "percent": min(progress * 100, 999),
        "phrase": _dashboard_phrase(progress),
        "cumulative": int(totals.get("tokens", 0)),
        "active_days": int(totals.get("active_days", 0)),
        "goal_days": goal_days(data, goal),
        "month_average": month_average(data),
    }


def write_outputs(data: dict[str, Any], settings: dict[str, Any] | None = None) -> None:
    from . import dashboard  # local import to avoid a cycle

    paths.ensure_dirs()
    view = build_dashboard_view(data, settings)
    tmp_json = paths.DATA_JSON.with_suffix(".json.tmp")
    tmp_html = paths.DASHBOARD_HTML.with_suffix(".html.tmp")
    tmp_json.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp_json.replace(paths.DATA_JSON)
    tmp_html.write_text(dashboard.render_dashboard(data, view), encoding="utf-8")
    tmp_html.replace(paths.DASHBOARD_HTML)


def load_snapshot_safe() -> dict[str, Any]:
    try:
        with paths.DATA_JSON.open("r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {
            "generated_at": None,
            "timezone": _TZ_NAME,
            "totals": {"tokens": 0, "cost": 0.0, "active_days": 0},
            "daily": [],
            "tools": [],
            "models": [],
            "sources": {},
        }


def today_row(snapshot: dict[str, Any]) -> dict[str, Any]:
    key = dt.datetime.now(_LOCAL_TZ).date().isoformat()
    daily = snapshot.get("daily") or []
    for row in reversed(daily):
        if row.get("date") == key:
            return row
    if daily:
        return daily[-1]
    return {"date": key, "tools": {}, "total_tokens": 0, "cost": 0.0}


def month_average(snapshot: dict[str, Any]) -> int:
    rows = (snapshot.get("daily") or [])[-30:]
    if not rows:
        return 0
    return sum(int(r.get("total_tokens", 0)) for r in rows) // len(rows)


def goal_days(snapshot: dict[str, Any], goal: int) -> int:
    return len([r for r in (snapshot.get("daily") or []) if int(r.get("total_tokens", 0)) >= goal])


def human_tokens(tokens: int | float) -> str:
    value = float(tokens or 0)
    if value >= 100_000_000:
        return f"{value / 100_000_000:.2f}亿"
    if value >= 10_000:
        return f"{value / 10_000:.1f}万"
    return f"{value:.0f}"


def log_error(exc: BaseException) -> None:
    try:
        paths.ensure_dirs()
        with paths.ERROR_LOG.open("a", encoding="utf-8") as f:
            stamp = dt.datetime.now(_LOCAL_TZ).isoformat(timespec="seconds")
            f.write(f"[{stamp}] {exc!r}\n{traceback.format_exc()}\n")
    except Exception:
        pass
