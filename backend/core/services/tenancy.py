from __future__ import annotations

from pathlib import PurePosixPath
from uuid import UUID

from core.domain.exceptions import TenantAccessDeniedError, ValidationDomainError


def assert_company_scope(expected_company_id: UUID, actual_company_id: UUID | None) -> None:
    """Ensures every resource operation matches the authenticated tenant."""
    if actual_company_id is None or actual_company_id != expected_company_id:
        raise TenantAccessDeniedError()


def sanitize_tenant_relative_path(relative_path: str) -> str:
    """Normalizes and validates a relative path inside a tenant storage directory."""
    raw = str(relative_path).strip().replace("\\", "/")
    if not raw or raw.startswith("/"):
        raise ValidationDomainError(
            "Caminho de arquivo inválido para o escopo da empresa.",
            fields={"file": ["Caminho relativo inválido."]},
        )
    posix_path = PurePosixPath(raw)
    if any(part in ("", ".", "..") for part in posix_path.parts):
        raise ValidationDomainError(
            "Caminho de arquivo não permitido.",
            fields={"file": ["Navegação entre diretórios não permitida."]},
        )
    return posix_path.as_posix()
