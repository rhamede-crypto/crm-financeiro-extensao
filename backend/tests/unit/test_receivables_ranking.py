from __future__ import annotations

from datetime import date
from decimal import Decimal

from core.services.receivables import OverdueReceivableInput, rank_top_overdue_customers


def test_ranking_handles_partial_payments_settled_exclusion_ties_and_top5_cap() -> None:
    ref = date(2026, 10, 30)
    items = [
        # Settled -> excluded
        OverdueReceivableInput(
            party_name="Quitado SA",
            normalized_party="quitado sa",
            due_date=date(2026, 10, 1),
            amount=Decimal("5000.00"),
            paid_amount=Decimal("5000.00"),
            settled=True,
        ),
        # Partial payment: 1000 - 300 = 700 open
        OverdueReceivableInput(
            party_name="Cliente Parcial",
            normalized_party="cliente parcial",
            due_date=date(2026, 10, 10),
            amount=Decimal("1000.00"),
            paid_amount=Decimal("300.00"),
            settled=False,
        ),
        # Tie at 500.00: recent due date (Oct 25) must win over older due date (Oct 05)
        OverdueReceivableInput(
            party_name="Empate Antigo",
            normalized_party="empate antigo",
            due_date=date(2026, 10, 5),
            amount=Decimal("500.00"),
            paid_amount=Decimal("0.00"),
            settled=False,
        ),
        OverdueReceivableInput(
            party_name="Empate Recente",
            normalized_party="empate recente",
            due_date=date(2026, 10, 25),
            amount=Decimal("500.00"),
            paid_amount=Decimal("0.00"),
            settled=False,
        ),
        OverdueReceivableInput(
            party_name="Cliente D",
            normalized_party="cliente d",
            due_date=date(2026, 10, 12),
            amount=Decimal("400.00"),
            paid_amount=Decimal("0.00"),
            settled=False,
        ),
        OverdueReceivableInput(
            party_name="Cliente E",
            normalized_party="cliente e",
            due_date=date(2026, 10, 14),
            amount=Decimal("300.00"),
            paid_amount=Decimal("0.00"),
            settled=False,
        ),
        OverdueReceivableInput(
            party_name="Cliente F",
            normalized_party="cliente f",
            due_date=date(2026, 10, 16),
            amount=Decimal("100.00"),
            paid_amount=Decimal("0.00"),
            settled=False,
        ),
    ]

    ranked = rank_top_overdue_customers(
        items=items,
        reference_date=ref,
        min_30d_balance=Decimal("-1000.00"),
    )
    assert len(ranked) == 5
    assert [r["name"] for r in ranked] == [
        "Cliente Parcial",
        "Empate Recente",
        "Empate Antigo",
        "Cliente D",
        "Cliente E",
    ]
    assert ranked[0]["amount"] == "700.00"
    assert ranked[0]["impactPct"] == 70.0
    assert ranked[0]["days"] == 20


def test_ranking_with_less_than_5_clients_and_no_deficit() -> None:
    ref = date(2026, 10, 30)
    ranked = rank_top_overdue_customers(
        items=[
            OverdueReceivableInput(
                party_name="Mercado Horizonte",
                normalized_party="mercado horizonte",
                due_date=date(2026, 10, 20),
                amount=Decimal("800.00"),
                paid_amount=Decimal("0.00"),
                settled=False,
            ),
            OverdueReceivableInput(
                party_name="Padaria Sul",
                normalized_party="padaria sul",
                due_date=date(2026, 10, 15),
                amount=Decimal("200.00"),
                paid_amount=Decimal("0.00"),
                settled=False,
            ),
        ],
        reference_date=ref,
        min_30d_balance=Decimal("1500.00"),
    )
    assert len(ranked) == 2
    assert ranked[0]["impactPct"] == 80.0
    assert ranked[1]["impactPct"] == 20.0
