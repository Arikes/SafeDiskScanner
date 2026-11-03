"""Shared cancellation and path-component validation for storage scans."""


class ScanCancelled(Exception):
    pass


def _check(cancel):
    if cancel is not None and cancel.is_set():
        raise ScanCancelled()


def _component(value):
    return isinstance(value, str) and value not in ('', '.', '..') and '/' not in value and '\x00' not in value
