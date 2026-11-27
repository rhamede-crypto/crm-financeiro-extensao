from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal

from core.services.cost_anomalies import CostAnomalyEntry, detect_cost_anomalies


def test_detect_cost_anomalies_triggers_above_threshold_with_evidence() -> None:
    ref = date(2026, 10, 30)
    prev_day = ref - timedelta(days=80)
    curr_day = ref - timedelta(days=15)

    entries = [
        # Revenue flat: 10000 -> 10000 (0%)
        CostAnomalyEntry(
            "receivable", prev_day, Decimal("10000.00"), "Vendas", "Varios", "varios", ""
        ),
        CostAnomalyEntry(
            "receivable", curr_day, Decimal("10000.00"), "Vendas", "Varios", "varios", ""
        ),
        # Embalagens jumped 21.6%: 3800 -> 4620.80
        CostAnomalyEntry(
            "payable",
            prev_day,
            Decimal("3800.00"),
            "Compra de caixas e embalagens",
            "Distribuidora Aurora",
            "distribuidora aurora",
            "",
        ),
        CostAnomalyEntry(
            "payable",
            curr_day,
            Decimal("4620.80"),
            "Compra de caixas e embalagens",
            "Distribuidora Aurora",
            "distribuidora aurora",
            "",
        ),
    ]

    result = detect_cost_anomalies(entries=entries, reference_date=ref, threshold_pct=12.0)
    assert result.state == "ok"
    assert len(result.alerts) == 1
    alert = result.alerts[0]
    assert alert["category"] == "Embalagens"
    assert alert["supplier"] == "Distribuidora Aurora"
    assert alert["change"] == 21.6
    assert alert["evidence"]["previousBimester"] == "3800.00"
    assert alert["evidence"]["currentBimester"] == "4620.80"
    assert alert["evidence"]["revenueChangePct"] == 0.0


def test_detect_cost_anomalies_suppresses_when_revenue_grows_proportionally() -> None:
    ref = date(2026, 10, 30)
    prev_day = ref - timedelta(days=80)
    curr_day = ref - timedelta(days=15)

    entries = [
        CostAnomalyEntry("receivable", prev_day, Decimal("10000.00"), "Vendas", "V", "v", ""),
        CostAnomalyEntry("receivable", curr_day, Decimal("12500.00"), "Vendas", "V", "v", ""),
        CostAnomalyEntry(
            "payable",
            prev_day,
            Decimal("1000.00"),
            "Insumos",
            "Fornecedor B",
            "fornecedor b",
            "",
        ),
        CostAnomalyEntry(
            "payable",
            curr_day,
            Decimal("1250.00"),
            "Insumos",
            "Fornecedor B",
            "fornecedor b",
            "",
        ),
    ]
    result = detect_cost_anomalies(entries=entries, reference_date=ref, threshold_pct=12.0)
    assert result.state == "ok"
    assert result.alerts == []


def test_detect_cost_anomalies_handles_insufficient_data_and_zero_base() -> None:
    ref = date(2026, 10, 30)
    # Only current bimester has costs -> insufficient_data
    only_curr = detect_cost_anomalies(
        entries=[
            CostAnomalyEntry(
                "payable",
                ref - timedelta(days=10),
                Decimal("500.00"),
                "Luz",
                "Energia",
                "energia",
                "",
            )
        ],
        reference_date=ref,
    )
    assert only_curr.state == "insufficient_data"
    assert only_curr.alerts == []

    # Zero base for a new supplier while another supplier has baseline -> no ZeroDivisionError
    mixed = detect_cost_anomalies(
        entries=[
            CostAnomalyEntry(
                "payable",
                ref - timedelta(days=80),
                Decimal("500.00"),
                "Aluguel",
                "Imobiliaria",
                "imobiliaria",
                "",
            ),
            CostAnomalyEntry(
                "payable",
                ref - timedelta(days=10),
                Decimal("500.00"),
                "Aluguel",
                "Imobiliaria",
                "imobiliaria",
                "",
            ),
            CostAnomalyEntry(
                "payable",
                ref - timedelta(days=10),
                Decimal("900.00"),
                "Caixas",
                "Novo Fornecedor",
                "novo fornecedor",
                "",
            ),
        ],
        reference_date=ref,
    )
    assert mixed.state == "ok"
    assert mixed.alerts == []
