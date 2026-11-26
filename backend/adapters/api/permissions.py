from __future__ import annotations

from rest_framework.permissions import BasePermission

from .tenancy import resolve_request_company


class HasCompanyScope(BasePermission):
    """Requires an authenticated session bound to an onboarded company."""

    def has_permission(self, request, view) -> bool:
        company = resolve_request_company(request)
        request.company = company
        return True
