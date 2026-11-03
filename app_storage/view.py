"""Tk storage page; background work reaches the UI through a queue."""
import os
import queue
import threading
import time
import tkinter as tk
from tkinter import ttk

from .models import ApplicationUsage
from .presentation import measurement_text, usage_values
from .service import scan_applications


class AppStoragePage:
    def __init__(self, frame, notebook, format_size, open_path, browse_path):
        self.frame, self.notebook = frame, notebook
        self.format_size, self.open_path, self.browse_path = format_size, open_path, browse_path
        self.events = queue.Queue()
        self.cancel = threading.Event()
        self.started = self.running = self.stopped = False
        self.run_id = 0
        self.usages = {}
        self.warnings = ()
        self.sort_column, self.descending = 'total', True
        self.dirty = False
        self.last_render = 0
        self.detail_paths = {}
        self.frame.configure(padding=16)
        frame.columnconfigure(0, weight=1)
        frame.rowconfigure(3, weight=3)
        frame.rowconfigure(6, weight=2)

        head = ttk.Frame(frame, style='Card.TFrame')
        head.grid(row=0, column=0, sticky='ew')
        ttk.Label(head, text='应用空间占用', style='Section.TLabel').pack(side='left')
        self.cancel_button = ttk.Button(head, text='取消统计', command=self.stop, state='disabled')
        self.cancel_button.pack(side='right')
        self.start_button = ttk.Button(head, text='重新扫描', command=self.start, style='Accent.TButton')
        self.start_button.pack(side='right', padx=(12, 8))
        ttk.Button(head, text='扫描说明', command=self.show_scan_info, style='Ghost.TButton').pack(side='right')
        scope = ttk.Label(frame, text='扫描常见安装目录并结合系统索引；外部数据覆盖当前用户与系统 Library，未匹配不代表没有数据。',
                          style='CardMuted.TLabel', wraplength=740)
        scope.grid(row=1, column=0, sticky='w', pady=(8, 12))
        self.scope_label = scope
        search = ttk.Frame(frame, style='Card.TFrame')
        search.grid(row=2, column=0, sticky='ew', pady=(0, 10))
        ttk.Label(search, text='查找应用', style='CardMuted.TLabel').pack(side='left', padx=(0, 10))
        self.query = tk.StringVar()
        self.search_entry = ttk.Entry(search, textvariable=self.query, width=28)
        self.search_entry.pack(side='left', fill='x', expand=True)
        self.count = tk.StringVar(value='尚未扫描')
        ttk.Label(search, textvariable=self.count, style='CardMuted.TLabel').pack(side='right', padx=(12, 0))
        self.query.trace_add('write', lambda *_: self.render())

        self.table = self._table(frame, 3, (
            ('name', '应用名称', 210, 'w'), ('package', 'App 包', 100, 'e'),
            ('external', '外部数据（已识别）', 140, 'e'), ('total', '已确认合计 ↓', 115, 'e'),
            ('status', '状态', 150, 'w')))
        for key in ('name', 'package', 'external', 'total'):
            self.table.heading(key, command=lambda col=key: self.sort(col))
        self.table.bind('<<TreeviewSelect>>', lambda _: self.show_details())
        self.status = tk.StringVar(value='首次进入此页自动扫描；统计只读取文件，不会卸载或清理应用。')
        self.status_label = ttk.Label(frame, textvariable=self.status, style='CardMuted.TLabel', wraplength=740)
        self.status_label.grid(row=4, column=0, sticky='w', pady=(8, 12))

        detail_head = ttk.Frame(frame, style='Card.TFrame')
        detail_head.grid(row=5, column=0, sticky='ew', pady=(0, 8))
        self.detail_title = tk.StringVar(value='选择应用查看目录明细')
        ttk.Label(detail_head, textvariable=self.detail_title, style='Section.TLabel').pack(side='left')
        ttk.Button(detail_head, text='在文件浏览中查看', command=self.browse_selected, style='SoftAccent.TButton').pack(side='right')
        self.details = self._table(frame, 6, (
            ('category', '项目', 120, 'w'), ('size', '大小', 100, 'e'),
            ('confidence', '关联', 90, 'w'), ('path', '具体路径', 420, 'w')))
        self.details.bind('<<TreeviewSelect>>', lambda _: self.show_reason())
        self.details.bind('<Double-1>', lambda _: self.open_selected())
        self.reason = tk.StringVar(value='共享和疑似数据单独列出，不计入已确认合计。大小为已分配文件块估算，不等于可释放空间。')
        self.reason_label = ttk.Label(frame, textvariable=self.reason, style='CardMuted.TLabel', wraplength=740)
        self.reason_label.grid(row=7, column=0, sticky='w', pady=(8, 0))
        frame.bind('<Configure>', self._resize)
        notebook.bind('<<NotebookTabChanged>>', self._tab_changed, add='+')
        frame.bind('<Destroy>', self._destroy, add='+')
        for table in (self.table, self.details):
            for sequence in ('<Command-a>', '<Command-A>', '<<SelectAll>>'):
                table.bind(sequence, self.select_all)
        frame.after(100, self.poll)

    def _table(self, parent, row, columns):
        area = ttk.Frame(parent, style='Card.TFrame')
        area.grid(row=row, column=0, sticky='nsew')
        area.columnconfigure(0, weight=1)
        area.rowconfigure(0, weight=1)
        table = ttk.Treeview(area, columns=tuple(c[0] for c in columns), show='headings', height=4, selectmode='extended')
        for key, title, width, anchor in columns:
            table.heading(key, text=title, anchor=anchor)
            table.column(key, width=width, minwidth=width if key not in ('name', 'path') else 150,
                         stretch=key in ('name', 'path'), anchor=anchor)
        table.grid(row=0, column=0, sticky='nsew')
        vertical = ttk.Scrollbar(area, orient='vertical', command=table.yview)
        vertical.grid(row=0, column=1, sticky='ns')
        horizontal = ttk.Scrollbar(area, orient='horizontal', command=table.xview)
        horizontal.grid(row=1, column=0, sticky='ew')
        table.configure(yscrollcommand=vertical.set, xscrollcommand=horizontal.set)
        return table

    def _resize(self, event):
        if event.widget is self.frame:
            for label in (self.scope_label, self.status_label, self.reason_label):
                label.configure(wraplength=max(250, event.width - 32))

    def _tab_changed(self, _):
        if self.notebook.select() == str(self.frame) and not self.started:
            self.start()

    def _destroy(self, event):
        if event.widget is self.frame:
            self.cancel.set()

    def start(self):
        if self.running:
            return
        self.started = self.running = True
        self.stopped = False
        self.run_id += 1
        self.cancel = threading.Event()
        self.usages.clear()
        self.warnings = ()
        self.table.delete(*self.table.get_children())
        self.details.delete(*self.details.get_children())
        self.detail_paths.clear()
        self.detail_title.set('选择应用查看目录明细')
        self.status.set('正在发现已安装应用…')
        self.reason.set('共享和疑似数据不计入已确认合计；外部数据仅统计已识别的位置。')
        self.count.set('正在发现…')
        self.start_button.configure(state='disabled')
        self.cancel_button.configure(state='normal')
        threading.Thread(target=self._worker, args=(self.run_id, self.cancel), daemon=True).start()

    def _worker(self, run_id, cancel):
        def emit(kind, value):
            self.events.put((run_id, kind, value))
        try:
            scan_applications(cancel, emit)
        except Exception as exc:
            emit('error', '应用统计异常：%s' % exc)

    def stop(self):
        self.cancel.set()
        self.cancel_button.configure(state='disabled')
        self.status.set('正在取消，保留已完成的统计…')

    def poll(self):
        if not self.frame.winfo_exists():
            return
        for _ in range(160):
            try:
                run_id, kind, value = self.events.get_nowait()
            except queue.Empty:
                break
            if run_id != self.run_id:
                continue
            if kind == 'apps':
                for app in value:
                    self.usages.setdefault(app.path, ApplicationUsage(app, (), {}))
                self.dirty = True
            elif kind == 'usage':
                self.usages[value.app.path] = value
                self.dirty = True
            elif kind == 'progress':
                if not self.cancel.is_set():
                    self.status.set(value)
            elif kind == 'warnings':
                self.warnings = value
            elif kind in ('done', 'error'):
                self.running = False
                self.stopped = bool(value) if kind == 'done' else True
                self.start_button.configure(state='normal')
                self.cancel_button.configure(state='disabled')
                completed = sum(not usage.pending for usage in self.usages.values())
                text = ('已取消' if value else '统计完成') if kind == 'done' else value
                text += ' · 已发现 %d 个应用，%d 个已完成' % (len(self.usages), completed)
                if self.warnings:
                    text += ' · %d 处无法读取，扫描范围不完整' % len(self.warnings)
                self.status.set(text)
                self.dirty = True
        if self.dirty and (not self.running or time.monotonic() - self.last_render > .5):
            self.render()
        self.frame.after(100, self.poll)

    def size_text(self, measurement):
        return measurement_text(measurement, self.format_size, self.stopped)

    def sort(self, column):
        self.descending = not self.descending if column == self.sort_column else column != 'name'
        self.sort_column = column
        for key, title in (('name', '应用名称'), ('package', 'App 包'), ('external', '外部数据（已识别）'), ('total', '已确认合计')):
            self.table.heading(key, text=title + ((' ↓' if self.descending else ' ↑') if key == column else ''))
        self.render()

    def render(self):
        query = self.query.get().strip().casefold()
        usages = [u for u in self.usages.values() if query in (u.app.name + ' ' + u.app.bundle_id + ' ' + u.app.path).casefold()]
        def value(usage):
            if self.sort_column == 'name':
                return usage.app.name.casefold()
            if self.sort_column == 'package':
                return usage.package.size if usage.package else None
            return usage.external_bytes if self.sort_column == 'external' else usage.total_bytes
        known = sorted((u for u in usages if value(u) is not None),
                       key=lambda u: (value(u), u.app.name.casefold()), reverse=self.descending)
        unknown = sorted((u for u in usages if value(u) is None), key=lambda u: u.app.name.casefold())
        visible = known + unknown
        wanted = {u.app.path for u in visible}
        for row in self.table.get_children():
            if row not in wanted:
                self.table.delete(row)
        for index, usage in enumerate(visible):
            row = usage_values(usage, self.format_size, self.stopped)
            if self.table.exists(usage.app.path):
                self.table.item(usage.app.path, values=row)
                self.table.move(usage.app.path, '', index)
            else:
                self.table.insert('', 'end', iid=usage.app.path, values=row)
        self.count.set('%d / %d 个应用' % (len(visible), len(self.usages)))
        self.last_render = time.monotonic()
        self.dirty = False
        self.show_details()

    def selected_usage(self):
        selected = self.table.selection()
        return self.usages.get(selected[0]) if selected else None

    def show_details(self):
        usage = self.selected_usage()
        selected_paths = {self.detail_paths[row][0] for row in self.details.selection() if row in self.detail_paths}
        self.details.delete(*self.details.get_children())
        self.detail_paths.clear()
        if usage is None:
            self.detail_title.set('选择应用查看目录明细')
            self.reason.set('共享和疑似数据单独列出，不计入已确认合计。大小为已分配文件块估算，不等于可释放空间。')
            return
        self.detail_title.set('目录明细')
        self.reason.set('%s · %s · 共享 %s / 疑似 %s（均不计合计）%s' % (
            usage.app.name, usage.app.bundle_id or '无应用标识', self.format_size(usage.shared_bytes),
            self.format_size(usage.suspected_bytes), ' · ' + usage.app.warning if usage.app.warning else ''))
        entries = [(usage.app.path, 'App 包', '本体', '应用程序包', usage.package)]
        labels = {'confirmed': '已确认', 'shared': '共享', 'suspected': '疑似'}
        for location in usage.locations:
            owners = [self.usages[path].app.name for path in location.owners if path in self.usages]
            reason = location.reason + ('；关联应用：' + '、'.join(owners) if location.confidence == 'shared' else '')
            entries.append((location.path, location.category, labels[location.confidence], reason,
                            usage.measurements.get(location.path)))
        for path, category, confidence, reason, measurement in entries:
            row = self.details.insert('', 'end', values=(category, self.size_text(measurement), confidence, path))
            self.detail_paths[row] = (path, reason + ('；' + '；'.join(measurement.errors) if measurement and measurement.errors else ''))
            if path in selected_paths:
                self.details.selection_add(row)

    def show_reason(self):
        selected = self.details.selection()
        if selected and selected[0] in self.detail_paths:
            path, reason = self.detail_paths[selected[0]]
            self.reason.set('%s · %s' % (reason, path))

    def selected_path(self):
        selected = self.details.selection()
        if selected and selected[0] in self.detail_paths:
            return self.detail_paths[selected[0]][0]
        usage = self.selected_usage()
        return usage.app.path if usage else None

    def browse_selected(self):
        path = self.selected_path()
        if path:
            self.browse_path(path if os.path.isdir(path) else os.path.dirname(path))

    def open_selected(self):
        path = self.selected_path()
        if path:
            self.open_path(path)

    def select_all(self, event):
        event.widget.selection_set(event.widget.get_children())
        return 'break'

    def show_scan_info(self):
        popup = tk.Toplevel(self.frame)
        popup.title('应用空间统计说明')
        popup.transient(self.frame.winfo_toplevel())
        popup.geometry('720x440')
        area = ttk.Frame(popup, padding=16)
        area.pack(fill='both', expand=True)
        style = ttk.Style(self.frame)
        text = tk.Text(area, wrap='word', padx=12, pady=12,
                       background=style.lookup('Card.TFrame', 'background'),
                       foreground=style.lookup('TLabel', 'foreground'))
        scroll = ttk.Scrollbar(area, orient='vertical', command=text.yview)
        scroll.pack(side='right', fill='y')
        text.configure(yscrollcommand=scroll.set)
        text.pack(fill='both', expand=True)
        content = ('应用发现：/Applications、~/Applications、系统应用目录，并用 Spotlight 补充。'
                   '未索引的自定义目录、其他用户的应用及非 .app 命令行工具可能遗漏。\n\n'
                   '外部数据：当前用户 ~/Library 与 /Library 下的标准目录。'
                   '按应用标识或 App Group 匹配；名称匹配仅作为疑似。自定义资源目录可能遗漏。\n\n'
                   '合计仅包含 App 包和已确认的独占外部数据。共享、疑似数据不加入合计。'
                   '0B 表示本次已匹配的范围为零，不代表应用没有其他数据。\n\n'
                   '大小按已分配文件块估算，不包含目录元数据，内部符号链接不跟随；'
                   'APFS 克隆与快照使它不等于可释放空间。≥ 表示读取异常后的已知下限。\n\n'
                   '本次扫描范围异常：\n' + ('\n'.join(self.warnings) if self.warnings else '暂无已报告异常。'))
        text.insert('1.0', content)
        text.configure(state='disabled')
        ttk.Button(popup, text='关闭', command=popup.destroy).pack(pady=(0, 12))
        popup.bind('<Escape>', lambda _: popup.destroy())
