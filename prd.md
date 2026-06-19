# TokenStep for Windows — PRD

---
## Version Update: v0.1.5 (Windows dashboard parity) - 2026-06-19

### Feature Summary
Bring the Windows HTML dashboard to visual/functional parity with the macOS native
"今日" (Today) view: a today step-ring hero, a stat strip including 达标天数, and a
daily-goal line on the 30-day chart.

### Background / Why
A community member's screenshot showed the **macOS native app** (sidebar + rich
"今日" step-ring hero). The Windows port is a **system-tray app** whose "Open
Dashboard" opened a simpler HTML report — so the today step-ring / goal experience
only lived in the tray menu, making the two interfaces look different. This was a
UI-parity gap, not a settings issue and not a data bug (the different totals come
from different people/machines).

### Business Value
- The shared dashboard now looks consistent across macOS and Windows, so community
  members comparing screenshots see the same "step ring" experience.
- Surfaces the daily goal, today's completion %, and 达标天数 where users expect them.

### Solution Overview
`collector.build_dashboard_view(data, settings)` derives the Today metrics (goal,
today tokens, completion %, motivational phrase, 累计/活跃/达标, 本月均值) and
`write_outputs(data, settings)` passes them to `dashboard.render_dashboard(data,
view)`, which renders a CSS conic-gradient ring hero, a 3-card stat strip, and a
dashed daily-goal line over the existing 30-day chart. Token parsing, cache,
updater, icon, and settings are untouched.

### ASCII Prototype
```
+--------------------------------------------------------------+
| 我的 AI 步数                              本地统计·不读取内容 |
+--------------------------------------------------------------+
| 今日                                                         |
|   ( ◜◝ )   今日完成                                          |
|   (6407万)   64%   节奏不错                                  |
|   ( ◟◞ )   [消耗金额 $159]  [本月均值 1.96亿]               |
|   目标 1亿                                                   |
+--------------------------------------------------------------+
| 累计 61.46亿 | 活跃天数 36天 | 达标天数 25天                 |
+--------------------------------------------------------------+
| 最近 30 天   ▂▃▅█▆▃▂ ......... ---- 目标 1亿 (dashed) ----   |
+--------------------------------------------------------------+
| 按客户端 | 主力模型 | 按天明细 | 数据源                      |
+--------------------------------------------------------------+
```

### Affected Components
| Component | Change Type | Description |
|-----------|-------------|-------------|
| `tokenstep/dashboard.py` | Modified | New hero ring + stat strip + goal line; `render_dashboard(data, view)` |
| `tokenstep/collector.py` | Modified | Added `build_dashboard_view` / `_dashboard_phrase`; `write_outputs(data, settings)` |
| `tokenstep/tray.py` | Modified | Passes `self.settings` to `write_outputs` |
| `tokenstep_app.py` | Modified | `--collect` passes settings to `write_outputs` |
| collector parsing / cache / updater / icon / settings / autostart | No Change | Data layer untouched; only the render gained a derived `view` block |

### Key Implementation Points
1. Daily goal is a setting (not in usage.json), so it is injected into the render via `view`.
2. The ring uses a CSS `conic-gradient` capped at 100% even when completion > 100%.
3. The 30-day chart scales to `max(goal, daily max)` so the goal line is always visible.

### Acceptance Criteria
- [x] Dashboard shows today step-ring with today tokens vs goal and completion %
- [x] Motivational phrase matches macOS thresholds (满/快到/节奏/热身)
- [x] Stat strip shows 累计 / 活跃天数 / 达标天数
- [x] 30-day chart shows a dashed daily-goal line
- [x] Existing breakdowns (客户端/模型/明细/数据源) still render
- [x] No change to token counts, cache, or other subsystems
- [x] Portable exe rebuilt with the new dashboard
