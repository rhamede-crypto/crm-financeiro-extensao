from __future__ import annotations

from datetime import date
from typing import Any

from django.utils import timezone

from adapters.persistence.models import Company, FinancialEntry
from core.services.cashflow import CashflowEntry, project_cashflow


def build_company_dashboard(
    company: Company,
    *,
    reference_date: date | None = None,
) -> dict[str, Any]:
    ref_date = reference_date or timezone.localdate()
    entries_qs = FinancialEntry.objects.for_company(company.id)
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
        for e in entries_qs
    ]
    cashflow = project_cashflow(
        initial_balance=company.initial_balance,
        entries=entries,
        reference_date=ref_date,
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
        "ranking": [],
        "alerts": [],
    }
