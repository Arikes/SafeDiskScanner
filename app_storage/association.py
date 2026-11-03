"""Associate standard Library locations with apps, preserving confidence and sharing."""
from dataclasses import replace
import os
import plistlib
import re
from xml.parsers.expat import ExpatError

from .common import _check, _component
from .models import RelatedPath


def _data_candidates(home, system_library, cancel):
    candidates, warnings = [], []
    categories = (('Application Support', '资源与数据'), ('Caches', '缓存'), ('Logs', '日志'),
                  ('Preferences', '配置'), ('Saved Application State', '窗口状态'),
                  ('HTTPStorages', '网络数据'), ('WebKit', '网页数据'),
                  ('Containers', '沙盒数据'), ('Group Containers', '共享容器'))
    for library in (os.path.join(home, 'Library'), system_library):
        for directory, category in categories:
            _check(cancel)
            root = os.path.join(library, directory)
            try:
                with os.scandir(root) as entries:
                    children = sorted(entries, key=lambda e: e.name)
            except FileNotFoundError:
                continue
            except OSError as exc:
                warnings.append('%s：%s' % (root, exc))
                continue
            for entry in children:
                _check(cancel)
                key = entry.name
                if directory == 'Preferences' and key.endswith('.plist'):
                    key = key[:-6]
                elif directory == 'Saved Application State' and key.endswith('.savedState'):
                    key = key[:-11]
                if directory == 'Containers' and re.fullmatch(r'[0-9A-Fa-f-]{36}', key):
                    try:
                        with open(os.path.join(entry.path, '.com.apple.containermanagerd.metadata.plist'), 'rb') as stream:
                            metadata = plistlib.load(stream)
                        identifier = metadata.get('MCMMetadataIdentifier') if isinstance(metadata, dict) else None
                        if _component(identifier):
                            key = identifier
                    except (OSError, ValueError, plistlib.InvalidFileException, ExpatError, TypeError, OverflowError) as exc:
                        warnings.append('%s：容器标识读取失败：%s' % (entry.path, exc))
                candidates.append((entry.path, key.casefold(), directory, category))
                # Common vendor/app layout, e.g. Application Support/Google/Chrome.
                if directory == 'Application Support':
                    try:
                        if not entry.is_dir(follow_symlinks=False):
                            continue
                        with os.scandir(entry.path) as nested:
                            for child in nested:
                                _check(cancel)
                                candidates.append((child.path, child.name.casefold(), directory, category))
                    except OSError as exc:
                        warnings.append('%s：%s' % (entry.path, exc))
    return candidates, warnings


def associate_data(apps, home, system_library, cancel=None):
    candidates, warnings = _data_candidates(home, system_library, cancel)
    mapping = {app.path: [] for app in apps}
    identifiers, groups, names = {}, {}, {}
    for app in apps:
        if app.bundle_id:
            identifiers.setdefault(app.bundle_id.casefold(), set()).add(app.path)
        for group in app.groups:
            groups.setdefault(group.casefold(), set()).add(app.path)
        for name in (app.name, os.path.basename(app.path)[:-4]):
            if _component(name):
                names.setdefault(name.casefold(), set()).add(app.path)
    matches = {}
    for source, key, directory, category in candidates:
        _check(cancel)
        path = os.path.realpath(source)
        if any(path == app.path or path.startswith(app.path + os.sep) for app in apps):
            continue
        owners = groups.get(key, set()) if directory == 'Group Containers' else identifiers.get(key, set())
        guesses = names.get(key, set()) if directory not in ('Containers', 'Group Containers') else set()
        for owner in owners | guesses:
            confidence = ('shared' if len(owners) > 1 else 'confirmed') if owner in owners else 'suspected'
            reason = ('App Group 标识匹配' if directory == 'Group Containers' else '应用标识匹配') if owner in owners else '仅名称匹配，归属待确认'
            location = RelatedPath(path, category, confidence, reason,
                                   tuple(sorted(owners)) if owner in owners else (owner,))
            previous = matches.get((owner, path))
            if previous is None or previous.confidence == 'suspected':
                matches[owner, path] = location
    real_owners = {}
    for (owner, path), location in matches.items():
        if location.confidence != 'suspected':
            real_owners.setdefault(path, set()).add(owner)
    # Nested directories owned by different apps also overlap physically.
    # Share the same owner set for an entire overlapping subtree.
    for path in sorted(real_owners, key=lambda p: p.count(os.sep)):
        parent = os.path.dirname(path)
        while parent != os.path.dirname(parent):
            if parent in real_owners:
                real_owners[parent].update(real_owners[path])
                real_owners[path] = real_owners[parent]
                break
            parent = os.path.dirname(parent)
    for (owner, path), location in matches.items():
        if location.confidence != 'suspected':
            owners = tuple(sorted(real_owners[path]))
            location = replace(location, owners=owners,
                               confidence='shared' if len(owners) > 1 else 'confirmed')
        mapping[owner].append(location)
    for owner, paths in mapping.items():
        kept = []
        for location in sorted(paths, key=lambda p: (p.path.count(os.sep), p.path)):
            if not any(location.path.startswith(parent.path + os.sep) and
                       (parent.confidence != 'suspected' or location.confidence == 'suspected') for parent in kept):
                kept.append(location)
        mapping[owner] = tuple(kept)
    return mapping, warnings
