# -*- coding: utf-8 -*-
"""Render the local HTML dashboard.

Brings the Windows dashboard to parity with the macOS "今日" view: a today
step-ring hero (today vs daily goal, completion %, motivational phrase, spend and
month average), a stat strip (累计 / 活跃天数 / 达标天数), a 30-day chart with a
daily-goal line, and per-client / per-model breakdowns. Green "step" identity.
"""
from __future__ import annotations

import html
import json
from typing import Any

CODEX_COLOR = "#2DA44E"
CLAUDE_COLOR = "#216E39"


def _json_for_html(data: Any) -> str:
    payload = json.dumps(data, ensure_ascii=False)
    return payload.replace("</", "<\\/")


def render_dashboard(data: dict[str, Any], view: dict[str, Any] | None = None) -> str:
    inline_data = _json_for_html(data)
    inline_view = _json_for_html(view or {})
    generated_at = html.escape(data.get("generated_at") or "等待同步")
    return f"""<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>TokenStep · 我的 AI 步数</title>
  <style>
    :root {{
      --ink: #1f2937;
      --muted: #6b7280;
      --line: #e5e7eb;
      --panel: rgba(255, 255, 255, 0.97);
      --green: #2da44e;
      --green-dark: #216e39;
      --green-bright: #2fca63;
      --mint: #d8f3dc;
      --track: #e7edf0;
      --codex: {CODEX_COLOR};
      --claude: {CLAUDE_COLOR};
    }}
    * {{ box-sizing: border-box; }}
    html, body {{ max-width: 100%; overflow-x: hidden; }}
    body {{
      margin: 0;
      min-height: 100vh;
      font-family: ui-sans-serif, -apple-system, "Segoe UI", "Microsoft YaHei", "PingFang SC", sans-serif;
      color: var(--ink);
      background:
        radial-gradient(circle at 15% 10%, rgba(255, 255, 255, 0.5), transparent 30%),
        linear-gradient(135deg, #2da44e 0%, #1f9d57 45%, #16a34a 100%);
      padding: 28px;
    }}
    .shell {{
      max-width: 1180px;
      margin: 0 auto;
      background: var(--panel);
      border: 1px solid rgba(255,255,255,.75);
      border-radius: 28px;
      box-shadow: 0 32px 80px rgba(17, 24, 39, .22);
      padding: 34px clamp(20px, 4vw, 52px) 48px;
      overflow: hidden;
    }}
    header {{ display: flex; justify-content: space-between; align-items: flex-start; gap: 18px; margin-bottom: 26px; }}
    h1 {{ margin: 0; font-size: clamp(28px, 4vw, 44px); line-height: 1.08; }}
    .updated {{ margin-top: 8px; color: var(--muted); font-size: 14px; }}
    .actions {{ display: flex; gap: 10px; align-items: center; color: var(--muted); white-space: nowrap; font-size: 15px; }}

    /* Today hero */
    .hero {{ border: 1px solid var(--line); background: #fff; border-radius: 20px; padding: 30px clamp(20px, 3vw, 38px); }}
    .hero-eyebrow {{ font-size: 22px; font-weight: 800; }}
    .hero-eyebrow small {{ display:block; font-size: 14px; font-weight: 600; color: var(--muted); margin-top: 4px; }}
    .hero-grid {{ display: flex; align-items: center; gap: clamp(20px, 4vw, 48px); margin-top: 18px; flex-wrap: wrap; }}
    .ring {{
      width: 200px; height: 200px; border-radius: 50%; flex: 0 0 auto;
      background: conic-gradient(var(--green) calc(var(--p, 0) * 1%), var(--track) 0);
      display: grid; place-items: center;
      box-shadow: 0 10px 26px rgba(33, 110, 57, .18);
    }}
    .ring-hole {{ width: 150px; height: 150px; border-radius: 50%; background: #fff; display: grid; place-items: center; text-align: center; }}
    .ring-top {{ font-size: 34px; font-weight: 800; line-height: 1; }}
    .ring-sub {{ font-size: 15px; font-weight: 700; color: var(--muted); margin-top: 8px; }}
    .hero-right {{ flex: 1 1 260px; min-width: 240px; }}
    .hero-label {{ font-size: 16px; font-weight: 700; color: var(--muted); }}
    .hero-pct {{ font-size: clamp(44px, 6vw, 60px); font-weight: 800; line-height: 1.02; margin: 6px 0 2px; }}
    .hero-phrase {{ font-size: 20px; font-weight: 800; color: var(--green-dark); margin-bottom: 16px; }}
    .pills {{ display: flex; gap: 12px; flex-wrap: wrap; }}
    .pill {{ background: #f6faf7; border: 1px solid #e6efe9; border-radius: 14px; padding: 12px 16px; }}
    .pill span {{ display: block; font-size: 13px; color: var(--muted); font-weight: 700; }}
    .pill b {{ font-size: 20px; }}

    .cards {{ display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 18px; margin-top: 22px; }}
    .metric {{ border: 1px solid var(--line); background: #fff; border-radius: 16px; padding: 24px 26px; }}
    .metric .value {{ font-size: clamp(28px, 4vw, 40px); font-weight: 800; line-height: 1; }}
    .metric .label {{ color: #9ca3af; margin-top: 10px; font-size: 17px; font-weight: 700; }}
    .metric .detail {{ color: #b6bcc4; margin-top: 4px; font-size: 13px; font-weight: 600; }}

    .panel {{ border: 1px solid var(--line); background: #fff; border-radius: 16px; padding: 28px; margin-top: 22px; overflow: hidden; }}
    .panel h2 {{ margin: 0 0 18px; font-size: 23px; }}
    .legend {{ display: flex; gap: 22px; flex-wrap: wrap; color: var(--muted); font-size: 16px; margin-bottom: 16px; }}
    .legend span {{ display: inline-flex; align-items: center; gap: 8px; font-weight: 700; }}
    .dot {{ width: 12px; height: 12px; border-radius: 999px; display: inline-block; }}
    .chart-wrap {{ height: 320px; display: grid; grid-template-rows: 1fr auto; gap: 10px; }}
    .chart {{ position: relative; height: 100%; display: flex; gap: 4px; align-items: flex-end; padding-top: 14px; border-bottom: 1px solid var(--line); overflow: hidden; }}
    .bar {{ flex: 1 1 7px; min-width: 3px; max-width: 14px; height: 100%; display: flex; flex-direction: column-reverse; border-radius: 4px 4px 0 0; overflow: hidden; }}
    .seg {{ width: 100%; min-height: 1px; }}
    .goal-line {{ position: absolute; left: 0; right: 0; border-top: 2px dashed rgba(33,110,57,.55); pointer-events: none; }}
    .goal-tag {{ position: absolute; right: 0; transform: translateY(-50%); font-size: 12px; font-weight: 700; color: var(--green-dark); background: rgba(216,243,220,.85); padding: 1px 7px; border-radius: 999px; }}
    .axis {{ display: flex; justify-content: space-between; color: #9ca3af; font-size: 15px; font-weight: 700; }}
    .rows {{ display: grid; gap: 16px; }}
    .usage-row {{ display: grid; grid-template-columns: minmax(110px, 170px) minmax(120px, 1fr) minmax(110px, auto); gap: 18px; align-items: center; min-height: 32px; }}
    .name {{ color: #4b5563; font-size: 18px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }}
    .track {{ height: 12px; background: #f1f3f6; border-radius: 999px; overflow: hidden; }}
    .fill {{ height: 100%; border-radius: 999px; min-width: 4px; }}
    .amount {{ color: #6b7280; font-size: 17px; font-weight: 700; text-align: right; white-space: nowrap; }}
    table {{ width: 100%; border-collapse: collapse; font-size: 16px; }}
    th, td {{ padding: 13px 6px; border-bottom: 1px solid #f0f1f3; text-align: right; white-space: nowrap; }}
    th:first-child, td:first-child {{ text-align: left; }}
    th {{ color: #9ca3af; font-size: 14px; font-weight: 800; }}
    td {{ color: #4b5563; font-weight: 600; }}
    td.total {{ color: #111827; font-weight: 800; }}
    .source-grid {{ display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 12px; color: var(--muted); font-size: 14px; }}
    .source {{ background: #f9fafb; border: 1px solid #eef0f3; border-radius: 12px; padding: 12px; }}
    .source b {{ color: var(--ink); display: block; margin-bottom: 6px; }}
    @media (max-width: 820px) {{
      body {{ padding: 12px; }}
      .shell {{ border-radius: 22px; padding: 24px 16px 34px; }}
      header {{ flex-direction: column; }}
      .cards, .source-grid {{ grid-template-columns: 1fr; }}
      .panel {{ padding: 20px 14px; }}
      .chart-wrap {{ height: 240px; }}
      .hero-grid {{ justify-content: center; }}
    }}
  </style>
</head>
<body>
  <main class="shell">
    <header>
      <div>
        <h1>我的 AI 步数</h1>
        <div class="updated">更新于 {generated_at} · TokenStep for Windows</div>
      </div>
      <div class="actions">本地统计 · 只统计数量，不读取内容</div>
    </header>

    <section class="hero">
      <div class="hero-eyebrow">今日<small>今天和 AI 一起走了多远</small></div>
      <div class="hero-grid">
        <div class="ring" id="ring">
          <div class="ring-hole">
            <div class="ring-top" id="todayTokens">-</div>
            <div class="ring-sub" id="goalText">目标 -</div>
          </div>
        </div>
        <div class="hero-right">
          <div class="hero-label">今日完成</div>
          <div class="hero-pct" id="pct">-</div>
          <div class="hero-phrase" id="phrase">-</div>
          <div class="pills">
            <div class="pill"><span>消耗金额</span><b id="todayCost">-</b></div>
            <div class="pill"><span>本月均值</span><b id="monthAvg">-</b></div>
          </div>
        </div>
      </div>
    </section>

    <section class="cards">
      <div class="metric"><div class="value" id="cumulative">-</div><div class="label">累计 AI 步数</div><div class="detail">所有本机记录</div></div>
      <div class="metric"><div class="value" id="activeDays">-</div><div class="label">活跃天数</div><div class="detail">有 AI 使用的日期</div></div>
      <div class="metric"><div class="value" id="goalDays">-</div><div class="label">达标天数</div><div class="detail">达到每日目标</div></div>
    </section>

    <section class="panel">
      <h2>最近 30 天</h2>
      <div class="legend">
        <span><i class="dot" style="background:var(--codex)"></i>Codex</span>
        <span><i class="dot" style="background:var(--claude)"></i>Claude Code</span>
        <span style="color:#9ca3af">细线是每日目标</span>
      </div>
      <div class="chart-wrap">
        <div class="chart" id="chart"></div>
        <div class="axis"><span id="firstDate">-</span><span id="lastDate">-</span></div>
      </div>
    </section>

    <section class="panel">
      <h2>按客户端</h2>
      <div class="rows" id="tools"></div>
    </section>

    <section class="panel">
      <h2>主力模型</h2>
      <div class="rows" id="models"></div>
    </section>

    <section class="panel">
      <h2>按天明细</h2>
      <div style="overflow:auto">
        <table>
          <thead>
            <tr><th>日期</th><th>Codex</th><th>Claude Code</th><th>合计</th><th>预估成本</th></tr>
          </thead>
          <tbody id="dailyRows"></tbody>
        </table>
      </div>
    </section>

    <section class="panel">
      <h2>数据源</h2>
      <div class="source-grid" id="sources"></div>
    </section>
  </main>

  <script>
    window.USAGE_DATA = {inline_data};
    window.VIEW = {inline_view};
    const data = window.USAGE_DATA;
    const view = window.VIEW || {{}};
    const colors = {{ "Codex": "{CODEX_COLOR}", "Claude Code": "{CLAUDE_COLOR}" }};
    const tools = ["Codex", "Claude Code"];

    function trimNum(s) {{ return String(s).replace(/\\.0+$/, "").replace(/(\\.\\d*?)0+$/, "$1"); }}
    function fmtTokens(n) {{
      n = Number(n || 0);
      if (n >= 100000000) return trimNum((n / 100000000).toFixed(2)) + "亿";
      if (n >= 10000) return trimNum((n / 10000).toFixed(1)) + "万";
      return Math.round(n).toString();
    }}
    function fmtMoney(n) {{
      return "$" + Number(n || 0).toLocaleString(undefined, {{ minimumFractionDigits: 2, maximumFractionDigits: 2 }});
    }}
    function shortDate(s) {{ return String(s || "").slice(0, 10); }}
    function axisDate(s) {{ const v = shortDate(s); return window.innerWidth < 520 ? v.slice(5) : v; }}

    // Today hero
    const goal = Number(view.goal || 0);
    const todayTokens = Number(view.today_tokens || 0);
    const pct = Number(view.percent || 0);
    document.getElementById("todayTokens").textContent = fmtTokens(todayTokens);
    document.getElementById("goalText").textContent = "目标 " + fmtTokens(goal);
    document.getElementById("pct").textContent = Math.round(pct) + "%";
    document.getElementById("phrase").textContent = view.phrase || "";
    document.getElementById("todayCost").textContent = fmtMoney(view.today_cost);
    document.getElementById("monthAvg").textContent = fmtTokens(view.month_average);
    document.getElementById("ring").style.setProperty("--p", Math.max(0, Math.min(100, pct)));

    document.getElementById("cumulative").textContent = fmtTokens(view.cumulative != null ? view.cumulative : data.totals.tokens);
    document.getElementById("activeDays").textContent = (view.active_days != null ? view.active_days : data.totals.active_days) + " 天";
    document.getElementById("goalDays").textContent = (view.goal_days || 0) + " 天";

    // 30-day chart with daily-goal line
    const chartData = (data.daily || []).slice(-30);
    const max = Math.max(1, goal, ...chartData.map(d => d.total_tokens));
    const chart = document.getElementById("chart");
    chart.innerHTML = chartData.map(day => {{
      const height = Math.max(1, day.total_tokens / max * 100);
      const segments = tools.map(tool => {{
        const value = (day.tools && day.tools[tool]) || 0;
        if (!value) return "";
        const segPct = Math.max(1, value / day.total_tokens * 100);
        return `<div class="seg" style="height:${{segPct}}%;background:${{colors[tool]}}" title="${{tool}} ${{fmtTokens(value)}}"></div>`;
      }}).join("");
      return `<div class="bar" style="height:${{height}}%" title="${{day.date}} ${{fmtTokens(day.total_tokens)}}">${{segments}}</div>`;
    }}).join("");
    if (goal > 0 && goal <= max) {{
      const bottomPct = goal / max * 100;
      const line = document.createElement("div");
      line.className = "goal-line";
      line.style.bottom = bottomPct + "%";
      line.innerHTML = `<span class="goal-tag">目标 ${{fmtTokens(goal)}}</span>`;
      chart.appendChild(line);
    }}
    document.getElementById("firstDate").textContent = axisDate(chartData[0]?.date || "-");
    document.getElementById("lastDate").textContent = axisDate(chartData[chartData.length - 1]?.date || "-");

    function renderRows(id, rows, nameFn) {{
      const host = document.getElementById(id);
      rows = rows || [];
      const maxTokens = Math.max(1, ...rows.map(r => r.tokens));
      host.innerHTML = rows.slice(0, 12).map(row => {{
        const width = Math.max(1, row.tokens / maxTokens * 100);
        return `<div class="usage-row">
          <div class="name" title="${{nameFn(row)}}">${{nameFn(row)}}</div>
          <div class="track"><div class="fill" style="width:${{width}}%;background:${{row.color}}"></div></div>
          <div class="amount">${{fmtTokens(row.tokens)}} · ${{(row.percent||0).toFixed(1)}}%</div>
        </div>`;
      }}).join("");
    }}
    renderRows("tools", data.tools, row => row.tool);
    renderRows("models", data.models, row => row.model);

    const dailyRows = document.getElementById("dailyRows");
    dailyRows.innerHTML = (data.daily || []).slice().reverse().slice(0, 45).map(day => `
      <tr>
        <td>${{shortDate(day.date)}}</td>
        <td>${{day.tools && day.tools.Codex ? fmtTokens(day.tools.Codex) : "—"}}</td>
        <td>${{day.tools && day.tools["Claude Code"] ? fmtTokens(day.tools["Claude Code"]) : "—"}}</td>
        <td class="total">${{fmtTokens(day.total_tokens)}}</td>
        <td>${{fmtMoney(day.cost)}}</td>
      </tr>
    `).join("");

    const sources = document.getElementById("sources");
    sources.innerHTML = Object.entries(data.sources || {{}}).map(([name, meta]) => `
      <div class="source">
        <b>${{name}}</b>
        状态：${{meta.status || "unknown"}}<br>
        文件：${{meta.files || 0}} · 记录：${{meta.records || 0}}
      </div>
    `).join("");
  </script>
</body>
</html>
"""
