# -*- coding: utf-8 -*-
"""The Windows system-tray application.

Shows a live progress-ring icon for today's AI token usage versus the daily goal,
a menu with today's numbers, and actions to open the dashboard, refresh, change
settings, and toggle autostart. A background thread refreshes on the configured
interval.
"""
from __future__ import annotations

import threading
import webbrowser

import pystray
from pystray import Menu, MenuItem

from . import __version__
from . import autostart, collector, icon as icon_mod, paths, sharecard, updater
from . import settings as settings_mod
from .settings_ui import open_settings_dialog


class TokenStepTray:
    def __init__(self) -> None:
        paths.ensure_dirs()
        collector.ensure_pricing_file()
        self.settings = settings_mod.load()
        collector.configure_timezone(self.settings.get("timezone"))
        self.snapshot = collector.load_snapshot_safe()
        self.refreshing = False
        self.available_update: dict | None = None
        self.checking_update = False
        self._stop = threading.Event()
        self._wakeup = threading.Event()
        self._lock = threading.Lock()

        self.icon = pystray.Icon(
            "TokenStep",
            self._render_icon(),
            self._tooltip(),
            menu=self._build_menu(),
        )

    # -- derived state -----------------------------------------------------

    def _today(self) -> dict:
        return collector.today_row(self.snapshot)

    def _progress(self) -> float:
        goal = int(self.settings.get("daily_goal_tokens", 100_000_000))
        today = int(self._today().get("total_tokens", 0))
        return (today / goal) if goal > 0 else 0.0

    def _render_icon(self):
        return icon_mod.progress_ring(self._progress(), self.refreshing)

    def _tooltip(self) -> str:
        today = int(self._today().get("total_tokens", 0))
        goal = int(self.settings.get("daily_goal_tokens", 100_000_000))
        pct = min(self._progress() * 100, 999)
        # Tray tooltips are short; keep it compact.
        return (
            f"TokenStep · 今日 {collector.human_tokens(today)}"
            f" / {collector.human_tokens(goal)} ({pct:.0f}%)"
        )

    def _phrase(self) -> str:
        p = self._progress()
        if p >= 1:
            return "今日目标完成"
        if p >= 0.65:
            return "快走满目标"
        if p >= 0.3:
            return "节奏很好"
        return "继续热身"

    # -- menu --------------------------------------------------------------

    def _build_menu(self) -> Menu:
        return Menu(
            MenuItem(
                lambda item: f"今日 AI 步数：{collector.human_tokens(self._today().get('total_tokens', 0))}",
                None,
                enabled=False,
            ),
            MenuItem(
                lambda item: f"目标 {collector.human_tokens(self.settings.get('daily_goal_tokens', 0))}"
                f" · {min(self._progress() * 100, 999):.0f}%  {self._phrase()}",
                None,
                enabled=False,
            ),
            MenuItem(
                lambda item: f"预估成本：${self._today().get('cost', 0):.2f}"
                f" · 活跃 {self.snapshot.get('totals', {}).get('active_days', 0)} 天",
                None,
                enabled=False,
            ),
            Menu.SEPARATOR,
            MenuItem("打开仪表盘", self._on_open_dashboard, default=True),
            MenuItem(
                lambda item: "同步中…" if self.refreshing else "立即刷新",
                self._on_refresh_now,
            ),
            MenuItem("设置…", self._on_open_settings),
            Menu.SEPARATOR,
            MenuItem("复制今日截图", self._on_copy_screenshot),
            MenuItem("保存今日截图…", self._on_save_screenshot),
            Menu.SEPARATOR,
            MenuItem(
                lambda item: f"⬆ 有新版本 v{self.available_update['version']} · 打开下载页"
                if self.available_update
                else "检查更新",
                self._on_update_clicked,
            ),
            Menu.SEPARATOR,
            MenuItem(
                "开机自启",
                self._on_toggle_autostart,
                checked=lambda item: autostart.is_enabled(),
            ),
            MenuItem("退出", self._on_quit),
        )

    # -- actions -----------------------------------------------------------

    def _on_open_dashboard(self, icon=None, item=None) -> None:
        try:
            if not paths.DASHBOARD_HTML.exists():
                self._refresh_once()
            webbrowser.open(paths.DASHBOARD_HTML.as_uri())
        except Exception as exc:
            collector.log_error(exc)

    def _on_refresh_now(self, icon=None, item=None) -> None:
        threading.Thread(target=self._refresh_once, daemon=True).start()

    def _on_open_settings(self, icon=None, item=None) -> None:
        def runner() -> None:
            open_settings_dialog(self.settings, on_saved=self._on_settings_saved)

        threading.Thread(target=runner, daemon=True).start()

    def _on_settings_saved(self, new_settings: dict) -> None:
        with self._lock:
            self.settings = new_settings
        collector.configure_timezone(self.settings.get("timezone"))
        self._apply_visuals()
        self._wakeup.set()  # re-evaluate refresh interval immediately

    def _on_toggle_autostart(self, icon=None, item=None) -> None:
        try:
            autostart.toggle()
        except Exception as exc:
            collector.log_error(exc)
        self._update_menu()

    def _on_quit(self, icon=None, item=None) -> None:
        self._stop.set()
        self._wakeup.set()
        self.icon.stop()

    # -- screenshot / share card ------------------------------------------

    def _build_card(self):
        with self._lock:
            snapshot = self.snapshot
            settings = self.settings
        view = collector.build_dashboard_view(snapshot, settings)
        return sharecard.render_share_card(snapshot, view)

    def _on_copy_screenshot(self, icon=None, item=None) -> None:
        def runner() -> None:
            try:
                ok = sharecard.copy_to_clipboard(self._build_card())
                self._notify("今日截图已复制到剪贴板。" if ok else "复制失败，请改用“保存今日截图”。")
            except Exception as exc:
                collector.log_error(exc)
                self._notify("生成截图失败，请稍后再试。")

        threading.Thread(target=runner, daemon=True).start()

    def _on_save_screenshot(self, icon=None, item=None) -> None:
        def runner() -> None:
            try:
                img = self._build_card()
            except Exception as exc:
                collector.log_error(exc)
                self._notify("生成截图失败，请稍后再试。")
                return
            path = self._ask_save_path(sharecard.default_filename("today"))
            if not path:
                return
            try:
                sharecard.save_card(img, path)
                self._notify(f"已保存：{path}")
                self._reveal(path)
            except Exception as exc:
                collector.log_error(exc)
                self._notify("保存截图失败，请稍后再试。")

        threading.Thread(target=runner, daemon=True).start()

    @staticmethod
    def _ask_save_path(default_name: str) -> str | None:
        import os
        import tkinter as tk
        from tkinter import filedialog

        pictures = os.path.join(os.path.expanduser("~"), "Pictures")
        initial_dir = pictures if os.path.isdir(pictures) else os.path.expanduser("~")
        root = tk.Tk()
        root.withdraw()
        try:
            root.attributes("-topmost", True)
        except Exception:
            pass
        path = filedialog.asksaveasfilename(
            parent=root,
            title="保存今日截图",
            defaultextension=".png",
            initialfile=default_name,
            initialdir=initial_dir,
            filetypes=[("PNG 图片", "*.png")],
        )
        root.destroy()
        return path or None

    @staticmethod
    def _reveal(path: str) -> None:
        import os
        import subprocess

        try:
            subprocess.Popen(["explorer", "/select,", os.path.normpath(path)])
        except Exception:
            pass

    # -- updates -----------------------------------------------------------

    def _notify(self, message: str, title: str = "TokenStep") -> None:
        try:
            self.icon.notify(message, title)
        except Exception:
            pass

    def _on_update_clicked(self, icon=None, item=None) -> None:
        if self.available_update:
            try:
                webbrowser.open(self.available_update.get("page_url", updater.RELEASES_PAGE_URL))
            except Exception as exc:
                collector.log_error(exc)
        else:
            threading.Thread(target=self._check_updates, args=(False,), daemon=True).start()

    def _check_updates(self, silent: bool) -> None:
        with self._lock:
            if self.checking_update:
                return
            if silent and not self.settings.get("auto_update_enabled", True):
                return
            self.checking_update = True
        try:
            info = updater.check_for_updates(__version__)
        except Exception as exc:
            collector.log_error(exc)
            info = None
        finally:
            with self._lock:
                self.checking_update = False

        if info and info.get("version") == self.settings.get("skipped_update_version"):
            info = None

        if info:
            self.available_update = info
            self._notify(
                f"发现新版本 v{info['version']}，点击托盘菜单打开下载页。",
                "TokenStep 有更新",
            )
            self._update_menu()
        elif not silent:
            self._notify(f"已是最新版本（v{__version__}）。")

    # -- refresh -----------------------------------------------------------

    def _refresh_once(self) -> None:
        with self._lock:
            if self.refreshing:
                return
            self.refreshing = True
        self._apply_visuals()
        try:
            data = collector.collect_all(self.settings)
            collector.write_outputs(data, self.settings)
            with self._lock:
                self.snapshot = data
        except Exception as exc:
            collector.log_error(exc)
        finally:
            with self._lock:
                self.refreshing = False
            self._apply_visuals()

    def _apply_visuals(self) -> None:
        try:
            self.icon.icon = self._render_icon()
            self.icon.title = self._tooltip()
            self._update_menu()
        except Exception:
            pass

    def _update_menu(self) -> None:
        try:
            self.icon.update_menu()
        except Exception:
            pass

    def _worker(self) -> None:
        # Initial collection on startup.
        self._refresh_once()
        while not self._stop.is_set():
            interval = int(self.settings.get("refresh_interval_seconds", 60))
            wait_for = interval if interval > 0 else 60
            woke = self._wakeup.wait(timeout=wait_for)
            self._wakeup.clear()
            if self._stop.is_set():
                break
            if woke:
                # Settings changed; loop again to recompute interval without collecting.
                continue
            if int(self.settings.get("refresh_interval_seconds", 60)) == 0:
                continue  # manual mode: skip automatic collection
            self._refresh_once()

    # -- lifecycle ---------------------------------------------------------

    def _on_setup(self, icon: pystray.Icon) -> None:
        icon.visible = True
        threading.Thread(target=self._worker, daemon=True).start()
        # Best-effort update check shortly after launch (respects the setting).
        if self.settings.get("auto_update_enabled", True):
            threading.Thread(target=self._check_updates, args=(True,), daemon=True).start()

    def run(self) -> None:
        self.icon.run(setup=self._on_setup)


def main() -> int:
    # Single-instance guard via a named Windows mutex.
    try:
        import ctypes

        mutex = ctypes.windll.kernel32.CreateMutexW(None, False, "TokenStepWin_SingleInstance")
        if ctypes.windll.kernel32.GetLastError() == 183:  # ERROR_ALREADY_EXISTS
            return 0
        _ = mutex  # keep handle alive for process lifetime
    except Exception:
        pass

    TokenStepTray().run()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
