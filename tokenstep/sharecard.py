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

from PIL import Image, ImageDraw, ImageFont

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
