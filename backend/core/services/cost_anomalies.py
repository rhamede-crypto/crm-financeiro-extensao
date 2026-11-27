from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal
from typing import Any

from core.domain.value_objects import normalize_ascii_text
from core.ports.ai import AIRequest

CATEGORY_KEYWORDS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("Embalagens", ("embalag", "caixa", "sacola", "pote", "copo", "descartav")),
    (
        "Insumos e Mercadorias",
        ("insumo", "ingrediente", "mercadoria", "estoque", "farinha", "bebida", "carne", "cafe"),
    ),
    ("Energia e Utilidades", ("energia", "luz", "agua", "gas", "internet", "telefone")),
    ("Logística e Frete", ("frete", "entrega", "motoboy", "combustivel", "transporte")),
    ("Ocupação e Aluguel", ("aluguel", "condominio", "iptu", "locacao")),
    (
        "Serviços e Tecnologia",
        ("software", "sistema", "contabilidade", "manutencao", "limpeza", "servico", "marketing"),
    ),
)

MONTH_ABBR_PT = (
    "Jan",
    "Fev",
    "Mar",
    "Abr",
    "Mai",
    "Jun",
    "Jul",
    "Ago",
    "Set",
    "Out",
    "Nov",
    "Dez",
)


@dataclass(frozen=True, slots=True)
class CostAnomalyEntry:
    entry_type: str
    entry_date: date
    amount: Decimal
    description: str
    party_name: str
    normalized_party: str
    category: str


@dataclass(frozen=True, slots=True)
class CostAnomaliesResult:
    state: str
    detail: str
    alerts: list[dict[str, Any]]
    revenue_change_pct: float | None


def categorize_expense(description: str, explicit_category: str = "") -> str:
    cleaned = explicit_category.strip()
    if cleaned:
        return cleaned
    norm_desc = normalize_ascii_text(description)
    for category, tokens in CATEGORY_KEYWORDS:
        if any(token in norm_desc for token in tokens):
            return category
    return "Outras Despesas"


def _format_bimester_label(prev_start: date, curr_end: date) -> str:
    return (
        f"{MONTH_ABBR_PT[prev_start.month - 1]}–"
        f"{MONTH_ABBR_PT[curr_end.month - 1]} {curr_end.year}"
    )


def detect_cost_anomalies(
    *,
    entries: list[CostAnomalyEntry],
    reference_date: date,
    threshold_pct: float = 12.0,
    ai_port: Any | None = None,
) -> CostAnomaliesResult:
    """Compares bimonthly expense growth per (category, supplier) against revenue growth."""
    curr_start = reference_date - timedelta(days=59)
    prev_start = reference_date - timedelta(days=119)
    prev_end = reference_date - timedelta(days=60)

    rev_prev = Decimal("0.00")
    rev_curr = Decimal("0.00")
    costs_prev: dict[tuple[str, str], dict[str, Any]] = {}
    costs_curr: dict[tuple[str, str], dict[str, Any]] = {}
    has_prev_costs = False
    has_curr_costs = False

    for entry in entries:
        if entry.entry_date < prev_start or entry.entry_date > reference_date:
            continue
        is_curr = entry.entry_date >= curr_start

        is_inflow = entry.entry_type == "receivable" or (
            entry.entry_type == "settled" and entry.amount > Decimal("0.00")
        )
        is_outflow = entry.entry_type == "payable" or (
            entry.entry_type == "settled" and entry.amount < Decimal("0.00")
        )

        if is_inflow:
            if is_curr:
                rev_curr += abs(entry.amount)
            else:
                rev_prev += abs(entry.amount)
            continue

        if is_outflow:
            category = categorize_expense(entry.description, entry.category)
            norm_supplier = entry.normalized_party or "fornecedor-nao-informado"
            supplier_label = entry.party_name.strip() or "Fornecedor não informado"
            key = (category, norm_supplier)
            target = costs_curr if is_curr else costs_prev
            if is_curr:
                has_curr_costs = True
            else:
                has_prev_costs = True

            bucket = target.get(key)
            if bucket is None:
                target[key] = {
                    "category": category,
                    "supplier": supplier_label,
                    "norm_supplier": norm_supplier,
                    "total": abs(entry.amount),
                }
            else:
                bucket["total"] += abs(entry.amount)

    if not has_prev_costs or not has_curr_costs:
        return CostAnomaliesResult(
            state="insufficient_data",
            detail="Dados insuficientes para comparar dois bimestres completos de custos.",
            alerts=[],
            revenue_change_pct=None,
        )

    if rev_prev > Decimal("0.00"):
        rev_delta_dec = ((rev_curr - rev_prev) / rev_prev) * Decimal("100")
        rev_delta_pct = round(float(rev_delta_dec), 1)
    else:
        rev_delta_dec = Decimal("0.00")
        rev_delta_pct = 0.0

    threshold_dec = Decimal(str(threshold_pct))
    period_label = _format_bimester_label(prev_start, reference_date)
    alerts: list[dict[str, Any]] = []

    for key, curr_data in costs_curr.items():
        prev_data = costs_prev.get(key)
        if prev_data is None or prev_data["total"] <= Decimal("0.00"):
            continue

        prev_total: Decimal = prev_data["total"]
        curr_total: Decimal = curr_data["total"]
        cost_delta_dec = ((curr_total - prev_total) / prev_total) * Decimal("100")
        excess_dec = cost_delta_dec - rev_delta_dec
        if excess_dec < threshold_dec:
            continue

        cost_delta_pct = round(float(cost_delta_dec), 1)
        excess_pct = round(float(excess_dec), 1)
        supplier_name = curr_data["supplier"]
        norm_supplier = curr_data["norm_supplier"]
        category = curr_data["category"]
        supplier_id = f"contato-{norm_supplier}-fornecedor"

        recommendation = _build_recommendation(
            ai_port=ai_port,
            category=category,
            change_pct=cost_delta_pct,
            summary=(
                f"Bimestre anterior {prev_total:.2f}, bimestre atual {curr_total:.2f}, "
                f"receita {rev_delta_pct:.1f}%."
            ),
            supplier_name=supplier_name,
        )
        alerts.append(
            {
                "id": f"alerta-{norm_supplier}-{normalize_ascii_text(category).replace(' ', '-')}",
                "supplierId": supplier_id,
                "supplier": supplier_name,
                "category": category,
                "period": period_label,
                "change": cost_delta_pct,
                "recommendation": recommendation,
                "evidence": {
                    "previousBimester": f"{prev_total:.2f}",
                    "currentBimester": f"{curr_total:.2f}",
                    "costChangePct": cost_delta_pct,
                    "revenueChangePct": rev_delta_pct,
                    "excessChangePct": excess_pct,
                    "thresholdPct": threshold_pct,
                    "previousRange": f"{prev_start.isoformat()}..{prev_end.isoformat()}",
                    "currentRange": f"{curr_start.isoformat()}..{reference_date.isoformat()}",
                },
            }
        )

    alerts.sort(key=lambda item: (-item["change"], item["category"], item["supplier"]))
    return CostAnomaliesResult(
        state="ok",
        detail="",
        alerts=alerts,
        revenue_change_pct=rev_delta_pct,
    )


def _build_recommendation(
    *,
    ai_port: Any | None,
    category: str,
    change_pct: float,
    summary: str,
    supplier_name: str,
) -> str:
    fallback = (
        f"Renegociar valores de {category} com {supplier_name} e cotar alternativa "
        f"(alta de {change_pct:.1f}%)."
    )
    if ai_port is None:
        return fallback
    try:
        if hasattr(ai_port, "run_prompt"):
            res = ai_port.run_prompt(
                "cost_anomaly_recommendation",
                variables={
                    "category": category,
                    "change_pct": f"{change_pct:.1f}",
                    "summary": summary,
                },
                known_names=(supplier_name,),
                contains_sensitive_data=True,
            )
            return res.content.strip() or fallback
        res = ai_port.generate(
            AIRequest(
                prompt_key="cost_anomaly_recommendation",
                rendered_prompt=summary,
                system_instruction="Sugira renegociacao",
                max_output_tokens=200,
                timeout_seconds=8.0,
                contains_sensitive_data=True,
            )
        )
        return res.content.strip() or fallback
    except Exception:
        return fallback
