from __future__ import annotations

import calendar
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date, timedelta
from decimal import ROUND_HALF_UP, Decimal
from statistics import median
from typing import Any

TWO_PLACES = Decimal("0.01")


@dataclass(frozen=True, slots=True)
class CashflowEntry:
    entry_type: str
    entry_date: date
    due_date: date | None
    amount: Decimal
    paid_amount: Decimal
    normalized_description: str
    normalized_party: str
    settled: bool


@dataclass(frozen=True, slots=True)
class ConfirmedPromise:
    normalized_party: str
    promise_date: date
    amount: Decimal
    created_date: date | None = None


@dataclass(frozen=True, slots=True)
class CashProjectionResult:
    reference_date: date
    starting_balance: Decimal
    projections: list[dict[str, Any]]
    negative_date: str | None
    negative_before_month_end: bool
    month_end_alert: bool
    daily_balances: list[tuple[date, Decimal]]
    confirmed_promises_total: Decimal = Decimal("0.00")


def _add_months(year: int, month: int, offset: int) -> tuple[int, int]:
    total = (year * 12 + (month - 1)) + offset
    return total // 12, (total % 12) + 1


def _clamp_day(year: int, month: int, day: int) -> date:
    last_day = calendar.monthrange(year, month)[1]
    return date(year, month, min(day, last_day))


def _entry_direction_and_total(entry: CashflowEntry) -> tuple[int, Decimal]:
    if entry.entry_type == "receivable":
        return 1, abs(entry.amount)
    if entry.entry_type == "payable":
        return -1, abs(entry.amount)
    # settled cashflow: signed amount
    if entry.amount < Decimal("0.00"):
        return -1, abs(entry.amount)
    return 1, abs(entry.amount)


def _apply_confirmed_promises(
    *,
    promises: Sequence[ConfirmedPromise],
    reference_date: date,
    end_date: date,
    daily_deltas: dict[date, Decimal],
    settled_inflows: dict[str, list[tuple[date, Decimal]]],
    overdue_receivables: dict[str, Decimal],
    future_receivables: dict[str, list[list[Any]]],
) -> Decimal:
    confirmed_promises_total = Decimal("0.00")
    sorted_promises = sorted(
        promises,
        key=lambda p: (p.created_date or date.min, p.promise_date, p.normalized_party),
    )
    for promise in sorted_promises:
        amt = promise.amount.quantize(TWO_PLACES, rounding=ROUND_HALF_UP)
        if amt <= Decimal("0.00"):
            continue
        if promise.promise_date < reference_date or promise.promise_date > end_date:
            continue

        party_key = promise.normalized_party
        effective = amt

        if party_key and party_key in settled_inflows:
            cutoff = promise.created_date or reference_date
            remaining_needed = effective
            for idx, (s_date, s_amt) in enumerate(settled_inflows[party_key]):
                if s_amt <= Decimal("0.00") or s_date < cutoff:
                    continue
                consumed = min(remaining_needed, s_amt)
                settled_inflows[party_key][idx] = (s_date, s_amt - consumed)
                remaining_needed -= consumed
                if remaining_needed <= Decimal("0.00"):
                    break
            effective = remaining_needed

        if effective <= Decimal("0.00"):
            continue

        if party_key:
            overdue_avail = overdue_receivables.get(party_key, Decimal("0.00"))
            covered_overdue = min(overdue_avail, effective)
            if covered_overdue > Decimal("0.00"):
                overdue_receivables[party_key] = overdue_avail - covered_overdue

            to_deduct_future = effective - covered_overdue
            if to_deduct_future > Decimal("0.00") and party_key in future_receivables:
                for item in sorted(future_receivables[party_key], key=lambda pair: pair[0]):
                    if item[1] <= Decimal("0.00"):
                        continue
                    deduct = min(to_deduct_future, item[1])
                    item[1] -= deduct
                    daily_deltas[item[0]] = daily_deltas.get(item[0], Decimal("0.00")) - deduct
                    to_deduct_future -= deduct
                    if to_deduct_future <= Decimal("0.00"):
                        break

        daily_deltas[promise.promise_date] = (
            daily_deltas.get(promise.promise_date, Decimal("0.00")) + effective
        )
        confirmed_promises_total += effective

    return confirmed_promises_total.quantize(TWO_PLACES, rounding=ROUND_HALF_UP)


def project_cashflow(
    *,
    initial_balance: Decimal,
    entries: list[CashflowEntry],
    reference_date: date,
    promises: Sequence[ConfirmedPromise] = (),
) -> CashProjectionResult:
    """Deterministically projects 30/60/90-day daily cash balances without double counting."""
    init = initial_balance.quantize(TWO_PLACES, rounding=ROUND_HALF_UP)
    if not entries and not promises and init == Decimal("0.00"):
        return CashProjectionResult(
            reference_date=reference_date,
            starting_balance=init,
            projections=[],
            negative_date=None,
            negative_before_month_end=False,
            month_end_alert=False,
            daily_balances=[],
            confirmed_promises_total=Decimal("0.00"),
        )

    end_date = reference_date + timedelta(days=90)
    starting_cash = init
    daily_deltas: dict[date, Decimal] = {}
    explicit_month_keys: set[tuple[int, str, str, int, int]] = set()
    historical_by_key: dict[tuple[int, str, str], list[tuple[date, Decimal]]] = {}
    settled_inflows: dict[str, list[tuple[date, Decimal]]] = {}
    overdue_receivables: dict[str, Decimal] = {}
    future_receivables: dict[str, list[list[Any]]] = {}

    for entry in entries:
        direction, total = _entry_direction_and_total(entry)
        signed_total = total * direction

        if entry.settled:
            if entry.entry_date <= reference_date:
                starting_cash += signed_total
            elif entry.entry_date <= end_date:
                daily_deltas[entry.entry_date] = (
                    daily_deltas.get(entry.entry_date, Decimal("0.00")) + signed_total
                )
            if direction == 1 and entry.normalized_party:
                settled_inflows.setdefault(entry.normalized_party, []).append(
                    (entry.entry_date, total)
                )
            explicit_month_keys.add(
                (
                    direction,
                    entry.normalized_description,
                    entry.normalized_party,
                    entry.entry_date.year,
                    entry.entry_date.month,
                )
            )
            if entry.entry_date <= reference_date:
                historical_by_key.setdefault(
                    (direction, entry.normalized_description, entry.normalized_party),
                    [],
                ).append((entry.entry_date, total))
            continue

        # Open item: partial payments already realized count in starting_cash
        paid = min(total, max(Decimal("0.00"), entry.paid_amount))
        if paid > Decimal("0.00"):
            starting_cash += paid * direction

        remaining = total - paid
        scheduled_date = entry.due_date or entry.entry_date
        if remaining > Decimal("0.00"):
            explicit_month_keys.add(
                (
                    direction,
                    entry.normalized_description,
                    entry.normalized_party,
                    scheduled_date.year,
                    scheduled_date.month,
                )
            )
            if reference_date < scheduled_date <= end_date:
                daily_deltas[scheduled_date] = (
                    daily_deltas.get(scheduled_date, Decimal("0.00")) + (remaining * direction)
                )
                if entry.entry_type == "receivable" and entry.normalized_party:
                    future_receivables.setdefault(entry.normalized_party, []).append(
                        [scheduled_date, remaining]
                    )
            elif scheduled_date == reference_date:
                daily_deltas[reference_date] = (
                    daily_deltas.get(reference_date, Decimal("0.00")) + (remaining * direction)
                )
                if entry.entry_type == "receivable" and entry.normalized_party:
                    future_receivables.setdefault(entry.normalized_party, []).append(
                        [reference_date, remaining]
                    )
            elif scheduled_date < reference_date and entry.entry_type == "receivable":
                if entry.normalized_party:
                    overdue_receivables[entry.normalized_party] = (
                        overdue_receivables.get(entry.normalized_party, Decimal("0.00"))
                        + remaining
                    )

    # Detect monthly recurrences (>= 2 consecutive past months) and project missing future months
    for (direction, norm_desc, norm_party), occurrences in historical_by_key.items():
        if not norm_desc:
            continue
        months_seen = sorted({(dt.year, dt.month) for dt, _ in occurrences})
        has_consecutive = any(
            (y2 * 12 + m2) - (y1 * 12 + m1) == 1
            for (y1, m1), (y2, m2) in zip(months_seen, months_seen[1:])
        )
        if not has_consecutive:
            continue

        typical_day = int(round(median(dt.day for dt, _ in occurrences)))
        typical_amount = Decimal(
            str(median(float(val) for _, val in occurrences))
        ).quantize(TWO_PLACES, rounding=ROUND_HALF_UP)

        for offset in range(0, 4):
            proj_year, proj_month = _add_months(reference_date.year, reference_date.month, offset)
            if (direction, norm_desc, norm_party, proj_year, proj_month) in explicit_month_keys:
                continue
            proj_date = _clamp_day(proj_year, proj_month, typical_day)
            if reference_date < proj_date <= end_date:
                daily_deltas[proj_date] = (
                    daily_deltas.get(proj_date, Decimal("0.00")) + (typical_amount * direction)
                )

    confirmed_promises_total = _apply_confirmed_promises(
        promises=promises,
        reference_date=reference_date,
        end_date=end_date,
        daily_deltas=daily_deltas,
        settled_inflows=settled_inflows,
        overdue_receivables=overdue_receivables,
        future_receivables=future_receivables,
    )

    running = starting_cash + daily_deltas.get(reference_date, Decimal("0.00"))
    daily_balances: list[tuple[date, Decimal]] = [(reference_date, running)]
    negative_date: date | None = reference_date if running < Decimal("0.00") else None

    for day_offset in range(1, 91):
        current_day = reference_date + timedelta(days=day_offset)
        running += daily_deltas.get(current_day, Decimal("0.00"))
        daily_balances.append((current_day, running))
        if negative_date is None and running < Decimal("0.00"):
            negative_date = current_day

    month_end = date(
        reference_date.year,
        reference_date.month,
        calendar.monthrange(reference_date.year, reference_date.month)[1],
    )
    negative_before_month_end = negative_date is not None and negative_date <= month_end

    projections = [
        {"days": window, "amount": f"{daily_balances[window][1]:.2f}"}
        for window in (30, 60, 90)
    ]

    return CashProjectionResult(
        reference_date=reference_date,
        starting_balance=starting_cash,
        projections=projections,
        negative_date=negative_date.isoformat() if negative_date else None,
        negative_before_month_end=negative_before_month_end,
        month_end_alert=negative_before_month_end,
        daily_balances=daily_balances,
        confirmed_promises_total=confirmed_promises_total,
    )
