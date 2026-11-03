import pathlib
import tempfile
import unittest
from test_scanner import scanner


class SidebarPreferencesTests(unittest.TestCase):
    def test_missing_or_invalid_preference_defaults_to_expanded(self):
        with tempfile.TemporaryDirectory() as folder:
            path = pathlib.Path(folder) / 'settings.json'
            self.assertFalse(scanner.load_sidebar_collapsed(path))
            for content in ('broken', '[]', '{}', '{"sidebar_collapsed": "false"}',
                            '{"sidebar_collapsed": 1}', '{"sidebar_collapsed": null}'):
                path.write_text(content)
                self.assertFalse(scanner.load_sidebar_collapsed(path))

    def test_collapse_and_expand_survive_reload_without_losing_other_preferences(self):
        with tempfile.TemporaryDirectory() as folder:
            path = pathlib.Path(folder) / 'config/settings.json'
            scanner.save_sort_direction(False, path)
            scanner.save_type_filter({'ext:.wav'}, path)
            self.assertTrue(scanner.save_sidebar_collapsed(True, path))
            self.assertTrue(scanner.load_sidebar_collapsed(path))
            scanner.save_sort_direction(True, path)
            self.assertTrue(scanner.load_sidebar_collapsed(path))
            self.assertTrue(scanner.save_sidebar_collapsed(False, path))
            self.assertFalse(scanner.load_sidebar_collapsed(path))
            self.assertEqual(scanner.load_type_filter(path), {'ext:.wav'})
            self.assertTrue(scanner.load_sort_direction(path))

    def test_unwritable_settings_location_reports_failure(self):
        with tempfile.TemporaryDirectory() as folder:
            parent = pathlib.Path(folder) / 'file'
            parent.write_text('keep')
            self.assertFalse(scanner.save_sidebar_collapsed(True, parent / 'settings.json'))
            self.assertEqual(parent.read_text(), 'keep')


if __name__ == '__main__':
    unittest.main()
