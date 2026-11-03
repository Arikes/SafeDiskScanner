import unittest
from types import SimpleNamespace
from unittest.mock import Mock
from test_scanner import make_app
from test_sorting import Table


class SelectAllTests(unittest.TestCase):
    def setUp(self):
        self.app = make_app()
        self.app.flist = Table()
        self.app.res = Table()

    def test_browser_selects_visible_files_and_folders_without_parent(self):
        self.app.file_items = [(10, True, 'folder', '/folder', ''),
                               (20, False, 'sound.wav', '/sound.wav', ''),
                               (30, False, 'hidden.mp4', '/hidden.mp4', '')]
        self.app.excluded_file_types = {'ext:.mp4'}
        self.app._render_list()
        result = self.app.on_list_select_all(SimpleNamespace(widget=self.app.flist))
        selected = [self.app.flist.item(row, 'values')[0] for row in self.app.flist.selection()]
        self.assertEqual(selected, ['sound.wav', 'folder'])
        self.assertEqual(self.app.res.selection(), ())
        self.assertEqual(result, 'break')

    def test_results_selects_every_result_without_changing_browser_selection(self):
        self.app.flist.selected = ('existing',)
        self.app.res.insert('', 'end', values=(1, '20B', '/a'), tags=())
        self.app.res.insert('', 'end', values=(2, '10B', '/b'), tags=())
        self.app.on_list_select_all(SimpleNamespace(widget=self.app.res))
        paths = [self.app.res.item(row, 'values')[2] for row in self.app.res.selection()]
        self.assertEqual(paths, ['/a', '/b'])
        self.assertEqual(self.app.flist.selection(), ('existing',))

    def test_empty_lists_select_nothing(self):
        for table in (self.app.flist, self.app.res):
            with self.subTest(table=table):
                self.assertEqual(self.app.on_list_select_all(SimpleNamespace(widget=table)), 'break')
                self.assertEqual(table.selection(), ())

    def shortcut_context(self, focused_class='TButton', popup=False):
        self.app.root = Mock()
        self.app.browse_tab = 'browser'
        self.app.scan_tab = 'scanner'
        self.app.notebook = Mock()
        self.app.notebook.select.return_value = 'browser'
        focus = SimpleNamespace(winfo_class=lambda: focused_class,
                                winfo_toplevel=lambda: object() if popup else self.app.root)
        self.app.root.focus_get.return_value = focus
        self.app.flist.focus_set = Mock()
        self.app.res.focus_set = Mock()
        self.app.flist.insert('', 'end', values=('a', '1B', '文件', '', '/a'), tags=())
        self.app.flist.insert('', 'end', values=('b', '2B', '文件', '', '/b'), tags=())
        self.app.res.insert('', 'end', values=(1, '1B', '/result'), tags=())
        return SimpleNamespace(widget=focus)

    def test_shortcut_from_button_selects_current_tab_list(self):
        event = self.shortcut_context()
        self.assertEqual(self.app.on_list_select_all(event), 'break')
        self.assertEqual(self.app.flist.selection(), ('0', '1'))
        self.assertEqual(self.app.res.selection(), ())
        self.app.flist.selection_set(())
        self.app.notebook.select.return_value = 'scanner'
        self.assertEqual(self.app.on_list_select_all(event), 'break')
        self.assertEqual(self.app.flist.selection(), ())
        self.assertEqual(self.app.res.selection(), ('0',))

    def test_shortcut_from_text_fields_and_popup_leaves_files_unchanged(self):
        for widget_class, popup in (('TEntry', False), ('TSpinbox', False), ('Text', False), ('TButton', True)):
            with self.subTest(widget_class=widget_class, popup=popup):
                event = self.shortcut_context(widget_class, popup)
                self.assertIsNone(self.app.on_list_select_all(event))
                self.assertEqual(self.app.flist.selection(), ())
                self.assertEqual(self.app.res.selection(), ())

    def test_shortcut_with_no_child_focus_selects_visible_browser(self):
        self.shortcut_context()
        self.app.root.focus_get.return_value = None
        self.assertEqual(self.app.on_list_select_all(SimpleNamespace(widget=self.app.root)), 'break')
        self.assertEqual(self.app.flist.selection(), ('0', '1'))


if __name__ == '__main__':
    unittest.main()
