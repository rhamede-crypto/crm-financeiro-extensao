from __future__ import annotations

import hashlib
import json
from collections.abc import Callable
from typing import Any
from uuid import UUID

from django.db import IntegrityError, transaction
from rest_framework.response import Response

from adapters.persistence.models import Company, IdempotencyRecord
from core.domain.exceptions import StateConflictError


def _hash_payload(payload: Any) -> str:
    canonical = json.dumps(payload, sort_keys=True, ensure_ascii=False, default=str)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def run_idempotent(
    *,
    company: Company,
    scope_path: str,
    idempotency_key: str | None,
    payload_signature: Any,
    execute: Callable[[], tuple[int, dict[str, Any]]],
) -> Response:
    """Executes an operation at most once per (company, scope_path, idempotency_key)."""
    key = (idempotency_key or "").strip()
    if not key:
        status_code, body = execute()
        return Response(body, status=status_code)

    request_hash = _hash_payload(payload_signature)
    existing = (
        IdempotencyRecord.objects.for_company(company.id)
        .filter(scope_path=scope_path, idempotency_key=key)
        .first()
    )
    if existing is not None:
        if existing.request_hash != request_hash:
            raise StateConflictError(
                "Chave de idempotência já utilizada para outra requisição.",
                code="idempotency_mismatch",
            )
        return Response(existing.response_body, status=existing.status_code)

    try:
        with transaction.atomic():
            status_code, body = execute()
            IdempotencyRecord.objects.create(
                company_id=company.id,
                scope_path=scope_path,
                idempotency_key=key,
                request_hash=request_hash,
                status_code=status_code,
                response_body=body,
            )
            return Response(body, status=status_code)
    except IntegrityError:
        replay = (
            IdempotencyRecord.objects.for_company(company.id)
            .filter(scope_path=scope_path, idempotency_key=key)
            .first()
        )
        if replay is not None and replay.request_hash == request_hash:
            return Response(replay.response_body, status=replay.status_code)
        raise StateConflictError("Concorrência na chave de idempotência.")


def tenant_storage_path(job_id: UUID, filename: str) -> str:
    safe_name = filename.replace("\\", "/").split("/")[-1].strip() or "upload.bin"
    return f"imports/{job_id}/{safe_name}"
