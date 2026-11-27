from __future__ import annotations

from datetime import date
from decimal import Decimal

from core.ports.ai import AIResponse
from core.services.cashflow import CashflowEntry, ConfirmedPromise, project_cashflow
from core.services.timeline import extract_promise_suggestion


def test_extract_promise_suggestion_parses_brl_and_dates():
    suggestion_br = extract_promise_suggestion(
        "Cliente prometeu pagar R$ 2.500,50 em 25/04/2026 via PIX.",
        reference_date=date(2026, 4, 10),
    )
    assert suggestion_br is not None
    assert suggestion_br.amount == Decimal("2500.50")
    assert suggestion_br.promise_date == date(2026, 4, 25)
    assert suggestion_br.to_dict()["amount"] == "2500.50"
    assert suggestion_br.to_dict()["date"] == "2026-04-25"

    suggestion_iso = extract_promise_suggestion(
        "Acordo confirmado para 2026-04-28 no valor de R$ 1200.",
        reference_date=date(2026, 4, 10),
    )
    assert suggestion_iso is not None
    assert suggestion_iso.amount == Decimal("1200.00")
    assert suggestion_iso.promise_date == date(2026, 4, 28)

    plain_note = extract_promise_suggestion(
        "Retornamos ligação solicitando comprovante.",
        reference_date=date(2026, 4, 10),
    )
    assert plain_note is None

    invalid_negative = extract_promise_suggestion(
        "Estorno previsto de -500,00 em 2026-04-28.",
        reference_date=date(2026, 4, 10),
    )
    assert invalid_negative is None


def test_extract_promise_suggestion_uses_ai_refinement_with_validation():
    class StubAI:
        def generate(self, request):
            return AIResponse(
                content=(
                    '{"title": "Pagamento boleto abril", '
                    '"amount": "900.00", "date": "2026-04-22"}'
                ),
                provider="stub",
            )

    refined = extract_promise_suggestion(
        "Prometeu pagar R$ 850,00 em 20/04/2026",
        reference_date=date(2026, 4, 10),
        ai_port=StubAI(),
    )
    assert refined is not None
    assert refined.title == "Pagamento boleto abril"
    assert refined.amount == Decimal("900.00")
    assert refined.promise_date == date(2026, 4, 22)

    class BadAI:
        def generate(self, request):
            return AIResponse(content='{"amount": "-10", "date": "bad"}', provider="stub")

    fallback = extract_promise_suggestion(
        "Prometeu pagar R$ 850,00 em 20/04/2026",
        reference_date=date(2026, 4, 10),
        ai_port=BadAI(),
    )
    assert fallback is not None
    assert fallback.amount == Decimal("850.00")
    assert fallback.promise_date == date(2026, 4, 20)


def test_project_cashflow_integrates_promises_without_double_counting():
    ref = date(2026, 4, 10)
    # 1. Overdue receivable does not enter future daily_deltas until promised
    overdue = CashflowEntry(
        entry_type="receivable",
        entry_date=date(2026, 3, 25),
        due_date=date(2026, 3, 30),
        amount=Decimal("1000.00"),
        paid_amount=Decimal("0.00"),
        normalized_description="fatura vencida",
        normalized_party="cliente alfa",
        settled=False,
    )
    without_promise = project_cashflow(
        initial_balance=Decimal("500.00"),
        entries=[overdue],
        reference_date=ref,
    )
    assert without_promise.starting_balance == Decimal("500.00")
    assert without_promise.projections[0]["amount"] == "500.00"
    assert without_promise.confirmed_promises_total == Decimal("0.00")

    promise = ConfirmedPromise(
        normalized_party="cliente alfa",
        promise_date=date(2026, 4, 20),
        amount=Decimal("1000.00"),
        created_date=ref,
    )
    with_promise = project_cashflow(
        initial_balance=Decimal("500.00"),
        entries=[overdue],
        reference_date=ref,
        promises=[promise],
    )
    # Starting balance (realized cash) remains untouched; future projection increases by promise.
    assert with_promise.starting_balance == Decimal("500.00")
    assert with_promise.projections[0]["amount"] == "1500.00"
    assert with_promise.confirmed_promises_total == Decimal("1000.00")

    # 2. Future open receivable rescheduled by earlier promise: no double counting
    future_open = CashflowEntry(
        entry_type="receivable",
        entry_date=date(2026, 4, 10),
        due_date=date(2026, 4, 28),
        amount=Decimal("1000.00"),
        paid_amount=Decimal("0.00"),
        normalized_description="fatura futura",
        normalized_party="cliente beta",
        settled=False,
    )
    rescheduled = project_cashflow(
        initial_balance=Decimal("0.00"),
        entries=[future_open],
        reference_date=ref,
        promises=[
            ConfirmedPromise(
                normalized_party="cliente beta",
                promise_date=date(2026, 4, 18),
                amount=Decimal("1000.00"),
                created_date=ref,
            )
        ],
    )
    assert rescheduled.projections[0]["amount"] == "1000.00"

    # 3. Subsequent settled payment eliminates promise forecast cleanly
    settled_after = CashflowEntry(
        entry_type="receivable",
        entry_date=date(2026, 4, 12),
        due_date=date(2026, 4, 12),
        amount=Decimal("1000.00"),
        paid_amount=Decimal("1000.00"),
        normalized_description="baixa pix",
        normalized_party="cliente alfa",
        settled=True,
    )
    after_settlement = project_cashflow(
        initial_balance=Decimal("500.00"),
        entries=[settled_after],
        reference_date=ref,
        promises=[promise],
    )
    assert after_settlement.projections[0]["amount"] == "1500.00"
    assert after_settlement.confirmed_promises_total == Decimal("0.00")
