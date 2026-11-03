"""Coordinate background application scans and publish snapshots through callbacks."""
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import replace
import os

from .association import associate_data
from .common import ScanCancelled, _check
from .discovery import discover_applications, spotlight_applications, read_app_groups
from .measurement import measure_path
from .models import ApplicationUsage


def scan_applications(cancel, emit, roots=None, indexed_paths=None, home=None, system_library=None):
    """Emit apps, immutable usage snapshots, warnings, then done(cancelled)."""
    home = home or os.path.expanduser('~')
    roots = roots if roots is not None else ['/Applications', os.path.join(home, 'Applications'),
            '/System/Applications', '/System/Library/CoreServices',
            '/System/Cryptexes/App/System/Applications']
    system_library = system_library or '/Library'
    cancelled = False
    try:
        apps, warnings = discover_applications(roots, cancel=cancel)
        emit('apps', tuple(apps))
        if indexed_paths is None:
            indexed_paths, warning = spotlight_applications()
            if warning:
                warnings.append(warning)
        _check(cancel)
        if indexed_paths:
            apps, extra_warnings = discover_applications([app.path for app in apps], indexed_paths, cancel)
            warnings.extend(extra_warnings)
            emit('apps', tuple(apps))
        emit('progress', '正在识别应用标识和外部数据目录…')
        enriched = []
        with ThreadPoolExecutor(max_workers=2) as pool:
            futures = {pool.submit(read_app_groups, app.path): app for app in apps}
            try:
                for future in as_completed(futures):
                    _check(cancel)
                    app = futures[future]
                    group_ids, warning = future.result()
                    enriched.append(replace(app, groups=group_ids, warning='；'.join(filter(None, (app.warning, warning)))))
            finally:
                for future in futures:
                    future.cancel()
        apps = enriched
        mapping, extra_warnings = associate_data(apps, home, system_library, cancel)
        warnings.extend(extra_warnings)
        if warnings:
            emit('warnings', tuple(warnings))
        consumers, measured = {}, {}
        by_path = {app.path: app for app in apps}
        scope_issues = {app.path: tuple(extra_warnings) + ((app.warning,) if app.warning else ()) for app in apps}
        for app in apps:
            emit('usage', ApplicationUsage(app, mapping[app.path], {}, scope_issues[app.path]))
            for path in (app.path, *(p.path for p in mapping[app.path])):
                consumers.setdefault(path, set()).add(app.path)
        emit('progress', '正在计算 App 包和已识别外部数据的大小…')
        with ThreadPoolExecutor(max_workers=2) as pool:
            futures = {pool.submit(measure_path, path, cancel): path for path in consumers}
            try:
                for future in as_completed(futures):
                    _check(cancel)
                    path = futures[future]
                    measured[path] = future.result()
                    for owner in consumers[path]:
                        locations = mapping[owner]
                        snapshot = {p: measured[p] for p in (owner, *(p.path for p in locations)) if p in measured}
                        emit('usage', ApplicationUsage(by_path[owner], locations, snapshot, scope_issues[owner]))
            finally:
                for future in futures:
                    future.cancel()
    except ScanCancelled:
        cancelled = True
    finally:
        emit('done', cancelled)
