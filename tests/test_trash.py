import json
import queue
import unittest
from unittest.mock import Mock, patch
from test_scanner import scanner, make_app


class TrashTests(unittest.TestCase):
    def test_selection_filters_parent_row_and_preserves_multiple_paths(self):
        app = make_app()
        table = Mock()
        table.selection.return_value = ('up', 'a', 'b')
        values = {'up': ('..', '—', '上级目录', '上一级', '/parent'),
                  'a': ('a', '1B', '文件', '', '/folder/a'),
                  'b': ('b', '1B', '文件夹', '', '/folder/b')}
        table.item.side_effect = lambda row, key: values[row]
        self.assertEqual(app._selected_trash_paths(table, 4), ['/folder/a', '/folder/b'])

    def test_normalization_keeps_symlink_path_and_excludes_root(self):
        self.assertEqual(scanner.normalize_trash_paths(['/', '/tmp/a', '/tmp/a', '/tmp/../tmp/link']), ['/tmp/a', '/tmp/link'])

    def test_cancel_confirmation_does_not_start_deletion(self):
        app = make_app(); app._deleting = False; app.root = Mock()
        with patch.object(scanner.messagebox, 'askyesno', return_value=False), patch.object(scanner.threading, 'Thread') as thread:
            app.delete_paths(['/tmp/example'])
        thread.assert_not_called()
        self.assertFalse(app._deleting)

    def test_worker_waits_for_readers_and_preserves_partial_failures(self):
        app = make_app(); app.trash_result_q = queue.Queue()
        app.size_req_q = Mock(); app._scan_thread = Mock()
        results = [{'path': '/tmp/a', 'trashed': True}, {'path': '/tmp/b', 'trashed': False, 'error': 'Permission denied'}]
        with patch.object(scanner, 'trash_items', return_value=results):
            app._trash_worker(['/tmp/a', '/tmp/b'])
        app.size_req_q.join.assert_called_once_with()
        app._scan_thread.join.assert_called_once_with()
        self.assertEqual(app.trash_result_q.get_nowait(), results)

    def test_native_adapter_passes_paths_as_json_not_shell_commands(self):
        paths = ['/tmp/中文 \'test\'\n$(literal)', '/tmp/folder']
        results = [{'path': p, 'trashed': False, 'error': 'missing'} for p in paths]
        with patch.object(scanner.subprocess, 'run', return_value=Mock(stdout=json.dumps(results))) as run:
            self.assertEqual(scanner.trash_items(paths), results)
        self.assertEqual(json.loads(run.call_args.kwargs['input']), paths)
        self.assertIsInstance(run.call_args.args[0], list)
        self.assertFalse(run.call_args.kwargs.get('shell', False))

    def test_right_click_keeps_group_and_deletes_selected_paths_in_both_lists(self):
        for method, attribute, values in (
            ('on_flist_rmb', 'flist', {'a': ('a', '1B', '文件', '', '/tmp/a'), 'b': ('b', '2B', '文件夹', '', '/tmp/b')}),
            ('on_res_rmb', 'res', {'a': (1, '1B', '/tmp/a'), 'b': (2, '2B', '/tmp/b')})):
            with self.subTest(method=method):
                app = make_app(); app._ctx_menu = Mock(); app.delete_paths = Mock()
                table = Mock(); table.selection.return_value = ('a', 'b'); table.identify_row.return_value = 'a'
                table.item.side_effect = lambda row, key: values[row]
                setattr(app, attribute, table)
                getattr(app, method)(Mock(x_root=1, y_root=1, y=1))
                table.selection_set.assert_not_called()
                actions = [c.kwargs for c in app._ctx_menu.add_command.call_args_list if c.kwargs['label'].startswith('删除')]
                self.assertEqual(len(actions), 1)
                actions[0]['command']()
                app.delete_paths.assert_called_once_with(['/tmp/a', '/tmp/b'])

    def test_parent_navigation_row_has_disabled_delete(self):
        app = make_app(); app._ctx_menu = Mock(); app.flist = Mock()
        app.flist.identify_row.return_value = 'up'; app.flist.selection.return_value = ('up',)
        app.flist.item.return_value = ('..', '—', '上级目录', '上一级', '/tmp')
        app.on_flist_rmb(Mock(x_root=1, y_root=1, y=1))
        action = [c.kwargs for c in app._ctx_menu.add_command.call_args_list if c.kwargs['label'].startswith('删除')][0]
        self.assertEqual(action['state'], 'disabled')

    def test_success_refreshes_views_but_keeps_failed_items(self):
        app = make_app(); app._deleting = True; app.current_path = '/tmp'; app.root = Mock()
        app.dir_size_cache = {'/tmp': 123}; app.file_operation_status = Mock(); app.scan_status = Mock()
        app.refresh_disk = Mock(); app.navigate = Mock(); app.tree = Mock(); app.tree.get_children.return_value = ()
        rows = {'a': [1, '1B', '/tmp/a'], 'b': [2, '2B', '/tmp/b']}
        app.res = Mock()
        app.res.get_children.side_effect = lambda: list(rows)
        app.res.item.side_effect = lambda row, key: rows[row]
        app.res.delete.side_effect = lambda row: rows.pop(row)
        with patch.object(scanner.messagebox, 'showwarning') as warning:
            app._handle_trash_result([{'path': '/tmp/a', 'trashed': True}, {'path': '/tmp/b', 'trashed': False, 'error': 'denied'}])
        self.assertEqual(list(rows), ['b'])
        self.assertEqual(app.dir_size_cache, {})
        self.assertFalse(app._deleting)
        app.res.set.assert_called_once_with('b', 'rank', 1)
        app.navigate.assert_called_once_with('/tmp')
        warning.assert_called_once()

    def test_late_scan_messages_cannot_reinsert_deleted_files(self):
        app = make_app(); app._scanning = True; app._deleting = True
        app.current_path = '/tmp'; app.root = Mock(); app.navigate = Mock(); app.file_operation_status = Mock()
        app.scan_result_q.put(('done', 1, [(1, '/tmp/a')], '/tmp', False))
        def finish(message):
            self.assertTrue(message[4])
            app._scanning = False
        app._handle_scan_msg = Mock(side_effect=finish)
        with patch.object(scanner.messagebox, 'showwarning'):
            app._handle_trash_result([{'path': '/tmp/a', 'trashed': False, 'error': 'denied'}])
        self.assertTrue(app.scan_result_q.empty())
        self.assertFalse(app._scanning)
        app._handle_scan_msg.assert_called_once()

    def test_failure_in_helper_reports_all_items(self):
        with patch.object(scanner.subprocess, 'run', side_effect=OSError('helper failed')):
            results = scanner.trash_items(['/tmp/a', '/tmp/b'])
        self.assertEqual([r['path'] for r in results], ['/tmp/a', '/tmp/b'])
        self.assertTrue(all(not r['trashed'] and r['error'] for r in results))


if __name__ == '__main__':
    unittest.main()
