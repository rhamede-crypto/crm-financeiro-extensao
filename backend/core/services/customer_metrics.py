from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import ROUND_HALF_UP, Decimal
from typing import Any

TWO_PLACES = Decimal("0.01")


@dataclass(frozen=True, slots=True)
class CustomerEntryInput:
    entry_id: str
    entry_date: date
    due_date: date | None
    amount: Decimal
    paid_amount: Decimal
    description: str
    settled: bool


def compute_customer_profile(
    *,
    entries: list[CustomerEntryInput],
    reference_date: date,
) -> dict[str, Any]:
    """Deterministically computes LTV, average ticket, overdue evidence, and customer score."""
    if not entries:
        return {
            "metrics": {
                "ltv": "0.00",
                "average": None,
                "score": "Sem histórico",
                "openBalance": "0.00",
                "overdueCount": 0,
                "evidence": {
                    "paidEntriesCount": 0,
                    "lateEntriesCount": 0,
                    "maxOverdueDays": 0,
                    "missingDueDateCount": 0,
                    "averageDenominator": "paid_or_partial_entries",
                },
            },
            "invoices": [],
            "history": [],
        }

    ltv = Decimal("0.00")
    paid_count = 0
    open_balance = Decimal("0.00")
    overdue_count = 0
    overdue_open = Decimal("0.00")
    max_overdue_days = 0
    late_count = 0
    dated_count = 0
    missing_due_count = 0

    invoices: list[dict[str, Any]] = []
    history: list[dict[str, Any]] = []

    for entry in entries:
        total = abs(entry.amount).quantize(TWO_PLACES, rounding=ROUND_HALF_UP)
        paid = (
            total
            if entry.settled
            else min(total, max(Decimal("0.00"), entry.paid_amount)).quantize(
                TWO_PLACES, rounding=ROUND_HALF_UP
            )
        )
        open_amt = (total - paid).quantize(TWO_PLACES, rounding=ROUND_HALF_UP)

        if entry.due_date is None:
            missing_due_count += 1
        else:
            dated_count += 1

        if paid > Decimal("0.00"):
            ltv += paid
            paid_count += 1
            history.append(
                {
                    "id": entry.entry_id,
                    "date": entry.entry_date.isoformat(),
                    "label": entry.description,
                    "amount": f"{paid:.2f}",
                    "partial": not entry.settled,
                }
            )
            if entry.settled and entry.due_date is not None and entry.entry_date > entry.due_date:
                late_count += 1

        if not entry.settled and open_amt > Decimal("0.00"):
            open_balance += open_amt
            invoices.append(
                {
                    "id": entry.entry_id,
                    "label": entry.description,
                    "amount": f"{open_amt:.2f}",
                    "originalAmount": f"{total:.2f}",
                    "paidAmount": f"{paid:.2f}",
                    "due": entry.due_date.isoformat() if entry.due_date else None,
                }
            )
            if entry.due_date is not None and entry.due_date < reference_date:
                days_late = (reference_date - entry.due_date).days
                overdue_count += 1
                overdue_open += open_amt
                max_overdue_days = max(max_overdue_days, days_late)
                late_count += 1

    average_str = (
        f"{(ltv / paid_count).quantize(TWO_PLACES, rounding=ROUND_HALF_UP):.2f}"
        if paid_count > 0
        else None
    )

    if max_overdue_days >= 30 or overdue_count >= 2 or (overdue_count >= 1 and overdue_open > ltv):
        score = "Crítico"
    elif (
        overdue_count >= 1
        or late_count >= 2
        or (dated_count > 0 and (late_count / dated_count) >= 0.25)
    ):
        score = "Atraso Recorrente"
    else:
        score = "Bom Pagador"

    invoices.sort(key=lambda inv: (inv["due"] or "9999-12-31", inv["label"]))
    history.sort(key=lambda item: item["date"], reverse=True)

    return {
        "metrics": {
            "ltv": f"{ltv:.2f}",
            "average": average_str,
            "score": score,
            "openBalance": f"{open_balance:.2f}",
            "overdueCount": overdue_count,
            "evidence": {
                "paidEntriesCount": paid_count,
                "lateEntriesCount": late_count,
                "maxOverdueDays": max_overdue_days,
                "missingDueDateCount": missing_due_count,
                "averageDenominator": "paid_or_partial_entries",
            },
        },
        "invoices": invoices,
        "history": history,
    }
