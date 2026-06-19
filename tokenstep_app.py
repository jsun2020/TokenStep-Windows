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


def main() -> int:
    if "--collect" in sys.argv or "print-summary" in sys.argv:
        return _collect_once()
    from tokenstep.tray import main as tray_main

    return tray_main()


if __name__ == "__main__":
    raise SystemExit(main())
