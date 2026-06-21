# -*- coding: utf-8 -*-
"""A small Tkinter settings dialog.

Runs its own Tk root + mainloop so it can be launched from a worker thread by the
tray app. Lets the user pick the daily goal, refresh interval, and autostart.
"""
from __future__ import annotations

from typing import Any, Callable

import tkinter as tk
from tkinter import ttk

from . import autostart, settings as settings_mod

# (label, tokens)
GOAL_PRESETS = [
    ("5000 万", 50_000_000),
    ("1 亿（默认）", 100_000_000),
    ("2 亿", 200_000_000),
    ("5 亿", 500_000_000),
    ("10 亿", 1_000_000_000),
]

# (label, seconds)
INTERVAL_PRESETS = [
    ("手动", 0),
    ("1 分钟", 60),
    ("5 分钟", 300),
    ("15 分钟", 900),
]


def _goal_label(tokens: int) -> str:
    for label, value in GOAL_PRESETS:
        if value == tokens:
            return label
    if tokens >= 100_000_000:
        return f"{tokens / 100_000_000:.2f} 亿"
    return f"{tokens / 10_000:.0f} 万"


def open_settings_dialog(
    current: dict[str, Any],
    on_saved: Callable[[dict[str, Any]], None] | None = None,
) -> None:
    root = tk.Tk()
    root.title("TokenStep 设置")
    root.resizable(False, False)
    try:
        root.attributes("-topmost", True)
    except Exception:
        pass

    frame = ttk.Frame(root, padding=20)
    frame.grid(row=0, column=0, sticky="nsew")

    ttk.Label(frame, text="TokenStep 设置", font=("Segoe UI", 14, "bold")).grid(
        row=0, column=0, columnspan=2, sticky="w", pady=(0, 14)
    )

    # Daily goal --------------------------------------------------------------
    ttk.Label(frame, text="每日目标").grid(row=1, column=0, sticky="w", pady=6)
    goal_labels = [label for label, _ in GOAL_PRESETS]
    current_goal_label = _goal_label(int(current.get("daily_goal_tokens", 100_000_000)))
    if current_goal_label not in goal_labels:
        goal_labels = [current_goal_label] + goal_labels
    goal_var = tk.StringVar(value=current_goal_label)
    goal_box = ttk.Combobox(
        frame, textvariable=goal_var, values=goal_labels, state="readonly", width=18
    )
    goal_box.grid(row=1, column=1, sticky="e", pady=6)

    # Refresh interval --------------------------------------------------------
    ttk.Label(frame, text="刷新频率").grid(row=2, column=0, sticky="w", pady=6)
    interval_labels = [label for label, _ in INTERVAL_PRESETS]
    cur_interval = int(current.get("refresh_interval_seconds", 60))
    cur_interval_label = next(
        (lbl for lbl, sec in INTERVAL_PRESETS if sec == cur_interval), "1 分钟"
    )
    interval_var = tk.StringVar(value=cur_interval_label)
    interval_box = ttk.Combobox(
        frame, textvariable=interval_var, values=interval_labels, state="readonly", width=18
    )
    interval_box.grid(row=2, column=1, sticky="e", pady=6)

    # Autostart ---------------------------------------------------------------
    autostart_var = tk.BooleanVar(value=autostart.is_enabled())
    ttk.Checkbutton(frame, text="开机自动启动", variable=autostart_var).grid(
        row=3, column=0, columnspan=2, sticky="w", pady=(10, 2)
    )

    # Auto update check -------------------------------------------------------
    autoupdate_var = tk.BooleanVar(value=bool(current.get("auto_update_enabled", True)))
    ttk.Checkbutton(frame, text="启动时检查更新", variable=autoupdate_var).grid(
        row=4, column=0, columnspan=2, sticky="w", pady=(2, 2)
    )

    ask_var = tk.BooleanVar(value=bool(current.get("ask_before_downloading_updates", True)))
    ttk.Checkbutton(frame, text="下载前先询问", variable=ask_var).grid(
        row=5, column=0, columnspan=2, sticky="w", padx=(18, 0), pady=(0, 2)
    )

    verify_var = tk.BooleanVar(value=bool(current.get("require_verified_updates", True)))
    ttk.Checkbutton(frame, text="仅安装校验通过的版本（有 SHA-256 时）", variable=verify_var).grid(
        row=6, column=0, columnspan=2, sticky="w", padx=(18, 0), pady=(0, 4)
    )

    ttk.Label(
        frame,
        text="数据仅保存在本机，不上传任何代码或对话内容。",
        foreground="#6b7280",
        wraplength=300,
    ).grid(row=7, column=0, columnspan=2, sticky="w", pady=(8, 12))

    status_var = tk.StringVar(value="")
    ttk.Label(frame, textvariable=status_var, foreground="#216E39").grid(
        row=8, column=0, columnspan=2, sticky="w"
    )

    def do_save() -> None:
        goal_tokens = next(
            (v for label, v in GOAL_PRESETS if label == goal_var.get()),
            int(current.get("daily_goal_tokens", 100_000_000)),
        )
        interval_seconds = next(
            (s for label, s in INTERVAL_PRESETS if label == interval_var.get()), 60
        )
        new_settings = settings_mod.save(
            {
                **current,
                "daily_goal_tokens": goal_tokens,
                "refresh_interval_seconds": interval_seconds,
                "auto_update_enabled": autoupdate_var.get(),
                "ask_before_downloading_updates": ask_var.get(),
                "require_verified_updates": verify_var.get(),
            }
        )
        try:
            autostart.set_enabled(autostart_var.get())
        except Exception:
            pass
        if on_saved:
            try:
                on_saved(new_settings)
            except Exception:
                pass
        root.destroy()

    button_row = ttk.Frame(frame)
    button_row.grid(row=9, column=0, columnspan=2, sticky="e", pady=(14, 0))
    ttk.Button(button_row, text="取消", command=root.destroy).grid(row=0, column=0, padx=(0, 8))
    ttk.Button(button_row, text="保存", command=do_save).grid(row=0, column=1)

    root.update_idletasks()
    width = root.winfo_width()
    height = root.winfo_height()
    x = (root.winfo_screenwidth() - width) // 2
    y = (root.winfo_screenheight() - height) // 3
    root.geometry(f"+{x}+{y}")

    root.mainloop()
