"""Discover application bundles and read their macOS identity metadata."""
import os
import plistlib
import subprocess
from xml.parsers.expat import ExpatError

from .common import _check, _component
from .models import Application


def discover_applications(roots, indexed_paths=(), cancel=None):
    """Enumerate .app packages, stopping at package boundaries and symlink dirs."""
    _check(cancel)
    found, warnings, visited = set(), [], set()
    stack = [os.path.abspath(path) for path in roots]
    while stack:
        _check(cancel)
        path = stack.pop()
        if path.lower().endswith('.app') and os.path.isdir(path):
            found.add(os.path.realpath(path))
            continue
        real = os.path.realpath(path)
        if real in visited:
            continue
        visited.add(real)
        try:
            with os.scandir(path) as entries:
                for entry in entries:
                    _check(cancel)
                    if entry.name.lower().endswith('.app') and entry.is_dir():
                        found.add(os.path.realpath(entry.path))
                    elif entry.is_dir(follow_symlinks=False):
                        stack.append(entry.path)
        except FileNotFoundError:
            continue
        except OSError as exc:
            warnings.append('%s：%s' % (path, exc))
    for path in indexed_paths:
        _check(cancel)
        if path.lower().endswith('.app') and os.path.isdir(path):
            found.add(os.path.realpath(path))
    applications = []
    for path in sorted(found):
        _check(cancel)
        # A nested helper belongs to its outer application's package size.
        if any(part.lower().endswith('.app') for part in path.split(os.sep)[:-1]):
            continue
        if '.Trash' in path.split(os.sep) or '.Trashes' in path.split(os.sep):
            continue
        name, bundle_id, warning = os.path.basename(path)[:-4], '', ''
        try:
            with open(os.path.join(path, 'Contents', 'Info.plist'), 'rb') as stream:
                info = plistlib.load(stream)
            if not isinstance(info, dict):
                raise ValueError('应用信息格式异常')
            for key in ('CFBundleDisplayName', 'CFBundleName'):
                if isinstance(info.get(key), str) and info[key].strip():
                    name = info[key]
                    break
            value = info.get('CFBundleIdentifier')
            if _component(value):
                bundle_id = value
            else:
                warning = '缺少有效应用标识，外部数据识别受限'
        except (OSError, ValueError, plistlib.InvalidFileException, ExpatError, TypeError, OverflowError) as exc:
            warning = '无法读取应用信息：%s' % exc
        applications.append(Application(path, name, bundle_id, warning=warning))
    return sorted(applications, key=lambda app: (app.name.casefold(), app.path)), warnings


def spotlight_applications():
    try:
        result = subprocess.run(['/usr/bin/mdfind', '-0', 'kMDItemContentType == "com.apple.application-bundle"'],
                                capture_output=True, timeout=8, check=True)
        return [os.fsdecode(path) for path in result.stdout.split(b'\x00') if path], ''
    except (OSError, subprocess.SubprocessError) as exc:
        return [], '系统索引不可用，仅列举常见安装目录：%s' % exc


def read_app_groups(path):
    """Read signed entitlements; never execute an installed app."""
    try:
        result = subprocess.run(['/usr/bin/codesign', '-d', '--entitlements', ':-', path],
                                capture_output=True, timeout=3)
        if result.returncode:
            return (), '无法读取签名，App Group 识别受限'
        if not result.stdout.strip():
            return (), ''
        info = plistlib.loads(result.stdout)
        if not isinstance(info, dict):
            raise ValueError('签名权限格式异常')
        groups = info.get('com.apple.security.application-groups', [])
        if not isinstance(groups, list):
            raise ValueError('App Group 格式异常')
        return tuple(value for value in groups if _component(value)), ''
    except (OSError, ValueError, plistlib.InvalidFileException, ExpatError, subprocess.SubprocessError, TypeError, OverflowError) as exc:
        return (), 'App Group 识别失败：%s' % exc
