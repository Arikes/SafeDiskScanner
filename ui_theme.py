"""Shared presentation for the Tk/ttk desktop UI; no filesystem or scan logic."""
import tkinter as tk
from tkinter import font as tkfont
from tkinter import ttk


PALETTES = {
    'light': {
        'win_bg': '#f4f6f9', 'tree_bg': '#ffffff', 'sidebar': '#edf1f6',
        'tree_fg': '#242c39', 'muted': '#667085', 'border': '#e3e8f0', 'error': '#b42318',
        'heading_bg': '#f7f9fc', 'input_bg': '#f7f9fc',
        'accent': '#3264df', 'accent_active': '#2653c4', 'accent_text': '#2859cf',
        'soft_accent': '#edf3ff', 'soft_active': '#e0eaff',
        'selected_bg': '#e7efff', 'selected_fg': '#214da8',
        'btn_bg': '#edf1f6', 'btn_active': '#e2e8f1', 'disabled': '#a0a9b8',
        'dir': '#42546e', 'file': '#242c39', 'up': '#3264df',
        'thumb': '#d3dbe7', 'thumb_active': '#a9b7ca', 'usage_fill': '#dfe9fb',
    },
    'dark': {
        'win_bg': '#141820', 'tree_bg': '#1d232d', 'sidebar': '#191f29',
        'tree_fg': '#e8edf5', 'muted': '#a1adbf', 'border': '#303949', 'error': '#ffb4ab',
        'heading_bg': '#252d3a', 'input_bg': '#171d27',
        'accent': '#386cde', 'accent_active': '#477bea', 'accent_text': '#9abaff',
        'soft_accent': '#263a5e', 'soft_active': '#30476f',
        'selected_bg': '#2b4166', 'selected_fg': '#eef4ff',
        'btn_bg': '#2b3443', 'btn_active': '#354155', 'disabled': '#718097',
        'dir': '#bacbe5', 'file': '#e8edf5', 'up': '#9abaff',
        'thumb': '#3b475b', 'thumb_active': '#61718b', 'usage_fill': '#263a56',
    },
}


class DiskOverview(tk.Canvas):
    """Compact capacity summary over a solid, proportional usage background."""

    def __init__(self, master, metrics, usage_var, refresh, mode):
        super().__init__(master, height=54, borderwidth=0, highlightthickness=0, takefocus=0)
        self.metrics = metrics
        self.usage_var = usage_var
        self.percentage = 0
        self.palette = PALETTES[mode]
        self.fill = self.create_rectangle(0, 0, 0, 54, outline='')
        self.metric_items = [
            (self.create_text(0, 0, anchor='w', text=label, font=('Helvetica Neue', 10)),
             self.create_text(0, 0, anchor='w', font=('Helvetica Neue', 13, 'bold')))
            for label, _ in metrics
        ]
        self.usage_text = self.create_text(0, 0, anchor='e', font=('Helvetica Neue', 10))
        self.refresh_button = ttk.Button(self, text='刷新磁盘', command=refresh, style='Compact.TButton')
        self.refresh_window = self.create_window(0, 0, anchor='e', window=self.refresh_button)
        self.bind('<Configure>', self._redraw)
        self.set_theme(mode)

    def set_usage(self, percentage):
        self.percentage = max(0, min(100, percentage))
        self._redraw()

    def set_theme(self, mode):
        self.palette = PALETTES[mode]
        self.configure(background=self.palette['tree_bg'])
        self._redraw()

    def _redraw(self, event=None):
        width, height = self.winfo_width(), self.winfo_height()
        if width < 100:
            return
        p = self.palette
        middle = height / 2
        self.coords(self.fill, 0, 0, width * self.percentage / 100, height)
        self.itemconfigure(self.fill, fill=p['usage_fill'])
        button_width = self.refresh_button.winfo_reqwidth()
        button_left = width - 16 - button_width
        usage_right = button_left - 20
        metric_width = (usage_right - 110 - 16) / 3
        for col, ((label, value), (_, variable)) in enumerate(zip(self.metric_items, self.metrics)):
            left = 16 + col * metric_width
            self.coords(label, left, middle)
            self.itemconfigure(label, fill=p['muted'])
            label_right = self.bbox(label)[2]
            self.coords(value, label_right + 8, middle)
            self.itemconfigure(value, text=variable.get(), fill=p['accent_text'] if col == 2 else p['tree_fg'])
        self.coords(self.usage_text, usage_right, middle)
        self.itemconfigure(self.usage_text, text=self.usage_var.get(), fill=p['muted'])
        self.coords(self.refresh_window, width - 16, middle)


def configure_typography(root):
    for name in ('TkDefaultFont', 'TkTextFont', 'TkMenuFont', 'TkHeadingFont'):
        tkfont.nametofont(name, root=root).configure(family='Helvetica Neue', size=11)


def _images(app, p):
    """Keep the images alive and recolor them on appearance changes."""
    if not hasattr(app, '_modern_images'):
        app._modern_images = {
            name: tk.PhotoImage(master=app.root, width=3, height=4)
            for name in ('tab', 'tab_selected', 'tab_hover')
        }
        app._modern_images['field'] = tk.PhotoImage(master=app.root, width=3, height=3)
        app._modern_images['field_focus'] = tk.PhotoImage(master=app.root, width=3, height=3)
        app._modern_images['progress_track'] = tk.PhotoImage(master=app.root, width=3, height=5)
        app._modern_images['progress_fill'] = tk.PhotoImage(master=app.root, width=3, height=5)
        app._modern_images['scroll_track'] = tk.PhotoImage(master=app.root, width=9, height=9)
        for name, width, height in (('scroll_v', 9, 24), ('scroll_v_hover', 9, 24), ('scroll_h', 24, 9), ('scroll_h_hover', 24, 9)):
            app._modern_images[name] = tk.PhotoImage(master=app.root, width=width, height=height)
        for name in ('check_off', 'check_hover', 'check_on', 'check_mixed', 'check_disabled'):
            app._modern_images[name] = tk.PhotoImage(master=app.root, width=22, height=18)
    images = app._modern_images
    for name, color in (('tab', p['win_bg']), ('tab_selected', p['tree_bg']), ('tab_hover', p['btn_bg'])):
        images[name].put(color, to=(0, 0, 3, 4))
    images['tab_selected'].put(p['accent'], to=(0, 3, 3, 4))
    for name, color in (('field', p['border']), ('field_focus', p['accent'])):
        images[name].put(color, to=(0, 0, 3, 3))
        images[name].put(p['input_bg'], to=(1, 1, 2, 2))
    images['progress_track'].put(p['heading_bg'], to=(0, 0, 3, 5))
    images['progress_fill'].put(p['accent'], to=(0, 0, 3, 5))
    images['scroll_track'].put(p['tree_bg'], to=(0, 0, 9, 9))
    for name in ('scroll_v', 'scroll_v_hover', 'scroll_h', 'scroll_h_hover'):
        vertical = name.startswith('scroll_v')
        width, height = (9, 24) if vertical else (24, 9)
        images[name].put(p['tree_bg'], to=(0, 0, width, height))
        color = p['thumb_active'] if name.endswith('hover') else p['thumb']
        images[name].put(color, to=(2, 1, 7, 23) if vertical else (1, 2, 23, 7))
    for name in ('check_off', 'check_hover', 'check_on', 'check_mixed', 'check_disabled'):
        image = images[name]
        image.put(p['tree_bg'], to=(0, 0, 22, 18))
        border = p['accent'] if name in ('check_on', 'check_mixed', 'check_hover') else p['thumb_active']
        fill = p['accent'] if name in ('check_on', 'check_mixed') else p['tree_bg']
        if name == 'check_disabled':
            border, fill = p['border'], p['heading_bg']
        image.put(border, to=(1, 2, 16, 17))
        image.put(fill, to=(2, 3, 15, 16))
        if name == 'check_on':
            for x, y in ((4, 9), (5, 10), (6, 11), (7, 12), (8, 11), (9, 10), (10, 9), (11, 8), (12, 7)):
                image.put('#ffffff', to=(x, y, x + 2, y + 2))
        elif name == 'check_mixed':
            image.put('#ffffff', to=(4, 8, 13, 11))
    return images


def apply_modern_theme(app, mode):
    app.mode = mode
    p = PALETTES[mode]
    style = app.style
    style.theme_use('clam')
    app.root.configure(background=p['win_bg'])
    images = _images(app, p)
    if 'Modern.tab' not in style.element_names():
        style.element_create('Modern.tab', 'image', images['tab'],
                             ('selected', images['tab_selected']), ('active', images['tab_hover']),
                             border=(0, 0, 0, 1), sticky='nswe')
        style.element_create('Modern.check', 'image', images['check_off'],
                             ('disabled', images['check_disabled']), ('alternate', images['check_mixed']),
                             ('selected', images['check_on']), ('active', images['check_hover']),
                             ('focus', images['check_hover']), sticky='w')
        for orient, prefix, border in (('Vertical', 'scroll_v', (0, 3, 0, 3)), ('Horizontal', 'scroll_h', (3, 0, 3, 0))):
            style.element_create('Modern.' + orient + '.Scrollbar.trough', 'image', images['scroll_track'], sticky='nswe')
            style.element_create('Modern.' + orient + '.Scrollbar.thumb', 'image', images[prefix],
                                 ('active', images[prefix + '_hover']), ('pressed', images[prefix + '_hover']), border=border, sticky='nswe')
        style.element_create('Modern.field', 'image', images['field'], ('focus', images['field_focus']), border=1, sticky='nswe')
        style.element_create('Modern.Horizontal.Progressbar.trough', 'image', images['progress_track'], sticky='nswe')
        style.element_create('Modern.Horizontal.Progressbar.pbar', 'image', images['progress_fill'], sticky='nswe')
    # Replace raised tab edges with a quiet surface and a one-pixel active line.
    style.layout('Workspace.TNotebook.Tab', [('Modern.tab', {'sticky': 'nswe', 'children': [
        ('Notebook.padding', {'sticky': 'nswe', 'children': [('Notebook.label', {'sticky': 'nswe'})]})]})])
    style.configure('Workspace.TNotebook', background=p['win_bg'], borderwidth=0,
                    bordercolor=p['win_bg'], lightcolor=p['win_bg'], darkcolor=p['win_bg'], tabmargins=(0, 0, 116, 0))
    style.configure('Workspace.TNotebook.Tab', font=('Helvetica Neue', 11, 'bold'), padding=(20, 10))
    style.map('Workspace.TNotebook.Tab', padding=[('selected', (20, 10)), ('!selected', (20, 10))],
              foreground=[('selected', p['accent_text']), ('active', p['tree_fg']), ('!selected', p['muted'])])
    for name, bg in (('TFrame', p['win_bg']), ('Card.TFrame', p['tree_bg']), ('Sidebar.TFrame', p['sidebar'])):
        style.configure(name, background=bg, borderwidth=0, relief='flat')
    style.configure('TLabel', background=p['win_bg'], foreground=p['tree_fg'], font=('Helvetica Neue', 11))
    for name, bg, fg, font in (
        ('Title.TLabel', p['win_bg'], p['tree_fg'], ('Helvetica Neue', 17, 'bold')),
        ('Muted.TLabel', p['win_bg'], p['muted'], ('Helvetica Neue', 10)),
        ('CardMuted.TLabel', p['tree_bg'], p['muted'], ('Helvetica Neue', 10)),
        ('Section.TLabel', p['tree_bg'], p['tree_fg'], ('Helvetica Neue', 12, 'bold')),
        ('Metric.TLabel', p['tree_bg'], p['tree_fg'], ('Helvetica Neue', 18, 'bold')),
        ('FreeMetric.TLabel', p['tree_bg'], p['accent_text'], ('Helvetica Neue', 18, 'bold')),
        ('ScanPath.TLabel', p['tree_bg'], p['tree_fg'], ('Helvetica Neue', 12)),
        ('SidebarTitle.TLabel', p['sidebar'], p['muted'], ('Helvetica Neue', 10, 'bold')),
        ('SidebarMuted.TLabel', p['sidebar'], p['muted'], ('Helvetica Neue', 10)),
        ('Empty.TLabel', p['tree_bg'], p['muted'], ('Helvetica Neue', 11)),
        ('Error.TLabel', p['tree_bg'], p['error'], ('Helvetica Neue', 11)),
    ):
        style.configure(name, background=bg, foreground=fg, font=font)
    # Same geometry for every button state; the border also acts as a focus cue.
    style.layout('TButton', [('Button.border', {'sticky': 'nswe', 'children': [
        ('Button.padding', {'sticky': 'nswe', 'children': [('Button.label', {'sticky': 'nswe'})]})]})])
    button_styles = (
        ('TButton', p['btn_bg'], p['btn_active'], p['tree_fg']),
        ('Small.TButton', p['btn_bg'], p['btn_active'], p['tree_fg']),
        ('Ghost.TButton', p['tree_bg'], p['heading_bg'], p['muted']),
        ('Compact.TButton', p['tree_bg'], p['heading_bg'], p['muted']),
        ('Header.TButton', p['win_bg'], p['btn_active'], p['muted']),
        ('Nav.TButton', p['sidebar'], p['btn_active'], p['tree_fg']),
        ('SoftAccent.TButton', p['soft_accent'], p['soft_active'], p['accent_text']),
        ('Accent.TButton', p['accent'], p['accent_active'], '#ffffff'),
    )
    for name, bg, hover, fg in button_styles:
        style.configure(name, background=bg, foreground=fg, font=('Helvetica Neue', 11),
                        padding=(12, 6), width=0, anchor='center', borderwidth=1,
                        relief='flat', bordercolor=bg, lightcolor=bg, darkcolor=bg)
        style.map(name, background=[('disabled', p['btn_bg']), ('pressed', hover), ('active', hover)],
                  foreground=[('disabled', p['disabled']), ('!disabled', fg)],
                  bordercolor=[('focus', p['accent']), ('active', hover), ('!focus', bg)],
                  lightcolor=[('active', hover), ('!active', bg)], darkcolor=[('active', hover), ('!active', bg)])
    style.configure('Accent.TButton', font=('Helvetica Neue', 11, 'bold'))
    style.configure('Compact.TButton', font=('Helvetica Neue', 10), padding=(8, 2))
    def flat_field(nodes):
        result = []
        for element, options in nodes:
            options = dict(options)
            if 'children' in options:
                options['children'] = flat_field(options['children'])
            result.append(('Modern.field' if element.endswith('.field') else element, options))
        return result
    for name in ('TEntry', 'TSpinbox'):
        style.layout(name, flat_field(style.layout(name)))

        style.configure(name, fieldbackground=p['input_bg'], foreground=p['tree_fg'],
                        insertcolor=p['tree_fg'], padding=(9, 7), borderwidth=1, relief='flat',
                        bordercolor=p['border'], lightcolor=p['input_bg'], darkcolor=p['input_bg'],
                        arrowcolor=p['muted'], arrowsize=12)
        style.map(name, bordercolor=[('focus', p['accent']), ('!focus', p['border'])],
                  fieldbackground=[('readonly', p['heading_bg']), ('!disabled', p['input_bg'])])
    style.layout('Card.TCheckbutton', [('Checkbutton.padding', {'sticky': 'nswe', 'children': [
        ('Modern.check', {'side': 'left', 'sticky': 'w'}), ('Checkbutton.label', {'side': 'left', 'sticky': 'w'})]})])
    style.configure('Card.TCheckbutton', background=p['tree_bg'], foreground=p['tree_fg'],
                    font=('Helvetica Neue', 11), padding=(0, 2))
    style.map('Card.TCheckbutton', background=[('active', p['tree_bg'])],
              foreground=[('disabled', p['disabled']), ('focus', p['accent_text']), ('!disabled', p['tree_fg'])])
    style.layout('Treeview', [('Treeview.treearea', {'sticky': 'nswe'})])
    style.configure('Treeview', background=p['tree_bg'], fieldbackground=p['tree_bg'], foreground=p['tree_fg'],
                    rowheight=30, font=('Helvetica Neue', 11), borderwidth=0, relief='flat')
    style.map('Treeview', background=[('selected', p['selected_bg'])], foreground=[('selected', p['selected_fg'])])
    style.layout('Treeview.Heading', [('Treeheading.cell', {'sticky': 'nswe'}),
        ('Treeheading.padding', {'sticky': 'nswe', 'children': [('Treeheading.text', {'sticky': 'we'})]})])
    style.configure('Treeview.Heading', background=p['heading_bg'], foreground=p['muted'],
                    font=('Helvetica Neue', 10, 'bold'), padding=(10, 9), relief='flat', borderwidth=0)
    style.map('Treeview.Heading', background=[('active', p['btn_bg'])], foreground=[('active', p['tree_fg'])])
    style.configure('Sidebar.Treeview', background=p['sidebar'], fieldbackground=p['sidebar'], rowheight=29)
    app.tree.configure(style='Sidebar.Treeview')
    for table in (app.tree, app.flist, app.res):
        bg = p['sidebar'] if table is app.tree else p['tree_bg']
        for tag, fg in (('dir', p['dir']), ('file', p['file']), ('normal', p['tree_fg']), ('up', p['up'])):
            table.tag_configure(tag, foreground=fg, background=bg)
    for orient, side in (('Vertical', 'ns'), ('Horizontal', 'we')):
        style.layout(orient + '.TScrollbar', [('Modern.' + orient + '.Scrollbar.trough', {'sticky': side, 'children': [
            ('Modern.' + orient + '.Scrollbar.thumb', {'expand': 1, 'sticky': 'nswe'})]})])
    style.configure('TScrollbar', background=p['thumb'], troughcolor=p['tree_bg'], borderwidth=0,
                    bordercolor=p['tree_bg'], lightcolor=p['thumb'], darkcolor=p['thumb'], arrowsize=9,
                    gripcount=0, relief='flat')
    style.map('TScrollbar', background=[('active', p['thumb_active']), ('pressed', p['thumb_active'])])
    style.layout('Disk.Horizontal.TProgressbar', [('Modern.Horizontal.Progressbar.trough', {'sticky': 'nswe', 'children': [
        ('Modern.Horizontal.Progressbar.pbar', {'side': 'left', 'sticky': 'ns'})]})])
    style.configure('Disk.Horizontal.TProgressbar', background=p['accent'], troughcolor=p['heading_bg'],
                    bordercolor=p['heading_bg'], lightcolor=p['accent'], darkcolor=p['accent'], borderwidth=0, thickness=5)
    style.configure('TPanedwindow', background=p['win_bg'])
    style.configure('Sash', sashthickness=10, background=p['win_bg'], gripcount=0)
    style.configure('TSeparator', background=p['border'])
    app.appearance_btn.configure(text='深色外观' if mode == 'dark' else '浅色外观', style='Header.TButton')
    app._ctx_menu.configure(background=p['tree_bg'], foreground=p['tree_fg'],
                            activebackground=p['selected_bg'], activeforeground=p['selected_fg'],
                            borderwidth=0, relief='flat', font=('Helvetica Neue', 11))
    app.disk_overview.set_theme(mode)
