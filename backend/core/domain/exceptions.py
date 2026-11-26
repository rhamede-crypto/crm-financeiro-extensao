from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class DomainError(Exception):
    """Base semantic error raised by the domain core."""

    message: str
    code: str = "domain_error"
    fields: dict[str, list[str]] = field(default_factory=dict)

    def __str__(self) -> str:
        return self.message


class ValidationDomainError(DomainError):
    def __init__(
        self,
        message: str = "Confira os dados informados.",
        fields: dict[str, list[str]] | None = None,
        code: str = "validation_error",
    ) -> None:
        super().__init__(message=message, code=code, fields=fields or {})


class AuthenticationDomainError(DomainError):
    def __init__(
        self,
        message: str = "Sua sessão expirou.",
        code: str = "authentication_required",
    ) -> None:
        super().__init__(message=message, code=code)


class CompanyOnboardingRequiredError(DomainError):
    def __init__(
        self,
        message: str = "Cadastre a empresa para continuar.",
        code: str = "company_required",
    ) -> None:
        super().__init__(message=message, code=code)


class TenantAccessDeniedError(DomainError):
    def __init__(
        self,
        message: str = "Acesso negado para os dados desta empresa.",
        code: str = "tenant_access_denied",
    ) -> None:
        super().__init__(message=message, code=code)


class ResourceNotFoundError(DomainError):
    def __init__(
        self,
        message: str = "Recurso não encontrado.",
        code: str = "not_found",
    ) -> None:
        super().__init__(message=message, code=code)


class StateConflictError(DomainError):
    def __init__(
        self,
        message: str = "O estado do recurso já mudou.",
        code: str = "conflict",
    ) -> None:
        super().__init__(message=message, code=code)


class PayloadTooLargeError(DomainError):
    def __init__(
        self,
        message: str = "O arquivo está vazio ou ultrapassa o limite de tamanho.",
        code: str = "payload_too_large",
    ) -> None:
        super().__init__(message=message, code=code)
