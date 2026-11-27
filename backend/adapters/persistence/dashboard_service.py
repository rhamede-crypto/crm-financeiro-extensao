from __future__ import annotations

from datetime import date
from typing import Any

from django.conf import settings
from django.utils import timezone

from adapters.ai.gateway import ResilientAIGateway
from adapters.persistence.models import Company, FinancialEntry
from core.services.cashflow import CashflowEntry, project_cashflow
from core.services.cost_anomalies import CostAnomalyEntry, detect_cost_anomalies
from core.services.receivables import OverdueReceivableInput, rank_top_overdue_customers


def build_company_dashboard(
    company: Company,
    *,
    reference_date: date | None = None,
) -> dict[str, Any]:
    ref_date = reference_date or timezone.localdate()
    db_entries = list(FinancialEntry.objects.for_company(company.id))
    entries = [
        CashflowEntry(
            entry_type=e.entry_type,
            entry_date=e.entry_date,
            due_date=e.due_date,
            amount=e.amount,
            paid_amount=e.paid_amount,
            normalized_description=e.normalized_description,
            normalized_party=e.normalized_party,
            settled=e.settled,
        )
        for e in db_entries
    ]
    cashflow = project_cashflow(
        initial_balance=company.initial_balance,
        entries=entries,
        reference_date=ref_date,
    )

    min_30d_balance = (
        min(bal for _, bal in cashflow.daily_balances[:31])
        if cashflow.daily_balances
        else None
    )
    overdue_inputs = [
        OverdueReceivableInput(
            party_name=e.party_name,
            normalized_party=e.normalized_party,
            due_date=e.due_date,
            amount=e.amount,
            paid_amount=e.paid_amount,
            settled=e.settled,
            contact_id=str(e.contact_id) if e.contact_id else None,
        )
        for e in db_entries
        if e.entry_type == "receivable"
    ]
    ranking = rank_top_overdue_customers(
        items=overdue_inputs,
        reference_date=ref_date,
        min_30d_balance=min_30d_balance,
    )

    cost_inputs = [
        CostAnomalyEntry(
            entry_type=e.entry_type,
            entry_date=e.entry_date,
            amount=e.amount,
            description=e.description,
            party_name=e.party_name,
            normalized_party=e.normalized_party,
            category=e.category,
            contact_id=str(e.contact_id) if e.contact_id else None,
        )
        for e in db_entries
    ]
    cost_result = detect_cost_anomalies(
        entries=cost_inputs,
        reference_date=ref_date,
        threshold_pct=float(getattr(settings, "COST_ANOMALY_THRESHOLD_PCT", 12.0)),
        ai_port=ResilientAIGateway(),
    )

    return {
        "projections": cashflow.projections,
        "negativeDate": cashflow.negative_date,
        "negativeBeforeMonthEnd": cashflow.negative_before_month_end,
        "monthEndAlert": cashflow.month_end_alert,
        "referenceDate": cashflow.reference_date.isoformat(),
        "updatedAt": company.last_consolidated_at.isoformat()
        if company.last_consolidated_at
        else None,
        "ranking": ranking,
        "alerts": cost_result.alerts,
        "costAlertsState": cost_result.state,
        "costAlertsDetail": cost_result.detail,
    }
