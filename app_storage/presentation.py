"""Format storage snapshots for display without importing Tk or accessing files."""


def measurement_text(measurement, format_size, stopped=False):
    if measurement is None:
        return '未完成' if stopped else '待统计'
    if measurement.size is None:
        return '无法读取'
    return ('≥ ' if measurement.errors else '') + format_size(measurement.size)


def usage_values(usage, format_size, stopped=False):
    state = '已取消' if usage.pending and stopped else '统计中' if usage.pending else '已完成'
    if usage.partial:
        state += ' · 不完整'
    for confidence, label in (('shared', '共享'), ('suspected', '疑似')):
        if any(p.confidence == confidence for p in usage.locations):
            state += ' · ' + label
    confirmed = [usage.measurements.get(p.path) for p in usage.locations if p.confidence == 'confirmed']
    incomplete_external = bool(usage.scope_warnings) or any(value is not None and value.errors for value in confirmed)
    if usage.package is None and not usage.locations:
        external = '待识别'
    elif usage.external_bytes is not None:
        external = ('≥ ' if incomplete_external else '') + format_size(usage.external_bytes)
    elif any(value is None for value in confirmed):
        external = '未完成' if stopped else '待统计'
    elif usage.scope_warnings:
        external = '范围受限'
    else:
        external = '无法读取'
    total = usage.total_bytes
    incomplete_total = incomplete_external or (usage.package is not None and bool(usage.package.errors))
    return (usage.app.name, measurement_text(usage.package, format_size, stopped), external,
            ('≥ ' if incomplete_total else '') + format_size(total) if total is not None else '—', state)
