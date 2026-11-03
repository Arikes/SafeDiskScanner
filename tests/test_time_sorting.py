import os
import pathlib
import tempfile
import unittest
from unittest.mock import Mock, patch
from test_scanner import scanner, make_app
from test_sorting import Table


class TimeSortingTests(unittest.TestCase):
    def app(self):
        app = make_app()
        app.flist = Table()
        app.sort_hint_var = Mock()
        app.file_operation_status = Mock()
        # Displayed times are identical; sorting must use original timestamps.
        app.file_items = [(10, False, 'old.wav', '/old', '2026-11-03 12:00'),
                          (-1, True, 'new-folder', '/folder', '2026-11-03 12:00'),
                          (20, False, 'middle.wav', '/middle', '2026-11-03 12:00')]
        app._file_mtimes = {'/old': 10, '/folder': 30, '/middle': 20}
        return app

    def names(self, app):
        return [app.flist.item(row, 'values')[0] for row in app.flist.get_children()]

    def test_time_header_switches_sort_then_toggles_without_losing_selection(self):
        app = self.app()
        app._render_list()
        selected = app._file_row_ids['/old']
        app.flist.selected = (selected,)
        ids = set(app.flist.rows)
        with patch.object(scanner, 'save_mtime_sort_direction', return_value=True):
            app.toggle_mtime_sort()
            self.assertEqual(self.names(app), ['new-folder', 'middle.wav', 'old.wav'])
            self.assertEqual(app.flist.headers['size']['text'], '大小')
            self.assertIn('↓', app.flist.headers['mtime']['text'])
            app.toggle_mtime_sort()
        self.assertEqual(self.names(app), ['old.wav', 'middle.wav', 'new-folder'])
        self.assertIn('↑', app.flist.headers['mtime']['text'])
        self.assertEqual(app.flist.selection(), (selected,))
        self.assertEqual(set(app.flist.rows), ids)

    def test_filtered_time_order_survives_size_updates_and_directory_switch(self):
        app = self.app()
        app.sort_column = 'mtime'
        app.mtime_sort_descending = False
        app.excluded_file_types = {'folder'}
        app._render_list()
        app._update_row_size('/old', 999)
        self.assertFalse(app._size_sort_dirty)
        app._reorder_file_rows()
        self.assertEqual(self.names(app), ['old.wav', 'middle.wav'])
        app.file_items = [(1, False, 'latest.wav', '/latest', ''), (2, False, 'earliest.wav', '/earliest', '')]
        app._file_mtimes = {'/latest': 200, '/earliest': 100}
        app._render_list()
        self.assertEqual(self.names(app), ['earliest.wav', 'latest.wav'])

    def test_switching_back_to_size_restores_its_direction_then_toggles(self):
        app = self.app()
        app.sort_column = 'mtime'
        app._render_list()
        with patch.object(scanner, 'save_sort_direction', return_value=True):
            app.toggle_size_sort()
            self.assertEqual(self.names(app), ['middle.wav', 'old.wav', 'new-folder'])
            self.assertEqual(app.flist.headers['mtime']['text'], '修改时间')
            app.toggle_size_sort()
        self.assertEqual(self.names(app), ['old.wav', 'middle.wav', 'new-folder'])

    def test_time_preference_survives_reload_and_other_preference_updates(self):
        with tempfile.TemporaryDirectory() as folder:
            path = pathlib.Path(folder) / 'settings.json'
            self.assertEqual(scanner.load_browser_sort(path), ('size', True))
            scanner.save_sort_direction(False, path)
            self.assertTrue(scanner.save_mtime_sort_direction(False, path))
            scanner.save_type_filter({'ext:.wav'}, path)
            scanner.save_sidebar_collapsed(True, path)
            self.assertEqual(scanner.load_browser_sort(path), ('mtime', False))
            self.assertFalse(scanner.load_sort_direction(path))
            scanner.save_sort_direction(True, path)
            self.assertEqual(scanner.load_browser_sort(path), ('size', False))
            self.assertEqual(scanner.load_type_filter(path), {'ext:.wav'})
            self.assertTrue(scanner.load_sidebar_collapsed(path))

    def test_corrupt_or_invalid_time_preferences_have_safe_defaults(self):
        with tempfile.TemporaryDirectory() as folder:
            path = pathlib.Path(folder) / 'settings.json'
            for content in ('broken', '[]', '{"browser_sort_column": "other", "mtime_sort_descending": "false"}'):
                path.write_text(content)
                self.assertEqual(scanner.load_browser_sort(path), ('size', True))

    def test_navigation_preserves_subminute_timestamp_precision(self):
        app = self.app()
        app.sort_column = 'mtime'
        app.path_var = Mock()
        app.show_hidden = Mock()
        app.show_hidden.get.return_value = False
        with tempfile.TemporaryDirectory() as folder:
            early = pathlib.Path(folder) / 'early'
            late = pathlib.Path(folder) / 'late'
            early.write_text('a')
            late.write_text('b')
            for path, timestamp in ((early, 1800000001000000000), (late, 1800000002000000000)):
                os.utime(path, ns=(timestamp, timestamp))
            app.navigate(folder)
            self.assertEqual(self.names(app), ['late', 'early'])
            self.assertGreater(app._file_mtimes[str(late)], app._file_mtimes[str(early)])


if __name__ == '__main__':
    unittest.main()
