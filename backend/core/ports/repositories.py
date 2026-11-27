from __future__ import annotations

from typing import Protocol
from uuid import UUID

from core.domain.entities import CompanyScope, HealthDependencyStatus


class HealthProbePort(Protocol):
    def check(self) -> HealthDependencyStatus:
        ...


class CompanyScopeRepositoryPort(Protocol):
    def get_company_for_user(self, user_id: UUID) -> CompanyScope | None:
        ...
