from __future__ import annotations

from uuid import UUID

from celery import shared_task

from adapters.persistence.models import ImportJobRecord
from core.domain.exceptions import TenantAccessDeniedError
from core.domain.value_objects import ImportStatus


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
