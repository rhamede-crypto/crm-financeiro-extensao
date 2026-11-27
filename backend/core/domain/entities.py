from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID

from .value_objects import MoneyDecimal


@dataclass(frozen=True, slots=True)
class UserIdentity:
    id: UUID
    name: str
    email: str


@dataclass(frozen=True, slots=True)
class CompanyScope:
    id: UUID
    name: str
    segment: str = ""
    tax_regime: str = ""
    initial_balance: MoneyDecimal = MoneyDecimal.from_value("0.00")


@dataclass(frozen=True, slots=True)
class HealthDependencyStatus:
    name: str
    ok: bool
    detail: str = ""


@dataclass(frozen=True, slots=True)
class HealthCheckResult:
    ok: bool
    dependencies: tuple[HealthDependencyStatus, ...]
