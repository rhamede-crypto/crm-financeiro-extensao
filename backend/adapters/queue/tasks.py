from __future__ import annotations

import json
import time
from uuid import UUID

from celery import shared_task
from django.db import transaction

from adapters.persistence.models import ImportJobRecord
from adapters.storage.local_storage import TenantLocalFileStorage
from adapters.storage.spreadsheet_reader import read_spreadsheet_table
from core.domain.exceptions import TenantAccessDeniedError, ValidationDomainError
from core.domain.value_objects import ImportStatus
from core.services.etl import extract_table_preview


@shared_task(bind=True, name="imports.verify_company_job_scope")
def verify_company_job_scope(self, company_id: str, job_id: str) -> dict[str, str]:
    """Validates tenant ownership inside the Celery worker before touching a job."""
    parsed_company = UUID(company_id)
    parsed_job = UUID(job_id)

    job = ImportJobRecord.objects.for_company(parsed_company).filter(id=parsed_job).first()
    if job is None:
        raise TenantAccessDeniedError(
            "Job não pertence à empresa informada na fila.",
        )

    if job.status == ImportStatus.QUEUED.value:
        job.status = ImportStatus.PROCESSING.value
        job.last_worker_task_id = str(self.request.id or "")
        job.save(update_fields=["status", "last_worker_task_id", "updated_at"])

    return {
        "company_id": str(job.company_id),
        "job_id": str(job.id),
        "status": job.status,
    }


def _relative_from_storage_key(company_id: UUID, storage_key: str) -> str:
    prefix = f"companies/{company_id}/"
    if storage_key.startswith(prefix):
        return storage_key[len(prefix) :]
    return storage_key


@shared_task(
    bind=True,
    name="imports.process_import_job",
    autoretry_for=(OSError,),
    retry_backoff=True,
    max_retries=3,
)
def process_import_job(self, company_id: str, job_id: str) -> dict[str, str]:
    """Idempotently parses uploaded spreadsheet in a company-isolated worker task."""
    started = time.perf_counter()
    parsed_company = UUID(company_id)
    parsed_job = UUID(job_id)

    job = (
        ImportJobRecord.objects.for_company(parsed_company)
        .select_related("stored_file")
        .filter(id=parsed_job)
        .first()
    )
    if job is None:
        raise TenantAccessDeniedError("Job não pertence à empresa informada na fila.")

    if job.status in {
        ImportStatus.COMPLETED.value,
        ImportStatus.CANCELED.value,
        ImportStatus.FAILED.value,
    }:
        return {"company_id": company_id, "job_id": job_id, "status": job.status}

    if job.stored_file is None:
        job.status = ImportStatus.FAILED.value
        job.error_message = "Arquivo de origem ausente."
        job.save(update_fields=["status", "error_message", "updated_at"])
        return {"company_id": company_id, "job_id": job_id, "status": job.status}

    storage = TenantLocalFileStorage()
    relative_path = _relative_from_storage_key(parsed_company, job.stored_file.storage_key)

    try:
        raw_bytes = storage.read_bytes(parsed_company, relative_path)
        table = read_spreadsheet_table(job.filename, raw_bytes)
        preview_data = extract_table_preview(table)

        parsed_rel = f"imports/{job.id}/parsed.json"
        parsed_key = storage.save_bytes(
            parsed_company,
            parsed_rel,
            json.dumps(preview_data.rows, ensure_ascii=False).encode("utf-8"),
        )
        elapsed_ms = max(1, int((time.perf_counter() - started) * 1000))

        with transaction.atomic():
            locked = (
                ImportJobRecord.objects.for_company(parsed_company)
                .select_for_update()
                .get(id=parsed_job)
            )
            if locked.status in {ImportStatus.COMPLETED.value, ImportStatus.CANCELED.value}:
                return {"company_id": company_id, "job_id": job_id, "status": locked.status}
            locked.columns_json = preview_data.columns
            locked.preview_json = preview_data.preview
            locked.row_count = len(preview_data.rows)
            locked.parsed_rows_storage_key = parsed_key
            locked.processing_duration_ms = elapsed_ms
            locked.last_worker_task_id = str(self.request.id or "")
            locked.status = ImportStatus.REVIEW.value
            locked.save(
                update_fields=[
                    "columns_json",
                    "preview_json",
                    "row_count",
                    "parsed_rows_storage_key",
                    "processing_duration_ms",
                    "last_worker_task_id",
                    "status",
                    "updated_at",
                ]
            )
        return {"company_id": company_id, "job_id": job_id, "status": ImportStatus.REVIEW.value}
    except ValidationDomainError as exc:
        elapsed_ms = max(1, int((time.perf_counter() - started) * 1000))
        job.status = ImportStatus.FAILED.value
        job.error_message = exc.message
        job.processing_duration_ms = elapsed_ms
        job.save(update_fields=["status", "error_message", "processing_duration_ms", "updated_at"])
        return {"company_id": company_id, "job_id": job_id, "status": job.status}
