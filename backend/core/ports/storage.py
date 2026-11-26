from __future__ import annotations

from typing import Protocol
from uuid import UUID


class TenantFileStoragePort(Protocol):
    def save_bytes(self, company_id: UUID, relative_path: str, content: bytes) -> str:
        ...

    def read_bytes(self, company_id: UUID, relative_path: str) -> bytes:
        ...

    def exists(self, company_id: UUID, relative_path: str) -> bool:
        ...
