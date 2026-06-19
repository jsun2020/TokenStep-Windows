# -*- coding: utf-8 -*-
"""Render the tray progress-ring icon with Pillow.

Mirrors the macOS StatusBarIconRenderer: a faint grey track, a green progress
arc filling clockwise from 12 o'clock, and a center dot (green normally, grey
while refreshing).
"""
from __future__ import annotations

from PIL import Image, ImageDraw

GREEN = (45, 164, 78, 255)        # tokenGreen
TRACK = (90, 90, 90, 60)          # faint ring
GREY_DOT = (150, 150, 150, 230)   # refreshing state


def progress_ring(progress: float, refreshing: bool = False, size: int = 128) -> Image.Image:
    progress = max(0.0, min(1.0, float(progress)))
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)

    pad = size * 0.16
    box = (pad, pad, size - pad, size - pad)
    line_width = max(2, int(size * 0.13))

    # Full faint track.
    draw.arc(box, 0, 360, fill=TRACK, width=line_width)

    # Progress arc: clockwise from the top (12 o'clock = -90 degrees).
    if progress > 0:
        start = -90.0
        end = -90.0 + 360.0 * progress
        draw.arc(box, start, end, fill=GREEN, width=line_width)

    # Center dot.
    radius = size * 0.05
    center = size / 2
    dot = GREY_DOT if refreshing else GREEN
    draw.ellipse(
        (center - radius, center - radius, center + radius, center + radius),
        fill=dot,
    )
    return img


def app_icon(size: int = 256) -> Image.Image:
    """The full TokenStep brand icon (v0.1.5) for the app/window/executable."""
    from . import appicon  # local import; only needed when building the icon

    return appicon.render(size)
