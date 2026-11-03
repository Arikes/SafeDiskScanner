#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
大文件扫描器 —— 本地磁盘空间管理工具
功能：
  1. 显示当前磁盘总容量 / 已使用 / 剩余，并用进度条直观展示占用比例
  2. 从根目录(/)开始浏览目录与文件，目录和文件均展示占用大小，按大小降序排列
  3. 一键扫描指定目录下最大的 N 个文件，支持中途取消
  4. 后台线程扫描，界面保持流畅；同名与权限受限目录自动跳过不报错

运行方式：  python3 大文件扫描器.py
"""
import os
import sys
import shutil
import threading
import queue
import heapq
import time
import subprocess
import stat
import json
import tempfile
import tkinter as tk
from tkinter import ttk, messagebox
from ui_theme import PALETTES, DiskOverview, apply_modern_theme, configure_typography
from app_storage.view import AppStoragePage

APP_VERSION = "1.8.0"

# ---------------- 工具函数 ----------------

def fmt_size(n):
    """把字节数格式化为人类可读字符串"""
    if n is None:
        return "—"
    size = float(n)
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if size < 1024 or unit == "TB":
            return ("%d%s" if unit == "B" else "%.1f%s") % (size, unit) if unit == "B" else ("%.1f%s" % (size, unit))
        size /= 1024.0

def fmt_size_raw(n):
    if n is None:
        return 0
    return int(n)

def disk_usage(path):
    """返回 (总容量, 已使用, 剩余) 字节数"""
    try:
        u = shutil.disk_usage(path)
        return u.total, u.used, u.free
    except Exception:
        return 0, 0, 0

def is_macos():
    return sys.platform == "darwin"

def open_in_finder(path):
    """在访达中打开：文件则定位并选中(open -R)，目录则打开该目录"""
    try:
        if os.path.isfile(path):
            subprocess.Popen(["open", "-R", path])
        else:
            subprocess.Popen(["open", path])
    except Exception:
        pass


def sort_settings_path():
    return os.path.join(os.path.expanduser("~"), "Library", "Application Support",
                        "SafeDiskScanner", "settings.json")


def load_sort_direction(settings_path=None):
    """缺失或损坏配置不妨碍启动，默认按大小降序。"""
    try:
        with open(settings_path or sort_settings_path(), encoding="utf-8") as stream:
            settings = json.load(stream)
        value = settings.get("size_sort_descending", True) if isinstance(settings, dict) else True
        return value if type(value) is bool else True
    except (OSError, ValueError):
        return True


def _save_preferences(updates, settings_path=None):
    """合并配置后原子保存，排序和筛选设置互不覆盖。"""
    path = os.path.abspath(settings_path or sort_settings_path())
    temporary = None
    try:
        try:
            with open(path, encoding="utf-8") as stream:
                settings = json.load(stream)
            if not isinstance(settings, dict):
                settings = {}
        except (FileNotFoundError, ValueError):
            settings = {}
        settings.update(updates)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        fd, temporary = tempfile.mkstemp(prefix=".settings-", suffix=".json", dir=os.path.dirname(path))
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            json.dump(settings, stream, ensure_ascii=False, indent=2)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
        temporary = None
        return True
    except OSError:
        return False
    finally:
        if temporary is not None:
            try:
                os.unlink(temporary)
            except OSError:
                pass


def save_sort_direction(descending, settings_path=None):
    return _save_preferences({"browser_sort_column": "size", "size_sort_descending": bool(descending)}, settings_path)


def load_browser_sort(settings_path=None):
    """旧配置默认继续按大小排序；修改时间首次使用降序。"""
    try:
        with open(settings_path or sort_settings_path(), encoding="utf-8") as stream:
            settings = json.load(stream)
        if not isinstance(settings, dict):
            return "size", True
        column = settings.get("browser_sort_column", "size")
        descending = settings.get("mtime_sort_descending", True)
        return (column if column in ("size", "mtime") else "size",
                descending if type(descending) is bool else True)
    except (OSError, ValueError):
        return "size", True


def save_mtime_sort_direction(descending, settings_path=None):
    return _save_preferences({"browser_sort_column": "mtime", "mtime_sort_descending": bool(descending)}, settings_path)


def load_type_filter(settings_path=None):
    try:
        with open(settings_path or sort_settings_path(), encoding="utf-8") as stream:
            settings = json.load(stream)
        values = settings.get("excluded_file_types", []) if isinstance(settings, dict) else []
        if not isinstance(values, list):
            return set()
        return {value.casefold() for value in values if isinstance(value, str) and
                (value.casefold() in ("folder", "no_extension") or
                 (value.casefold().startswith("ext:.") and len(value) > 5 and "/" not in value))}
    except (OSError, ValueError):
        return set()


def save_type_filter(excluded_types, settings_path=None):
    return _save_preferences({"excluded_file_types": sorted(excluded_types)}, settings_path)


def load_sidebar_collapsed(settings_path=None):
    try:
        with open(settings_path or sort_settings_path(), encoding="utf-8") as stream:
            settings = json.load(stream)
        value = settings.get("sidebar_collapsed", False) if isinstance(settings, dict) else False
        return value if type(value) is bool else False
    except (OSError, ValueError):
        return False


def save_sidebar_collapsed(collapsed, settings_path=None):
    return _save_preferences({"sidebar_collapsed": bool(collapsed)}, settings_path)


def browser_item_type(item):
    if item[1]:
        return "folder"
    extension = os.path.splitext(item[2])[1].casefold()
    return "ext:" + extension if extension and extension != "." else "no_extension"


def browser_type_label(key):
    if key == "folder":
        return "文件夹"
    if key == "no_extension":
        return "无扩展名"
    return key[5:].upper() + " 文件"


def normalize_trash_paths(paths):
    """仅规范化路径拼写，不解析符号链接；根目录和重复项不参与删除。"""
    unique = list(dict.fromkeys(os.path.abspath(path) for path in paths if path))
    unique = [path for path in unique if path != os.path.abspath(os.sep)]
    # 同时选中目录和它的子项时只移动目录，避免重复删除导致误报。
    parents = [path for path in unique if os.path.isdir(path) and not os.path.islink(path)]
    return [path for path in unique
            if not any(path != parent and path.startswith(parent + os.sep) for parent in parents)]


def trash_items(paths):
    """调用随应用打包的原生工具；失败时只报错，不回退到永久删除。"""
    base = getattr(sys, "_MEIPASS", os.path.join(os.path.dirname(os.path.abspath(__file__)), "build"))
    helper = os.path.join(base, "trash-helper")
    try:
        result = subprocess.run([helper], input=json.dumps(paths), text=True,
                                capture_output=True, check=True)
        receipts = json.loads(result.stdout)
        if not isinstance(receipts, list) or [r.get("path") for r in receipts] != list(paths):
            raise ValueError("删除工具返回了不完整的结果")
        return receipts
    except (OSError, ValueError, subprocess.SubprocessError) as exc:
        detail = getattr(exc, "stderr", None) or str(exc)
        return [{"path": path, "trashed": False, "error": detail} for path in paths]


# ---------------- 双模式(深色/浅色)配色 ----------------

def detect_system_mode():
    """检测 macOS 系统外观：深色为 dark，浅色为 light"""
    try:
        r = subprocess.run(["defaults", "read", "-g", "AppleInterfaceStyle"],
                           capture_output=True, text=True)
        if r.returncode == 0 and "Dark" in r.stdout:
            return "dark"
    except Exception:
        pass
    return "light"


# ---------------- 主应用 ----------------

class ScannerApp:
    def __init__(self, root):
        self.root = root
        root.title("大文件扫描器 v%s - 磁盘空间管理" % APP_VERSION)
        root.geometry("1180x820")
        root.minsize(900, 720)
        configure_typography(root)

        # 外观模式：自动跟随系统(深色/浅色)，也可手动切换。
        # 使用 clam 主题 + 显式调色板，确保两种模式下文字都清晰可读。
        self.style = ttk.Style(root)
        try:
            self.style.theme_use("clam")
        except Exception:
            pass
        self.mode = detect_system_mode()

        # 状态
        self.current_path = os.path.expanduser("~")   # 当前浏览目录
        self.scope_root = os.path.expanduser("~")      # 默认扫描当前用户的主目录
        self.scan_limit = 200                          # 保留最大文件数量
        self.scan_cancel = threading.Event()           # 取消标志
        self._scanning = False                         # 是否正在扫描
        self._deleting = False
        self._scan_thread = None
        self.trash_result_q = queue.Queue()
        self.show_hidden = tk.BooleanVar(value=False)  # 是否显示隐藏文件(默认隐藏)
        self.dir_size_cache = {}                       # 目录大小缓存 path->bytes
        self._size_cancel = threading.Event()         # 导航代次，取消离开目录后的旧计算
        self.dir_size_pending = set()                  # 正在计算大小的目录
        self.file_items = []                           # 当前列表的原始数据 (size, is_dir, name, path)
        self._browser_read_error = None
        self.size_sort_descending = load_sort_direction()
        self.sort_column, self.mtime_sort_descending = load_browser_sort()
        self._file_mtimes = {}
        self.excluded_file_types = load_type_filter()
        self.sidebar_collapsed = load_sidebar_collapsed()
        self._sidebar_width = 210
        self._type_filter_popup = None
        self._file_item_indexes = {}
        self._file_order = []
        self._size_sort_dirty = False

        # 线程间通信队列
        self.size_req_q = queue.Queue()                # 目录大小计算请求 path
        self.size_res_q = queue.Queue()                # 目录大小计算结果 (path, size)
        self.scan_result_q = queue.Queue()             # 扫描进度/结果消息

        # 顶部概览与工作区；只重排控件，事件仍沿用原有处理方法。
        shell = ttk.Frame(root, padding=(20, 16, 20, 10))
        shell.pack(fill="both", expand=True)
        shell.columnconfigure(0, weight=1)
        shell.rowconfigure(1, weight=1)

        self.disk_var = tk.StringVar(value="计算中…")
        self.disk_total_var = tk.StringVar(value="—")
        self.disk_used_var = tk.StringVar(value="—")
        self.disk_free_var = tk.StringVar(value="—")
        self.disk_overview = DiskOverview(
            shell, (("总容量", self.disk_total_var), ("已使用空间", self.disk_used_var),
                    ("剩余可用空间", self.disk_free_var)),
            self.disk_var, self.refresh_disk, self.mode)
        self.disk_overview.grid(row=0, column=0, sticky="ew", pady=(0, 12))

        self.notebook = ttk.Notebook(shell, style="Workspace.TNotebook")
        self.notebook.grid(row=1, column=0, sticky="nsew")
        self.appearance_btn = ttk.Button(self.notebook, command=self.toggle_theme, style="Header.TButton")
        self.appearance_btn.place(relx=1, x=-12, y=20, anchor="e")
        self.browse_tab = ttk.Frame(self.notebook)
        self.scan_tab = ttk.Frame(self.notebook, style="Card.TFrame")
        self.cleanup_tab = ttk.Frame(self.notebook, style="Card.TFrame")
        self.search_tab = ttk.Frame(self.notebook, style="Card.TFrame")
        self.notebook.add(self.browse_tab, text="文件浏览")
        self.notebook.add(self.scan_tab, text="大文件扫描")
        self.notebook.add(self.cleanup_tab, text="磁盘清理")
        self.notebook.add(self.search_tab, text="快速检索")
        self.notebook.select(self.browse_tab)
        self.notebook.enable_traversal()
        self.app_storage_page = AppStoragePage(self.cleanup_tab, self.notebook, fmt_size,
                                               open_in_finder, self.browse_app_storage_path)
        workspace = ttk.PanedWindow(self.browse_tab, orient="horizontal")
        self.workspace = workspace
        workspace.pack(fill="both", expand=True, pady=(10, 0))
        left = ttk.Frame(workspace, style="Sidebar.TFrame", padding=14, width=210)
        self.sidebar = left
        if not self.sidebar_collapsed:
            workspace.add(left, weight=0)
        left.columnconfigure(0, weight=1)
        left.rowconfigure(3, weight=1)
        sidebar_head = ttk.Frame(left, style="Sidebar.TFrame")
        sidebar_head.grid(row=0, column=0, sticky="ew", pady=(0, 10))
        ttk.Label(sidebar_head, text="位置", style="SidebarTitle.TLabel").pack(side="left")
        self.sidebar_collapse_button = ttk.Button(sidebar_head, text="收起", style="Nav.TButton", command=self.toggle_sidebar)
        self.sidebar_collapse_button.pack(side="right")
        quick = ttk.Frame(left, style="Sidebar.TFrame")
        quick.grid(row=1, column=0, sticky="ew", pady=(0, 8))
        quick.columnconfigure((0, 1), weight=1)
        ttk.Button(quick, text="主目录", command=lambda: self.navigate(os.path.expanduser("~")), style="Nav.TButton").grid(row=0, column=0, sticky="ew", padx=(0, 4))
        ttk.Button(quick, text="根目录 /", command=lambda: self.navigate("/"), style="Nav.TButton").grid(row=0, column=1, sticky="ew")
        ttk.Label(left, text="双击目录以浏览", style="SidebarMuted.TLabel").grid(row=2, column=0, sticky="w", pady=(0, 8))
        tree_area = ttk.Frame(left, style="Sidebar.TFrame")
        tree_area.grid(row=3, column=0, sticky="nsew")
        tree_area.columnconfigure(0, weight=1)
        tree_area.rowconfigure(0, weight=1)
        self.tree = ttk.Treeview(tree_area, show="tree", selectmode="browse")
        self.tree.column("#0", width=175, minwidth=130)
        self.tree.grid(row=0, column=0, sticky="nsew")
        tv = ttk.Scrollbar(tree_area, orient="vertical", command=self.tree.yview)
        tv.grid(row=0, column=1, sticky="ns")
        self.tree.configure(yscrollcommand=tv.set)
        tx = ttk.Scrollbar(tree_area, orient="horizontal", command=self.tree.xview)
        tx.grid(row=1, column=0, sticky="ew")
        self.tree.configure(xscrollcommand=tx.set)
        self.tree.bind("<<TreeviewOpen>>", self.on_tree_open)
        self.tree.bind("<Double-1>", self.on_tree_dbl)

        browse = ttk.Frame(workspace, style="Card.TFrame", padding=(16, 14))
        workspace.add(browse, weight=1)
        browse.columnconfigure(0, weight=1)
        browse.rowconfigure(3, weight=1)
        head = ttk.Frame(browse, style="Card.TFrame")
        head.grid(row=0, column=0, sticky="ew", pady=(0, 10))
        self.sidebar_expand_button = ttk.Button(head, text="展开目录树", style="SoftAccent.TButton", command=self.toggle_sidebar)
        if self.sidebar_collapsed:
            self.sidebar_expand_button.pack(side="left", padx=(0, 12))
        self.browser_heading = ttk.Label(head, text="当前目录", style="Section.TLabel")
        self.browser_heading.pack(side="left")
        self.sort_hint_var = tk.StringVar()
        ttk.Label(head, textvariable=self.sort_hint_var, style="CardMuted.TLabel").pack(side="left", padx=10)
        ttk.Button(head, text="刷新列表", command=lambda: self.navigate(self.current_path), style="Ghost.TButton").pack(side="right")
        ttk.Checkbutton(head, text="显示隐藏文件", variable=self.show_hidden, command=self.on_show_hidden, style="Card.TCheckbutton").pack(side="right", padx=12)
        path_frame = ttk.Frame(browse, style="Card.TFrame")
        path_frame.grid(row=1, column=0, sticky="ew", pady=(0, 10))
        path_frame.columnconfigure(1, weight=1)
        ttk.Button(path_frame, text="向上", command=self.go_up, style="Small.TButton").grid(row=0, column=0, padx=(0, 8))
        self.path_var = tk.StringVar(value=self.current_path)
        self.path_entry = ttk.Entry(path_frame, textvariable=self.path_var, width=20)
        self.path_entry.grid(row=0, column=1, sticky="ew")
        self.path_entry.bind("<Return>", lambda e: self.navigate(self.path_var.get()))
        ttk.Button(path_frame, text="转到", command=lambda: self.navigate(self.path_var.get()), style="SoftAccent.TButton").grid(row=0, column=2, padx=(8, 0))
        self._populate_tree()

        filter_bar = ttk.Frame(browse, style="Card.TFrame")
        filter_bar.grid(row=2, column=0, sticky="ew", pady=(0, 8))
        self.filter_summary_var = tk.StringVar()
        summary = ttk.Label(filter_bar, textvariable=self.filter_summary_var, style="CardMuted.TLabel", wraplength=400)
        summary.pack(side="left", fill="x", expand=True)
        ttk.Button(filter_bar, text="全部展示", command=self.reset_type_filter, style="Ghost.TButton").pack(side="right", padx=(8, 0))
        ttk.Button(filter_bar, text="筛选类型…", command=self.open_type_filter, style="SoftAccent.TButton").pack(side="right", padx=(8, 0))
        filter_bar.bind("<Configure>", lambda e: summary.configure(wraplength=max(100, e.width - 220)))
        files_area = ttk.Frame(browse, style="Card.TFrame")
        files_area.grid(row=3, column=0, sticky="nsew")
        files_area.columnconfigure(0, weight=1)
        files_area.rowconfigure(0, weight=1)
        cols = ("name", "size", "type", "mtime")
        self.flist = ttk.Treeview(files_area, columns=cols, show="headings", height=6, selectmode="extended")
        for name, title, width, anchor, stretch in (("name", "名称", 270, "w", True),
                ("size", "大小", 95, "e", False), ("type", "类型", 110, "center", False),
                ("mtime", "修改时间", 145, "center", False)):
            self.flist.heading(name, text=title, anchor=anchor)
            self.flist.column(name, width=width, minwidth=width if not stretch else 170, anchor=anchor, stretch=stretch)
        self.flist.heading("size", command=self.toggle_size_sort)
        self.flist.heading("mtime", command=self.toggle_mtime_sort)
        self.flist.heading("type", command=self.open_type_filter)
        self._update_sort_headers()
        self._update_type_filter_header()
        self.flist.grid(row=0, column=0, sticky="nsew")
        fsv = ttk.Scrollbar(files_area, orient="vertical", command=self.flist.yview)
        fsv.grid(row=0, column=1, sticky="ns")
        fsx = ttk.Scrollbar(files_area, orient="horizontal", command=self.flist.xview)
        fsx.grid(row=1, column=0, sticky="ew")
        self.flist.configure(yscrollcommand=fsv.set, xscrollcommand=fsx.set)
        self.flist.bind("<Double-1>", self.on_flist_dbl)
        self.browser_empty_label = ttk.Label(self.flist, style="Empty.TLabel", justify="center")

        scan = ttk.Frame(self.scan_tab, style="Card.TFrame", padding=16)
        scan.pack(fill="both", expand=True)
        self.scope_var = tk.StringVar(value=self.scope_root)
        self.scan_scope_var = tk.StringVar(value=self.scope_root)
        scan.columnconfigure(0, weight=1)
        scan.rowconfigure(3, weight=1)
        scan_head = ttk.Frame(scan, style="Card.TFrame")
        scan_head.grid(row=0, column=0, sticky="ew", pady=(0, 10))
        scan_title = ttk.Frame(scan_head, style="Card.TFrame")
        scan_title.pack(fill="x", pady=(0, 8))
        ttk.Label(scan_title, text="扫描范围", style="Section.TLabel").pack(side="left")
        ttk.Checkbutton(scan_title, text="显示隐藏文件", variable=self.show_hidden,
                        command=self.on_show_hidden, style="Card.TCheckbutton").pack(side="right")
        scope_description = ttk.Label(scan_head, textvariable=self.scan_scope_var,
                                      style="ScanPath.TLabel", wraplength=700)
        scope_description.pack(anchor="w", fill="x", pady=(0, 6))
        scan_head.bind("<Configure>", lambda e: scope_description.configure(wraplength=max(100, e.width)))
        ttk.Label(scan_head, text="递归检索所选目录及其子目录，按大小保留最大的文件。修改设置后点击“扫描大文件”开始。",
                  style="CardMuted.TLabel", wraplength=650).pack(anchor="w")
        settings = ttk.Frame(scan, style="Card.TFrame")
        settings.grid(row=1, column=0, sticky="ew", pady=(4, 0))
        ttk.Label(settings, text="扫描设置", style="Section.TLabel").pack(anchor="w", pady=(0, 10))
        controls = ttk.Frame(settings, style="Card.TFrame")
        controls.pack(fill="x")
        controls.columnconfigure(1, weight=1)
        ttk.Label(controls, text="扫描目录", style="CardMuted.TLabel").grid(row=0, column=0, padx=(0, 8))
        ttk.Entry(controls, textvariable=self.scope_var, width=16).grid(row=0, column=1, columnspan=5, sticky="ew")
        ttk.Label(controls, text="最大文件数", style="CardMuted.TLabel").grid(row=1, column=0, padx=(0, 8), pady=(8, 0))
        self.limit_var = tk.StringVar(value=str(self.scan_limit))
        ttk.Spinbox(controls, from_=50, to=5000, increment=50, textvariable=self.limit_var, width=6).grid(row=1, column=1, sticky="w", pady=(8, 0))
        self.scan_btn = ttk.Button(controls, text="扫描大文件", command=self.start_scan, style="Accent.TButton")
        self.scan_btn.grid(row=1, column=4, padx=(14, 6), pady=(8, 0))
        self.cancel_btn = ttk.Button(controls, text="取消扫描", command=self.cancel_scan, state="disabled", style="Small.TButton")
        self.cancel_btn.grid(row=1, column=5, pady=(8, 0))
        status_row = ttk.Frame(scan, style="Card.TFrame")
        status_row.grid(row=2, column=0, sticky="ew", pady=(8, 8))
        status_row.columnconfigure(0, weight=1)
        self.scan_status = tk.StringVar(value="设置扫描目录，查找占用空间最大的文件")
        status_label = ttk.Label(status_row, textvariable=self.scan_status, style="CardMuted.TLabel", wraplength=500)
        status_label.grid(row=0, column=0, sticky="w")
        status_row.bind("<Configure>", lambda e: status_label.configure(wraplength=max(100, e.width - 110)))
        self.scan_progress = ttk.Progressbar(status_row, mode="indeterminate", length=90, style="Disk.Horizontal.TProgressbar")
        self.scan_progress.grid(row=0, column=1, sticky="e", padx=(12, 0))
        results_area = ttk.Frame(scan, style="Card.TFrame")
        results_area.grid(row=3, column=0, sticky="nsew")
        results_area.columnconfigure(0, weight=1)
        results_area.rowconfigure(1, weight=1)
        results_heading = ttk.Frame(results_area, style="Card.TFrame")
        results_heading.grid(row=0, column=0, columnspan=2, sticky="ew", pady=(0, 10))
        ttk.Label(results_heading, text="扫描结果", style="Section.TLabel").pack(side="left")
        ttk.Label(results_heading, text="双击或右键可在访达中定位", style="CardMuted.TLabel").pack(side="right")
        self.res = ttk.Treeview(results_area, columns=("rank", "size", "path"), show="headings", height=4, selectmode="extended")
        for name, title, width, anchor in (("rank", "序号", 50, "center"), ("size", "大小", 95, "e"), ("path", "完整路径", 550, "w")):
            self.res.heading(name, text=title, anchor=anchor)
            self.res.column(name, width=width, minwidth=width if name != "path" else 400, anchor=anchor, stretch=name == "path")
        self.res.grid(row=1, column=0, sticky="nsew")
        rsv = ttk.Scrollbar(results_area, orient="vertical", command=self.res.yview)
        rsv.grid(row=1, column=1, sticky="ns")
        rsx = ttk.Scrollbar(results_area, orient="horizontal", command=self.res.xview)
        rsx.grid(row=2, column=0, sticky="ew")
        self.res.configure(yscrollcommand=rsv.set, xscrollcommand=rsx.set)
        self.res.bind("<Double-1>", self.on_res_dbl)
        self.res.bind("<Button-2>", self.on_res_rmb)
        self.res.bind("<Button-3>", self.on_res_rmb)
        for table in (self.flist, self.res):
            table.bind("<<SelectAll>>", self.on_list_select_all)
        for sequence in ("<<SelectAll>>", "<Command-a>", "<Command-A>"):
            root.bind(sequence, self.on_list_select_all)
        self.results_empty_label = ttk.Label(self.res, style="Empty.TLabel", justify="center")
        self.scan_status.trace_add("write", lambda *_: self.root.after_idle(self._sync_results_empty))
        self._sync_results_empty()

        self._ctx_menu = tk.Menu(root, tearoff=0)
        self.tree.bind("<Button-2>", self.on_tree_rmb)
        self.tree.bind("<Button-3>", self.on_tree_rmb)
        self.flist.bind("<Button-2>", self.on_flist_rmb)
        self.flist.bind("<Button-3>", self.on_flist_rmb)
        self.file_operation_status = tk.StringVar(value="支持多选  ·  右键文件或文件夹可移到废纸篓")
        ttk.Label(shell, textvariable=self.file_operation_status, style="Muted.TLabel").grid(row=2, column=0, sticky="w", pady=(10, 0))

        # 启动后台线程与轮询
        self._size_workers = [threading.Thread(target=self._size_worker_loop, daemon=True)
                              for _ in range(4)]
        for worker in self._size_workers:
            worker.start()
        self.refresh_disk()
        self.navigate(self.current_path)
        self.apply_theme(self.mode)      # 在所有控件创建后应用配色
        self.root.after(120, self._poll)

    # ---------- 外观模式 ----------
    def browse_app_storage_path(self, path):
        self.notebook.select(self.browse_tab)
        self.navigate(path)

    def toggle_theme(self):
        self.mode = "dark" if self.mode == "light" else "light"
        self.apply_theme(self.mode)

    def apply_theme(self, mode):
        """仅更新展示层，所有业务控件和事件绑定继续使用 ttk。"""
        apply_modern_theme(self, mode)

    def _sync_results_empty(self):
        if self.res.get_children():
            self.results_empty_label.place_forget()
            return
        if self._scanning:
            text = "正在查找大文件…\n扫描期间可切换到文件浏览，或随时取消"
        else:
            text = "扫描结果将显示在这里\n选择扫描目录后，点击“扫描大文件”"
        self.results_empty_label.configure(text=text)
        self.results_empty_label.place(relx=0.5, rely=0.55, anchor="center")

    def toggle_sidebar(self):
        if self.sidebar_collapsed:
            self.workspace.insert(0, self.sidebar, weight=0)
            self.sidebar_expand_button.pack_forget()
            self.sidebar_collapsed = False
            self.root.after_idle(lambda: self.workspace.sashpos(0, self._sidebar_width)
                                 if not self.sidebar_collapsed else None)
            self.sidebar_collapse_button.focus_set()
        else:
            self._sidebar_width = max(175, self.sidebar.winfo_width())
            self.workspace.forget(self.sidebar)
            self.sidebar_expand_button.pack(side="left", before=self.browser_heading, padx=(0, 12))
            self.sidebar_collapsed = True
            self.sidebar_expand_button.focus_set()
        if not save_sidebar_collapsed(self.sidebar_collapsed):
            self.file_operation_status.set("目录树显示已切换，但未能保存配置；请检查用户配置目录权限")

    # ---------- 磁盘信息 ----------
    def refresh_disk(self):
        total, used, free = disk_usage("/")
        if total == 0:
            self.disk_var.set("无法获取磁盘信息")
            self.disk_overview.set_usage(0)
            return
        pct = used / total * 100
        self.disk_total_var.set(fmt_size(total).replace("GB", " GB").replace("TB", " TB"))
        self.disk_used_var.set(fmt_size(used).replace("GB", " GB").replace("TB", " TB"))
        self.disk_free_var.set(fmt_size(free).replace("GB", " GB").replace("TB", " TB"))
        self.disk_var.set("已使用 %.1f%%" % pct)
        self.disk_overview.set_usage(pct)

    # ---------- 目录树 ----------
    def _populate_tree(self):
        self.tree.delete(*self.tree.get_children())
        root_node = self.tree.insert("", "end", text=" / ", open=True, values=("/",),
                                     tags=("normal",))
        self._add_children(root_node, "/")
        # 定位到主目录
        home = os.path.expanduser("~")
        # 尝试展开到主目录路径
        rel = home.lstrip("/").split("/")
        cur = root_node
        acc = "/"
        for part in rel:
            acc = os.path.join(acc, part) if acc != "/" else "/" + part
            found = None
            for cid in self.tree.get_children(cur):
                if self.tree.item(cid, "values")[0] == acc:
                    found = cid
                    break
            if found is None:
                break
            cur = found
            self.tree.item(cur, open=True)
            self._add_children(cur, acc)
        self.current_path = home
        self.path_var.set(home)

    def _add_children(self, parent_id, path):
        """为目录树节点添加一级子目录（懒加载）"""
        if self.tree.get_children(parent_id):
            return
        try:
            with os.scandir(path) as it:
                for e in it:
                    if not self.show_hidden.get() and e.name.startswith("."):
                        continue
                    try:
                        if e.is_dir(follow_symlinks=False):
                            self.tree.insert(parent_id, "end", text=e.name, values=(e.path,),
                                             tags=("normal",))
                    except (PermissionError, OSError):
                        continue
        except (PermissionError, OSError):
            pass

    def on_show_hidden(self):
        """切换显示隐藏文件后，刷新目录树与当前文件列表"""
        self._populate_tree()
        self.navigate(self.current_path)

    def on_tree_open(self, event):
        node = self.tree.focus()
        path = self.tree.item(node, "values")[0]
        self._add_children(node, path)

    def on_tree_dbl(self, event):
        node = self.tree.identify_row(event.y)
        if node:
            path = self.tree.item(node, "values")[0]
            self.navigate(path)

    def on_tree_rmb(self, event):
        """目录树右键：在访达中打开 / 扫描该目录大文件"""
        node = self.tree.identify_row(event.y)
        if node:
            self.tree.selection_set(node)
            self.tree.focus(node)
        path = self.tree.item(node, "values")[0] if node else "/"
        self._ctx_menu.delete(0, "end")
        self._ctx_menu.add_command(label="在访达中打开", command=lambda: open_in_finder(path))
        self._ctx_menu.add_command(label="扫描该目录大文件", command=lambda: self.start_scan_for(path))
        try:
            self._ctx_menu.tk_popup(event.x_root, event.y_root)
        finally:
            self._ctx_menu.grab_release()

    # ---------- 文件列表浏览 ----------
    def navigate(self, path):
        path = os.path.abspath(os.path.expanduser(path))
        if not os.path.isdir(path):
            messagebox.showwarning("提示", "该路径不存在或不是目录:\n%s" % path)
            return
        self._close_type_filter()
        self._reset_size_requests()
        self.current_path = path
        self.path_var.set(path)
        self.flist.delete(*self.flist.get_children())
        self._file_row_ids = {}
        self._file_item_indexes = {}
        self._file_order = []
        self._size_sort_dirty = False
        self.file_items = []
        self._file_mtimes = {}
        self._browser_read_error = None
        try:
            with os.scandir(path) as it:
                for e in it:
                    if not self.show_hidden.get() and e.name.startswith("."):
                        continue
                    try:
                        is_dir = e.is_dir(follow_symlinks=False)
                        is_file = e.is_file(follow_symlinks=False)
                        if not is_dir and not is_file:
                            continue
                        st = e.stat(follow_symlinks=False)
                        size = 0
                        mtime = time.strftime("%Y-%m-%d %H:%M", time.localtime(st.st_mtime))
                        if is_file:
                            size = st.st_size
                        elif is_dir:
                            size = self.dir_size_cache.get(e.path, -1)
                            if size < 0 and e.path not in self.dir_size_pending and not self._deleting:
                                self.dir_size_pending.add(e.path)
                                self.size_req_q.put((e.path, self._size_cancel))
                        self.file_items.append((size if is_file else size, is_dir, e.name, e.path, mtime))
                        self._file_mtimes[e.path] = st.st_mtime_ns
                    except (PermissionError, OSError):
                        continue
        except (PermissionError, OSError) as ex:
            self._reset_size_requests()
            self.file_items.clear()
            self._file_mtimes.clear()
            self._browser_read_error = "读取权限异常" if isinstance(ex, PermissionError) else "目录读取异常"
            self._render_list()
            messagebox.showerror("错误", "无法读取目录:\n%s\n%s" % (path, ex))
            return
        self._render_list()

    def _sorted_file_items(self):
        # 文件与文件夹统一排序；时间使用原始时间戳，避免显示到分钟造成精度丢失。
        visible = [item for item in self.file_items if browser_item_type(item) not in self.excluded_file_types]
        if self.sort_column == "mtime":
            return sorted(visible, key=lambda item: (
                item[3] not in self._file_mtimes,
                -self._file_mtimes.get(item[3], 0) if self.mtime_sort_descending else self._file_mtimes.get(item[3], 0)))
        return sorted(visible, key=lambda item: (
            item[0] < 0, -item[0] if self.size_sort_descending else item[0]))

    def _available_file_types(self):
        counts = {}
        for item in self.file_items:
            key = browser_item_type(item)
            counts[key] = counts.get(key, 0) + 1
        return counts

    def _update_type_filter_header(self):
        active = bool(self.excluded_file_types)
        self.flist.heading("type", text="类型 ▾ ●" if active else "类型 ▾")
        visible = sum(browser_item_type(item) not in self.excluded_file_types for item in self.file_items)
        description = "已筛选" if active else "全部展示"
        text = "类型：%s · %d / %d 项" % (description, visible, len(self.file_items))
        read_error = getattr(self, "_browser_read_error", None)
        if read_error:
            text = read_error + " · 当前目录内容不可读取"
        if not visible and self.file_items:
            text += " · 没有符合条件的项目"
        self.filter_summary_var.set(text)
        if hasattr(self, "browser_empty_label"):
            if read_error:
                guidance = "请检查目录访问权限后，点击“刷新列表”重试" if read_error == "读取权限异常" else "请确认目录或磁盘可用后，点击“刷新列表”重试"
                self.browser_empty_label.configure(text=read_error + "\n" + guidance, style="Error.TLabel")
                self.browser_empty_label.place(relx=0.5, rely=0.55, anchor="center")
            elif visible:
                self.browser_empty_label.place_forget()
            else:
                message = "没有符合筛选条件的项目\n调整类型筛选，或点击“全部展示”" if self.file_items else "此目录暂无可显示项目"
                self.browser_empty_label.configure(text=message, style="Empty.TLabel")
                self.browser_empty_label.place(relx=0.5, rely=0.55, anchor="center")

    def _close_type_filter(self):
        popup = self._type_filter_popup
        self._type_filter_popup = None
        if popup is not None:
            try:
                popup.grab_release()
            except tk.TclError:
                pass
            try:
                popup.destroy()
                self.flist.focus_set()
            except tk.TclError:
                pass

    def _commit_type_filter(self):
        selected = []
        for row in self.flist.selection():
            values = self.flist.item(row, "values")
            if len(values) > 4:
                selected.append(values[4])
        self._close_type_filter()
        self._render_list()
        remaining = [self._file_row_ids[path] for path in selected if path in self._file_row_ids]
        if remaining:
            self.flist.selection_set(remaining)
        if not save_type_filter(self.excluded_file_types):
            self.file_operation_status.set("筛选已应用，但未能保存配置；请检查用户配置目录权限")

    def apply_type_filter(self, visible_keys, available_keys):
        # 本目录没有的类型继续保留其选择；未遇见过的新类型默认展示。
        visible_keys, available_keys = set(visible_keys), set(available_keys)
        self.excluded_file_types.difference_update(visible_keys & available_keys)
        self.excluded_file_types.update(available_keys - visible_keys)
        self._commit_type_filter()

    def reset_type_filter(self):
        self.excluded_file_types.clear()
        self._commit_type_filter()

    def open_type_filter(self):
        if self._type_filter_popup is not None:
            self._close_type_filter()
            return
        counts = self._available_file_types()
        keys = sorted(counts, key=lambda key: (0 if key == "folder" else 2 if key == "no_extension" else 1, key))
        popup = tk.Toplevel(self.root)
        self._type_filter_popup = popup
        popup.withdraw()
        popup.transient(self.root)
        # 交互式筛选使用系统管理的窗口；macOS 无边框窗口关闭后可能残留键盘激活状态。
        popup.title("筛选类型")
        popup.protocol("WM_DELETE_WINDOW", self._close_type_filter)
        popup.resizable(False, False)
        palette = PALETTES[self.mode]
        popup.configure(background=palette["border"])
        panel = ttk.Frame(popup, style="Card.TFrame", padding=18)
        panel.pack(fill="both", expand=True, padx=1, pady=1)
        panel.columnconfigure(0, weight=1)
        panel.rowconfigure(3, weight=1)
        ttk.Label(panel, text="按类型筛选", style="Section.TLabel").grid(row=0, column=0, sticky="w")
        ttk.Label(panel, text="只统计当前目录的直接子项，勾选表示展示", style="CardMuted.TLabel").grid(row=1, column=0, sticky="w", pady=(6, 10))
        variables = {key: tk.BooleanVar(value=key not in self.excluded_file_types) for key in keys}
        master_var = tk.IntVar(value=1)
        master = ttk.Checkbutton(panel, text="全选本目录", variable=master_var, style="Card.TCheckbutton")
        master.grid(row=2, column=0, sticky="w", pady=(0, 8))
        def sync_master():
            enabled = sum(var.get() for var in variables.values())
            partial = 0 < enabled < len(variables)
            master_var.set(-1 if partial else int(enabled == len(variables)))
            master.state(["alternate"] if partial else ["!alternate"])
        def select_all():
            checked = master_var.get() == 1
            for var in variables.values():
                var.set(checked)
            sync_master()
        master.configure(command=select_all)
        options = ttk.Frame(panel, style="Card.TFrame")
        options.grid(row=3, column=0, sticky="nsew")
        options.columnconfigure(0, weight=1)
        options.rowconfigure(0, weight=1)
        canvas = tk.Canvas(options, background=palette["tree_bg"], highlightthickness=0, height=min(240, max(44, len(keys) * 32)))
        canvas.grid(row=0, column=0, sticky="nsew")
        scroll = ttk.Scrollbar(options, orient="vertical", command=canvas.yview)
        scroll.grid(row=0, column=1, sticky="ns")
        canvas.configure(yscrollcommand=scroll.set)
        rows = ttk.Frame(canvas, style="Card.TFrame")
        window = canvas.create_window(0, 0, anchor="nw", window=rows)
        rows.bind("<Configure>", lambda e: canvas.configure(scrollregion=canvas.bbox("all")))
        canvas.bind("<Configure>", lambda e: canvas.itemconfigure(window, width=e.width))
        for key in keys:
            label = browser_type_label(key)
            if key.startswith("ext:"):
                label += " (%s)" % key[4:]
            ttk.Checkbutton(rows, text="%s    %d 项" % (label, counts[key]), variable=variables[key],
                            command=sync_master, style="Card.TCheckbutton").pack(anchor="w", fill="x", pady=5)
        if not keys:
            master.state(["disabled"])
            ttk.Label(rows, text="当前目录没有可筛选的类型", style="CardMuted.TLabel").pack(anchor="w", pady=10)
        sync_master()
        def wheel(event):
            step = int(event.delta / 120) if abs(event.delta) >= 120 else int(event.delta)
            canvas.yview_scroll(-max(-3, min(3, step)), "units")
            return "break"
        popup.bind("<MouseWheel>", wheel)
        footer = ttk.Frame(panel, style="Card.TFrame")
        footer.grid(row=4, column=0, sticky="ew", pady=(14, 0))
        def apply():
            self.apply_type_filter({key for key, var in variables.items() if var.get()}, keys)
        ttk.Button(footer, text="重置全部", command=self.reset_type_filter, style="Small.TButton").pack(side="left")
        ttk.Button(footer, text="应用", command=apply, style="Accent.TButton", width=6).pack(side="right")
        ttk.Button(footer, text="取消", command=self._close_type_filter, style="Small.TButton").pack(side="right", padx=8)
        def outside(event):
            if not (popup.winfo_rootx() <= event.x_root < popup.winfo_rootx() + popup.winfo_width() and
                    popup.winfo_rooty() <= event.y_root < popup.winfo_rooty() + popup.winfo_height()):
                self._close_type_filter()
                return "break"
        popup.bind("<ButtonPress-1>", outside)
        popup.bind("<Escape>", lambda e: self._close_type_filter())
        popup.bind("<Return>", lambda e: apply())
        popup.update_idletasks()
        width = max(380, popup.winfo_reqwidth())
        height = popup.winfo_reqheight()
        x = max(8, min(self.flist.winfo_pointerx() - 30, popup.winfo_screenwidth() - width - 8))
        y = max(8, min(self.flist.winfo_rooty() + 40, popup.winfo_screenheight() - height - 8))
        popup.geometry("%dx%d+%d+%d" % (width, height, x, y))
        popup.deiconify()
        popup.update_idletasks()
        popup.lift()
        popup.focus_set()
        popup.grab_set()

    def _update_sort_headers(self):
        descending = self.mtime_sort_descending if self.sort_column == "mtime" else self.size_sort_descending
        arrow = "↓" if descending else "↑"
        direction = "降序" if descending else "升序"
        for column, title in (("size", "大小"), ("mtime", "修改时间")):
            self.flist.heading(column, text=title + (" " + arrow if self.sort_column == column else ""))
        field = "修改时间" if self.sort_column == "mtime" else "大小"
        self.sort_hint_var.set("按%s%s · 点击表头切换" % (field, direction))

    def toggle_size_sort(self):
        if self.sort_column == "size":
            self.size_sort_descending = not self.size_sort_descending
        self.sort_column = "size"
        self._update_sort_headers()
        self._reorder_file_rows()
        if not save_sort_direction(self.size_sort_descending):
            self.file_operation_status.set("排序已切换，但未能保存配置；请检查用户配置目录权限")

    def toggle_mtime_sort(self):
        if self.sort_column == "mtime":
            self.mtime_sort_descending = not self.mtime_sort_descending
        self.sort_column = "mtime"
        self._update_sort_headers()
        self._reorder_file_rows()
        if not save_mtime_sort_direction(self.mtime_sort_descending):
            self.file_operation_status.set("排序已切换，但未能保存配置；请检查用户配置目录权限")

    def _render_list(self):
        self.flist.delete(*self.flist.get_children())
        self._file_row_ids = {}
        self._file_item_indexes = {item[3]: index for index, item in enumerate(self.file_items)}
        self._file_order = []
        self._size_sort_dirty = False
        for size, is_dir, name, path, mtime in self._sorted_file_items():
            size_txt = fmt_size(size) if size >= 0 else "计算中…"
            self._file_row_ids[path] = self.flist.insert(
                "", "end", values=(name, size_txt, browser_type_label(browser_item_type((size, is_dir, name, path, mtime))), mtime, path),
                tags=("dir" if is_dir else "file",))
            self._file_order.append(path)
        self._update_type_filter_header()

    def _reorder_file_rows(self):
        order = [item[3] for item in self._sorted_file_items()]
        if order != self._file_order:
            for index, path in enumerate(order):
                self.flist.move(self._file_row_ids[path], "", index)
            self._file_order = order
        self._size_sort_dirty = False

    def on_list_select_all(self, event):
        """非输入状态下，全选当前标签页的列表；输入框保留文字全选。"""
        table = event.widget
        if table is not self.flist and table is not self.res:
            focus = self.root.focus_get()
            if focus is not None:
                if focus.winfo_toplevel() is not self.root:
                    return
                if focus.winfo_class() in ("Entry", "TEntry", "Spinbox", "TSpinbox", "Text", "TCombobox", "Combobox"):
                    return
            tab = self.notebook.select()
            if tab == str(self.browse_tab):
                table = self.flist
            elif tab == str(self.scan_tab):
                table = self.res
            else:
                return
            table.focus_set()
        rows = table.get_children()
        if table is self.flist:
            rows = tuple(row for row in rows if table.item(row, "values")[0] != "..")
        table.selection_set(rows)
        return "break"

    def on_flist_dbl(self, event):
        iid = self.flist.identify_row(event.y)
        if not iid:
            return
        vals = self.flist.item(iid, "values")
        path = vals[4] if len(vals) > 4 else ""
        if os.path.isdir(path):
            self.navigate(path)
        else:
            open_in_finder(path)

    def on_flist_rmb(self, event):
        """文件列表右键：在访达中打开；若是文件夹，另支持扫描该目录大文件"""
        row = self.flist.identify_row(event.y)
        if not row:
            return
        if row not in self.flist.selection():
            self.flist.selection_set(row)
        self.flist.focus(row)
        vals = self.flist.item(row, "values")
        path = vals[4] if len(vals) > 4 else ""
        is_dir = (len(vals) > 2 and vals[2] == "文件夹")
        self._ctx_menu.delete(0, "end")
        self._ctx_menu.add_command(label="在访达中打开", command=lambda: open_in_finder(path))
        if is_dir:
            self._ctx_menu.add_command(label="扫描该目录大文件",
                                       command=lambda: self.start_scan_for(path))
        paths = self._selected_trash_paths(self.flist, 4) if vals[0] != ".." else []
        self._add_trash_menu(paths)
        try:
            self._ctx_menu.tk_popup(event.x_root, event.y_root)
        finally:
            self._ctx_menu.grab_release()

    def _selected_trash_paths(self, table, path_column):
        paths = []
        for row in table.selection():
            values = table.item(row, "values")
            if len(values) > path_column and not (path_column == 4 and values[0] == ".."):
                paths.append(values[path_column])
        return normalize_trash_paths(paths)

    def _add_trash_menu(self, paths):
        self._ctx_menu.add_separator()
        label = "删除（移到废纸篓）…" if len(paths) <= 1 else "删除所选 %d 项（移到废纸篓）…" % len(paths)
        self._ctx_menu.add_command(label=label, command=lambda: self.delete_paths(paths),
                                   state="normal" if paths and not self._deleting else "disabled")

    def delete_paths(self, paths):
        if self._deleting:
            return
        paths = normalize_trash_paths(paths)
        if not paths:
            return
        preview = "\n".join(paths[:8])
        if len(paths) > 8:
            preview += "\n…另有 %d 项" % (len(paths) - 8)
        text = "将以下 %d 个项目移到废纸篓？\n文件夹及其中的内容将一起移动，可从废纸篓恢复。\n\n%s" % (len(paths), preview)
        if self._scanning:
            text += "\n\n正在进行的大文件扫描会先停止。"
        if not messagebox.askyesno("确认删除", text, parent=self.root, default="no"):
            return
        self._deleting = True
        self._reset_size_requests()
        if self._scanning:
            self.cancel_scan()
        self.file_operation_status.set("正在将 %d 个项目移到废纸篓…" % len(paths))
        threading.Thread(target=self._trash_worker, args=(paths,), daemon=True).start()

    def _trash_worker(self, paths):
        # 等旧读取任务退出；删除期间导航不创建新目录大小任务。
        self.size_req_q.join()
        scan_thread = self._scan_thread
        if scan_thread is not None:
            scan_thread.join()
        self.trash_result_q.put(trash_items(paths))

    def _handle_trash_result(self, results):
        # Worker 已等待扫描线程退出，清掉可能在本轮 poll 中途抵达的消息。
        if self._scanning:
            while True:
                try:
                    self.scan_result_q.get_nowait()
                except queue.Empty:
                    break
            self._handle_scan_msg(("done", None, None, None, True))
        self._deleting = False
        moved = [result["path"] for result in results if result.get("trashed")]
        failures = [result for result in results if not result.get("trashed")]
        if moved:
            self.dir_size_cache.clear()
            def removed(path):
                return any(path == parent or path.startswith(parent + os.sep) for parent in moved)
            for row in self.res.get_children():
                values = self.res.item(row, "values")
                if len(values) > 2 and removed(values[2]):
                    self.res.delete(row)
            for rank, row in enumerate(self.res.get_children(), 1):
                self.res.set(row, "rank", rank)
            # 更新已展开的目录节点，不重置用户的导航位置和展开状态。
            nodes = list(self.tree.get_children())
            while nodes:
                node = nodes.pop()
                values = self.tree.item(node, "values")
                if values and removed(values[0]):
                    self.tree.delete(node)
                else:
                    nodes.extend(self.tree.get_children(node))
            self.refresh_disk()
            if self.res.get_children():
                self.scan_status.set("已移到废纸篓 %d 项，列表保留其余扫描结果" % len(moved))
            elif not self._scanning:
                self.scan_status.set("已移到废纸篓 %d 项" % len(moved))
        # 即使有失败项也恢复被暂停的目录大小任务。
        target = self.current_path if os.path.isdir(self.current_path) else os.path.expanduser("~")
        self.navigate(target)
        self.file_operation_status.set("已移到废纸篓 %d 项%s" % (len(moved), "，%d 项失败" % len(failures) if failures else ""))
        if failures:
            details = "\n\n".join("%s\n%s" % (r["path"], r.get("error", "未知错误")) for r in failures[:8])
            messagebox.showwarning("部分项目未能删除", details, parent=self.root)

    def go_up(self):
        parent = os.path.dirname(self.current_path)
        if parent and parent != self.current_path:
            self.navigate(parent)

    # ---------- 目录大小后台计算 ----------
    def _reset_size_requests(self):
        """把后台算力让给当前目录，旧任务在下次遍历检查时退出。"""
        self._size_cancel.set()
        self._size_cancel = threading.Event()
        while True:
            try:
                self.size_req_q.get_nowait()
                self.size_req_q.task_done()
            except queue.Empty:
                break
        self.dir_size_pending.clear()

    def _size_worker_loop(self):
        while True:
            path, cancel = self.size_req_q.get()
            try:
                if cancel.is_set():
                    continue
                size = self._compute_dir_size(path, cancel)
                if size is not None and not cancel.is_set():
                    self.size_res_q.put((path, size, cancel))
            finally:
                self.size_req_q.task_done()

    def _compute_dir_size(self, path, cancel=None):
        """显式栈后序汇总：只缓存完整子树，取消时不把部分大小当成结果。"""
        # 不随符号链接进入目录，文件大小仍使用逻辑字节数。
        stack = [(path, None, False)]
        totals = {}
        while stack:
            if cancel is not None and cancel.is_set():
                return None
            current, parent, complete = stack.pop()
            if complete:
                size = totals.pop(current)
                self.dir_size_cache[current] = size
                if parent is not None:
                    totals[parent] += size
                else:
                    return size
                continue
            cached = self.dir_size_cache.get(current)
            if cached is not None:
                if parent is None:
                    return cached
                totals[parent] += cached
                continue
            total = 0
            children = []
            try:
                with os.scandir(current) as entries:
                    for entry in entries:
                        if cancel is not None and cancel.is_set():
                            return None
                        try:
                            if entry.is_dir(follow_symlinks=False):
                                children.append(entry.path)
                            elif entry.is_file(follow_symlinks=False):
                                total += entry.stat(follow_symlinks=False).st_size
                        except OSError:
                            continue
            except OSError:
                # 无权读取时保留既有“跳过”行为，不缓存该目录的零值。
                if parent is None:
                    return 0
                continue
            totals[current] = total
            stack.append((current, parent, True))
            stack.extend((child, current, False) for child in children)
        return 0

    def _poll(self):
        # 处理目录大小结果
        while True:
            try:
                path, size, cancel = self.size_res_q.get_nowait()
            except queue.Empty:
                break
            if cancel is not self._size_cancel:
                continue
            self.dir_size_pending.discard(path)
            self._update_row_size(path, size)
        if self._size_sort_dirty:
            self._reorder_file_rows()
        # 处理扫描结果
        while True:
            try:
                msg = self.scan_result_q.get_nowait()
            except queue.Empty:
                break
            self._handle_scan_msg(msg)
        try:
            self._handle_trash_result(self.trash_result_q.get_nowait())
        except queue.Empty:
            pass
        self.root.after(120, self._poll)

    def _update_row_size(self, path, size):
        # 原始模型包含被筛掉的行，重新勾选时也要显示已完成的大小。
        index = self._file_item_indexes.get(path)
        if index is not None:
            old = self.file_items[index]
            self.file_items[index] = (size,) + old[1:]
        iid = self._file_row_ids.get(path)
        if iid is not None:
            self.flist.set(iid, "size", fmt_size(size))
            if self.sort_column == "size":
                self._size_sort_dirty = True

    # ---------- 大文件扫描 ----------
    def start_scan(self):
        if self._deleting:
            messagebox.showinfo("提示", "正在移动文件到废纸篓，请稍后再扫描", parent=self.root)
            return
        if self._scanning:
            messagebox.showinfo("提示", "正在扫描中，请先取消当前扫描")
            return
        scope = self.scope_var.get().strip()
        scope = os.path.abspath(os.path.expanduser(scope))
        if not os.path.isdir(scope):
            messagebox.showwarning("提示", "扫描根目录无效:\n%s" % scope)
            return
        try:
            self.scan_limit = int(self.limit_var.get())
        except ValueError:
            self.scan_limit = 200
        self.scope_root = scope
        self.scan_scope_var.set(scope)
        self.res.delete(*self.res.get_children())
        self.scan_cancel.clear()
        self._scanning = True
        self.scan_btn.config(state="disabled")
        self.cancel_btn.config(state="normal")
        self.scan_progress.start(12)
        self.scan_status.set("正在扫描 %s …" % scope)
        include_hidden = self.show_hidden.get()   # 主线程取值，线程内不访问Tk变量
        self._scan_thread = threading.Thread(target=self._scan_worker, args=(scope, include_hidden), daemon=True)
        self._scan_thread.start()

    def start_scan_for(self, path):
        """快捷扫描指定目录下的大文件（供右键菜单调用）"""
        self.notebook.select(self.scan_tab)
        if not self._scanning:
            self.scope_var.set(path)
        self.start_scan()

    def cancel_scan(self):
        self.scan_cancel.set()
        self.scan_status.set("正在取消…")

    def _scan_worker(self, root, include_hidden):
        # 直接消费 DirEntry 的类型/元数据，省掉 os.walk 后逐路径再查询。
        top = []
        files = 0
        limit = max(1, self.scan_limit)
        pending = [root]
        last_post = time.monotonic()
        while pending:
            if self.scan_cancel.is_set():
                self.scan_result_q.put(("done", None, None, None, True))
                return
            directory = pending.pop()
            children = []
            try:
                with os.scandir(directory) as entries:
                    for entry in entries:
                        if self.scan_cancel.is_set():
                            self.scan_result_q.put(("done", None, None, None, True))
                            return
                        if not include_hidden and entry.name.startswith("."):
                            continue
                        try:
                            if entry.is_dir(follow_symlinks=False):
                                children.append(entry.path)
                                continue
                            # 与旧扫描一致：文件链接计目标大小，目录链接不遍历。
                            info = entry.stat()
                            if not stat.S_ISREG(info.st_mode):
                                continue
                            size = info.st_size
                        except OSError:
                            continue
                        files += 1
                        if len(top) < limit:
                            heapq.heappush(top, (size, entry.path))
                        elif size > top[0][0]:
                            heapq.heapreplace(top, (size, entry.path))
                        # 每 128 个文件检查一次发布间隔，减少逐文件时钟调用。
                        if files % 128 == 0:
                            now = time.monotonic()
                            if now - last_post > 0.25:
                                self.scan_result_q.put(("progress", files, sorted(top, reverse=True), None, False))
                                last_post = now
            except OSError:
                pass
            # 栈反向入队，保持 os.walk 原本的子目录访问顺序和同大小截断结果。
            pending.extend(reversed(children))
        if self.scan_cancel.is_set():
            self.scan_result_q.put(("done", None, None, None, True))
        else:
            self.scan_result_q.put(("done", files, sorted(top, reverse=True), root, False))

    def _handle_scan_msg(self, msg):
        kind = msg[0]
        if kind == "progress":
            files, snapshot = msg[1], msg[2]
            self.scan_status.set("已扫描 %d 个文件，当前最大 %d 个…" % (files, len(snapshot)))
        elif kind == "done":
            files, snapshot, root, cancelled = msg[1], msg[2], msg[3], msg[4]
            self._scanning = False
            self.scan_progress.stop()
            self.scan_btn.config(state="normal")
            self.cancel_btn.config(state="disabled")
            self.res.delete(*self.res.get_children())
            if cancelled:
                self.scan_status.set("扫描已取消")
                return
            for i, (sz, fp) in enumerate(snapshot, 1):
                self.res.insert("", "end", values=(i, fmt_size(sz), fp), tags=("normal",))
            self.scan_status.set("扫描完成：共 %d 个文件，展示最大 %d 个（来源 %s）"
                                 % (files, len(snapshot), root))

    def on_res_dbl(self, event):
        iid = self.res.identify_row(event.y)
        if iid:
            vals = self.res.item(iid, "values")
            if len(vals) > 2:
                open_in_finder(vals[2])

    def on_res_rmb(self, event):
        """大文件扫描结果右键：在访达中打开/定位该文件"""
        row = self.res.identify_row(event.y)
        if not row:
            return
        if row not in self.res.selection():
            self.res.selection_set(row)
        self.res.focus(row)
        vals = self.res.item(row, "values")
        path = vals[2] if len(vals) > 2 else ""
        self._ctx_menu.delete(0, "end")
        self._ctx_menu.add_command(label="在访达中打开", command=lambda: open_in_finder(path))
        self._add_trash_menu(self._selected_trash_paths(self.res, 2))
        try:
            self._ctx_menu.tk_popup(event.x_root, event.y_root)
        finally:
            self._ctx_menu.grab_release()


def main():
    root = tk.Tk()
    ScannerApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()
