import os
import plistlib
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import patch

import app_storage as storage
from app_storage.presentation import usage_values


class AppStorageTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.apps = self.root / 'Applications'
        self.apps.mkdir()
        self.home = self.root / 'home'
        self.home.mkdir()
        self.system = self.root / 'Library'
        self.system.mkdir()

    def app(self, name='Editor', bundle_id='com.example.editor', groups=()):
        path = self.apps / (name + '.app')
        (path / 'Contents').mkdir(parents=True, exist_ok=True)
        (path / 'Contents/Info.plist').write_bytes(plistlib.dumps({
            'CFBundleIdentifier': bundle_id, 'CFBundleDisplayName': name,
            'CFBundlePackageType': 'APPL'}))
        return storage.Application(str(path), name, bundle_id, groups)

    def data(self, suffix, content=b'data'):
        path = self.home / 'Library' / suffix
        path.mkdir(parents=True)
        (path / 'data').write_bytes(content)
        return str(path)

    def test_discovery_deduplicates_paths_and_ignores_nested_helpers_and_stale_index(self):
        app = self.app()
        helper = Path(app.path) / 'Contents/Helpers/Helper.app/Contents'
        helper.mkdir(parents=True)
        (helper / 'Info.plist').write_bytes(plistlib.dumps({'CFBundleIdentifier': 'helper'}))
        (self.apps / 'Alias.app').symlink_to(app.path)
        apps, warnings = storage.discover_applications(
            [str(self.apps)], [app.path, str(helper.parent), str(self.apps / 'Gone.app')])
        self.assertEqual([a.path for a in apps], [app.path])
        self.assertEqual(apps[0].bundle_id, 'com.example.editor')
        self.assertEqual(warnings, [])

    def test_broken_metadata_still_lists_application_without_guessing_identifier(self):
        app = self.app()
        (Path(app.path) / 'Contents/Info.plist').write_bytes(b'broken')
        apps, _ = storage.discover_applications([str(self.apps)])
        self.assertEqual(len(apps), 1)
        self.assertEqual(apps[0].bundle_id, '')
        self.assertTrue(apps[0].warning)

    def test_exact_identifiers_and_groups_are_confirmed_names_are_only_suspected(self):
        app = self.app(groups=('TEAM.shared.editor',))
        exact = self.data('Application Support/com.example.editor')
        cache = self.data('Caches/com.example.editor')
        group = self.data('Group Containers/TEAM.shared.editor')
        guessed = self.data('Application Support/Vendor/Editor')
        self.data('Application Support/EditorBackup')
        mapping, warnings = storage.associate_data([app], str(self.home), str(self.system))
        paths = {p.path: p.confidence for p in mapping[app.path]}
        self.assertEqual(paths, {exact: 'confirmed', cache: 'confirmed', group: 'confirmed', guessed: 'suspected'})
        self.assertFalse(warnings)

    def test_shared_data_is_not_included_in_either_application_total(self):
        first = self.app('One', 'com.example.one', ('TEAM.shared',))
        second = self.app('Two', 'com.example.two', ('TEAM.shared',))
        shared = self.data('Group Containers/TEAM.shared')
        mapping, _ = storage.associate_data([first, second], str(self.home), str(self.system))
        location = mapping[first.path][0]
        self.assertEqual(location.confidence, 'shared')
        self.assertEqual(set(location.owners), {first.path, second.path})
        usage = storage.ApplicationUsage(first, mapping[first.path], {
            first.path: storage.Measurement(100), shared: storage.Measurement(80)})
        self.assertEqual(usage.external_bytes, 0)
        self.assertEqual(usage.total_bytes, 100)
        self.assertEqual(usage.shared_bytes, 80)

    def test_name_collision_does_not_upgrade_another_apps_data_to_shared(self):
        first = self.app('Same', 'com.example.one')
        second = self.app('Other', 'com.example.two')
        # 第二个应用的显示名恰好等于第一个应用的标识。
        second = storage.Application(second.path, first.bundle_id, second.bundle_id)
        path = self.data('Caches/com.example.one')
        mapping, _ = storage.associate_data([first, second], str(self.home), str(self.system))
        self.assertEqual(mapping[first.path][0].confidence, 'confirmed')
        self.assertEqual(mapping[first.path][0].path, path)
        self.assertEqual(mapping[second.path][0].confidence, 'suspected')

    def test_parent_child_locations_are_not_counted_twice(self):
        app = self.app()
        parent = self.data('Application Support/com.example.editor')
        child = self.data('Application Support/com.example.editor/com.example.editor')
        mapping, _ = storage.associate_data([app], str(self.home), str(self.system))
        self.assertEqual([p.path for p in mapping[app.path]], [parent])
        self.assertNotIn(child, [p.path for p in mapping[app.path]])

    def test_duplicate_app_copies_keep_separate_packages_but_share_external_data(self):
        first = self.app()
        second = self.app('Editor Copy')
        self.data('Containers/com.example.editor')
        mapping, _ = storage.associate_data([first, second], str(self.home), str(self.system))
        self.assertEqual(mapping[first.path][0].confidence, 'shared')

    def test_allocated_size_ignores_symlinks_and_deduplicates_hard_links(self):
        path = self.root / 'files'
        path.mkdir()
        original = path / 'file'
        original.write_bytes(b'x' * 9000)
        os.link(original, path / 'hardlink')
        (path / 'loop').symlink_to(path)
        outside = self.root / 'outside'
        outside.write_bytes(b'y' * 100000)
        (path / 'outside').symlink_to(outside)
        result = storage.measure_path(str(path), threading.Event())
        self.assertEqual(result.size, original.stat().st_blocks * 512)
        self.assertFalse(result.errors)

    def test_permission_failure_keeps_unknown_size_instead_of_zero(self):
        app = self.app()
        with patch('app_storage.measurement.os.scandir', side_effect=PermissionError('denied')):
            measurement = storage.measure_path(app.path, threading.Event())
        self.assertIsNone(measurement.size)
        self.assertTrue(measurement.errors)
        usage = storage.ApplicationUsage(app, (), {app.path: measurement})
        self.assertIsNone(usage.total_bytes)
        self.assertTrue(usage.partial)

    def test_unmeasured_and_suspected_data_are_not_presented_as_known_total(self):
        app = self.app()
        guessed = storage.RelatedPath('/guess', '资源与数据', 'suspected', '名称匹配', (app.path,))
        initial = storage.ApplicationUsage(app, (guessed,), {})
        self.assertIsNone(initial.total_bytes)
        complete = storage.ApplicationUsage(app, (guessed,), {
            app.path: storage.Measurement(100), '/guess': storage.Measurement(500)})
        self.assertEqual(complete.total_bytes, 100)
        self.assertEqual(complete.suspected_bytes, 500)

    def test_cancel_interrupts_discovery_and_size_walk(self):
        cancel = threading.Event()
        cancel.set()
        with self.assertRaises(storage.ScanCancelled):
            storage.discover_applications([str(self.apps)], cancel=cancel)
        with self.assertRaises(storage.ScanCancelled):
            storage.measure_path(str(self.apps), cancel)

    def test_scan_emits_applications_before_sizes_and_finishes_with_results(self):
        app = self.app()
        self.data('Caches/com.example.editor')
        events = []
        with patch('app_storage.service.read_app_groups', return_value=((), '')):
            storage.scan_applications(threading.Event(), lambda *event: events.append(event),
                                      roots=[str(self.apps)], indexed_paths=[],
                                      home=str(self.home), system_library=str(self.system))
        self.assertEqual(events[0][0], 'apps')
        self.assertEqual(events[-1], ('done', False))
        final = [event[1] for event in events if event[0] == 'usage'][-1]
        self.assertEqual(final.app.path, app.path)
        self.assertIsNotNone(final.total_bytes)
        self.assertGreater(final.external_bytes, 0)
        self.assertFalse(final.pending)

    def test_external_permission_failure_is_displayed_as_unreadable_not_pending_or_zero(self):
        app = self.app()
        location = storage.RelatedPath('/data', '沙盒数据', 'confirmed', '标识匹配', (app.path,))
        usage = storage.ApplicationUsage(app, (location,), {
            app.path: storage.Measurement(100), '/data': storage.Measurement(None, ('denied',))})
        row = usage_values(usage, lambda value: '%dB' % value)
        self.assertEqual(row[2], '无法读取')
        self.assertEqual(row[3], '—')
        self.assertIn('不完整', row[4])

    def test_partial_external_size_is_marked_as_lower_bound_in_both_totals(self):
        app = self.app()
        location = storage.RelatedPath('/data', '沙盒数据', 'confirmed', '标识匹配', (app.path,))
        usage = storage.ApplicationUsage(app, (location,), {
            app.path: storage.Measurement(100), '/data': storage.Measurement(50, ('child denied',))})
        row = usage_values(usage, lambda value: '%dB' % value)
        self.assertEqual(row[2:4], ('≥ 50B', '≥ 150B'))

    def test_cancelled_unmeasured_application_does_not_display_zero(self):
        app = self.app()
        row = usage_values(storage.ApplicationUsage(app, (), {}), str, stopped=True)
        self.assertEqual(row[1:4], ('未完成', '待识别', '—'))
        self.assertIn('已取消', row[4])

    def test_malformed_xml_metadata_does_not_hide_other_applications(self):
        broken = self.app('Broken')
        good = self.app('Good', 'com.example.good')
        (Path(broken.path) / 'Contents/Info.plist').write_bytes(b'<?xml version="1.0"?><plist><dict></plist>')
        apps, _ = storage.discover_applications([str(self.apps)])
        self.assertEqual({a.path for a in apps}, {broken.path, good.path})
        self.assertTrue(next(a for a in apps if a.path == broken.path).warning)

    def test_symlink_aliases_merge_confirmed_owners_before_computing_shared_data(self):
        first = self.app('One', 'com.example.one')
        second = self.app('Two', 'com.example.two')
        path = self.data('Caches/com.example.one')
        (Path(path).parent / 'com.example.two').symlink_to(path)
        mapping, _ = storage.associate_data([first, second], str(self.home), str(self.system))
        for app in (first, second):
            self.assertEqual(mapping[app.path][0].confidence, 'shared')
            self.assertEqual(set(mapping[app.path][0].owners), {first.path, second.path})

    def test_enumeration_denied_marks_external_scope_unknown_in_final_usage(self):
        self.app()
        self.data('Caches/com.example.editor')
        original = os.scandir
        denied = str(self.home / 'Library/Caches')
        def scandir(path):
            if path == denied:
                raise PermissionError('denied')
            return original(path)
        events = []
        with patch('app_storage.association.os.scandir', side_effect=scandir), patch('app_storage.service.read_app_groups', return_value=((), '')):
            storage.scan_applications(threading.Event(), lambda *event: events.append(event),
                                      roots=[str(self.apps)], indexed_paths=[],
                                      home=str(self.home), system_library=str(self.system))
        final = [value for kind, value in events if kind == 'usage'][-1]
        row = usage_values(final, lambda value: '%dB' % value)
        self.assertIsNone(final.external_bytes)
        self.assertEqual(row[2:4], ('范围受限', '—'))
        self.assertIn('不完整', row[4])

    def test_overlapping_directories_of_different_apps_are_not_both_exclusive(self):
        first = self.app('One', 'com.example.one')
        second = self.app('Two', 'com.example.two')
        self.data('Application Support/com.example.one/com.example.two')
        mapping, _ = storage.associate_data([first, second], str(self.home), str(self.system))
        for app in (first, second):
            self.assertEqual(mapping[app.path][0].confidence, 'shared')
            self.assertEqual(set(mapping[app.path][0].owners), {first.path, second.path})


if __name__ == '__main__':
    unittest.main()
