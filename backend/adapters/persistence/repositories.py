from __future__ import annotations

from uuid import UUID

from core.domain.entities import CompanyScope
from core.domain.value_objects import MoneyDecimal

from .models import CompanyMembership


class DjangoCompanyScopeRepository:
    def get_company_for_user(self, user_id: UUID) -> CompanyScope | None:
        membership = (
            CompanyMembership.objects.select_related("company")
            .filter(user_id=user_id)
            .first()
        )
        if membership is None:
            return None
        company = membership.company
        return CompanyScope(
            id=company.id,
            name=company.name,
            segment=company.segment,
            tax_regime=company.tax_regime,
            initial_balance=MoneyDecimal.from_value(company.initial_balance),
        )
