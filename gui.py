"""Cross-platform desktop UI; analysis runs in a separate cancellable process."""

from pathlib import Path
import json
import os
import subprocess
import sys
import time
import tkinter as tk
from tkinter import ttk, filedialog, messagebox
from PIL import Image, ImageTk, ImageGrab
from main import APP, VERSION, STATE
from platform_support import open_path


class Application:
    def __init__(self, args):
        self.args = args
        self.root = tk.Tk()
        self.root.title(APP)
        self.root.geometry("1300x860")
        self.root.minsize(1050, 700)
        self.root.configure(bg="#f2f5fa")
        self.root.protocol("WM_DELETE_WINDOW", self.close)
        self.process = None
        self.worker_log = None
        self.output = None
        self.result = None
        self.last_message = None
        self.preview_source = None
        self.image_ref = None
        self.resize_job = None
        self.closing = False
        STATE.mkdir(parents=True, exist_ok=True)
        try:
            self.preferences = json.loads((STATE / "settings.json").read_text(encoding="utf-8"))
        except (OSError, ValueError):
            self.preferences = {}
        self.source = tk.StringVar()
        self.destination = tk.StringVar(
            value=args.output
            or self.preferences.get("output", str(Path.home() / "Downloads" / "RPBotMapStudio"))
        )
        self.mode = tk.StringVar(value="Đầy đủ" if args.mode == "full" else "Nhanh")
        self.density = tk.StringVar(value="Vừa")
        self.want_cloud = tk.BooleanVar(value=True)
        self.phase = tk.StringVar(value="Chọn RTAB-Map, quỹ đạo, pose graph hoặc point cloud.")
        self.file_info = tk.StringVar(value="Chưa chọn file")
        self.filter = tk.StringVar()
        self._styles()
        self._layout()
        icon = Path(getattr(sys, "_MEIPASS", Path(__file__).parent)) / "assets" / "map_studio.ico"
        if sys.platform == "win32" and icon.exists():
            self.root.iconbitmap(str(icon))
        else:
            png = icon.with_suffix(".png")
            if png.exists():
                self.icon_image = tk.PhotoImage(file=str(png))
                self.root.iconphoto(True, self.icon_image)
        selected = args.file or args.database
        if selected:
            self.root.after(200, lambda: self.choose_file(selected))
        if args.open_result:
            self.root.after(250, lambda: self.load_result(args.open_result))
            if args.smoke:
                self.root.after(900, lambda: self.smoke_result("complete"))
        elif args.smoke:
            self.root.after(500, self.start)
        self.root.after(100, self.root.deiconify)
        self.root.after(250, self.poll)

    def _styles(self):
        style = ttk.Style(self.root)
        style.theme_use("clam")
        style.configure(".", font=("Segoe UI", 10))
        style.configure("TFrame", background="#f2f5fa")
        style.configure("Card.TFrame", background="white")
        style.configure("TLabel", background="#f2f5fa", foreground="#21364f")
        style.configure("Muted.TLabel", foreground="#61718a")
        style.configure("Card.TLabel", background="white", foreground="#61718a")
        style.configure(
            "Metric.TLabel", background="white", foreground="#183956", font=("Segoe UI", 23, "bold")
        )
        style.configure(
            "TButton", padding=(12, 9), background="#e5edf6", foreground="#233d5b", borderwidth=0
        )
        style.map(
            "TButton",
            background=[("active", "#d3e4f6"), ("disabled", "#edf0f5")],
            foreground=[("disabled", "#9aa6b8")],
        )
        style.configure(
            "Accent.TButton",
            background="#246bdf",
            foreground="white",
            font=("Segoe UI", 11, "bold"),
        )
        style.map(
            "Accent.TButton",
            background=[("active", "#1858bf"), ("disabled", "#a1b8dc")],
            foreground=[("disabled", "#f2f5fa")],
        )
        style.configure("TEntry", padding=7, fieldbackground="white")
        style.configure("TCombobox", padding=6, fieldbackground="white")
        style.map("TCombobox", fieldbackground=[("readonly", "white")])
        style.configure("TCheckbutton", background="#f2f5fa")
        style.configure("TNotebook", background="#f2f5fa", borderwidth=0)
        style.configure("TNotebook.Tab", padding=(18, 10), background="#e6edf6")
        style.map(
            "TNotebook.Tab",
            background=[("selected", "white")],
            foreground=[("selected", "#1f61be")],
        )
        style.configure(
            "Treeview",
            rowheight=30,
            fieldbackground="white",
            background="white",
            foreground="#23405b",
            borderwidth=0,
        )
        style.configure(
            "Horizontal.TProgressbar", background="#2875e4", troughcolor="#dce5f1", borderwidth=0
        )

    def _layout(self):
        header = tk.Frame(self.root, bg="#14283e", height=90)
        header.pack(fill="x")
        header.pack_propagate(False)
        tk.Label(
            header, text="RPBot Map Studio", font=("Segoe UI", 23, "bold"), fg="white", bg="#14283e"
        ).pack(anchor="w", padx=25, pady=(15, 0))
        tk.Label(
            header,
            text="Offline SLAM analysis · Windows / Linux · RTAB-Map + portable formats",
            font=("Segoe UI", 10),
            fg="#a9c0d9",
            bg="#14283e",
        ).pack(anchor="w", padx=27, pady=(3, 10))
        shell = ttk.Frame(self.root, padding=18)
        shell.pack(fill="both", expand=True)
        left_shell = ttk.Frame(shell, width=310)
        left_shell.pack(side="left", fill="y", padx=(0, 15))
        left_shell.pack_propagate(False)
        left_canvas = tk.Canvas(left_shell, bg="#f2f5fa", highlightthickness=0, width=292)
        left_canvas.pack(side="left", fill="both", expand=True)
        left_scroll = ttk.Scrollbar(left_shell, orient="vertical", command=left_canvas.yview)
        left_scroll.pack(side="right", fill="y")
        left_canvas.configure(yscrollcommand=left_scroll.set)
        left = ttk.Frame(left_canvas, width=292)
        left_canvas.create_window((0, 0), window=left, anchor="nw", width=292)
        left.bind(
            "<Configure>", lambda e: left_canvas.configure(scrollregion=left_canvas.bbox("all"))
        )

        def wheel(event):
            x = self.root.winfo_pointerx()
            y = self.root.winfo_pointery()
            if (
                left_shell.winfo_rootx() <= x < left_shell.winfo_rootx() + left_shell.winfo_width()
                and left_shell.winfo_rooty()
                <= y
                < left_shell.winfo_rooty() + left_shell.winfo_height()
            ):
                left_canvas.yview_scroll(-int(event.delta / 120), "units")

        self.root.bind_all("<MouseWheel>", wheel, add="+")
        left_canvas.bind("<Button-4>", lambda e: left_canvas.yview_scroll(-1, "units"))
        left_canvas.bind("<Button-5>", lambda e: left_canvas.yview_scroll(1, "units"))
        ttk.Label(left, text="DỮ LIỆU SLAM", font=("Segoe UI", 10, "bold")).pack(
            anchor="w", pady=(0, 9)
        )
        self.choose_button = ttk.Button(left, text="Chọn file dữ liệu…", command=self.choose_file)
        self.choose_button.pack(fill="x")
        self.source_entry = ttk.Entry(left, textvariable=self.source)
        self.source_entry.pack(fill="x", pady=(8, 4))
        ttk.Label(left, textvariable=self.file_info, style="Muted.TLabel", wraplength=290).pack(
            anchor="w", pady=(0, 18)
        )
        ttk.Label(left, text="NƠI LƯU KẾT QUẢ", font=("Segoe UI", 10, "bold")).pack(
            anchor="w", pady=(0, 7)
        )
        self.output_entry = ttk.Entry(left, textvariable=self.destination)
        self.output_entry.pack(fill="x")
        self.output_button = ttk.Button(left, text="Đổi thư mục…", command=self.choose_output)
        self.output_button.pack(fill="x", pady=(6, 18))
        ttk.Label(left, text="Chế độ phân tích").pack(anchor="w")
        self.mode_box = ttk.Combobox(
            left, textvariable=self.mode, values=["Đầy đủ", "Nhanh"], state="readonly"
        )
        self.mode_box.pack(fill="x", pady=(5, 4))
        ttk.Label(
            left,
            text="Đầy đủ: PDF, CSV, PNG/SVG và từng chỉ số.\nNhanh: hình tổng hợp, PDF và CSV.",
            style="Muted.TLabel",
            wraplength=290,
        ).pack(anchor="w", pady=(0, 13))
        self.cloud_check = ttk.Checkbutton(
            left, text="Dựng point cloud từ RTAB-Map RGB-D", variable=self.want_cloud
        )
        self.cloud_check.pack(anchor="w")
        self.density_box = ttk.Combobox(
            left, textvariable=self.density, values=["Vừa", "Nét hơn"], state="readonly"
        )
        self.density_box.pack(fill="x", pady=(6, 16))
        self.start_button = ttk.Button(
            left, text="Phân tích dữ liệu", style="Accent.TButton", command=self.start
        )
        self.start_button.pack(fill="x", pady=(0, 7))
        self.cancel_button = ttk.Button(
            left, text="Hủy xử lý", command=self.cancel, state="disabled"
        )
        self.cancel_button.pack(fill="x")
        ttk.Label(
            left,
            text="File gốc được giữ nguyên.\nMỗi lần phân tích tạo thư mục kết quả riêng.",
            style="Muted.TLabel",
            wraplength=290,
        ).pack(anchor="w", pady=(14, 12))
        ttk.Separator(left).pack(fill="x", pady=8)
        ttk.Label(left, text="KẾT QUẢ GẦN ĐÂY", font=("Segoe UI", 10, "bold")).pack(
            anchor="w", pady=(4, 7)
        )
        self.history = ttk.Combobox(left, state="readonly", values=[])
        self.history.pack(fill="x")
        ttk.Button(left, text="Mở kết quả đã có", command=self.open_history).pack(fill="x", pady=6)
        self.history_paths = []
        self.refresh_history()
        ttk.Label(left, text="v" + VERSION, style="Muted.TLabel").pack(anchor="w", pady=(10, 12))
        right = ttk.Frame(shell)
        right.pack(side="left", fill="both", expand=True)
        cards = ttk.Frame(right)
        cards.pack(fill="x", pady=(0, 13))
        self.card_labels = {}
        for i, (key, title) in enumerate(
            [
                ("nodes", "NODE HỢP LỆ"),
                ("metrics", "CHỈ SỐ"),
                ("cloud", "ĐIỂM 3D"),
                ("figures", "HÌNH XUẤT"),
            ]
        ):
            cards.columnconfigure(i, weight=1)
            card = ttk.Frame(cards, style="Card.TFrame", padding=12)
            card.grid(row=0, column=i, sticky="ew", padx=(0, 8 if i < 3 else 0))
            ttk.Label(card, text=title, style="Card.TLabel", font=("Segoe UI", 9)).pack(anchor="w")
            label = ttk.Label(card, text="—", style="Metric.TLabel")
            label.pack(anchor="w", pady=(5, 0))
            self.card_labels[key] = label
        ttk.Label(right, textvariable=self.phase, wraplength=850).pack(fill="x", pady=(0, 7))
        self.bar = ttk.Progressbar(right, maximum=100)
        self.bar.pack(fill="x", pady=(0, 12))
        actions = ttk.Frame(right)
        actions.pack(fill="x", pady=(0, 12))
        self.action_buttons = {}
        for key, title, fn in [
            ("report", "Mở báo cáo", lambda: self.open_result("index.html")),
            ("pdf", "PDF", lambda: self.open_result("SLAM_report.pdf")),
            ("map", "Xem map 3D", lambda: self.open_result("view_map_3d.html")),
            ("zip", "Gói ZIP", lambda: self.open_result("RPBotMapStudio_report.zip")),
            ("folder", "Thư mục kết quả", lambda: self.open_result("")),
        ]:
            b = ttk.Button(actions, text=title, command=fn, state="disabled")
            b.pack(side="left", padx=(0, 6))
            self.action_buttons[key] = b
        self.tabs = ttk.Notebook(right)
        self.tabs.pack(fill="both", expand=True)
        overview = ttk.Frame(self.tabs)
        charts = ttk.Frame(self.tabs)
        logs = ttk.Frame(self.tabs)
        self.tabs.add(overview, text="Tổng quan")
        self.tabs.add(charts, text="Đồ thị")
        self.tabs.add(logs, text="Nhật ký")
        self.overview_text = tk.Text(
            overview,
            height=6,
            bg="white",
            fg="#344e69",
            font=("Segoe UI", 10),
            wrap="word",
            relief="flat",
            padx=14,
            pady=12,
        )
        self.overview_text.pack(fill="x", pady=(8, 8))
        self.set_overview(
            "Chọn dữ liệu SLAM rồi bấm “Phân tích dữ liệu”.\nApp tự đọc dữ liệu có trong file, tạo bản đồ và các đồ thị phù hợp.\nKhông cần kết nối Pi, ROS hay WSL."
        )
        self.overview_image = tk.Label(
            overview, text="Bản đồ và kết quả sẽ hiện ở đây", bg="white", fg="#8898aa"
        )
        self.overview_image.pack(fill="both", expand=True)
        toolbar = ttk.Frame(charts, padding=(0, 8))
        toolbar.pack(fill="x")
        ttk.Label(toolbar, text="Lọc đồ thị:").pack(side="left")
        ttk.Entry(toolbar, textvariable=self.filter).pack(
            side="left", fill="x", expand=True, padx=8
        )
        self.filter.trace_add("write", lambda *_: self.populate_charts())
        pane = ttk.Panedwindow(charts, orient="horizontal")
        pane.pack(fill="both", expand=True)
        list_frame = ttk.Frame(pane)
        preview = ttk.Frame(pane)
        pane.add(list_frame, weight=1)
        pane.add(preview, weight=3)
        self.tree = ttk.Treeview(list_frame, show="tree", selectmode="browse")
        self.tree.pack(side="left", fill="both", expand=True)
        scroll = ttk.Scrollbar(list_frame, orient="vertical", command=self.tree.yview)
        scroll.pack(side="right", fill="y")
        self.tree.configure(yscrollcommand=scroll.set)
        self.tree.bind("<<TreeviewSelect>>", self.chart_selected)
        self.chart_title = ttk.Label(
            preview, text="Chọn đồ thị bên trái", font=("Segoe UI", 11, "bold"), wraplength=600
        )
        self.chart_title.pack(fill="x", padx=10, pady=9)
        self.preview = tk.Label(preview, bg="white", fg="#8798ad")
        self.preview.pack(fill="both", expand=True)
        self.chart_note = ttk.Label(preview, wraplength=650, style="Muted.TLabel")
        self.chart_note.pack(fill="x", padx=10, pady=8)
        ttk.Button(preview, text="Mở hình gốc", command=self.open_chart).pack(anchor="e", pady=6)
        self.preview.bind("<Configure>", lambda e: self.schedule_resize())
        self.overview_image.bind("<Configure>", lambda e: self.schedule_resize())
        self.log = tk.Text(
            logs,
            bg="#122236",
            fg="#c3d7eb",
            font=("Consolas", 9),
            wrap="word",
            relief="flat",
            padx=12,
            pady=12,
        )
        self.log.pack(fill="both", expand=True, pady=8)

    def set_overview(self, text):
        self.overview_text.configure(state="normal")
        self.overview_text.delete("1.0", "end")
        self.overview_text.insert("end", text)
        self.overview_text.configure(state="disabled")

    def choose_file(self, path=None):
        if self.process and self.process.poll() is None:
            return
        if not path:
            path = filedialog.askopenfilename(
                parent=self.root,
                title="Chọn dữ liệu SLAM",
                filetypes=[
                    (
                        "SLAM data",
                        "*.db *.sqlite *.sqlite3 *.tum *.txt *.kitti *.csv *.g2o *.ply *.pcd",
                    ),
                    ("RTAB-Map", "*.db *.sqlite *.sqlite3"),
                    ("Trajectory", "*.tum *.txt *.kitti *.csv"),
                    ("Pose graph", "*.g2o"),
                    ("Point cloud", "*.ply *.pcd"),
                    ("All files", "*.*"),
                ],
            )
        if not path:
            return
        self.source.set(str(Path(path).resolve()))
        try:
            from analysis import inspect_file

            info = inspect_file(path)
            self.file_info.set(
                f"{info['name']}\n{info['format'].upper()} · {info['bytes'] / 1024**2:.1f} MB"
            )
            self.phase.set("Đã chọn database. Bấm Phân tích để xử lý.")
        except Exception as e:
            self.file_info.set(str(e))
            self.phase.set("Hãy chọn một định dạng được hỗ trợ.")

    def choose_output(self):
        path = filedialog.askdirectory(
            parent=self.root, title="Nơi lưu kết quả", initialdir=self.destination.get()
        )
        if path:
            self.destination.set(path)

    def set_busy(self, busy):
        for widget in [
            self.choose_button,
            self.source_entry,
            self.output_entry,
            self.output_button,
            self.start_button,
            self.cloud_check,
        ]:
            widget.configure(state="disabled" if busy else "normal")
        for widget in [self.mode_box, self.density_box]:
            widget.configure(state="disabled" if busy else "readonly")
        self.cancel_button.configure(state="normal" if busy else "disabled")

    def start(self):
        if self.process and self.process.poll() is None:
            return
        try:
            from analysis import inspect_file, new_output, atomic_json

            source = inspect_file(self.source.get())
            out = new_output(self.destination.get(), source["path"])
            job = {
                "source": source["path"],
                "output": str(out),
                "mode": "full" if self.mode.get() == "Đầy đủ" else "quick",
                "density": "fine" if self.density.get() == "Nét hơn" else "standard",
                "pointcloud": self.want_cloud.get(),
                "zip": True,
            }
            atomic_json(out / "job.json", job)
            self.output = out
            self.result = None
            self.last_message = None
            self.bar["value"] = 0
            self.tree.delete(*self.tree.get_children())
            self.set_busy(True)
            self.preview_source = None
            self.overview_source = None
            self.preview.configure(image="", text="Đang xử lý…")
            self.overview_image.configure(image="", text="Đang xử lý…")
            for label in self.card_labels.values():
                label.configure(text="—")
            for b in self.action_buttons.values():
                b.configure(state="disabled")
            self.phase.set("Đang khởi động bộ phân tích…")
            self.set_overview(
                "Đang xử lý bản sao độc lập của database.\nBạn có thể hủy giữa chừng; file gốc được giữ nguyên."
            )
            command = (
                [sys.executable, "--worker", str(out / "job.json")]
                if getattr(sys, "frozen", False)
                else [
                    sys.executable,
                    "-u",
                    str(Path(__file__).with_name("main.py")),
                    "--worker",
                    str(out / "job.json"),
                ]
            )
            env = os.environ.copy()
            env["PYTHONUTF8"] = "1"
            env["MPLBACKEND"] = "Agg"
            self.worker_log = (out / "worker.log").open("w", encoding="utf-8")
            self.process = subprocess.Popen(
                command,
                stdout=self.worker_log,
                stderr=subprocess.STDOUT,
                env=env,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
            self.preferences["output"] = self.destination.get()
            atomic_json(STATE / "settings.json", self.preferences)
        except Exception as e:
            self.set_busy(False)
            self.phase.set(str(e))
            if self.args.smoke:
                self.smoke_result("failed", str(e))
            else:
                messagebox.showerror(APP, str(e), parent=self.root)

    def cancel(self):
        if self.output and self.process and self.process.poll() is None:
            (self.output / "cancel.requested").touch()
            self.phase.set("Đang hủy sau bước xử lý hiện tại…")
            self.cancel_button.configure(state="disabled")

    def poll(self):
        if self.closing:
            return
        if self.process:
            progress = {}
            try:
                progress = json.loads((self.output / "progress.json").read_text(encoding="utf-8"))
            except (OSError, ValueError):
                pass
            if progress:
                self.bar["value"] = progress.get("percent", 0)
                self.phase.set(progress.get("message", ""))
                if progress.get("message") != self.last_message:
                    self.log.insert(
                        "end", time.strftime("%H:%M:%S") + "  " + progress.get("message", "") + "\n"
                    )
                    self.log.see("end")
                    self.last_message = progress.get("message")
            code = self.process.poll()
            if code is not None:
                if self.worker_log:
                    self.worker_log.close()
                    self.worker_log = None
                self.process = None
                self.set_busy(False)
                if progress.get("state") == "complete":
                    try:
                        self.load_result(self.output)
                        self.remember(self.output)
                        if self.args.smoke:
                            self.smoke_result("complete")
                    except Exception as exc:
                        message = "Báo cáo đã xuất nhưng không hiển thị được: " + str(exc)
                        self.phase.set(message)
                        if self.args.smoke:
                            self.smoke_result("failed", message)
                        else:
                            messagebox.showerror(APP, message, parent=self.root)
                elif progress.get("state") == "cancelled":
                    self.phase.set("Đã hủy. Database gốc được giữ nguyên.")
                    self.action_buttons["folder"].configure(state="normal")
                    if self.args.smoke:
                        self.smoke_result("cancelled")
                else:
                    message = (
                        progress.get("message")
                        or f"Bộ phân tích kết thúc bất thường (mã {code}). Xem worker.log trong thư mục kết quả."
                    )
                    self.phase.set(message)
                    self.action_buttons["folder"].configure(state="normal")
                    for name in ["worker.log", "analysis.log"]:
                        try:
                            self.log.insert(
                                "end",
                                "\n"
                                + (self.output / name).read_text(
                                    encoding="utf-8", errors="replace"
                                )[-12000:],
                            )
                            self.log.see("end")
                        except OSError:
                            pass
                    if self.args.smoke:
                        self.smoke_result("failed", message)
                    else:
                        messagebox.showerror(APP, message, parent=self.root)
        self.root.after(250, self.poll)

    def load_result(self, folder):
        folder = Path(folder)
        self.result = json.loads((folder / "manifest.json").read_text(encoding="utf-8"))
        self.output = folder
        r = self.result
        self.source.set(r["database"])
        self.file_info.set(f"{r['database_name']}\n{r['database_bytes'] / 1024**2:.1f} MB")
        for key, value in [
            ("nodes", r["nodes_valid"]),
            ("metrics", r["metric_count"]),
            ("cloud", r["pointcloud_vertices"]),
            ("figures", r["figure_count"]),
        ]:
            self.card_labels[key].configure(text=f"{value:,}")
        self.phase.set("Hoàn tất · " + r["database_name"])
        self.bar["value"] = 100
        text = f"{r['database_name']} · {r.get('input_format', 'RTAB-Map')} · {r['database_bytes'] / 1024**2:.1f} MB\n"
        text += f"{r['nodes_valid']} pose hợp lệ · {r['rgb_nodes']} RGB · {r['depth_nodes']} depth · {r['pdf_pages']} trang PDF\n"
        text += (
            "Quãng đường từ pose: " + f"{r['path_m']:.2f} m"
            if r.get("path_m") is not None
            else "Không có quãng đường theo thời gian"
        ) + f" · {r['links']} liên kết đã lưu\n"
        text += "\n".join(r["warnings"][:2])
        self.set_overview(text)
        self.populate_charts()
        target = folder / "map_2d.png"
        if not target.exists() and r["figures"]:
            target = folder / r["figures"][min(1, len(r["figures"]) - 1)]["file"]
        self.overview_source = target if target.exists() else None
        self.render_preview()
        available = {
            "report": "index.html",
            "pdf": "SLAM_report.pdf",
            "map": "view_map_3d.html",
            "zip": "RPBotMapStudio_report.zip",
            "folder": "",
        }
        for key, name in available.items():
            self.action_buttons[key].configure(
                state="normal" if (folder / name).exists() else "disabled"
            )
        self.tabs.select(0)

    def populate_charts(self):
        if not hasattr(self, "tree"):
            return
        self.tree.delete(*self.tree.get_children())
        self.chart_rows = {}
        if not self.result:
            return
        q = self.filter.get().lower().strip()
        for title, name in [("Hình tổng hợp", "figures"), ("Chỉ số đã lưu", "metrics")]:
            rows = [f for f in self.result.get(name, []) if q in f["title"].lower()]
            if not rows:
                continue
            parent = self.tree.insert("", "end", text=f"{title} ({len(rows)})", open=True)
            for f in rows:
                key = self.tree.insert(parent, "end", text=f["title"])
                self.chart_rows[key] = f

    def chart_selected(self, event=None):
        selected = self.tree.selection()
        if not selected or selected[0] not in self.chart_rows:
            return
        f = self.chart_rows[selected[0]]
        self.preview_source = self.output / f["file"]
        self.chart_title.configure(text=f["title"])
        self.chart_note.configure(
            text=f.get(
                "note", "Hằng số như đã ghi; không phải sai số thực." if f.get("constant") else ""
            )
        )
        self.render_preview()

    def schedule_resize(self):
        if self.resize_job:
            self.root.after_cancel(self.resize_job)
        self.resize_job = self.root.after(120, self.render_preview)

    def render_preview(self):
        self.resize_job = None
        for widget, path in [
            (self.preview, self.preview_source),
            (self.overview_image, getattr(self, "overview_source", None)),
        ]:
            if not path or not Path(path).exists():
                continue
            try:
                with Image.open(path) as source:
                    image = source.copy()
                image.thumbnail(
                    (max(100, widget.winfo_width() - 18), max(100, widget.winfo_height() - 18)),
                    Image.Resampling.LANCZOS,
                )
                photo = ImageTk.PhotoImage(image)
                widget.configure(image=photo, text="")
                widget.image = photo
            except (OSError, ValueError):
                pass

    def open_chart(self):
        if self.preview_source and self.preview_source.exists():
            open_path(self.preview_source)

    def open_result(self, name):
        if self.output and (self.output / name).exists():
            open_path(self.output / name)

    def remember(self, folder):
        from analysis import atomic_json

        entries = [str(folder)] + [
            p for p in self.preferences.get("history", []) if p != str(folder)
        ]
        self.preferences["history"] = entries[:12]
        atomic_json(STATE / "settings.json", self.preferences)
        self.refresh_history()

    def refresh_history(self):
        self.history_paths = [
            p for p in self.preferences.get("history", []) if (Path(p) / "manifest.json").is_file()
        ]
        self.history.configure(values=[Path(p).name for p in self.history_paths])
        if self.history_paths:
            self.history.current(0)

    def open_history(self):
        if self.process:
            return
        i = self.history.current()
        if i >= 0:
            try:
                self.load_result(self.history_paths[i])
            except (OSError, ValueError, KeyError) as e:
                messagebox.showerror(APP, "Không mở được báo cáo: " + str(e), parent=self.root)

    def smoke_result(self, state, message=""):
        self.root.deiconify()
        self.root.update()
        self.root.update_idletasks()
        if self.args.smoke_report:
            from analysis import atomic_json

            target = Path(self.args.smoke_report)
            target.parent.mkdir(parents=True, exist_ok=True)
            try:
                import ctypes

                self.root.update()
                if sys.platform != "win32":
                    bbox = (
                        self.root.winfo_rootx(),
                        self.root.winfo_rooty(),
                        self.root.winfo_rootx() + self.root.winfo_width(),
                        self.root.winfo_rooty() + self.root.winfo_height(),
                    )
                    ImageGrab.grab(bbox=bbox).save(target.with_suffix(".png"))
                    raise StopIteration
                user = ctypes.windll.user32
                user.GetAncestor.argtypes = [ctypes.c_void_p, ctypes.c_uint]
                user.GetAncestor.restype = ctypes.c_void_p
                hwnd = user.GetAncestor(self.root.winfo_id(), 2)
                ImageGrab.grab(window=hwnd).save(target.with_suffix(".png"))
            except Exception:
                pass
            atomic_json(
                target,
                {
                    "state": state,
                    "message": message,
                    "output": str(self.output),
                    "visible": bool(self.root.winfo_viewable()),
                    "window_id": self.root.winfo_id(),
                    "result": self.result,
                },
            )
        if self.args.quit_on_complete:
            self.root.after(500, self.close)

    def close(self):
        if self.closing:
            return
        self.closing = True
        if self.process and self.process.poll() is None:
            self.cancel()
            try:
                self.process.wait(timeout=3)
            except subprocess.TimeoutExpired:
                self.process.terminate()
                try:
                    self.process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    pass
        if self.worker_log:
            self.worker_log.close()
        self.root.destroy()

    def run(self):
        self.root.mainloop()
        return 0
