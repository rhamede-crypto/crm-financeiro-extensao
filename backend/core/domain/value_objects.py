from __future__ import annotations

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
