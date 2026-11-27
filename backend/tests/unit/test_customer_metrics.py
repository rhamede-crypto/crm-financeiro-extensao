from __future__ import annotations

from datetime import date
from decimal import Decimal

from core.services.customer_metrics import CustomerEntryInput, compute_customer_profile


def test_customer_profile_scores_partial_payments_and_missing_due_dates() -> None:
    ref = date(2026, 10, 30)

    assert compute_customer_profile(entries=[], reference_date=ref)["metrics"]["score"] == (
        "Sem histórico"
    )

    good = compute_customer_profile(
        entries=[
            CustomerEntryInput(
                "1", date(2026, 10, 1), None, Decimal("300.00"), Decimal("300.00"), "Sem venc", True
            ),
            CustomerEntryInput(
                "2",
                date(2026, 10, 10),
                date(2026, 10, 15),
                Decimal("500.00"),
                Decimal("500.00"),
                "Em dia",
                True,
            ),
        ],
        reference_date=ref,
    )
    assert good["metrics"]["score"] == "Bom Pagador"
    assert good["metrics"]["ltv"] == "800.00"
    assert good["metrics"]["average"] == "400.00"
    assert good["metrics"]["evidence"]["missingDueDateCount"] == 1

    recurring = compute_customer_profile(
        entries=[
            CustomerEntryInput(
                "1",
                date(2026, 9, 1),
                date(2026, 9, 10),
                Decimal("1000.00"),
                Decimal("1000.00"),
                "Pago",
                True,
            ),
            CustomerEntryInput(
                "2",
                date(2026, 10, 1),
                date(2026, 10, 20),
                Decimal("500.00"),
                Decimal("200.00"),
                "Parcial",
                False,
            ),
        ],
        reference_date=ref,
    )
    assert recurring["metrics"]["score"] == "Atraso Recorrente"
    assert recurring["metrics"]["ltv"] == "1200.00"
    assert recurring["metrics"]["average"] == "600.00"
    assert recurring["metrics"]["openBalance"] == "300.00"
    assert recurring["invoices"][0]["amount"] == "300.00"

    critical = compute_customer_profile(
        entries=[
            CustomerEntryInput(
                "1",
                date(2026, 8, 1),
                date(2026, 9, 1),
                Decimal("900.00"),
                Decimal("0.00"),
                "Antiga",
                False,
            ),
        ],
        reference_date=ref,
    )
    assert critical["metrics"]["score"] == "Crítico"
    assert critical["metrics"]["evidence"]["maxOverdueDays"] >= 30
