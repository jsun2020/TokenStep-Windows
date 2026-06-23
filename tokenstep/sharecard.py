# -*- coding: utf-8 -*-
"""Share-card screenshot.

Windows equivalent of the macOS v0.1.7 screenshot/share feature. Instead of
capturing the desktop, it renders a branded TokenStep "今日" stats card to a PNG
(with Pillow, no extra dependencies) so the user can share their AI step-count to
the community. Supports copy-to-clipboard and save-to-file.
"""
from __future__ import annotations

import datetime as dt
import io
import os
from pathlib import Path
from typing import Any

from PIL import Image, ImageChops, ImageDraw, ImageFilter, ImageFont

from . import appicon

SCALE = 2  # supersample for crisp text/arcs, downscaled on output
W = 1080
H = 824

# Palette (matches the dashboard / icon).
GREEN = (45, 164, 78)
GREEN_DARK = (33, 110, 57)
INK = (31, 41, 55)
MUTED = (107, 114, 128)
TRACK = (231, 237, 240)
PANEL = (255, 255, 255)
PILL_BG = (246, 250, 247)
PILL_LINE = (230, 239, 233)

_FONT_DIR = Path(os.environ.get("WINDIR", r"C:\Windows")) / "Fonts"
_FONT_CACHE: dict[tuple[int, bool], Any] = {}


def _font(size: int, bold: bool = False) -> ImageFont.FreeTypeFont:
    key = (size, bold)
    cached = _FONT_CACHE.get(key)
    if cached is not None:
        return cached
    names = ["msyhbd.ttc", "msyh.ttc", "simhei.ttf"] if bold else ["msyh.ttc", "simhei.ttf", "msyhbd.ttc"]
    for name in names:
        path = _FONT_DIR / name
        if path.exists():
            try:
                font = ImageFont.truetype(str(path), size)
                _FONT_CACHE[key] = font
                return font
            except Exception:
                continue
    font = ImageFont.load_default()
    _FONT_CACHE[key] = font
    return font


def _trim(value: str) -> str:
    return value.rstrip("0").rstrip(".") if "." in value else value


def fmt_tokens(n: float) -> str:
    n = float(n or 0)
    if n >= 100_000_000:
        return _trim(f"{n / 100_000_000:.2f}") + "亿"
    if n >= 10_000:
        return _trim(f"{n / 10_000:.1f}") + "万"
    return str(int(n))


def fmt_money(v: float) -> str:
    return f"${float(v or 0):,.2f}"


def default_filename(prefix: str = "today", now: dt.datetime | None = None) -> str:
    now = now or dt.datetime.now()
    return f"TokenStep-{prefix}-{now:%Y%m%d-%H%M}.png"


def _s(v: float) -> int:
    return round(v * SCALE)


def render_share_card(snapshot: dict[str, Any], view: dict[str, Any]) -> Image.Image:
    """Render the 'today' share card from a usage snapshot + dashboard view."""
    img = Image.new("RGB", (_s(W), _s(H)), GREEN)
    draw = ImageDraw.Draw(img)

    # Background: vertical green gradient.
    top, bottom = (45, 164, 78), (22, 163, 74)
    for y in range(_s(H)):
        t = y / max(1, _s(H) - 1)
        draw.line(
            [(0, y), (_s(W), y)],
            fill=(
                round(top[0] + (bottom[0] - top[0]) * t),
                round(top[1] + (bottom[1] - top[1]) * t),
                round(top[2] + (bottom[2] - top[2]) * t),
            ),
        )

    # White rounded panel.
    draw.rounded_rectangle((_s(36), _s(36), _s(W - 36), _s(H - 36)), radius=_s(40), fill=PANEL)

    left, right = 92, W - 92

    # Header: logo + brand (left), section + update time (right).
    logo = appicon.render(_s(88)).convert("RGBA")
    img.paste(logo, (_s(left), _s(70)), logo)
    draw.text((_s(left + 108), _s(74)), "TokenStep", font=_font(_s(38), bold=True), fill=INK)
    draw.text((_s(left + 110), _s(126)), "每天一个亿", font=_font(_s(24), bold=True), fill=GREEN_DARK)
    draw.text((_s(right), _s(74)), "今日", font=_font(_s(40), bold=True), fill=INK, anchor="ra")
    updated = view.get("today_date") or (snapshot.get("generated_at") or "")[:16].replace("T", " ")
    draw.text((_s(right), _s(132)), f"更新 {updated}", font=_font(_s(20)), fill=MUTED, anchor="ra")

    draw.line((_s(left), _s(184), _s(right), _s(184)), fill=(238, 240, 243), width=_s(2))

    # Hero ring.
    goal = max(1, int(view.get("goal", 100_000_000)))
    today_tokens = int(view.get("today_tokens", 0))
    pct = float(view.get("percent", 0))
    cx, cy, radius, ring_w = 250, 392, 132, 30
    box = (_s(cx - radius), _s(cy - radius), _s(cx + radius), _s(cy + radius))
    draw.arc(box, 0, 360, fill=TRACK, width=_s(ring_w))
    if pct > 0:
        draw.arc(box, -90, -90 + 360 * min(pct, 100) / 100.0, fill=GREEN, width=_s(ring_w))
    draw.text((_s(cx), _s(cy - 6)), fmt_tokens(today_tokens), font=_font(_s(50), bold=True), fill=INK, anchor="mm")
    draw.text((_s(cx), _s(cy + 44)), f"目标 {fmt_tokens(goal)}", font=_font(_s(22), bold=True), fill=MUTED, anchor="mm")

    # Hero right: completion %, phrase, pills.
    hx = 470
    draw.text((_s(hx), _s(300)), "今日完成", font=_font(_s(26), bold=True), fill=MUTED)
    draw.text((_s(hx), _s(330)), f"{round(pct)}%", font=_font(_s(78), bold=True), fill=INK)
    draw.text((_s(hx), _s(448)), view.get("phrase", ""), font=_font(_s(32), bold=True), fill=GREEN_DARK)

    _pill(draw, hx, 500, 210, "消耗金额", fmt_money(view.get("today_cost")))
    _pill(draw, hx + 226, 500, 210, "本月均值", fmt_tokens(view.get("month_average")))

    # Stat strip.
    tiles = [
        ("累计 AI 步数", fmt_tokens(view.get("cumulative")), "所有本机记录"),
        ("活跃天数", f"{int(view.get('active_days', 0))} 天", "有 AI 使用的日期"),
        ("达标天数", f"{int(view.get('goal_days', 0))} 天", "达到每日目标"),
    ]
    gap = 20
    tile_w = (right - left - gap * 2) / 3
    ty, th = 588, 146
    for i, (label, value, detail) in enumerate(tiles):
        tx = left + i * (tile_w + gap)
        draw.rounded_rectangle(
            (_s(tx), _s(ty), _s(tx + tile_w), _s(ty + th)), radius=_s(18), fill=PILL_BG, outline=PILL_LINE, width=_s(1)
        )
        draw.text((_s(tx + 26), _s(ty + 26)), value, font=_font(_s(42), bold=True), fill=INK)
        draw.text((_s(tx + 26), _s(ty + 88)), label, font=_font(_s(23), bold=True), fill=MUTED)
        draw.text((_s(tx + 26), _s(ty + 120)), detail, font=_font(_s(17)), fill=(176, 188, 196))

    # Footer.
    draw.text((_s(left), _s(752)), "本地统计 · 不上传内容 · TokenStep for Windows", font=_font(_s(20)), fill=MUTED)
    draw.text((_s(right), _s(752)), f"{dt.datetime.now():%Y-%m-%d}", font=_font(_s(20), bold=True), fill=MUTED, anchor="ra")

    return img.resize((W, H), Image.Resampling.LANCZOS)


def _pill(draw: ImageDraw.ImageDraw, x: float, y: float, w: float, label: str, value: str) -> None:
    draw.rounded_rectangle(
        (_s(x), _s(y), _s(x + w), _s(y + 72)), radius=_s(14), fill=PILL_BG, outline=PILL_LINE, width=_s(1)
    )
    draw.text((_s(x + 18), _s(y + 12)), label, font=_font(_s(17), bold=True), fill=MUTED)
    draw.text((_s(x + 18), _s(y + 36)), value, font=_font(_s(24), bold=True), fill=INK)


# ---------------------------------------------------------------------------
# Yesterday AI Rhythm share card (macOS 0.1.42 ShareRhythmCardView parity).
# Dark, neon style: a per-pattern gradient backdrop, a smoothed glowing usage
# wave with a peak marker, a peak capsule, the token console, three metrics, and
# a privacy footer. Hand-drawn Pillow glyphs stand in for the macOS SF Symbols.
# ---------------------------------------------------------------------------

RW = 600  # rhythm card logical width
RH = 840  # rhythm card logical height


def _rhythm_palette(tag: str) -> dict[str, Any]:
    if tag == "night_agent":
        return {
            "bg": [(2, 6, 17), (3, 14, 25), (8, 12, 35)],
            "accent": (74, 247, 139), "secondary": (62, 192, 255),
            "night": (45, 108, 255), "panel": (4, 38, 43),
        }
    if tag in ("morning_planner", "early_starter"):
        return {
            "bg": [(3, 15, 12), (4, 35, 27), (31, 30, 13)],
            "accent": (85, 246, 151), "secondary": (255, 190, 44),
            "night": (47, 152, 255), "panel": (4, 41, 34),
        }
    if tag in ("fragmented", "double_peak"):
        return {
            "bg": [(5, 8, 18), (4, 28, 27), (20, 12, 42)],
            "accent": (80, 246, 144), "secondary": (46, 214, 255),
            "night": (105, 92, 255), "panel": (5, 37, 42),
        }
    return {
        "bg": [(1, 10, 7), (3, 22, 17), (2, 19, 31)],
        "accent": (79, 244, 138), "secondary": (49, 205, 255),
        "night": (41, 104, 255), "panel": (3, 38, 41),
    }


def _lerp(a, b, t: float):
    return tuple(int(round(a[k] + (b[k] - a[k]) * t)) for k in range(3))


def _lerp_stops(stops, t: float):
    t = max(0.0, min(1.0, t))
    n = len(stops) - 1
    seg = min(int(t * n), n - 1)
    return _lerp(stops[seg], stops[seg + 1], t * n - seg)


def _diag_gradient(w: int, h: int, stops) -> Image.Image:
    """Diagonal (top-left -> bottom-right) multi-stop gradient, upscaled from a
    small swatch so the per-pixel loop stays cheap."""
    gw = gh = 128
    g = Image.new("RGB", (gw, gh))
    px = g.load()
    for y in range(gh):
        for x in range(gw):
            px[x, y] = _lerp_stops(stops, (x / (gw - 1) + y / (gh - 1)) / 2)
    return g.resize((w, h), Image.Resampling.BILINEAR)


def _radial_layer(w: int, h: int, cx: float, cy: float, radius: float, max_alpha: int) -> Image.Image:
    """An L-mode radial falloff mask (bright at center -> 0 at radius)."""
    gw = gh = 110
    layer = Image.new("L", (gw, gh), 0)
    px = layer.load()
    for y in range(gh):
        for x in range(gw):
            dx = (x / gw * w - cx) / radius
            dy = (y / gh * h - cy) / radius
            d = (dx * dx + dy * dy) ** 0.5
            a = max(0.0, 1.0 - d)
            px[x, y] = int(max_alpha * a * a)
    return layer.resize((w, h), Image.Resampling.BILINEAR)


def _add_glow(base: Image.Image, color, cx: float, cy: float, radius: float, max_alpha: int) -> None:
    mask = _radial_layer(base.width, base.height, cx, cy, radius, max_alpha)
    solid = Image.new("RGB", base.size, color)
    base.paste(solid, (0, 0), mask)


def _linear_swatch(w: int, h: int, colors, vertical: bool = False) -> Image.Image:
    img = Image.new("RGB", (w, h))
    px = img.load()
    span = h if vertical else w
    line = [_lerp_stops(colors, i / max(1, span - 1)) for i in range(span)]
    for y in range(h):
        for x in range(w):
            px[x, y] = line[y] if vertical else line[x]
    return img


def _anchor_xy(x: float, y: float, w: int, h: int, anchor: str) -> tuple[int, int]:
    ha = anchor[0] if anchor else "l"
    va = anchor[1] if len(anchor) > 1 else "a"
    ax = x - (w if ha == "r" else w / 2 if ha == "m" else 0)
    ay = y - (h if va in ("b", "d", "s") else h / 2 if va == "m" else 0)
    return int(round(ax)), int(round(ay))


def _gradient_text(img: Image.Image, x: float, y: float, text: str, font,
                   colors, anchor: str = "la", vertical: bool = False) -> None:
    if not text:
        return
    d = ImageDraw.Draw(img)
    l, t, r, b = d.textbbox((0, 0), text, font=font, anchor="la")
    w = max(1, r - l)
    h = max(1, b - t)
    mask = Image.new("L", (w, h), 0)
    ImageDraw.Draw(mask).text((-l, -t), text, font=font, fill=255, anchor="la")
    swatch = _linear_swatch(w, h, colors, vertical)
    img.paste(swatch, _anchor_xy(x, y, w, h, anchor), mask)


# -- hand-drawn glyphs (RGBA, sized) ---------------------------------------

def _g_crescent(size: int, color) -> Image.Image:
    s = size
    m = Image.new("L", (s, s), 0)
    d = ImageDraw.Draw(m)
    d.ellipse([s * 0.05, s * 0.05, s * 0.95, s * 0.95], fill=255)
    d.ellipse([s * 0.34, s * -0.02, s * 1.2, s * 0.86], fill=0)
    out = Image.new("RGBA", (s, s), color + (0,))
    out.putalpha(m)
    return out


def _g_moonstars(size: int, color) -> Image.Image:
    out = _g_crescent(size, color)
    d = ImageDraw.Draw(out)
    r = max(1, size // 16)
    for cx, cy in ((size * 0.74, size * 0.22), (size * 0.86, size * 0.5)):
        d.ellipse([cx - r, cy - r, cx + r, cy + r], fill=color + (255,))
    return out


def _g_sun(size: int, color) -> Image.Image:
    s = size
    out = Image.new("RGBA", (s, s), color + (0,))
    d = ImageDraw.Draw(out)
    c = s / 2
    rr = s * 0.24
    d.ellipse([c - rr, c - rr, c + rr, c + rr], fill=color + (255,))
    import math as _m
    ray = s * 0.42
    inner = s * 0.30
    for i in range(8):
        ang = i * _m.pi / 4
        d.line([(c + inner * _m.cos(ang), c + inner * _m.sin(ang)),
                (c + ray * _m.cos(ang), c + ray * _m.sin(ang))],
               fill=color + (255,), width=max(1, s // 12))
    return out


def _g_scope(size: int, color) -> Image.Image:
    s = size
    out = Image.new("RGBA", (s, s), (0, 0, 0, 0))
    d = ImageDraw.Draw(out)
    lw = max(2, s // 10)
    d.ellipse([lw, lw, s - lw, s - lw], outline=color + (255,), width=lw)
    d.line([(s / 2, 0), (s / 2, s)], fill=color + (255,), width=max(1, s // 14))
    d.line([(0, s / 2), (s, s / 2)], fill=color + (255,), width=max(1, s // 14))
    rr = s * 0.12
    d.ellipse([s / 2 - rr, s / 2 - rr, s / 2 + rr, s / 2 + rr], fill=color + (255,))
    return out


def _g_lock(size: int, color) -> Image.Image:
    s = size
    out = Image.new("RGBA", (s, s), (0, 0, 0, 0))
    d = ImageDraw.Draw(out)
    lw = max(2, s // 9)
    d.arc([s * 0.28, s * 0.08, s * 0.72, s * 0.6], 180, 360, fill=color + (255,), width=lw)
    d.rounded_rectangle([s * 0.2, s * 0.42, s * 0.8, s * 0.9], radius=s * 0.12, fill=color + (255,))
    return out


def _g_clock(size: int, color) -> Image.Image:
    s = size
    out = Image.new("RGBA", (s, s), (0, 0, 0, 0))
    d = ImageDraw.Draw(out)
    lw = max(2, s // 10)
    d.ellipse([lw, lw, s - lw, s - lw], outline=color + (255,), width=lw)
    c = s / 2
    d.line([(c, c), (c, s * 0.26)], fill=color + (255,), width=lw)
    d.line([(c, c), (s * 0.7, c)], fill=color + (255,), width=lw)
    return out


def _g_timer(size: int, color) -> Image.Image:
    s = size
    out = Image.new("RGBA", (s, s), (0, 0, 0, 0))
    d = ImageDraw.Draw(out)
    lw = max(2, s // 10)
    d.ellipse([lw, s * 0.18, s - lw, s - lw], outline=color + (255,), width=lw)
    d.line([(s * 0.36, s * 0.06), (s * 0.64, s * 0.06)], fill=color + (255,), width=lw)
    d.line([(s / 2, s * 0.06), (s / 2, s * 0.2)], fill=color + (255,), width=lw)
    c = s / 2 + s * 0.05
    d.line([(s / 2, c), (s / 2, s * 0.42)], fill=color + (255,), width=lw)
    return out


def _paste_glyph(base: Image.Image, glyph: Image.Image, cx: float, cy: float) -> None:
    base.paste(glyph, (int(cx - glyph.width / 2), int(cy - glyph.height / 2)), glyph)


def _draw_laurel(draw: ImageDraw.ImageDraw, cx: float, cy: float, h: float, color, mirrored: bool) -> None:
    """A small laurel sprig (curved stalk + leaves) flanking the tag title."""
    w = h * 0.7
    direction = -1 if mirrored else 1
    base = (cx, cy + h / 2)
    tip = (cx + direction * w * 0.5, cy - h / 2)
    ctrl = (cx + direction * w * 0.62, cy)
    draw.line([base, ctrl, tip], fill=color, width=max(1, int(h * 0.045)), joint="curve")
    for i in range(5):
        ly = cy + h * 0.32 - i * h * 0.15
        lx = cx + direction * (i * w * 0.07)
        leaf_w = w * 0.32
        leaf_h = h * 0.12
        x_a, x_b = sorted((lx, lx + direction * leaf_w))
        draw.ellipse([x_a, ly - leaf_h / 2, x_b, ly + leaf_h / 2], fill=color)


# -- wave geometry ----------------------------------------------------------

def _rhythm_wave_values(buckets: list[int]) -> list[float]:
    raw = [float(b) for b in buckets]

    def smooth(i: int) -> float:
        def v(o: int) -> float:
            j = i + o
            return raw[j] if 0 <= j < len(raw) else 0.0
        return v(0) * 0.78 + (v(-1) + v(1)) * 0.09 + (v(-2) + v(2)) * 0.02

    smoothed = [smooth(i) for i in range(len(raw))]
    mx = max(max(smoothed) if smoothed else 0.0, 1.0)
    out = []
    for v in smoothed:
        if v <= 0:
            out.append(0.04)
            continue
        norm = (min(v / mx, 1.0)) ** 0.68
        out.append(max(0.08, min(norm, 1.0)))
    return out


def _rhythm_points(values, left, right, top, bottom):
    n = len(values)
    denom = max(n - 1, 1)
    base_gap = (bottom - top) * 0.10
    head = (bottom - top) * 0.20
    usable = (bottom - top) - head
    pts = []
    for i, v in enumerate(values):
        x = left + (right - left) * i / denom
        y = bottom - base_gap - max(0.0, min(v, 1.0)) * usable
        pts.append((x, y))
    return pts


def _catmull(points, samples: int = 16):
    if len(points) < 2:
        return list(points)
    out = []
    n = len(points)
    for i in range(n - 1):
        p0 = points[max(i - 1, 0)]
        p1 = points[i]
        p2 = points[i + 1]
        p3 = points[min(i + 2, n - 1)]
        c1 = (p1[0] + (p2[0] - p0[0]) / 6, p1[1] + (p2[1] - p0[1]) / 6)
        c2 = (p2[0] - (p3[0] - p1[0]) / 6, p2[1] - (p3[1] - p1[1]) / 6)
        for s in range(samples):
            t = s / samples
            mt = 1 - t
            x = mt ** 3 * p1[0] + 3 * mt * mt * t * c1[0] + 3 * mt * t * t * c2[0] + t ** 3 * p2[0]
            y = mt ** 3 * p1[1] + 3 * mt * mt * t * c1[1] + 3 * mt * t * t * c2[1] + t ** 3 * p2[1]
            out.append((x, y))
    out.append(points[-1])
    return out


def _fmt_peak_window(peak_hour) -> str:
    if peak_hour is None:
        return "--"
    return f"{peak_hour:02d}:00-{(peak_hour + 1) % 24:02d}:00"


def render_rhythm_card(rhythm: dict[str, Any], brand_sub: str = "AI Token 使用追踪") -> Image.Image:
    """Render the 'Yesterday AI Rhythm' share card from a rhythm dict."""
    tag = rhythm.get("primary_tag", "quiet_day")
    pal = _rhythm_palette(tag)
    accent, secondary, night, panel = pal["accent"], pal["secondary"], pal["night"], pal["panel"]
    white = (255, 255, 255)

    W, H = _s(RW), _s(RH)
    img = _diag_gradient(W, H, pal["bg"]).convert("RGB")
    _add_glow(img, accent, _s(70), _s(720), _s(440), 70)
    _add_glow(img, secondary, _s(540), _s(120), _s(360), 46)

    draw = ImageDraw.Draw(img)
    # faint background grid (very low-opacity white, drawn on an overlay)
    grid = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    gdraw0 = ImageDraw.Draw(grid)
    for i in range(1, 11):
        x = W * i / 11
        gdraw0.line([(x, 0), (x, H)], fill=(255, 255, 255, 8), width=1)
    for i in range(1, 14):
        y = H * i / 14
        gdraw0.line([(0, y), (W, y)], fill=(255, 255, 255, 8), width=1)
    img.paste(Image.new("RGB", (W, H), (255, 255, 255)), (0, 0), grid.getchannel("A"))

    left, right = _s(30), _s(RW - 30)

    # -- header --
    logo = appicon.render(_s(50)).convert("RGBA")
    img.paste(logo, (left, _s(30)), logo)
    draw.text((left + _s(62), _s(30)), "TokenStep", font=_font(_s(23), bold=True), fill=white)
    draw.text((left + _s(63), _s(60)), brand_sub, font=_font(_s(15), bold=True), fill=(150, 160, 168))
    draw.text((right, _s(30)), _rhythm_display_date(rhythm.get("date", "")),
              font=_font(_s(18), bold=True), fill=accent, anchor="ra")
    draw.text((right, _s(58)), _rhythm_weekday(rhythm.get("date", "")),
              font=_font(_s(16), bold=True), fill=(150, 160, 168), anchor="ra")

    # -- hero --
    cx = _s(RW) / 2
    draw.text((cx, _s(100)), "昨日 AI 节奏", font=_font(_s(31), bold=True), fill=white, anchor="mm")
    title = rhythm.get("title", "")
    title_font = _font(_s(40), bold=True)
    tw = draw.textlength(title, font=title_font)
    _gradient_text(img, cx, _s(158), title, title_font, [accent, secondary], anchor="mm")
    _draw_laurel(draw, cx - tw / 2 - _s(26), _s(158), _s(52), accent, mirrored=True)
    _draw_laurel(draw, cx + tw / 2 + _s(26), _s(158), _s(52), accent, mirrored=False)
    draw.text((cx, _s(206)), rhythm.get("share_line", ""),
              font=_font(_s(16), bold=True), fill=(178, 186, 192), anchor="mm")

    # -- wave panel --
    chart_l, chart_r = _s(44), _s(RW - 44)
    chart_top, chart_bottom = _s(244), _s(440)
    values = _rhythm_wave_values(rhythm.get("buckets", [0] * 24))
    pts = _rhythm_points(values, chart_l, chart_r, chart_top, chart_bottom)
    curve = _catmull(pts, samples=16)

    # panel grid
    for i in range(1, 12):
        x = chart_l + (chart_r - chart_l) * i / 12
        draw.line([(x, chart_top), (x, chart_bottom)], fill=_lerp((0, 0, 0), accent, 0.10), width=1)
    for i in range(1, 4):
        y = chart_top + (chart_bottom - chart_top) * i / 4
        draw.line([(chart_l, y), (chart_r, y)], fill=_lerp((0, 0, 0), accent, 0.10), width=1)

    # area fill (accent fading down), masked by the curve polygon
    area_pts = curve + [(curve[-1][0], chart_bottom), (curve[0][0], chart_bottom)]
    poly_mask = Image.new("L", (W, H), 0)
    ImageDraw.Draw(poly_mask).polygon(area_pts, fill=255)
    fade = Image.new("L", (W, H), 0)
    fdraw = ImageDraw.Draw(fade)
    for y in range(chart_top, chart_bottom):
        t = (y - chart_top) / max(1, (chart_bottom - chart_top))
        fdraw.line([(0, y), (W, y)], fill=int(150 * max(0.0, 1.0 - t)))
    area_alpha = ImageChops.multiply(poly_mask, fade)
    area_color = Image.new("RGB", (W, H), accent)
    img.paste(area_color, (0, 0), area_alpha)

    # glow underlay
    glow = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    gdraw = ImageDraw.Draw(glow)
    gdraw.line(curve, fill=secondary + (140,), width=_s(13), joint="curve")
    glow = glow.filter(ImageFilter.GaussianBlur(_s(9)))
    img.paste(glow, (0, 0), glow)

    # sharp gradient stroke (accent -> secondary -> night along x)
    lw = _s(5)
    for i in range(len(curve) - 1):
        x0, _y0 = curve[i]
        frac = (curve[i][0] - chart_l) / max(1, (chart_r - chart_l))
        color = _lerp_stops([accent, secondary, night], frac)
        draw.line([curve[i], curve[i + 1]], fill=color, width=lw)
    for (px_, py_) in curve[::3]:
        rr = lw / 2
        frac = (px_ - chart_l) / max(1, (chart_r - chart_l))
        color = _lerp_stops([accent, secondary, night], frac)
        draw.ellipse([px_ - rr, py_ - rr, px_ + rr, py_ + rr], fill=color)

    # peak marker
    peak_hour = rhythm.get("peak_hour")
    if peak_hour is not None and 0 <= peak_hour < len(pts):
        ppt = pts[peak_hour]
        ys = int(ppt[1])
        while ys < chart_bottom:
            draw.line([(ppt[0], ys), (ppt[0], min(ys + _s(5), chart_bottom))],
                      fill=_lerp((0, 0, 0), secondary, 0.45), width=max(1, _s(1)))
            ys += _s(12)
        dot = _s(6)
        draw.ellipse([ppt[0] - dot, ppt[1] - dot, ppt[0] + dot, ppt[1] + dot],
                     fill=white, outline=secondary, width=_s(3))

    # axis labels
    axis_y = _s(454)
    icon_y = _s(478)
    axis = [(0, "moon"), (6, None), (12, "sun"), (18, None), (24, "moon")]
    for hour, sym in axis:
        ax = chart_l + (chart_r - chart_l) * hour / 24
        draw.text((ax, axis_y), f"{hour}时", font=_font(_s(13), bold=True),
                  fill=(150, 160, 168), anchor="mm")
        if sym == "moon":
            _paste_glyph(img, _g_crescent(_s(18), night), ax, icon_y)
        elif sym == "sun":
            _paste_glyph(img, _g_sun(_s(18), (255, 184, 32)), ax, icon_y)

    # -- peak capsule --
    cap_y0, cap_y1 = _s(500), _s(556)
    cap = _linear_swatch(right - left, cap_y1 - cap_y0, [_lerp((0, 0, 0), panel, 0.96), _lerp((0, 0, 0), panel, 0.62)])
    cap_mask = Image.new("L", (right - left, cap_y1 - cap_y0), 0)
    ImageDraw.Draw(cap_mask).rounded_rectangle([0, 0, right - left - 1, cap_y1 - cap_y0 - 1], radius=_s(16), fill=235)
    img.paste(cap, (left, cap_y0), cap_mask)
    draw.rounded_rectangle([left, cap_y0, right, cap_y1], radius=_s(16),
                           outline=_lerp((0, 0, 0), secondary, 0.45), width=_s(1))
    cap_mid = (cap_y0 + cap_y1) / 2
    _paste_glyph(img, _g_scope(_s(30), accent), left + _s(34), cap_mid)
    draw.text((left + _s(62), cap_mid), f"峰值 {_fmt_peak_window(peak_hour)}",
              font=_font(_s(19), bold=True), fill=white, anchor="lm")
    draw.text((right - _s(20), cap_mid), f"峰值 {fmt_tokens(rhythm.get('peak_tokens', 0))}",
              font=_font(_s(17), bold=True), fill=(200, 210, 216), anchor="rm")

    # -- token console --
    con_y0, con_y1 = _s(572), _s(662)
    con_mask = Image.new("L", (W, H), 0)
    ImageDraw.Draw(con_mask).rounded_rectangle([left, con_y0, right, con_y1], radius=_s(18), fill=int(255 * 0.24))
    img.paste(Image.new("RGB", (W, H), (0, 0, 0)), (0, 0), con_mask)
    draw.rounded_rectangle([left, con_y0, right, con_y1], radius=_s(18),
                           outline=_lerp((0, 0, 0), secondary, 0.30), width=_s(1))
    _draw_chevrons(img, left + _s(56), (con_y0 + con_y1) / 2, accent, secondary, mirrored=False)
    _draw_chevrons(img, right - _s(56), (con_y0 + con_y1) / 2, accent, secondary, mirrored=True)
    draw.text((cx, con_y0 + _s(22)), "昨日 Token", font=_font(_s(17), bold=True),
              fill=(190, 198, 204), anchor="mm")
    _gradient_text(img, cx, con_y0 + _s(58), fmt_tokens(rhythm.get("total_tokens", 0)),
                   _font(_s(46), bold=True), [accent, white], anchor="mm", vertical=True)

    # -- bottom metrics --
    met_y0, met_y1 = _s(676), _s(746)
    metrics = [
        ("clock", "活跃时段", f"{int(rhythm.get('active_hours', 0))} 个时段", accent),
        ("moon", "夜间占比", f"{round(float(rhythm.get('night_share', 0)) * 100)}%", night),
        ("timer", "最长连续", f"{int(rhythm.get('longest_streak', 0))} 小时", accent),
    ]
    col_w = (right - left) / 3
    for i, (sym, label, value, color) in enumerate(metrics):
        col_cx = left + col_w * (i + 0.5)
        if i > 0:
            dx = left + col_w * i
            draw.line([(dx, met_y0 + _s(8)), (dx, met_y1 - _s(8))], fill=(255, 255, 255), width=1)
        gly = {"clock": _g_clock, "moon": _g_moonstars, "timer": _g_timer}[sym](_s(16), color)
        label_w = draw.textlength(label, font=_font(_s(14), bold=True))
        total_w = gly.width + _s(6) + label_w
        gx = col_cx - total_w / 2 + gly.width / 2
        _paste_glyph(img, gly, gx, met_y0 + _s(14))
        draw.text((gx + gly.width / 2 + _s(6), met_y0 + _s(14)), label,
                  font=_font(_s(14), bold=True), fill=color, anchor="lm")
        draw.text((col_cx, met_y0 + _s(46)), value, font=_font(_s(24), bold=True),
                  fill=white, anchor="mm")

    # -- footer --
    foot_text = "本地统计 · 不上传对话"
    ff = _font(_s(14), bold=True)
    fw = draw.textlength(foot_text, font=ff) + _s(40)
    fy0, fy1 = _s(760), _s(796)
    fx0 = cx - fw / 2
    foot_mask = Image.new("L", (W, H), 0)
    ImageDraw.Draw(foot_mask).rounded_rectangle([fx0, fy0, fx0 + fw, fy1], radius=_s(18), fill=int(255 * 0.20))
    img.paste(Image.new("RGB", (W, H), (0, 0, 0)), (0, 0), foot_mask)
    foot_mid = (fy0 + fy1) / 2
    _paste_glyph(img, _g_lock(_s(15), (180, 188, 194)), fx0 + _s(18), foot_mid)
    draw.text((fx0 + _s(32), foot_mid), foot_text, font=ff, fill=(180, 188, 194), anchor="lm")

    # round the card corners
    out = img.resize((RW, RH), Image.Resampling.LANCZOS)
    corner = Image.new("L", (RW, RH), 0)
    ImageDraw.Draw(corner).rounded_rectangle([0, 0, RW - 1, RH - 1], radius=22, fill=255)
    rounded = Image.new("RGB", (RW, RH), (8, 12, 18))
    rounded.paste(out, (0, 0), corner)
    return rounded


def _draw_chevrons(img: Image.Image, cx: float, cy: float, accent, secondary, mirrored: bool) -> None:
    draw = ImageDraw.Draw(img)
    direction = 1 if mirrored else -1
    step = _s(13)
    cw = _s(9)
    ch = _s(12)
    lw = _s(4)
    colors = [_lerp((0, 0, 0), accent, 0.25), secondary,
              _lerp((0, 0, 0), accent, 0.54), _lerp((0, 0, 0), accent, 0.25)]
    for i in range(4):
        bx = cx + (i - 1.5) * step
        tip = bx + direction * cw / 2
        back = bx - direction * cw / 2
        col = colors[i]
        draw.line([(back, cy - ch / 2), (tip, cy), (back, cy + ch / 2)], fill=col, width=lw, joint="curve")


def _rhythm_display_date(date: str) -> str:
    try:
        d = dt.date.fromisoformat(date)
        return d.strftime("%Y.%m.%d")
    except Exception:
        return date or ""


_WEEKDAYS = ["星期一", "星期二", "星期三", "星期四", "星期五", "星期六", "星期日"]


def _rhythm_weekday(date: str) -> str:
    try:
        return _WEEKDAYS[dt.date.fromisoformat(date).weekday()]
    except Exception:
        return ""


def save_card(img: Image.Image, path: str) -> None:
    img.save(path, format="PNG")


def copy_to_clipboard(img: Image.Image) -> bool:
    """Copy a PIL image to the Windows clipboard as CF_DIB (no pywin32 needed)."""
    try:
        import ctypes

        buf = io.BytesIO()
        img.convert("RGB").save(buf, "BMP")
        data = buf.getvalue()[14:]  # strip 14-byte BITMAPFILEHEADER -> DIB
        buf.close()

        CF_DIB = 8
        GMEM_MOVEABLE = 0x0002
        k32 = ctypes.windll.kernel32
        u32 = ctypes.windll.user32
        k32.GlobalAlloc.restype = ctypes.c_void_p
        k32.GlobalAlloc.argtypes = [ctypes.c_uint, ctypes.c_size_t]
        k32.GlobalLock.restype = ctypes.c_void_p
        k32.GlobalLock.argtypes = [ctypes.c_void_p]
        k32.GlobalUnlock.argtypes = [ctypes.c_void_p]
        u32.OpenClipboard.argtypes = [ctypes.c_void_p]
        u32.SetClipboardData.restype = ctypes.c_void_p
        u32.SetClipboardData.argtypes = [ctypes.c_uint, ctypes.c_void_p]

        handle = k32.GlobalAlloc(GMEM_MOVEABLE, len(data))
        if not handle:
            return False
        ptr = k32.GlobalLock(handle)
        if not ptr:
            k32.GlobalFree(handle)
            return False
        ctypes.memmove(ptr, data, len(data))
        k32.GlobalUnlock(handle)

        if not u32.OpenClipboard(None):
            k32.GlobalFree(handle)
            return False
        try:
            u32.EmptyClipboard()
            if not u32.SetClipboardData(CF_DIB, handle):
                return False  # ownership not transferred; leak is negligible/best-effort
            return True
        finally:
            u32.CloseClipboard()
    except Exception:
        return False
