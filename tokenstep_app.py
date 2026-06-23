# -*- coding: utf-8 -*-
"""TokenStep for Windows - entry point.

Launch with pythonw.exe (no console) for normal use, or python.exe while
developing. Also supports `--collect` for a one-shot data refresh from the CLI.
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))


def _collect_once() -> int:
    from tokenstep import collector, settings as settings_mod

    settings = settings_mod.load()
    collector.ensure_pricing_file()
    data = collector.collect_all(settings)
    collector.write_outputs(data, settings)
    print(f"generated_at: {data['generated_at']}")
    print(f"total_tokens: {collector.human_tokens(data['totals']['tokens'])}")
    print(f"estimated_cost: ${data['totals']['cost']:.2f}")
    print(f"active_days: {data['totals']['active_days']}")
    for row in data["tools"]:
        print(f"  - {row['tool']}: {collector.human_tokens(row['tokens'])} ({row['percent']:.1f}%)")
    from tokenstep import paths

    print(f"dashboard: {paths.DASHBOARD_HTML}")
    return 0


def _screenshot_once() -> int:
    import os

    from tokenstep import collector, paths, sharecard, settings as settings_mod

    settings = settings_mod.load()
    collector.ensure_pricing_file()
    data = collector.collect_all(settings)
    collector.write_outputs(data, settings)
    view = collector.build_dashboard_view(data, settings)
    img = sharecard.render_share_card(data, view)

    # Optional explicit path as the argument after --screenshot.
    out = None
    argv = sys.argv
    if "--screenshot" in argv:
        idx = argv.index("--screenshot")
        if idx + 1 < len(argv) and not argv[idx + 1].startswith("-"):
            out = argv[idx + 1]
    if not out:
        pictures = os.path.join(os.path.expanduser("~"), "Pictures")
        base = pictures if os.path.isdir(pictures) else str(paths.ROOT)
        out = os.path.join(base, sharecard.default_filename("today"))
    sharecard.save_card(img, out)
    print(f"screenshot saved: {out}")
    return 0


def _rhythm_screenshot_once() -> int:
    import os

    from tokenstep import collector, paths, sharecard, settings as settings_mod

    settings = settings_mod.load()
    collector.ensure_pricing_file()
    data = collector.collect_all(settings)
    collector.write_outputs(data, settings)
    rhythm = collector.yesterday_rhythm(data)
    img = sharecard.render_rhythm_card(rhythm)

    out = None
    argv = sys.argv
    if "--rhythm-screenshot" in argv:
        idx = argv.index("--rhythm-screenshot")
        if idx + 1 < len(argv) and not argv[idx + 1].startswith("-"):
            out = argv[idx + 1]
    if not out:
        pictures = os.path.join(os.path.expanduser("~"), "Pictures")
        base = pictures if os.path.isdir(pictures) else str(paths.ROOT)
        out = os.path.join(base, sharecard.default_filename("rhythm"))
    sharecard.save_card(img, out)
    print(f"rhythm screenshot saved: {out}")
    return 0


def main() -> int:
    if "--collect" in sys.argv or "print-summary" in sys.argv:
        return _collect_once()
    if "--rhythm-screenshot" in sys.argv:
        return _rhythm_screenshot_once()
    if "--screenshot" in sys.argv:
        return _screenshot_once()
    from tokenstep.tray import main as tray_main

    return tray_main()


if __name__ == "__main__":
    raise SystemExit(main())
