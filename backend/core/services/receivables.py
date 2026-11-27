from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import ROUND_HALF_UP, Decimal
from typing import Any

TWO_PLACES = Decimal("0.01")


@dataclass(frozen=True, slots=True)
class OverdueReceivableInput:
    party_name: str
    normalized_party: str
    due_date: date | None
    amount: Decimal
    paid_amount: Decimal
    settled: bool
    contact_id: str | None = None


def rank_top_overdue_customers(
    *,
    items: list[OverdueReceivableInput],
    reference_date: date,
    min_30d_balance: Decimal | None = None,
    limit: int = 5,
) -> list[dict[str, Any]]:
    """Ranks up to 5 overdue customers by 30-day cash-need impact and most recent due date."""
    grouped: dict[str, dict[str, Any]] = {}

    for item in items:
        if item.settled or item.due_date is None or item.due_date >= reference_date:
            continue
        if not item.normalized_party:
            continue
        total = abs(item.amount).quantize(TWO_PLACES, rounding=ROUND_HALF_UP)
        paid = min(total, max(Decimal("0.00"), item.paid_amount))
        open_amount = (total - paid).quantize(TWO_PLACES, rounding=ROUND_HALF_UP)
        if open_amount <= Decimal("0.00"):
            continue

        days_overdue = (reference_date - item.due_date).days
        group_key = item.contact_id or item.normalized_party
        bucket = grouped.get(group_key)
        if bucket is None:
            grouped[group_key] = {
                "id": item.contact_id or f"contato-{item.normalized_party}",
                "name": item.party_name.strip() or item.normalized_party,
                "normalized": item.normalized_party,
                "total_open": open_amount,
                "days": days_overdue,
                "most_recent_due": item.due_date,
            }
        else:
            bucket["total_open"] += open_amount
            bucket["days"] = max(bucket["days"], days_overdue)
            bucket["most_recent_due"] = max(bucket["most_recent_due"], item.due_date)

    if not grouped:
        return []

    deficit_30d = (
        abs(min(Decimal("0.00"), min_30d_balance))
        if min_30d_balance is not None
        else Decimal("0.00")
    )
    grand_total_overdue = sum(
        (b["total_open"] for b in grouped.values()),
        Decimal("0.00"),
    )

    ranked_rows: list[dict[str, Any]] = []
    for bucket in grouped.values():
        total_open: Decimal = bucket["total_open"]
        if deficit_30d > Decimal("0.00"):
            covered = min(total_open, deficit_30d)
            impact_pct = round(float((covered / deficit_30d) * Decimal("100")), 1)
            impact_amount = covered
        else:
            impact_pct = (
                round(float((total_open / grand_total_overdue) * Decimal("100")), 1)
                if grand_total_overdue > Decimal("0.00")
                else 0.0
            )
            impact_amount = total_open

        ranked_rows.append(
            {
                "id": bucket["id"],
                "name": bucket["name"],
                "normalized": bucket["normalized"],
                "total_open": total_open,
                "days": bucket["days"],
                "most_recent_due": bucket["most_recent_due"],
                "impact_amount": impact_amount,
                "impact_pct": impact_pct,
            }
        )

    ranked_rows.sort(
        key=lambda row: (
            -row["impact_amount"],
            -row["total_open"],
            -row["most_recent_due"].toordinal(),
            row["normalized"],
        )
    )

    return [
        {
            "id": row["id"],
            "name": row["name"],
            "amount": f"{row['total_open']:.2f}",
            "days": row["days"],
            "impactAmount": f"{row['impact_amount']:.2f}",
            "impactPct": row["impact_pct"],
            "mostRecentDue": row["most_recent_due"].isoformat(),
        }
        for row in ranked_rows[:limit]
    ]
