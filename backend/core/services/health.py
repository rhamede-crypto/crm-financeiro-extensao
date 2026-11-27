from __future__ import annotations

from collections.abc import Sequence

from core.domain.entities import HealthCheckResult
from core.ports.repositories import HealthProbePort


class HealthService:
    """Evaluates technical dependencies through injected health probes."""

    def __init__(self, probes: Sequence[HealthProbePort]) -> None:
        self._probes = tuple(probes)

    def check(self) -> HealthCheckResult:
        statuses = tuple(probe.check() for probe in self._probes)
        return HealthCheckResult(
            ok=all(status.ok for status in statuses),
            dependencies=statuses,
        )
