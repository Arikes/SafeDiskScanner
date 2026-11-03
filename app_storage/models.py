"""Application, directory and measurement snapshots; no filesystem or UI work."""
from dataclasses import dataclass


@dataclass(frozen=True)
class Application:
    path: str
    name: str
    bundle_id: str
    groups: tuple = ()
    warning: str = ''


@dataclass(frozen=True)
class RelatedPath:
    path: str
    category: str
    confidence: str
    reason: str
    owners: tuple


@dataclass(frozen=True)
class Measurement:
    size: int | None
    errors: tuple = ()


@dataclass(frozen=True)
class ApplicationUsage:
    app: Application
    locations: tuple
    measurements: dict
    scope_warnings: tuple = ()

    @property
    def package(self):
        return self.measurements.get(self.app.path)

    def _sum(self, confidence):
        values = [self.measurements.get(p.path) for p in self.locations if p.confidence == confidence]
        if any(value is None or value.size is None for value in values):
            return None
        return sum(value.size for value in values)

    @property
    def external_bytes(self):
        value = self._sum('confirmed')
        return None if value == 0 and self.scope_warnings else value

    @property
    def shared_bytes(self):
        return self._sum('shared')

    @property
    def suspected_bytes(self):
        return self._sum('suspected')

    @property
    def total_bytes(self):
        if self.package is None or self.package.size is None or self.external_bytes is None:
            return None
        return self.package.size + self.external_bytes

    @property
    def pending(self):
        return any(path not in self.measurements for path in
                   (self.app.path, *(p.path for p in self.locations)))

    @property
    def partial(self):
        return bool(self.app.warning or self.scope_warnings or any(value.errors for value in self.measurements.values()))
