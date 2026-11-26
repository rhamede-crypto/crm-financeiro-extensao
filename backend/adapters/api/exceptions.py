from __future__ import annotations

from typing import Any

from rest_framework import status
from rest_framework.exceptions import (
    AuthenticationFailed,
    NotAuthenticated,
    PermissionDenied,
    ValidationError,
)
from rest_framework.response import Response
from rest_framework.views import exception_handler

from core.domain.exceptions import (
    AuthenticationDomainError,
    CompanyOnboardingRequiredError,
    DomainError,
    PayloadTooLargeError,
    ResourceNotFoundError,
    StateConflictError,
    TenantAccessDeniedError,
    ValidationDomainError,
)


def _normalize_errors(detail: Any) -> dict[str, list[str]]:
    if isinstance(detail, dict):
        normalized: dict[str, list[str]] = {}
        for key, value in detail.items():
            if isinstance(value, list):
                normalized[str(key)] = [str(item) for item in value]
            else:
                normalized[str(key)] = [str(value)]
        return normalized
    if isinstance(detail, list):
        return {"non_field_errors": [str(item) for item in detail]}
    return {}


def error_payload(
    message: str,
    errors: dict[str, list[str]] | None = None,
    code: str = "error",
) -> dict[str, Any]:
    return {
        "message": message,
        "errors": errors or {},
        "code": code,
    }


def api_exception_handler(exc: Exception, context: dict[str, Any]) -> Response | None:
    if isinstance(exc, AuthenticationDomainError):
        return Response(
            error_payload(exc.message, exc.fields, exc.code),
            status=status.HTTP_401_UNAUTHORIZED,
        )
    if isinstance(exc, (CompanyOnboardingRequiredError, TenantAccessDeniedError)):
        return Response(
            error_payload(exc.message, exc.fields, exc.code),
            status=status.HTTP_403_FORBIDDEN,
        )
    if isinstance(exc, ResourceNotFoundError):
        return Response(
            error_payload(exc.message, exc.fields, exc.code),
            status=status.HTTP_404_NOT_FOUND,
        )
    if isinstance(exc, StateConflictError):
        return Response(
            error_payload(exc.message, exc.fields, exc.code),
            status=status.HTTP_409_CONFLICT,
        )
    if isinstance(exc, PayloadTooLargeError):
        return Response(
            error_payload(exc.message, exc.fields, exc.code),
            status=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
        )
    if isinstance(exc, ValidationDomainError):
        return Response(
            error_payload(exc.message, exc.fields, exc.code),
            status=status.HTTP_422_UNPROCESSABLE_ENTITY,
        )
    if isinstance(exc, DomainError):
        return Response(
            error_payload(exc.message, exc.fields, exc.code),
            status=status.HTTP_400_BAD_REQUEST,
        )

    response = exception_handler(exc, context)
    if response is None:
        return None

    if isinstance(exc, (NotAuthenticated, AuthenticationFailed)):
        return Response(
            error_payload("Sua sessão expirou.", code="authentication_required"),
            status=status.HTTP_401_UNAUTHORIZED,
        )
    if isinstance(exc, PermissionDenied):
        return Response(
            error_payload("Você não tem permissão para esta operação.", code="permission_denied"),
            status=status.HTTP_403_FORBIDDEN,
        )
    if isinstance(exc, ValidationError):
        return Response(
            error_payload(
                "Confira os dados informados.",
                _normalize_errors(response.data),
                "validation_error",
            ),
            status=status.HTTP_422_UNPROCESSABLE_ENTITY,
        )

    message = (
        str(response.data.get("detail"))
        if isinstance(response.data, dict) and "detail" in response.data
        else "Não foi possível concluir a operação."
    )
    return Response(
        error_payload(message, _normalize_errors(response.data), "api_error"),
        status=response.status_code,
    )
