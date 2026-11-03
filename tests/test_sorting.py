import json
import pathlib
import tempfile
import unittest
from unittest.mock import Mock, patch
from test_scanner import scanner, make_app


class Table:
    def __init__(self):
        self.order = []
        self.rows = {}
        self.selected = ()
        self.headers = {}
    def get_children(self):
        return tuple(self.order)
    def delete(self, *rows):
        for row in rows:
            self.order.remove(row); del self.rows[row]
    def insert(self, parent, where, values, tags):
        row = str(len(self.rows))
        self.rows[row] = list(values); self.order.append(row)
        return row
    def set(self, row, column, value):
        self.rows[row][1] = value
    def move(self, row, parent, index):
        self.order.remove(row); self.order.insert(index, row)
    def selection(self):
        return self.selected
    def selection_set(self, rows):
        self.selected = tuple(rows)
    def item(self, row, key):
        return self.rows[row]
    def heading(self, name, **kwargs):
        self.headers[name] = kwargs


class SortingTests(unittest.TestCase):
    def app(self, descending=True):
        app = make_app()
        app.size_sort_descending = descending
        app.has_parent = True; app.parent_path = '/parent'
        app.sort_hint_var = Mock(); app.file_operation_status = Mock()
        app.flist = Table()
        app.file_items = [(10, True, 'small-dir', '/small-dir', ''),
                          (200, False, 'large-file', '/large-file', ''),
                          (-1, True, 'pending', '/pending', ''),
                          (20, False, 'medium-file', '/medium-file', '')]
        return app
    def names(self, app):
        return [app.flist.rows[row][0] for row in app.flist.order]
    def test_descending_sorts_files_and_folders_together_unknown_last(self):
        app = self.app(); app._render_list()
        self.assertEqual(self.names(app), ['..', 'large-file', 'medium-file', 'small-dir', 'pending'])
    def test_ascending_keeps_parent_first_unknown_last(self):
        app = self.app(False); app._render_list()
        self.assertEqual(self.names(app), ['..', 'small-dir', 'medium-file', 'large-file', 'pending'])
    def test_click_toggles_and_saves_without_recreating_or_losing_selected_rows(self):
        app = self.app(); app._render_list()
        selected = app._file_row_ids['/medium-file']; app.flist.selected = (selected,)
        original_ids = set(app.flist.rows)
        with patch.object(scanner, 'save_sort_direction', return_value=True) as save:
            app.toggle_size_sort()
        self.assertFalse(app.size_sort_descending)
        save.assert_called_once_with(False)
        self.assertEqual(set(app.flist.rows), original_ids)
        self.assertEqual(app.flist.selected, (selected,))
        self.assertEqual(self.names(app)[1:3], ['small-dir', 'medium-file'])
        self.assertIn('↑', app.flist.headers['size']['text'])
    def test_background_size_result_reorders_existing_rows(self):
        app = self.app(); app._render_list()
        app._update_row_size('/pending', 300)
        app._reorder_file_rows()
        self.assertEqual(self.names(app), ['..', 'pending', 'large-file', 'medium-file', 'small-dir'])
        self.assertEqual(next(x[0] for x in app.file_items if x[3] == '/pending'), 300)
    def test_new_directory_uses_existing_choice(self):
        app = self.app(False); app._render_list()
        app.file_items = [(999, False, 'large', '/large', ''), (1, True, 'small', '/small', '')]
        app._render_list()
        self.assertEqual(self.names(app), ['..', 'small', 'large'])
    def test_saved_direction_survives_reload_and_preserves_other_settings(self):
        with tempfile.TemporaryDirectory() as d:
            path = pathlib.Path(d) / 'config' / 'settings.json'
            path.parent.mkdir(); path.write_text(json.dumps({'other': 123}))
            self.assertTrue(scanner.save_sort_direction(False, path))
            self.assertIs(scanner.load_sort_direction(path), False)
            self.assertEqual(json.loads(path.read_text())['other'], 123)
            self.assertTrue(scanner.save_sort_direction(True, path))
            self.assertIs(scanner.load_sort_direction(path), True)
    def test_missing_corrupt_or_invalid_config_defaults_to_descending(self):
        with tempfile.TemporaryDirectory() as d:
            path = pathlib.Path(d) / 'settings.json'
            self.assertIs(scanner.load_sort_direction(path), True)
            for text in ('{broken', '[]', '{"size_sort_descending": "false"}'):
                path.write_text(text)
                self.assertIs(scanner.load_sort_direction(path), True)
    def test_directory_read_failure_still_allows_sorting_and_saving(self):
        app = self.app(); app._render_list()
        app.root = Mock(); app.path_var = Mock(); app.show_hidden = Mock(); app.show_hidden.get.return_value = False
        with tempfile.TemporaryDirectory() as d:
            path = pathlib.Path(d) / 'file'; path.write_text('data')
            with scanner.os.scandir(d) as entries:
                entry = next(entries)
            def broken_entries():
                yield entry
                raise OSError('device disconnected')
            context = Mock(); context.__enter__ = Mock(return_value=broken_entries()); context.__exit__ = Mock(return_value=False)
            with patch.object(scanner.os, 'scandir', return_value=context), patch.object(scanner.messagebox, 'showerror'):
                app.navigate(d)
            with patch.object(scanner, 'save_sort_direction', return_value=True) as save:
                app.toggle_size_sort()
            self.assertEqual(app.file_items, [])
            save.assert_called_once_with(False)

    def test_unwritable_config_does_not_undo_the_sort_change(self):
        app = self.app(); app._render_list()
        with patch.object(scanner, 'save_sort_direction', return_value=False):
            app.toggle_size_sort()
        self.assertFalse(app.size_sort_descending)
        app.file_operation_status.set.assert_called_once()


if __name__ == '__main__':
    unittest.main()
