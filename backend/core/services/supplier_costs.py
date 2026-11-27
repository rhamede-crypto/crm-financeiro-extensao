from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import ROUND_HALF_UP, Decimal
from typing import Any

TWO_PLACES = Decimal("0.01")


@dataclass(frozen=True, slots=True)
class SupplierCostEntry:
    entry_date: date
    amount: Decimal
    unit_name: str
    unit_price: Decimal | None


def _iter_months(start: date, end: date) -> list[tuple[int, int]]:
    months: list[tuple[int, int]] = []
    cur_idx = start.year * 12 + (start.month - 1)
    end_idx = end.year * 12 + (end.month - 1)
    while cur_idx <= end_idx:
        months.append((cur_idx // 12, (cur_idx % 12) + 1))
        cur_idx += 1
    return months


def build_supplier_cost_history(entries: list[SupplierCostEntry]) -> dict[str, Any]:
    """Builds monthly supplier spending and comparable unit price evolution."""
    if not entries:
        return {
            "costHistory": [],
            "hasComparablePrices": False,
            "priceNotice": "Sem dados de custos para este fornecedor.",
        }

    by_month: dict[tuple[int, int], list[SupplierCostEntry]] = {}
    for item in entries:
        by_month.setdefault((item.entry_date.year, item.entry_date.month), []).append(item)

    min_date = min(item.entry_date for item in entries)
    max_date = max(item.entry_date for item in entries)

    periods: list[dict[str, Any]] = []
    any_comparable = False

    for year, month in _iter_months(min_date, max_date):
        period_str = f"{year:04d}-{month:02d}"
        month_items = by_month.get((year, month), [])
        if not month_items:
            periods.append(
                {
                    "period": period_str,
                    "spending": None,
                    "unitPrice": None,
                    "unit": None,
                    "comparablePriceAvailable": False,
                }
            )
            continue

        spending = sum(
            (abs(i.amount) for i in month_items),
            Decimal("0.00"),
        ).quantize(TWO_PLACES, rounding=ROUND_HALF_UP)

        priced = [i for i in month_items if i.unit_price is not None]
        units = {i.unit_name.strip().lower() for i in priced if i.unit_name.strip()}
        if priced and len(units) <= 1:
            avg_unit = (
                sum((i.unit_price for i in priced if i.unit_price is not None), Decimal("0.00"))
                / len(priced)
            ).quantize(TWO_PLACES, rounding=ROUND_HALF_UP)
            unit_label = next((i.unit_name.strip() for i in priced if i.unit_name.strip()), "")
            unit_price_str: str | None = f"{avg_unit:.2f}"
            unit_out: str | None = unit_label or None
            comparable = True
            any_comparable = True
        else:
            unit_price_str = None
            unit_out = None
            comparable = False

        periods.append(
            {
                "period": period_str,
                "spending": f"{spending:.2f}",
                "unitPrice": unit_price_str,
                "unit": unit_out,
                "comparablePriceAvailable": comparable,
            }
        )

    return {
        "costHistory": periods,
        "hasComparablePrices": any_comparable,
        "priceNotice": None
        if any_comparable
        else "Sem preços comparáveis; exibindo apenas gastos mensais.",
    }
