import pathlib
import tempfile
import unittest
from unittest.mock import Mock, patch
from test_scanner import scanner, make_app
from test_sorting import Table


class StatusLabel:
    def __init__(self):
        self.options = {}
        self.visible = False

    def configure(self, **options):
        self.options.update(options)

    def place(self, **options):
        self.visible = True

    def place_forget(self):
        self.visible = False


class BrowserReadErrorsTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = pathlib.Path(self.tmp.name)
        self.app = make_app()
        self.app.flist = Table()
        self.app.path_var = Mock()
        self.app.sort_hint_var = Mock()
        self.app.show_hidden = Mock()
        self.app.show_hidden.get.return_value = False
        self.app.browser_empty_label = StatusLabel()
        self.app.file_operation_status = Mock()

    def fail_read(self, error):
        with patch.object(scanner.os, 'scandir', side_effect=error), patch.object(scanner.messagebox, 'showerror'):
            self.app.navigate(str(self.path))

    def test_permission_failure_replaces_empty_message_with_error_and_keeps_parent_navigation(self):
        self.app.navigate(str(self.path))
        self.assertIn('暂无', self.app.browser_empty_label.options['text'])
        self.fail_read(PermissionError('access denied'))
        self.assertTrue(self.app.browser_empty_label.visible)
        self.assertIn('读取权限异常', self.app.browser_empty_label.options['text'])
        self.assertNotIn('暂无', self.app.browser_empty_label.options['text'])
        self.assertIn('读取权限异常', self.app.filter_summary_var.set.call_args.args[0])
        self.assertEqual(self.app.flist.get_children(), ())
        with patch.object(self.app, 'navigate') as navigate:
            self.app.go_up()
        navigate.assert_called_once_with(str(self.path.parent))

    def test_io_failure_is_not_mislabelled_as_permission_failure(self):
        self.fail_read(OSError('device disconnected'))
        self.assertIn('目录读取异常', self.app.browser_empty_label.options['text'])
        self.assertNotIn('权限', self.app.browser_empty_label.options['text'])

    def test_sort_and_reset_filter_do_not_replace_error_with_empty_state(self):
        self.fail_read(PermissionError('access denied'))
        with patch.object(scanner, 'save_sort_direction', return_value=True), patch.object(scanner, 'save_type_filter', return_value=True):
            self.app.toggle_size_sort()
            self.app.reset_type_filter()
        self.assertIn('读取权限异常', self.app.browser_empty_label.options['text'])

    def test_successful_retry_clears_error_for_empty_and_nonempty_directories(self):
        self.fail_read(PermissionError('access denied'))
        self.app.navigate(str(self.path))
        self.assertIn('暂无', self.app.browser_empty_label.options['text'])
        self.assertEqual(self.app.browser_empty_label.options['style'], 'Empty.TLabel')
        self.assertNotIn('异常', self.app.filter_summary_var.set.call_args.args[0])
        self.fail_read(PermissionError('access denied'))
        (self.path / 'file.txt').write_text('data')
        self.app.navigate(str(self.path))
        self.assertFalse(self.app.browser_empty_label.visible)
        self.assertEqual(len(self.app.file_items), 1)


if __name__ == '__main__':
    unittest.main()
