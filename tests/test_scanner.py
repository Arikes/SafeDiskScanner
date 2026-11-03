import importlib.util
import pathlib
import queue
import tempfile
import threading
import unittest
from unittest.mock import Mock, patch

SOURCE = pathlib.Path(__file__).resolve().parents[1] / '大文件扫描器.py'
spec = importlib.util.spec_from_file_location('scanner', SOURCE)
scanner = importlib.util.module_from_spec(spec)
spec.loader.exec_module(scanner)


def make_app():
    app = object.__new__(scanner.ScannerApp)
    app.dir_size_cache = {}
    app.dir_size_pending = set()
    app.size_req_q = queue.Queue()
    app.size_res_q = queue.Queue()
    app.scan_result_q = queue.Queue()
    app.scan_cancel = threading.Event()
    app.scan_limit = 2
    app._scanning = False
    app._deleting = False
    app._scan_thread = None
    app.trash_result_q = queue.Queue()
    app._size_cancel = threading.Event()
    app.file_items = []
    app._file_item_indexes = {}
    app._file_order = []
    app._size_sort_dirty = False
    app.size_sort_descending = True
    app.sort_column = 'size'
    app.mtime_sort_descending = True
    app._file_mtimes = {}
    app.excluded_file_types = set()
    app._type_filter_popup = None
    app.filter_summary_var = Mock()
    return app


class ScannerTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = pathlib.Path(self.tmp.name)
        for name, size in [('a', 10), ('b', 200), ('c', 100), ('.hidden', 500)]:
            (self.root / name).write_bytes(b'x' * size)
        self.app = make_app()

    def done(self):
        msgs = []
        while not self.app.scan_result_q.empty():
            msgs.append(self.app.scan_result_q.get_nowait())
        return msgs[-1]

    def test_browser_scan_selects_scan_tab_before_starting(self):
        calls = []
        self.app.notebook = Mock()
        self.app.scan_tab = object()
        self.app.notebook.select.side_effect = lambda tab: calls.append(('tab', tab))
        self.app.scope_var = Mock()
        self.app.scope_var.set.side_effect = lambda path: calls.append(('path', path))
        self.app._scanning = False
        self.app.start_scan = lambda: calls.append(('start', None))
        self.app.start_scan_for(str(self.root))
        self.assertEqual(calls, [('tab', self.app.scan_tab), ('path', str(self.root)), ('start', None)])

    def test_existing_scan_keeps_its_scope_when_browser_requests_another(self):
        self.app.notebook = Mock()
        self.app.scan_tab = object()
        self.app.scope_var = Mock()
        self.app._scanning = True
        self.app.start_scan = Mock()
        self.app.start_scan_for('/another-directory')
        self.app.notebook.select.assert_called_once_with(self.app.scan_tab)
        self.app.scope_var.set.assert_not_called()
        self.app.start_scan.assert_called_once_with()

    def test_size_result_updates_its_row_without_walking_all_rows(self):
        updates = []
        class Table:
            def get_children(self):
                raise AssertionError('size updates must not scan every displayed row')
            def set(self, *args):
                updates.append(args)
        self.app.flist = Table()
        self.app._file_row_ids = {'/directory': 'row-id'}
        self.app._update_row_size('/directory', 1024)
        self.app._update_row_size('/old-directory', 1024)
        self.assertEqual(updates, [('row-id', 'size', '1.0KB')])

    def test_equal_size_cutoff_keeps_original_walk_order(self):
        scope = self.root / 'scope'; scope.mkdir()
        for name in ('z', 'a'):
            sub = scope / name; sub.mkdir()
            (sub / 'data').write_bytes(b'x' * 20)
        with scanner.os.scandir(scope) as entries:
            first = next(entries).path
        self.app.scan_limit = 1
        self.app._scan_worker(str(scope), True)
        self.assertEqual(self.done()[2], [(20, str(pathlib.Path(first) / 'data'))])

    def test_ranking_and_hidden_files(self):
        self.app._scan_worker(str(self.root), False)
        result = self.done()
        self.assertEqual(result[1], 3)
        self.assertEqual([v[0] for v in result[2]], [200, 100])
        self.app._scan_worker(str(self.root), True)
        self.assertEqual([v[0] for v in self.done()[2]], [500, 200])

    def test_does_not_walk_hidden_directories_unless_enabled(self):
        nested = self.root / '.cache'
        nested.mkdir()
        (nested / 'large').write_bytes(b'x' * 900)
        self.app._scan_worker(str(self.root), False)
        self.assertEqual(self.done()[1], 3)
        self.app._scan_worker(str(self.root), True)
        self.assertEqual(self.done()[1], 5)

    def test_cancel_checked_within_flat_directory(self):
        original = scanner.heapq.heappush
        def cancel_after_first(heap, value):
            original(heap, value)
            self.app.scan_cancel.set()
        with patch.object(scanner.heapq, 'heappush', side_effect=cancel_after_first):
            self.app._scan_worker(str(self.root), True)
        self.assertTrue(self.done()[4], 'cancellation must be observed before completing a flat directory')

    def test_directory_size_ignores_symlinks_and_reuses_cache(self):
        sub = self.root / 'sub'
        sub.mkdir()
        (sub / 'data').write_bytes(b'x' * 70)
        (self.root / 'link').symlink_to(sub, target_is_directory=True)
        self.assertEqual(self.app._compute_dir_size(str(self.root)), 880)
        with patch.object(scanner.os, 'scandir', side_effect=AssertionError('cached result should not walk')):
            self.assertEqual(self.app._compute_dir_size(str(sub)), 70)

    def test_cancelled_size_does_not_cache_partial_root(self):
        cancel = threading.Event()
        cancel.set()
        self.assertIsNone(self.app._compute_dir_size(str(self.root), cancel))
        self.assertNotIn(str(self.root), self.app.dir_size_cache)

    def test_rapid_navigation_discards_old_jobs(self):
        old = self.app._size_cancel
        self.app.size_req_q.put(('old', old))
        self.app.dir_size_pending.add('old')
        self.app._reset_size_requests()
        self.assertTrue(old.is_set())
        self.assertFalse(self.app._size_cancel.is_set())
        self.assertTrue(self.app.size_req_q.empty())
        self.assertFalse(self.app.dir_size_pending)

    def test_cancelled_job_never_publishes_partial_size(self):
        cancel = threading.Event()
        original = scanner.os.scandir
        app = self.app
        def interrupted(path):
            cancel.set()
            return original(path)
        with patch.object(scanner.os, 'scandir', side_effect=interrupted):
            self.assertIsNone(app._compute_dir_size(str(self.root), cancel))
        self.assertNotIn(str(self.root), app.dir_size_cache)
        self.assertEqual(app._compute_dir_size(str(self.root)), 810)

    def test_permission_error_is_skipped_and_not_cached_as_complete(self):
        with patch.object(scanner.os, 'scandir', side_effect=PermissionError):
            self.assertEqual(self.app._compute_dir_size(str(self.root)), 0)
            self.app._scan_worker(str(self.root), True)
        self.assertNotIn(str(self.root), self.app.dir_size_cache)
        result = self.done()
        self.assertEqual(result[1:3], (0, []))

    def test_slow_directory_does_not_block_other_directory_results(self):
        # Two real workers consume the production queue loop. Hold the first
        # directory before its I/O; the second result must arrive independently.
        slow_entered = threading.Event()
        release = threading.Event()
        original = self.app._compute_dir_size
        slow = str(self.root / 'slow')
        fast = str(self.root / 'fast')
        pathlib.Path(slow).mkdir(); pathlib.Path(fast).mkdir()
        (pathlib.Path(fast) / 'data').write_bytes(b'x' * 123)
        def compute(path, cancel=None):
            if path == slow:
                slow_entered.set()
                release.wait(3)
            return original(path, cancel)
        self.app._compute_dir_size = compute
        cancel = self.app._size_cancel
        self.app.size_req_q.put((slow, cancel))
        self.app.size_req_q.put((fast, cancel))
        workers = [threading.Thread(target=self.app._size_worker_loop, daemon=True) for _ in range(2)]
        try:
            for worker in workers:
                worker.start()
            self.assertTrue(slow_entered.wait(2))
            path, size, generation = self.app.size_res_q.get(timeout=2)
            self.assertEqual((path, size), (fast, 123))
            self.assertIs(generation, cancel)
        finally:
            release.set()
            self.app.size_req_q.join()

    def test_follow_file_symlink_but_not_directory_symlink_in_scan(self):
        (self.root / 'alias').symlink_to(self.root / 'b')
        sub = self.root / 'sub'; sub.mkdir()
        (sub / 'data').write_bytes(b'x' * 30)
        (self.root / 'aliasdir').symlink_to(sub, target_is_directory=True)
        self.app._scan_worker(str(self.root), False)
        result = self.done()
        self.assertEqual(result[1], 5)
        self.assertEqual([v[0] for v in result[2]], [200, 200])


if __name__ == '__main__':
    unittest.main()
