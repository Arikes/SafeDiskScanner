"""Cancellable allocated-size measurement with link handling and read-error reporting."""
import os
import stat

from .common import _check
from .models import Measurement


def measure_path(path, cancel):
    """Allocated file blocks; don't chase internal links or double-count hardlinks."""
    size, seen, errors = 0, set(), []
    stack = [path]
    root_readable = False
    while stack:
        _check(cancel)
        current = stack.pop()
        try:
            info = os.lstat(current)
            if stat.S_ISLNK(info.st_mode):
                continue
            if stat.S_ISDIR(info.st_mode):
                with os.scandir(current) as entries:
                    if current == path:
                        root_readable = True
                    for entry in entries:
                        _check(cancel)
                        stack.append(entry.path)
            elif stat.S_ISREG(info.st_mode):
                inode = (info.st_dev, info.st_ino)
                if inode not in seen:
                    seen.add(inode)
                    size += getattr(info, 'st_blocks', (info.st_size + 511) // 512) * 512
                if current == path:
                    root_readable = True
        except OSError as exc:
            if len(errors) < 20:
                errors.append('%s：%s' % (current, exc))
    return Measurement(size if root_readable else None, tuple(errors))
