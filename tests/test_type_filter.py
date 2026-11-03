import json
import pathlib
import tempfile
import unittest
from unittest.mock import Mock, patch
from test_scanner import scanner, make_app
from test_sorting import Table


def item(name, is_dir=False, size=1):
    return (size, is_dir, name, '/fixture/' + name, '')


class TypeFilterTests(unittest.TestCase):
    def app(self):
        app = make_app()
        app.flist = Table(); app.has_parent = True; app.parent_path = '/'
        app.filter_summary_var = Mock(); app.file_operation_status = Mock()
        app.excluded_file_types = set(); app._type_filter_popup = None
        app.file_items = [item('folder.wav', True, 9), item('song.WAV', size=8),
                          item('other.wav', size=7), item('voice.aac', size=6),
                          item('video.mp4', size=5), item('README', size=4)]
        return app
    def names(self, app):
        return [app.flist.rows[row][0] for row in app.flist.order]
    def test_available_types_are_current_level_case_insensitive_and_counted(self):
        app = self.app()
        self.assertEqual(app._available_file_types(), {'folder': 1, 'ext:.wav': 2, 'ext:.aac': 1, 'ext:.mp4': 1, 'no_extension': 1})
        self.assertEqual(scanner.browser_item_type(item('archive.tar.gz')), 'ext:.gz')
        self.assertEqual(scanner.browser_item_type(item('.gitignore')), 'no_extension')
        self.assertEqual(scanner.browser_item_type(item('a.')), 'no_extension')
    def test_default_shows_all_and_excluded_types_are_hidden(self):
        app = self.app(); app._render_list()
        self.assertEqual(len(self.names(app)), 7)
        app.excluded_file_types = {'folder', 'ext:.wav'}; app._render_list()
        self.assertEqual(self.names(app), ['..', 'voice.aac', 'video.mp4', 'README'])
        self.assertEqual(app._available_file_types()['ext:.wav'], 2)
    def test_apply_remembers_unchecked_types_and_keeps_visible_selection(self):
        app = self.app(); app._render_list()
        row = app._file_row_ids['/fixture/voice.aac']; app.flist.selected = (row,)
        with patch.object(scanner, 'save_type_filter', return_value=True) as save:
            app.apply_type_filter({'ext:.aac', 'ext:.mp4', 'no_extension'}, set(app._available_file_types()))
        self.assertEqual(app.excluded_file_types, {'folder', 'ext:.wav'})
        save.assert_called_once_with({'folder', 'ext:.wav'})
        self.assertEqual([app.flist.rows[r][0] for r in app.flist.selection()], ['voice.aac'])
        self.assertEqual(self.names(app), ['..', 'voice.aac', 'video.mp4', 'README'])
    def test_directory_switch_preserves_old_rules_and_new_types_are_visible(self):
        app = self.app(); app.excluded_file_types = {'ext:.wav'}
        app.file_items = [item('new.flac', size=10), item('again.WAV', size=3)]
        app._render_list()
        self.assertEqual(self.names(app), ['..', 'new.flac'])
        with patch.object(scanner, 'save_type_filter', return_value=True):
            app.apply_type_filter(set(), {'ext:.flac'})
        self.assertEqual(app.excluded_file_types, {'ext:.wav', 'ext:.flac'})
    def test_unchecking_all_keeps_parent_navigation_and_reset_restores_everything(self):
        app = self.app(); app._render_list()
        with patch.object(scanner, 'save_type_filter', return_value=True):
            app.apply_type_filter(set(), set(app._available_file_types()))
            self.assertEqual(self.names(app), ['..'])
            app.reset_type_filter()
        self.assertFalse(app.excluded_file_types)
        self.assertEqual(len(self.names(app)), 7)
    def test_background_size_of_filtered_folder_is_retained_for_reenabling(self):
        app = self.app(); app.excluded_file_types = {'folder'}
        app.file_items[0] = item('folder.wav', True, -1); app._render_list()
        app._update_row_size('/fixture/folder.wav', 999)
        app.excluded_file_types.clear(); app._render_list()
        self.assertEqual(self.names(app)[1], 'folder.wav')
        row = app._file_row_ids['/fixture/folder.wav']
        self.assertEqual(app.flist.rows[row][1], '999B')
    def test_sort_after_filter_only_moves_visible_rows(self):
        app = self.app(); app.excluded_file_types = {'folder', 'ext:.wav'}; app._render_list()
        app.size_sort_descending = False; app._reorder_file_rows()
        self.assertEqual(self.names(app), ['..', 'README', 'video.mp4', 'voice.aac'])
    def test_persist_filter_and_sort_independently_across_reloads(self):
        with tempfile.TemporaryDirectory() as d:
            path = pathlib.Path(d) / 'settings.json'
            self.assertEqual(scanner.load_type_filter(path), set())
            self.assertTrue(scanner.save_sort_direction(False, path))
            self.assertTrue(scanner.save_type_filter({'folder', 'ext:.wav'}, path))
            self.assertEqual(scanner.load_type_filter(path), {'folder', 'ext:.wav'})
            self.assertFalse(scanner.load_sort_direction(path))
            self.assertTrue(scanner.save_sort_direction(True, path))
            self.assertEqual(scanner.load_type_filter(path), {'folder', 'ext:.wav'})
            self.assertTrue(scanner.save_type_filter(set(), path))
            self.assertEqual(scanner.load_type_filter(path), set())
    def test_invalid_filter_config_defaults_to_all_types(self):
        with tempfile.TemporaryDirectory() as d:
            path = pathlib.Path(d) / 'settings.json'
            for value in ('broken', '[]', '{"excluded_file_types": "wav"}', '{"excluded_file_types": [1, null, "bad"]}'):
                path.write_text(value)
                self.assertEqual(scanner.load_type_filter(path), set())


if __name__ == '__main__':
    unittest.main()
