from __future__ import annotations

from datetime import date
from decimal import Decimal

from core.services.cashflow import CashflowEntry, project_cashflow


def _entry(
    entry_type: str,
    entry_date: date,
    amount: str,
    *,
    due_date: date | None = None,
    desc: str = "Lancamento",
    party: str = "Contato",
    settled: bool = False,
) -> CashflowEntry:
    return CashflowEntry(
        entry_type=entry_type,
        entry_date=entry_date,
        due_date=due_date,
        amount=Decimal(amount),
        paid_amount=Decimal(amount) if settled else Decimal("0.00"),
        normalized_description=desc.lower(),
        normalized_party=party.lower(),
        settled=settled,
    )


def test_empty_company_returns_empty_projections() -> None:
    res = project_cashflow(
        initial_balance=Decimal("0.00"),
        entries=[],
        reference_date=date(2026, 10, 15),
    )
    assert res.projections == []
    assert res.negative_date is None
    assert res.negative_before_month_end is False


def test_negative_initial_balance_and_month_end_alert() -> None:
    res = project_cashflow(
        initial_balance=Decimal("-200.00"),
        entries=[],
        reference_date=date(2026, 10, 15),
    )
    assert res.negative_date == "2026-10-15"
    assert res.negative_before_month_end is True
    assert res.month_end_alert is True
    assert res.projections == [
        {"days": 30, "amount": "-200.00"},
        {"days": 60, "amount": "-200.00"},
        {"days": 90, "amount": "-200.00"},
    ]


def test_month_rollover_recurrence_and_no_double_counting() -> None:
    entries = [
        _entry(
            "payable",
            date(2026, 1, 31),
            "1000.00",
            desc="Aluguel",
            party="Imobiliaria",
            settled=True,
        ),
        _entry(
            "payable",
            date(2025, 12, 31),
            "1000.00",
            desc="Aluguel",
            party="Imobiliaria",
            settled=True,
        ),
        # Open entry already exists for March 2026 -> should NOT be projected twice!
        _entry(
            "payable",
            date(2026, 2, 10),
            "1000.00",
            due_date=date(2026, 3, 25),
            desc="Aluguel",
            party="Imobiliaria",
            settled=False,
        ),
    ]
    res = project_cashflow(
        initial_balance=Decimal("4500.00"),
        entries=entries,
        reference_date=date(2026, 2, 15),
    )
    # Realized: 4500 - 1000 - 1000 = 2500
    # Feb 2026 recurrence clamped to 2026-02-28 (-1000 -> 1500)
    # Mar 2026 uses explicit open due 2026-03-25 (-1000 -> 500, NOT double-counted)
    # Apr 2026 recurrence on 2026-04-30 (-1000 -> -500)
    assert res.projections[0] == {"days": 30, "amount": "1500.00"}
    assert res.projections[1] == {"days": 60, "amount": "500.00"}
    assert res.projections[2] == {"days": 90, "amount": "-500.00"}
    assert res.negative_date == "2026-04-30"
    assert res.negative_before_month_end is False


def test_settling_receivable_moves_amount_into_realized_without_duplication() -> None:
    open_res = project_cashflow(
        initial_balance=Decimal("100.00"),
        entries=[
            _entry(
                "receivable",
                date(2026, 10, 1),
                "500.00",
                due_date=date(2026, 10, 20),
                settled=False,
            )
        ],
        reference_date=date(2026, 10, 10),
    )
    settled_res = project_cashflow(
        initial_balance=Decimal("100.00"),
        entries=[
            _entry(
                "receivable",
                date(2026, 10, 1),
                "500.00",
                due_date=date(2026, 10, 20),
                settled=True,
            )
        ],
        reference_date=date(2026, 10, 10),
    )
    assert open_res.projections[0]["amount"] == "600.00"
    assert settled_res.projections[0]["amount"] == "600.00"
