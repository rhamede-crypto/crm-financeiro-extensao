from __future__ import annotations

import calendar
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
class CashProjectionResult:
    reference_date: date
    starting_balance: Decimal
    projections: list[dict[str, Any]]
    negative_date: str | None
    negative_before_month_end: bool
    month_end_alert: bool
    daily_balances: list[tuple[date, Decimal]]


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


def project_cashflow(
    *,
    initial_balance: Decimal,
    entries: list[CashflowEntry],
    reference_date: date,
) -> CashProjectionResult:
    """Deterministically projects 30/60/90-day daily cash balances without double counting."""
    init = initial_balance.quantize(TWO_PLACES, rounding=ROUND_HALF_UP)
    if not entries and init == Decimal("0.00"):
        return CashProjectionResult(
            reference_date=reference_date,
            starting_balance=init,
            projections=[],
            negative_date=None,
            negative_before_month_end=False,
            month_end_alert=False,
            daily_balances=[],
        )

    end_date = reference_date + timedelta(days=90)
    starting_cash = init
    daily_deltas: dict[date, Decimal] = {}
    explicit_month_keys: set[tuple[int, str, str, int, int]] = set()
    historical_by_key: dict[tuple[int, str, str], list[tuple[date, Decimal]]] = {}

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
            elif scheduled_date == reference_date:
                # Due today and still unpaid is scheduled on day 1 if expected, or day 0;
                # schedule on reference_date + 0? Keep day 1..90 window clean at reference_date.
                daily_deltas[reference_date] = (
                    daily_deltas.get(reference_date, Decimal("0.00")) + (remaining * direction)
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
    )
