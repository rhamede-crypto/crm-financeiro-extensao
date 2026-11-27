from __future__ import annotations

from pathlib import Path
from uuid import UUID

from django.conf import settings

from core.domain.exceptions import ResourceNotFoundError, TenantAccessDeniedError
from core.services.tenancy import sanitize_tenant_relative_path


class TenantLocalFileStorage:
    """Stores and reads files strictly inside per-company subdirectories."""

    def __init__(self, root_dir: Path | str | None = None) -> None:
        self._root = Path(root_dir or settings.MEDIA_ROOT).resolve()

    def _tenant_dir(self, company_id: UUID) -> Path:
        return (self._root / "companies" / str(company_id)).resolve()

    def _resolve_target(self, company_id: UUID, relative_path: str) -> tuple[Path, str]:
        safe_relative = sanitize_tenant_relative_path(relative_path)
        tenant_dir = self._tenant_dir(company_id)
        target = (tenant_dir / safe_relative).resolve()
        if not target.is_relative_to(tenant_dir):
            raise TenantAccessDeniedError("Caminho fora do diretório isolado da empresa.")
        storage_key = f"companies/{company_id}/{safe_relative}"
        return target, storage_key

    def save_bytes(self, company_id: UUID, relative_path: str, content: bytes) -> str:
        target, storage_key = self._resolve_target(company_id, relative_path)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(content)
        return storage_key

    def read_bytes(self, company_id: UUID, relative_path: str) -> bytes:
        target, _ = self._resolve_target(company_id, relative_path)
        if not target.is_file():
            raise ResourceNotFoundError("Arquivo não encontrado para esta empresa.")
        return target.read_bytes()

    def exists(self, company_id: UUID, relative_path: str) -> bool:
        target, _ = self._resolve_target(company_id, relative_path)
        return target.is_file()
