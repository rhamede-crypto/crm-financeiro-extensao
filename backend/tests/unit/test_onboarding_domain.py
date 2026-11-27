from __future__ import annotations

import pytest

from core.domain.exceptions import ValidationDomainError
from core.domain.value_objects import CompanySegment, TaxRegime


def test_company_segment_accepts_canonical_and_accented_aliases() -> None:
    assert CompanySegment.parse("bar") == CompanySegment.BAR
    assert CompanySegment.parse("Restaurante") == CompanySegment.RESTAURANTE
    assert CompanySegment.parse("Clínica") == CompanySegment.CLINICA
    assert CompanySegment.parse("Comércio local") == CompanySegment.COMERCIO_LOCAL
    assert (
        CompanySegment.parse("", default=CompanySegment.COMERCIO_LOCAL)
        == CompanySegment.COMERCIO_LOCAL
    )

    with pytest.raises(ValidationDomainError):
        CompanySegment.parse("industria_pesada")


def test_tax_regime_accepts_simplified_regimes_and_rejects_unknown() -> None:
    assert TaxRegime.parse("simples_nacional") == TaxRegime.SIMPLES_NACIONAL
    assert TaxRegime.parse("MEI") == TaxRegime.MEI
    assert TaxRegime.parse("Lucro Presumido") == TaxRegime.LUCRO_PRESUMIDO
    assert TaxRegime.parse("", default=TaxRegime.SIMPLES_NACIONAL) == TaxRegime.SIMPLES_NACIONAL

    with pytest.raises(ValidationDomainError):
        TaxRegime.parse("regime_inexistente")
