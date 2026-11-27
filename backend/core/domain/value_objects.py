from __future__ import annotations

import unicodedata
from dataclasses import dataclass
from datetime import date
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from enum import StrEnum

from .exceptions import ValidationDomainError

TWO_PLACES = Decimal("0.01")


@dataclass(frozen=True, slots=True)
class MoneyDecimal:
    """Deterministic decimal money representation serialized as fixed 2-decimal text."""

    amount: Decimal

    def __post_init__(self) -> None:
        if not isinstance(self.amount, Decimal) or not self.amount.is_finite():
            raise ValidationDomainError(
                "Valor monetário inválido.",
                fields={"amount": ["Informe um número decimal válido."]},
            )
        quantized = self.amount.quantize(TWO_PLACES, rounding=ROUND_HALF_UP)
        object.__setattr__(self, "amount", quantized)

    @classmethod
    def from_value(cls, raw: str | int | Decimal) -> MoneyDecimal:
        if isinstance(raw, MoneyDecimal):
            return raw
        if isinstance(raw, float):
            raise ValidationDomainError(
                "Valor monetário não deve usar ponto flutuante.",
                fields={"amount": ["Envie o valor em texto decimal, como '8450.00'."]},
            )
        text = str(raw).strip()
        if not text:
            raise ValidationDomainError(
                "Valor monetário obrigatório.",
                fields={"amount": ["Informe um valor monetário."]},
            )
        try:
            return cls(Decimal(text))
        except InvalidOperation as exc:
            raise ValidationDomainError(
                "Valor monetário inválido.",
                fields={"amount": ["Formato decimal inválido."]},
            ) from exc

    def to_string(self) -> str:
        return f"{self.amount:.2f}"

    def __add__(self, other: MoneyDecimal) -> MoneyDecimal:
        return MoneyDecimal(self.amount + other.amount)

    def __sub__(self, other: MoneyDecimal) -> MoneyDecimal:
        return MoneyDecimal(self.amount - other.amount)


@dataclass(frozen=True, slots=True)
class CivilDate:
    """Strict calendar date serialized as YYYY-MM-DD."""

    value: date

    @classmethod
    def from_iso(cls, raw: str | date) -> CivilDate:
        if isinstance(raw, CivilDate):
            return raw
        if isinstance(raw, date):
            return cls(raw)
        text = str(raw).strip()
        try:
            parsed = date.fromisoformat(text)
        except ValueError as exc:
            raise ValidationDomainError(
                "Data civil inválida.",
                fields={"date": ["Use o formato AAAA-MM-DD."]},
            ) from exc
        if len(text) != 10:
            raise ValidationDomainError(
                "Data civil inválida.",
                fields={"date": ["Use o formato AAAA-MM-DD."]},
            )
        return cls(parsed)

    def to_iso(self) -> str:
        return self.value.isoformat()


class ImportStatus(StrEnum):
    QUEUED = "queued"
    PROCESSING = "processing"
    REVIEW = "review"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELED = "canceled"


class ImportType(StrEnum):
    RECEIVABLE = "receivable"
    PAYABLE = "payable"
    SETTLED = "settled"


class Weekday(StrEnum):
    MONDAY = "monday"
    TUESDAY = "tuesday"
    WEDNESDAY = "wednesday"
    THURSDAY = "thursday"
    FRIDAY = "friday"
    SATURDAY = "saturday"
    SUNDAY = "sunday"


def normalize_ascii_text(value: str | None) -> str:
    text = str(value or "").strip()
    decomposed = unicodedata.normalize("NFD", text)
    without_marks = "".join(ch for ch in decomposed if unicodedata.category(ch) != "Mn")
    return " ".join(without_marks.lower().split())


class CompanySegment(StrEnum):
    BAR = "bar"
    RESTAURANTE = "restaurante"
    CLINICA = "clinica"
    COMERCIO_LOCAL = "comercio_local"

    @classmethod
    def parse(cls, raw: str | None, *, default: CompanySegment | None = None) -> CompanySegment:
        normalized = normalize_ascii_text(raw).replace("-", "_").replace(" ", "_")
        aliases = {
            "bar": cls.BAR,
            "restaurante": cls.RESTAURANTE,
            "clinica": cls.CLINICA,
            "comercio": cls.COMERCIO_LOCAL,
            "comercio_local": cls.COMERCIO_LOCAL,
        }
        if not normalized:
            if default is not None:
                return default
            raise ValidationDomainError(
                "Informe o segmento da empresa.",
                fields={"segment": ["Selecione bar, restaurante, clínica ou comércio local."]},
            )
        if normalized not in aliases:
            raise ValidationDomainError(
                "Segmento inválido.",
                fields={"segment": ["Use bar, restaurante, clínica ou comércio local."]},
            )
        return aliases[normalized]


class TaxRegime(StrEnum):
    SIMPLES_NACIONAL = "simples_nacional"
    MEI = "mei"
    LUCRO_PRESUMIDO = "lucro_presumido"

    @classmethod
    def parse(cls, raw: str | None, *, default: TaxRegime | None = None) -> TaxRegime:
        normalized = normalize_ascii_text(raw).replace("-", "_").replace(" ", "_")
        aliases = {
            "simples": cls.SIMPLES_NACIONAL,
            "simples_nacional": cls.SIMPLES_NACIONAL,
            "mei": cls.MEI,
            "lucro_presumido": cls.LUCRO_PRESUMIDO,
        }
        if not normalized:
            if default is not None:
                return default
            raise ValidationDomainError(
                "Informe o regime tributário.",
                fields={"taxRegime": ["Use simples_nacional, mei ou lucro_presumido."]},
            )
        if normalized not in aliases:
            raise ValidationDomainError(
                "Regime tributário inválido.",
                fields={"taxRegime": ["Use simples_nacional, mei ou lucro_presumido."]},
            )
        return aliases[normalized]
