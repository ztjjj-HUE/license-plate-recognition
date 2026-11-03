"""右侧信息栏 + 多帧投票 + 统计图表 + 证据图。

不修改原文件：继承 RecordingViewer（进而继承 ViewerApp），
用 pack 的右边距给侧栏腾地方，再 place 一块面板过去。

    py launch_hud.py --auto-connect
"""

from __future__ import annotations

import time
import tkinter as tk
from collections import deque
from tkinter import messagebox, ttk

from pc_viewer.src.lpr_viewer.app_records import RecordingViewer
from pc_viewer.src.lpr_viewer.gui import ViewerApp

GREEN = "#35f0aa"
ORANGE = "#ffbd59"
GREY = "#8a94a0"
BG = "#1b2430"
TEXT = "#d8dee6"
BAR = "#3fa9f5"


class VoteGate:
    """连续 N 帧同一个车牌才算确认，抑制单帧误识。"""

    def __init__(self, need=3):
        self.need = int(need)
        self.buf = deque(maxlen=self.need)
        self.current = None

    def feed(self, frame):
        """返回 (是否已确认, 是否刚刚确认)。"""
        if getattr(frame, "state", None) != "PLATE" or not frame.detections:
            self.buf.clear()
            self.current = None
            return False, False

        plate = frame.detections[0].plate
        self.buf.append(plate)
        if len(self.buf) < self.need:
            return False, False
        if len(set(self.buf)) != 1:
            self.current = None          # 投票被打断，撤销“已确认”
            return False, False

        newly = self.current != plate
        self.current = plate
        return True, newly

    @property
    def progress(self):
        return len(self.buf)


class HudViewer(RecordingViewer):
    SIDEBAR_W = 300

    def __init__(self, root, replay=False, records_dir=None, vote_frames=3):
        self._last_plate = "—"
        self._last_conf = 0.0
        self._last_state = "未连接"
        self.voter = VoteGate(vote_frames)
        self._stats_window = None
        self._stats_canvas = None
        self._fullscreen = False

        super().__init__(root, replay=replay, records_dir=records_dir)

        self.canvas.pack_configure(padx=(8, self.SIDEBAR_W + 14))
        self._fit_window()
        self._build_sidebar()
        self._build_menu()                 # 覆盖基类：多两项（统计、全屏）
        self._bind_keys()
        self.root.after(60, self._layout_sidebar)
        self.root.bind("<Configure>", self._on_root_configure)
        self.root.after(400, self._tick_sidebar)

    def _fit_window(self):
        """原窗口 920x720 加侧栏后在小屏/高 DPI 下会超出屏幕，给个稳妥尺寸。"""
        self.root.geometry("1040x640+30+10")

    # ------------------------------------------------------------ 侧栏布局
    def _build_sidebar(self):
        bar = ttk.Frame(self.root)
        self.sidebar = bar

        inner = tk.Frame(bar, bg=BG, padx=14, pady=12)
        inner.pack(fill="both", expand=True)

        tk.Label(inner, text="实时识别", bg=BG, fg=GREY,
                 font=("Microsoft YaHei UI", 11)).pack(anchor="w")

        self.plate_label = tk.Label(inner, text="—", bg=BG, fg=GREY,
                                    font=("Microsoft YaHei UI", 30, "bold"))
        self.plate_label.pack(anchor="w", pady=(2, 0))

        self.badge_label = tk.Label(inner, text="", bg=BG, fg=ORANGE,
                                    font=("Microsoft YaHei UI", 10))
        self.badge_label.pack(anchor="w")

        self.conf_label = tk.Label(inner, text="置信度 —", bg=BG, fg=GREY,
                                   font=("Microsoft YaHei UI", 12))
        self.conf_label.pack(anchor="w", pady=(6, 0))
        self.conf_bar = ttk.Progressbar(inner, maximum=100, value=0)
        self.conf_bar.pack(fill="x", pady=(4, 2))

        self.state_label = tk.Label(inner, text="状态 未连接", bg=BG, fg=GREY,
                                    font=("Microsoft YaHei UI", 10))
        self.state_label.pack(anchor="w")

        ttk.Separator(inner).pack(fill="x", pady=10)

        tk.Label(inner, text="最近记录", bg=BG, fg=GREY,
                 font=("Microsoft YaHei UI", 11)).pack(anchor="w")
        self.record_box = tk.Frame(inner, bg=BG)
        self.record_box.pack(fill="x", pady=(4, 0))
        self._record_rows = []
        for _ in range(6):
            row = tk.Label(self.record_box, text="", bg=BG, fg=TEXT,
                           font=("Microsoft YaHei UI", 11), anchor="w")
            row.pack(fill="x")
            self._record_rows.append(row)

        ttk.Separator(inner).pack(fill="x", pady=10)

        self.stats_label = tk.Label(inner, text="今日 0 次 · 累计 0 条", bg=BG, fg=GREY,
                                    font=("Microsoft YaHei UI", 10))
        self.stats_label.pack(anchor="w")
        self.fps_label = tk.Label(inner, text="预览 0.0 fps", bg=BG, fg=GREY,
                                  font=("Microsoft YaHei UI", 10))
        self.fps_label.pack(anchor="w")

    def _on_root_configure(self, event):
        if event.widget is self.root:
            self._layout_sidebar()

    def _layout_sidebar(self):
        width = self.root.winfo_width()
        height = self.canvas.winfo_height()
        if width <= 1 or height <= 1:
            self.root.after(50, self._layout_sidebar)
            return
        self.sidebar.place(
            x=width - self.SIDEBAR_W - 8,
            y=self.canvas.winfo_y(),
            width=self.SIDEBAR_W,
            height=height,
        )

    # ------------------------------------------------------------ 每帧
    def _show_frame(self, frame):
        # 画面照常画：直接调用最底层的 ViewerApp，跳过基类的“来一帧记一条”
        ViewerApp._show_frame(self, frame)

        confirmed, newly = self.voter.feed(frame)
        if confirmed and not self._replay and self.recorder is not None:
            try:
                self.recorder.observe(frame, getattr(frame, "image_data", None))
            except Exception:
                pass
            if newly:
                self._beep()

        self._update_sidebar(frame, confirmed)
        if self._stats_window is not None and self._stats_window.winfo_exists():
            self._draw_stats()

    def _beep(self):
        try:
            import winsound
            winsound.Beep(1200, 80)
        except Exception:
            pass

    def _update_sidebar(self, frame, confirmed):
        if frame.state == "PLATE" and frame.detections:
            plate = frame.detections[0].plate
            conf = frame.detections[0].confidence_permille / 10.0
            self.plate_label.configure(text=plate, fg=GREEN if confirmed else ORANGE)
            self.conf_label.configure(text="置信度 {:.1f}%".format(conf), fg=TEXT)
            self.conf_bar.configure(value=conf)
            if confirmed:
                self.badge_label.configure(text="✓ 已确认", fg=GREEN)
            else:
                self.badge_label.configure(
                    text="校验中 {}/{}".format(self.voter.progress, self.voter.need), fg=ORANGE)
        else:
            self.plate_label.configure(text="未识别", fg=ORANGE)
            self.badge_label.configure(text="", fg=ORANGE)
            self.conf_label.configure(text="置信度 —", fg=GREY)
            self.conf_bar.configure(value=0)

        color = GREEN if frame.state == "PLATE" else ORANGE
        self.state_label.configure(text="状态 {}".format(frame.state), fg=color)

    # ------------------------------------------------------------ 菜单
    def _build_menu(self):
        menubar = tk.Menu(self.root)
        menu = tk.Menu(menubar, tearoff=0)
        menu.add_command(label="查看车牌记录…", command=self.open_history)
        menu.add_command(label="统计图表…", command=self.open_stats)
        menu.add_command(label="导出 CSV…", command=self.export_csv)
        menu.add_separator()
        menu.add_command(label="打开记录目录", command=self.open_records_dir)
        menu.add_separator()
        menu.add_command(label="全屏演示 (F11)", command=self.toggle_fullscreen)
        menubar.add_cascade(label="记录", menu=menu)
        self.root.config(menu=menubar)

    def _bind_keys(self):
        self.root.bind("<F11>", lambda _e: self.toggle_fullscreen())

    def toggle_fullscreen(self):
        self._fullscreen = not self._fullscreen
        self.root.attributes("-fullscreen", self._fullscreen)

    # ------------------------------------------------------------ 统计图表
    def open_stats(self):
        if self._stats_window is not None and self._stats_window.winfo_exists():
            self._stats_window.lift()
            self._draw_stats()
            return

        win = tk.Toplevel(self.root)
        win.title("识别统计")
        win.geometry("760x600")
        self._stats_window = win

        top = ttk.Frame(win, padding=8)
        top.pack(fill="x")
        ttk.Button(top, text="刷新", command=self._draw_stats).pack(side="left")
        self._stats_summary = tk.StringVar(value="")
        ttk.Label(top, textvariable=self._stats_summary).pack(side="right")

        self._stats_canvas = tk.Canvas(win, bg="#121a24", highlightthickness=0)
        self._stats_canvas.pack(fill="both", expand=True, padx=8, pady=(0, 8))
        win.bind("<Configure>", lambda _e: self._draw_stats())
        self._draw_stats()

    def _draw_stats(self):
        canvas = self._stats_canvas
        if canvas is None or not canvas.winfo_exists():
            return
        canvas.delete("all")
        width = max(400, canvas.winfo_width())
        height = max(300, canvas.winfo_height())

        try:
            hourly = self.recorder.hourly()
            daily = self.recorder.daily(7)
            top = self.recorder.top_plates(5)
            total = self.recorder.total()
        except Exception:
            hourly, daily, top, total = [0] * 24, [], [], 0

        self._stats_summary.set("累计 {} 条".format(total))

        # ① 今日各小时
        self._draw_block(canvas, 20, 20, width - 40, 170,
                         "今日各小时识别次数",
                         [(str(h), hourly[h]) for h in range(24)], BAR,
                         show_every=3)

        # ② 近 7 天
        self._draw_block(canvas, 20, 220, width - 40, 150,
                         "近 7 天",
                         [(day, count) for day, count in daily], "#7ed957")

        # ③ 车牌 Top5（横向条）
        self._draw_rank(canvas, 20, 400, width - 40, 160, top)

    def _draw_block(self, canvas, x, y, w, h, title, data, color, show_every=1):
        canvas.create_text(x, y, text=title, fill=TEXT, anchor="nw",
                           font=("Microsoft YaHei UI", 11, "bold"))
        top_value = max([v for _, v in data] or [0]) or 1
        base_y = y + h - 24
        bar_w = (w - 10) / max(1, len(data))
        for index, (label, value) in enumerate(data):
            left = x + index * bar_w + bar_w * 0.2
            right = x + (index + 1) * bar_w - bar_w * 0.2
            bar_h = (h - 50) * (value / top_value)
            if value > 0:
                canvas.create_rectangle(left, base_y - bar_h, right, base_y,
                                        fill=color, outline="")
                canvas.create_text((left + right) / 2, base_y - bar_h - 8,
                                   text=str(value), fill=TEXT,
                                   font=("Microsoft YaHei UI", 8))
            if index % show_every == 0:
                canvas.create_text((left + right) / 2, base_y + 12,
                                   text=str(label), fill=GREY,
                                   font=("Microsoft YaHei UI", 8))

    def _draw_rank(self, canvas, x, y, w, h, items):
        canvas.create_text(x, y, text="出现最多的车牌", fill=TEXT, anchor="nw",
                           font=("Microsoft YaHei UI", 11, "bold"))
        if not items:
            canvas.create_text(x + 10, y + 40, text="暂无记录", fill=GREY,
                               font=("Microsoft YaHei UI", 11))
            return
        top_value = max(v for _, v in items) or 1
        row_h = (h - 30) / len(items)
        for index, (plate, count) in enumerate(items):
            cy = y + 30 + index * row_h
            canvas.create_text(x + 10, cy + 8, text=plate, fill=TEXT, anchor="w",
                               font=("Microsoft YaHei UI", 11))
            bar_len = (w - 220) * (count / top_value)
            canvas.create_rectangle(x + 120, cy, x + 120 + bar_len, cy + 18,
                                    fill=BAR, outline="")
            canvas.create_text(x + 128 + bar_len, cy + 9, text=str(count),
                               fill=GREY, anchor="w", font=("Microsoft YaHei UI", 9))

    # ------------------------------------------------------------ 刷新
    def _tick_sidebar(self):
        try:
            if not self.root.winfo_exists():
                return
            self._refresh_records()
            self._refresh_stats()
            self.root.after(500, self._tick_sidebar)
        except tk.TclError:
            pass

    def _refresh_records(self):
        try:
            rows = self.recorder.recent(6)
        except Exception:
            rows = []
        for label, row in zip(self._record_rows, rows):
            label.configure(text="{}   {:.1f}%".format(row["plate"], row["confidence"]))
        for label in self._record_rows[len(rows):]:
            label.configure(text="")

    def _refresh_stats(self):
        try:
            today = self.recorder.daily_stats(1)
            count_today = today[0]["plates"] if today else 0
            total = self.recorder.total()
        except Exception:
            count_today, total = 0, 0
        self.stats_label.configure(text="今日 {} 次 · 累计 {} 条".format(count_today, total))

        times = getattr(self, "_frame_times", None)
        fps = 0.0
        if times and len(times) >= 2:
            span = times[-1] - times[0]
            if span > 0:
                fps = (len(times) - 1) / span
        self.fps_label.configure(text="预览 {:.1f} fps".format(fps))

    # ------------------------------------------------------------ 收尾
    def close(self):
        try:
            if self._stats_window is not None and self._stats_window.winfo_exists():
                self._stats_window.destroy()
        except Exception:
            pass
        super().close()
