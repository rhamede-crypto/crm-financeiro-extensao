from __future__ import annotations

from datetime import date
from decimal import Decimal

from core.services.supplier_costs import SupplierCostEntry, build_supplier_cost_history


def test_supplier_cost_history_with_comparable_prices_and_gap_month() -> None:
    res = build_supplier_cost_history(
        [
            SupplierCostEntry(date(2026, 8, 10), Decimal("3800.00"), "caixa", Decimal("38.00")),
            SupplierCostEntry(date(2026, 10, 12), Decimal("4620.00"), "caixa", Decimal("46.20")),
        ]
    )
    assert res["hasComparablePrices"] is True
    assert res["priceNotice"] is None
    assert res["costHistory"] == [
        {
            "period": "2026-08",
            "spending": "3800.00",
            "unitPrice": "38.00",
            "unit": "caixa",
            "comparablePriceAvailable": True,
        },
        {
            "period": "2026-09",
            "spending": None,
            "unitPrice": None,
            "unit": None,
            "comparablePriceAvailable": False,
        },
        {
            "period": "2026-10",
            "spending": "4620.00",
            "unitPrice": "46.20",
            "unit": "caixa",
            "comparablePriceAvailable": True,
        },
    ]


def test_supplier_cost_history_totals_only_flags_no_comparable_prices() -> None:
    res = build_supplier_cost_history(
        [
            SupplierCostEntry(date(2026, 9, 5), Decimal("1200.00"), "", None),
            SupplierCostEntry(date(2026, 10, 5), Decimal("1500.00"), "", None),
        ]
    )
    assert res["hasComparablePrices"] is False
    assert "Sem preços comparáveis" in res["priceNotice"]
    assert res["costHistory"][0]["spending"] == "1200.00"
    assert res["costHistory"][0]["unitPrice"] is None
