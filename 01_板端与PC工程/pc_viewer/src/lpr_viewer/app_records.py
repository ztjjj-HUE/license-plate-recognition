"""带“车牌记录”的上位机入口：继承原 ViewerApp，不改动原文件。

用法（在 BluePlate7010 目录下）：
    python -m pc_viewer.src.lpr_viewer.app_records --auto-connect
    python -m pc_viewer.src.lpr_viewer.app_records --host 169.254.72.156 --port 8767
    python -m pc_viewer.src.lpr_viewer.app_records --records-dir D:\\lpr_records

也可以直接跑 launch 的等价参数。记录目录默认在 %LOCALAPPDATA%\\BluePlate7010\\records。
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

from PIL import Image, ImageTk

from pc_viewer.src.lpr_viewer.gui import ViewerApp
from pc_viewer.src.lpr_viewer.records import PlateRecorder


class RecordingViewer(ViewerApp):
    def __init__(self, root, replay=False, records_dir=None):
        self.recorder = None
        self._history = None
        self._history_rows = {}
        self._thumb = None

        super().__init__(root, replay=replay)

        self.recorder = PlateRecorder(records_dir)
        if not replay:
            self.recorder.prune()
        self._build_menu()
        if replay:
            self.root.title(self.root.title() + " · 回放不记录")
        else:
            self.root.title(self.root.title() + " · 记录中")

    # ---------------------------------------------------------------- 记录
    def _show_frame(self, frame):
        super()._show_frame(frame)
        if self._replay or self.recorder is None:
            return
        try:
            self.recorder.observe(frame)      # 存储失败绝不影响预览
        except Exception:
            pass

    # ---------------------------------------------------------------- 菜单
    def _build_menu(self):
        menubar = tk.Menu(self.root)
        menu = tk.Menu(menubar, tearoff=0)
        menu.add_command(label="查看车牌记录…", command=self.open_history)
        menu.add_command(label="导出 CSV…", command=self.export_csv)
        menu.add_separator()
        menu.add_command(label="打开记录目录", command=self.open_records_dir)
        menubar.add_cascade(label="记录", menu=menu)
        self.root.config(menu=menubar)

    def open_records_dir(self):
        path = str(self.recorder.root)
        try:
            if os.name == "nt":
                os.startfile(path)                       # noqa: S606
            elif sys.platform == "darwin":
                subprocess.Popen(["open", path])
            else:
                subprocess.Popen(["xdg-open", path])
        except Exception as exc:
            messagebox.showinfo("记录目录", "{}\n({})".format(path, exc))

    def export_csv(self):
        target = filedialog.asksaveasfilename(
            title="导出车牌记录",
            defaultextension=".csv",
            initialfile="plate_records.csv",
            filetypes=[("CSV 文件", "*.csv")],
        )
        if not target:
            return
        try:
            count = self.recorder.export_csv(target)
        except Exception as exc:
            messagebox.showerror("导出失败", str(exc))
            return
        messagebox.showinfo("导出完成", "已导出 {} 条记录到：\n{}".format(count, target))

    # ---------------------------------------------------------------- 历史窗口
    def open_history(self):
        if self._history is not None and self._history.winfo_exists():
            self._history.lift()
            self.refresh_history()
            return

        win = tk.Toplevel(self.root)
        win.title("车牌记录")
        win.geometry("860x520")
        self._history = win

        top = ttk.Frame(win, padding=8)
        top.pack(fill="x")
        ttk.Label(top, text="车牌筛选").pack(side="left")
        self._query = tk.StringVar()
        entry = ttk.Entry(top, textvariable=self._query, width=16)
        entry.pack(side="left", padx=(4, 8))
        entry.bind("<Return>", lambda _e: self.refresh_history())
        ttk.Button(top, text="查询", command=self.refresh_history).pack(side="left")
        ttk.Button(top, text="刷新", command=self.refresh_history).pack(side="left", padx=4)
        ttk.Button(top, text="导出 CSV", command=self.export_csv).pack(side="left")
        self._summary = tk.StringVar(value="")
        ttk.Label(top, textvariable=self._summary).pack(side="right")

        body = ttk.Frame(win)
        body.pack(fill="both", expand=True, padx=8, pady=(0, 8))

        columns = ("time", "plate", "conf", "frames")
        tree = ttk.Treeview(body, columns=columns, show="headings", height=14)
        for col, title, width in (
            ("time", "最近出现", 200),
            ("plate", "车牌", 140),
            ("conf", "置信度", 90),
            ("frames", "帧数", 70),
        ):
            tree.heading(col, text=title)
            tree.column(col, width=width, anchor="center" if col != "time" else "w")
        scroll = ttk.Scrollbar(body, orient="vertical", command=tree.yview)
        tree.configure(yscrollcommand=scroll.set)
        tree.pack(side="left", fill="both", expand=True)
        scroll.pack(side="left", fill="y")
        tree.bind("<<TreeviewSelect>>", self._on_select)
        tree.bind("<Double-1>", self._open_image)
        self._tree = tree

        preview = ttk.Frame(body, width=320)
        preview.pack(side="right", fill="y", padx=(8, 0))
        self._preview = ttk.Label(preview, text="选中一行查看证据图", anchor="center")
        self._preview.pack(fill="both", expand=True)
        self._detail = tk.StringVar(value="")
        ttk.Label(preview, textvariable=self._detail, wraplength=300).pack(fill="x")

        self.refresh_history()

    def refresh_history(self):
        if self._history is None or not self._history.winfo_exists():
            return
        tree = self._tree
        for item in tree.get_children():
            tree.delete(item)
        self._history_rows.clear()

        rows = self.recorder.recent(200, self._query.get().strip())
        for row in rows:
            key = tree.insert("", "end", values=(row["last"], row["plate"],
                                                 "{:.1f}%".format(row["confidence"]),
                                                 row["frames"]))
            self._history_rows[key] = row
        total = self.recorder.total()
        self._summary.set("本页 {} 条 · 累计 {} 条".format(len(rows), total))

    def _selected_row(self):
        selection = self._tree.selection()
        if not selection:
            return None
        return self._history_rows.get(selection[0])

    def _on_select(self, _event=None):
        row = self._selected_row()
        if not row:
            return
        self._detail.set("首次 {}  置信度 {:.1f}%  帧数 {}".format(
            row["first"], row["confidence"], row["frames"]))
        path = row["image"]
        if not path or not Path(path).exists():
            self._preview.configure(image="", text="（无证据图）")
            self._preview.image = None
            return
        try:
            with Image.open(path) as img:
                img.thumbnail((300, 200))
                self._thumb = ImageTk.PhotoImage(img.convert("RGB"))
            self._preview.configure(image=self._thumb, text="")
            self._preview.image = self._thumb
        except Exception:
            self._preview.configure(image="", text="（图片读取失败）")

    def _open_image(self, _event=None):
        row = self._selected_row()
        if row and row["image"] and Path(row["image"]).exists():
            self.open_records_dir()
            try:
                os.startfile(row["image"])               # noqa: S606
            except Exception:
                pass

    # ---------------------------------------------------------------- 收尾
    def close(self):
        try:
            if self.recorder is not None:
                self.recorder.close()
        finally:
            super().close()


def main():
    parser = argparse.ArgumentParser(description="车牌识别上位机（带记录）")
    parser.add_argument("--replay", type=Path, help="模拟二进制回放，不写记录")
    parser.add_argument("--smoke-test", action="store_true")
    parser.add_argument("--host", default="169.254.72.156")
    parser.add_argument("--port", type=int, default=8767)
    parser.add_argument("--auto-connect", action="store_true")
    parser.add_argument("--records-dir", default=None, help="记录根目录")
    args = parser.parse_args()

    root = tk.Tk()

    if args.smoke_test:
        from pc_viewer.tools.make_replay import build_replay
        from shared.lpr_wire import StreamParser

        root.withdraw()
        packets = StreamParser().feed(build_replay())
        app = RecordingViewer(root, replay=True, records_dir=args.records_dir)
        app.accept_replay_packet(packets[0])
        if len(app.canvas.find_withtag("plate_box")) != 1:
            raise RuntimeError("smoke test: expected one box")
        app.accept_replay_packet(packets[-1])
        if app.canvas.find_withtag("plate_box"):
            raise RuntimeError("smoke test: old box not cleared")
        app.close()
        print("smoke test ok")
        return

    app = RecordingViewer(root, replay=args.replay is not None, records_dir=args.records_dir)
    app.host_var.set(args.host)
    app.tcp_port_var.set(str(args.port))
    if args.auto_connect and args.replay is None:
        root.after(100, app.toggle_connection)
    if args.replay is not None:
        from shared.lpr_wire import StreamParser

        parser2 = StreamParser()
        packets = parser2.feed(args.replay.read_bytes())
        app.connection_var.set(
            "模拟回放：{} 包，CRC 错误 {}（非实机识别，不写记录）".format(len(packets), parser2.crc_errors))
        for index, packet in enumerate(packets):
            root.after(300 + index * 550, lambda item=packet: app.accept_replay_packet(item))
    root.mainloop()


if __name__ == "__main__":
    main()
