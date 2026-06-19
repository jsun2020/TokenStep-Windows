# TokenStep for Windows

TokenStep turns your AI token usage into a daily "step ring" — like a step counter,
but for AI coding. It lives in the Windows **system tray**, shows today's progress
toward a token goal, and keeps a local history dashboard.

This is the Windows port of the macOS TokenStep menu-bar app. It reuses the same
cross-platform collector logic and matches the same data format, so the two stay
in sync conceptually. **Kept in sync through macOS v0.1.7.**

> **Credit & thanks:** This is a community **Windows port** of
> [TokenStep](https://github.com/Backtthefuture/TokenStep) (macOS) by **AI产品黄叔
> (Chaoqiang Huang)** — thank you for the original app and the "每天一个亿" idea 🙌
> Licensed under MIT; the original copyright and license are retained. Not affiliated
> with or endorsed by the original author.

## Download

Grab the latest **`TokenStep-<version>-win64.zip`** from
[Releases](https://github.com/jsun2020/TokenStep-Windows/releases), unzip, and run
`TokenStep.exe` — no install, no Python required. (The .exe is unsigned, so Windows
SmartScreen may warn on first run: **More info → Run anyway**.)

## What's new (synced from macOS)

- **0.1.7** — Share-card screenshot. The tray gains **复制今日截图** and
  **保存今日截图…**: TokenStep renders a branded "今日" stats card (logo, step-ring,
  今日完成 %, 消耗/本月均值, 累计/活跃/达标) and copies it to the clipboard or saves
  it as a PNG, so you can share your AI step-count to the community. (`--screenshot
  [path]` also available from the CLI.)
- **0.1.5** — Refreshed brand icon (circular base, ring + 3×3 contribution-green
  token grid), carried into the portable .exe. Dashboard brought to parity with the
  macOS "今日" view: a today step-ring hero (today vs daily goal, completion %,
  消耗金额 / 本月均值), a stat strip with 达标天数, and a daily-goal line on the
  30-day chart.
- **0.1.4** — Accurate OpenAI per-part pricing for Codex GPT-5.5 ($5 / $0.5 cached /
  $30 per 1M) and GPT-5.4 ($2.5 / $0.25 / $15). Affects cost estimates only, not
  token counts.
- **0.1.3** — Incremental collector cache (per-file, keyed by size + mtime): only
  changed logs are re-parsed, so a refresh over hundreds of MB of logs drops from
  ~8s to under 1s. Plus startup update checking (see below).
- Codex daily attribution is JSONL-first (per-event timestamps → correct per-day
  numbers), already the behaviour of this port's collector.

## What it tracks

- **Claude Code** — usage metadata from `~/.claude/projects/**/*.jsonl`
- **Codex** — token metadata from `~/.codex/sessions/**/*.jsonl` (SQLite fallback)

On Windows, `~` is your user folder (e.g. `C:\Users\<you>`), so these are exactly
the same locations the agents already write to.

> **Privacy:** TokenStep only reads usage *metadata* — date, model, client name,
> and token counts. It never reads or uploads your code, prompts, or conversation
> content. All data stays on your machine.

## Features

- **Tray progress ring** — a live icon that fills clockwise as you approach the
  daily goal (default 1 亿 / 100M tokens).
- **Tray menu** — today's AI steps, goal %, estimated cost, and active days.
- **HTML dashboard** — daily bars, per-client and per-model breakdowns, and a
  day-by-day table. Opens in your browser.
- **Settings dialog** — daily goal, refresh interval (manual / 1 / 5 / 15 min),
  and autostart-at-login.
- **Share-card screenshot** — 复制今日截图 / 保存今日截图… render a branded "今日"
  stats card (PNG) to the clipboard or a file, for sharing to the community.
- **Autostart** — optional launch on login via the Windows Run registry key.
- **Update check** — on launch (toggle: 启动时检查更新) and via the tray's
  *检查更新* item, it checks GitHub Releases and, if a newer version exists, shows
  a notification and a link to the download page. It is **check-only**: it never
  silently downloads or installs an .exe.
- **Local storage** — everything under `%APPDATA%\TokenStep`.

## Requirements

- Windows 10/11
- Python 3.10+ with `pystray` and `Pillow` (`tzdata` recommended for accurate
  timezone bucketing)

```powershell
python -m pip install -r requirements.txt
```

## Run (development)

```powershell
.\run.ps1
```

This launches the tray app with `pythonw.exe` (no console window). Look for the
green ring icon in the system tray (you may need to expand the tray overflow `^`).

One-shot data refresh without the UI (handy for testing):

```powershell
python tokenstep_app.py --collect
```

## Build a portable EXE

```powershell
.\build.ps1
```

Produces a single-file, windowed `dist\TokenStep.exe` with no Python install
required on the target machine. Double-click it, or drop a shortcut in
`shell:startup` (or enable **开机自启** in Settings) to run at login.

## Data locations

| Path | Purpose |
|------|---------|
| `%APPDATA%\TokenStep\data\usage.json` | aggregated usage snapshot |
| `%APPDATA%\TokenStep\dashboard.html`  | generated dashboard |
| `%APPDATA%\TokenStep\config\settings.json` | daily goal, interval, history, timezone, update prefs |
| `%APPDATA%\TokenStep\config\pricing.json`  | editable cost estimates |
| `%APPDATA%\TokenStep\cache\collector-cache.json` | per-file parse cache (safe to delete) |
| `%APPDATA%\TokenStep\logs\tokenstep.log`   | error log |

## Settings

`settings.json` matches the macOS app:

```json
{
  "daily_goal_tokens": 100000000,
  "refresh_interval_seconds": 60,
  "history_days": 180,
  "timezone": "Asia/Shanghai",
  "auto_update_enabled": true,
  "ask_before_downloading_updates": true,
  "require_verified_updates": true,
  "skipped_update_version": null
}
```

Cost estimates are approximate (edit `pricing.json`) and are **not** a bill.

## Notes

- **Leaderboard / ranking** is intentionally left out of this first version: it is
  **local-only** for now. The snapshot in `usage.json` is a clean, stable shape to
  POST to a shared backend later — when the group's leaderboard API is known, add
  an uploader that sends `totals` + `daily` (no content) on each refresh.
- Timezone defaults to `Asia/Shanghai`. Windows lacks the IANA tz database; install
  `tzdata` for exact named-zone handling, otherwise it falls back to UTC+8.
