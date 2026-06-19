# -*- coding: utf-8 -*-
"""TokenStep application icon (v0.1.5 design).

Ported from the macOS render_icon.py render_base_icon(): a circular white base,
a green progress ring with rounded caps and a top dot, and a 3x3 grid of
contribution-green token squares. Pure Pillow, so it works on Windows. Used to
generate the portable .exe icon (app.ico). The dynamic tray ring lives in
icon.py and is intentionally simpler.
"""
from __future__ import annotations

import math

from PIL import Image, ImageDraw, ImageFilter

SIZE = 1024
SCALE = 3
W = SIZE * SCALE


def sx(value: float) -> int:
    return round(value * SCALE)


def hex_to_rgb(value: str) -> tuple[int, int, int]:
    value = value.lstrip("#")
    return tuple(int(value[i : i + 2], 16) for i in (0, 2, 4))  # type: ignore[return-value]


def mix(a: str, b: str, t: float) -> tuple[int, int, int]:
    ar, ag, ab = hex_to_rgb(a)
    br, bg, bb = hex_to_rgb(b)
    return (
        round(ar + (br - ar) * t),
        round(ag + (bg - ag) * t),
        round(ab + (bb - ab) * t),
    )


def arc_points(cx: int, cy: int, radius: int, start_deg: float, end_deg: float, count: int):
    points = []
    for index in range(count + 1):
        angle = math.radians(start_deg + (end_deg - start_deg) * index / count)
        points.append((round(cx + math.cos(angle) * radius), round(cy + math.sin(angle) * radius)))
    return points


def draw_solid_arc_with_caps(
    draw: ImageDraw.ImageDraw,
    cx: int,
    cy: int,
    radius: int,
    start_deg: float,
    end_deg: float,
    width: int,
    fill: str,
    end_fill: str | None = None,
) -> None:
    bbox = (cx - radius, cy - radius, cx + radius, cy + radius)
    draw.arc(bbox, start=start_deg, end=end_deg, fill=hex_to_rgb(fill), width=width)
    cap_radius = width // 2
    start = arc_points(cx, cy, radius, start_deg, start_deg, 1)[0]
    end = arc_points(cx, cy, radius, end_deg, end_deg, 1)[0]
    draw.ellipse(
        (start[0] - cap_radius, start[1] - cap_radius, start[0] + cap_radius, start[1] + cap_radius),
        fill=hex_to_rgb(fill),
    )
    draw.ellipse(
        (end[0] - cap_radius, end[1] - cap_radius, end[0] + cap_radius, end[1] + cap_radius),
        fill=hex_to_rgb(end_fill or fill),
    )


def draw_token(draw: ImageDraw.ImageDraw, cx: int, cy: int, size: int, fill: str, shadow: Image.Image) -> None:
    radius = round(size * 0.24)
    rect = (cx - size // 2, cy - size // 2, cx + size // 2, cy + size // 2)
    shadow_draw = ImageDraw.Draw(shadow)
    shadow_draw.rounded_rectangle(
        (rect[0] + sx(6), rect[1] + sx(8), rect[2] + sx(6), rect[3] + sx(8)),
        radius=radius,
        fill=(18, 24, 38, 34),
    )
    draw.rounded_rectangle(rect, radius=radius, fill=hex_to_rgb(fill))
    inset = round(size * 0.16)
    draw.rounded_rectangle(
        (rect[0] + inset, rect[1] + inset, rect[2] - inset, rect[1] + inset + max(2, size // 12)),
        radius=max(1, size // 20),
        fill=(255, 255, 255, 70),
    )


def render_base_icon() -> Image.Image:
    image = Image.new("RGBA", (W, W), (0, 0, 0, 0))
    shadow = Image.new("RGBA", (W, W), (0, 0, 0, 0))
    shadow_draw = ImageDraw.Draw(shadow)

    cx = cy = sx(512)
    base_radius = sx(374)
    base_rect = (cx - base_radius, cy - base_radius, cx + base_radius, cy + base_radius)

    shadow_draw.ellipse(
        (base_rect[0], base_rect[1] + sx(30), base_rect[2], base_rect[3] + sx(30)),
        fill=(18, 24, 38, 42),
    )
    image.alpha_composite(shadow.filter(ImageFilter.GaussianBlur(sx(28))))

    draw = ImageDraw.Draw(image)
    for offset in range(base_rect[3] - base_rect[1]):
        t = offset / max(1, base_rect[3] - base_rect[1] - 1)
        fill = mix("#ffffff", "#eef8f1", t)
        y = base_rect[1] + offset
        span = math.sqrt(max(0, base_radius * base_radius - (y - cy) * (y - cy)))
        draw.line((round(cx - span), y, round(cx + span), y), fill=fill + (248,), width=1)

    draw.ellipse(base_rect, outline=(255, 255, 255, 230), width=sx(7))
    draw.ellipse(
        (base_rect[0] + sx(18), base_rect[1] + sx(18), base_rect[2] - sx(18), base_rect[3] - sx(18)),
        outline=(210, 226, 217, 110),
        width=sx(3),
    )

    radius = sx(268)
    width = sx(62)

    ring_shadow = Image.new("RGBA", (W, W), (0, 0, 0, 0))
    ring_shadow_draw = ImageDraw.Draw(ring_shadow)
    ring_shadow_draw.ellipse(
        (cx - radius, cy - radius + sx(7), cx + radius, cy + radius + sx(7)),
        outline=(18, 24, 38, 34),
        width=width,
    )
    image.alpha_composite(ring_shadow.filter(ImageFilter.GaussianBlur(sx(8))).point(lambda p: p // 6))

    draw.ellipse((cx - radius, cy - radius, cx + radius, cy + radius), outline=hex_to_rgb("#e7edf0"), width=width)
    draw_solid_arc_with_caps(draw, cx, cy, radius, -90, 158, width, "#2da44e", "#2fca63")

    inner_highlight = Image.new("RGBA", (W, W), (0, 0, 0, 0))
    highlight_draw = ImageDraw.Draw(inner_highlight)
    draw_solid_arc_with_caps(highlight_draw, cx, cy - sx(6), radius - sx(22), -82, 142, sx(4), "#d8f3dc")
    image.alpha_composite(inner_highlight.filter(ImageFilter.GaussianBlur(sx(1))).point(lambda p: min(255, p // 2)))

    token_shadow = Image.new("RGBA", (W, W), (0, 0, 0, 0))
    token_size = sx(54)
    gap = sx(50)
    token_positions = [
        (cx - gap, cy - gap),
        (cx, cy - gap),
        (cx + gap, cy - gap),
        (cx - gap, cy),
        (cx, cy),
        (cx + gap, cy),
        (cx - gap, cy + gap),
        (cx, cy + gap),
        (cx + gap, cy + gap),
    ]
    colors = [
        "#9be9a8", "#dff7e6", "#9be9a8",
        "#40c463", "#2da44e", "#40c463",
        "#9be9a8", "#dff7e6", "#216e39",
    ]
    for (tx, ty), fill in zip(token_positions, colors):
        draw_token(draw, tx, ty, token_size, fill, token_shadow)
    image.alpha_composite(token_shadow.filter(ImageFilter.GaussianBlur(sx(5))))

    # Redraw tokens after the shadow layer so their edges stay crisp.
    draw = ImageDraw.Draw(image)
    for (tx, ty), fill in zip(token_positions, colors):
        radius_token = round(token_size * 0.24)
        rect = (tx - token_size // 2, ty - token_size // 2, tx + token_size // 2, ty + token_size // 2)
        draw.rounded_rectangle(rect, radius=radius_token, fill=hex_to_rgb(fill))
        draw.rounded_rectangle(rect, radius=radius_token, outline=(255, 255, 255, 72), width=sx(2))

    draw.ellipse(
        (cx - sx(14), cy - radius - sx(14), cx + sx(14), cy - radius + sx(14)),
        fill=hex_to_rgb("#2da44e"),
    )

    return image.resize((SIZE, SIZE), Image.Resampling.LANCZOS)


def render(size: int = 256) -> Image.Image:
    """Return the app icon rendered (and downscaled) to `size`x`size`."""
    base = render_base_icon()
    if size != SIZE:
        return base.resize((size, size), Image.Resampling.LANCZOS)
    return base


def save_ico(path: str, sizes: tuple[int, ...] = (16, 24, 32, 48, 64, 128, 256)) -> None:
    """Write a multi-resolution Windows .ico for the executable."""
    base = render(256)
    base.save(path, format="ICO", sizes=[(s, s) for s in sizes])
