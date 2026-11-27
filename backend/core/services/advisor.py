from __future__ import annotations

import re
from typing import Any

from core.domain.value_objects import normalize_ascii_text
from core.services.privacy import sanitize_untrusted_text

CROSS_TENANT_PROBE_RE = re.compile(
    r"(?i)(outra\s+empresa|todas\s+as\s+empresas|empresa\s+[b-z0-9]|"
    r"select\s+.*from|drop\s+table|\[trecho_bloqueado\])"
)


def _fmt_brl(amount_str: str) -> str:
    val = float(amount_str)
    formatted = f"{abs(val):,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
    return f"-R$ {formatted}" if val < 0 else f"R$ {formatted}"


def answer_financial_question(
    *,
    question: str,
    dashboard: dict[str, Any],
    company_name: str,
    ai_port: Any | None = None,
) -> dict[str, Any]:
    """Answers financial questions strictly from deterministic company dashboard indicators."""
    sanitized_q = sanitize_untrusted_text(question, max_chars=2000)
    ref_date = str(dashboard.get("referenceDate") or "")
    updated_at = dashboard.get("updatedAt")

    if not sanitized_q or CROSS_TENANT_PROBE_RE.search(sanitized_q):
        return {
            "text": (
                f"Só é possível consultar os indicadores financeiros autorizados de "
                f"{company_name}, sem alterar escopo ou dados externos."
            ),
            "references": [],
            "insufficient": True,
            "referencePeriod": ref_date,
        }

    q_norm = normalize_ascii_text(sanitized_q)
    projections = dashboard.get("projections") or []
    negative_date = dashboard.get("negativeDate")
    ranking = dashboard.get("ranking") or []
    alerts = dashboard.get("alerts") or []
    cost_state = dashboard.get("costAlertsState", "insufficient_data")

    wants_cash = bool(re.search(r"\b(caixa|saldo|projec\w*|runway|negativ\w*|previs\w*)\b", q_norm))
    wants_debt = bool(
        re.search(
            r"\b(inadimplen\w*|atras\w*|cobranc\w*|devend\w*|ranking|top\s*5|client\w*)\b",
            q_norm,
        )
    )
    wants_cost = bool(
        re.search(r"\b(custo\w*|sangrament\w*|despes\w*|gast\w*|fornecedor\w*|alert\w*)\b", q_norm)
    )
    wants_summary = bool(re.search(r"\b(resumo|visao|indicador\w*|situacao|geral)\b", q_norm))

    parts: list[str] = []
    references: list[str] = []

    if wants_cash or wants_summary:
        if projections:
            p_map = {p["days"]: _fmt_brl(p["amount"]) for p in projections}
            neg_txt = (
                f" Atenção: há previsão de saldo negativo em {negative_date}."
                if negative_date
                else " Não há previsão de saldo negativo nos próximos 90 dias."
            )
            parts.append(
                f"Projeção determinística para {company_name} (ref. {ref_date}): "
                f"30 dias {p_map.get(30, '—')}, 60 dias {p_map.get(60, '—')}, "
                f"90 dias {p_map.get(90, '—')}.{neg_txt}"
            )
            references.append(f"Projeção de caixa • 30/60/90 dias (ref. {ref_date})")
        elif wants_cash:
            return {
                "text": (
                    "Ainda não há histórico ou saldo consolidado suficiente para projetar "
                    "o caixa de 30, 60 e 90 dias."
                ),
                "references": [],
                "insufficient": True,
                "referencePeriod": ref_date,
            }

    if wants_debt or (wants_summary and ranking):
        if ranking:
            top_lines = "; ".join(
                f"{idx}. {row['name']} ({_fmt_brl(row['amount'])}, {row['days']} dias)"
                for idx, row in enumerate(ranking, start=1)
            )
            parts.append(f"Top inadimplência em aberto: {top_lines}.")
            references.append(f"Top 5 de inadimplência (ref. {ref_date})")
        elif wants_debt:
            if updated_at:
                parts.append("Não há clientes inadimplentes em aberto até a data de referência.")
                references.append(f"Top 5 de inadimplência (ref. {ref_date})")
            else:
                return {
                    "text": "Ainda não há planilhas consolidadas para avaliar a inadimplência.",
                    "references": [],
                    "insufficient": True,
                    "referencePeriod": ref_date,
                }

    if wants_cost or (wants_summary and alerts):
        if alerts:
            alert_lines = "; ".join(
                f"{a['category']} ({a['supplier']}, +{a['change']}%): {a['recommendation']}"
                for a in alerts[:3]
            )
            parts.append(f"Alertas de variação de custos: {alert_lines}")
            references.append(f"Alertas de custos bimestrais (ref. {ref_date})")
        elif wants_cost:
            if cost_state == "ok":
                parts.append(
                    "Nenhuma categoria de custo superou o limite de anomalia bimestral "
                    "em relação à receita."
                )
                references.append(f"Análise bimestral de custos (ref. {ref_date})")
            else:
                return {
                    "text": (
                        "Dados insuficientes para comparar dois bimestres completos de custos "
                        "nesta empresa."
                    ),
                    "references": [],
                    "insufficient": True,
                    "referencePeriod": ref_date,
                }

    if not parts:
        return {
            "text": (
                "Não há dados ou referências suficientes nos indicadores financeiros "
                "da empresa para responder a essa pergunta."
            ),
            "references": [],
            "insufficient": True,
            "referencePeriod": ref_date,
        }

    # Optional AI phrasing check must still preserve deterministic metrics; we return exact
    # deterministic facts and only enrich with sanitized context if explicitly wanted.
    return {
        "text": " ".join(parts),
        "references": references,
        "insufficient": False,
        "referencePeriod": ref_date,
    }
