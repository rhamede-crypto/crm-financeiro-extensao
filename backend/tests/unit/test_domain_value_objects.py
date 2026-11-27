from __future__ import annotations

from decimal import Decimal

import pytest

from core.domain.entities import HealthDependencyStatus
from core.domain.exceptions import ValidationDomainError
from core.domain.value_objects import CivilDate, ImportStatus, MoneyDecimal
from core.prompts.registry import PromptRegistry
from core.services.health import HealthService
from core.services.tenancy import sanitize_tenant_relative_path


def test_money_decimal_serializes_with_two_places_and_rejects_floats() -> None:
    amount = MoneyDecimal.from_value("8450.5")
    assert amount.amount == Decimal("8450.50")
    assert amount.to_string() == "8450.50"

    total = amount + MoneyDecimal.from_value("100.25")
    assert total.to_string() == "8550.75"

    with pytest.raises(ValidationDomainError):
        MoneyDecimal.from_value(10.5)  # type: ignore[arg-type]


def test_civil_date_validates_iso_format() -> None:
    parsed = CivilDate.from_iso("2026-10-30")
    assert parsed.to_iso() == "2026-10-30"

    with pytest.raises(ValidationDomainError):
        CivilDate.from_iso("30/10/2026")


def test_import_status_matches_contract_states() -> None:
    assert [state.value for state in ImportStatus] == [
        "queued",
        "processing",
        "review",
        "completed",
        "failed",
        "canceled",
    ]


def test_prompt_registry_renders_and_truncates_by_core_limits() -> None:
    template = PromptRegistry.get("promise_extraction")
    rendered = template.render(note_text="Pagar R$ 500,00 em 2027-01-21. " * 300)
    assert len(rendered) <= template.limits.max_input_chars


def test_health_service_aggregates_probes_without_django() -> None:
    class OkProbe:
        def check(self) -> HealthDependencyStatus:
            return HealthDependencyStatus(name="database", ok=True)

    class FailProbe:
        def check(self) -> HealthDependencyStatus:
            return HealthDependencyStatus(name="broker", ok=False, detail="unavailable")

    assert HealthService([OkProbe()]).check().ok is True
    degraded = HealthService([OkProbe(), FailProbe()]).check()
    assert degraded.ok is False
    assert len(degraded.dependencies) == 2


def test_sanitize_tenant_relative_path_blocks_traversal() -> None:
    assert sanitize_tenant_relative_path("imports/planilha.csv") == "imports/planilha.csv"
    with pytest.raises(ValidationDomainError):
        sanitize_tenant_relative_path("../segredo.csv")
    with pytest.raises(ValidationDomainError):
        sanitize_tenant_relative_path("/etc/passwd")
