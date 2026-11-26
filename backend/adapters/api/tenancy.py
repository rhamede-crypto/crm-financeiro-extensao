from __future__ import annotations

from adapters.persistence.models import Company, CompanyMembership
from core.domain.exceptions import AuthenticationDomainError, CompanyOnboardingRequiredError


def resolve_request_company(request) -> Company:
    """Resolves the active tenant strictly from the authenticated user's server membership."""
    user = getattr(request, "user", None)
    if user is None or not user.is_authenticated:
        raise AuthenticationDomainError()

    membership = (
        CompanyMembership.objects.select_related("company")
        .filter(user_id=user.id)
        .first()
    )
    if membership is None:
        raise CompanyOnboardingRequiredError()

    return membership.company
