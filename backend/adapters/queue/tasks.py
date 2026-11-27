from __future__ import annotations

import json
import time
from datetime import datetime
from uuid import UUID
from zoneinfo import ZoneInfo

from celery import shared_task
from django.conf import settings
from django.db import IntegrityError, transaction

from adapters.ai.gateway import ResilientAIGateway
from adapters.notifications.email_adapter import DjangoEmailNotificationAdapter
from adapters.persistence.consolidation import consolidate_import_job
from adapters.persistence.models import (
    CompanyMembership,
    ImportJobRecord,
    ReminderDispatchLog,
    ReminderPreference,
)
from adapters.storage.local_storage import TenantLocalFileStorage
from adapters.storage.spreadsheet_reader import read_spreadsheet_table
from core.domain.exceptions import TenantAccessDeniedError, ValidationDomainError
from core.domain.value_objects import ImportStatus
from core.ports.notifications import NotificationMessage
from core.services.etl import extract_table_preview, propose_column_mapping
from core.services.reminders import evaluate_weekly_reminder


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
        proposal = propose_column_mapping(
            table,
            import_type=job.import_type,
            ai_port=ResilientAIGateway(),
        )

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
            locked.columns_json = proposal.columns
            locked.fields_json = proposal.fields
            locked.mapping_json = proposal.mapping
            locked.selected_mapping_json = proposal.selected_mapping
            locked.preview_json = proposal.preview
            locked.row_count = len(preview_data.rows)
            locked.parsed_rows_storage_key = parsed_key
            locked.processing_duration_ms = elapsed_ms
            locked.last_worker_task_id = str(self.request.id or "")
            locked.status = ImportStatus.REVIEW.value
            locked.save(
                update_fields=[
                    "columns_json",
                    "fields_json",
                    "mapping_json",
                    "selected_mapping_json",
                    "preview_json",
                    "row_count",
                    "parsed_rows_storage_key",
                    "processing_duration_ms",
                    "last_worker_task_id",
                    "status",
                    "updated_at",
                ]
            )

        if not proposal.needs_review:
            job.refresh_from_db()
            consolidated = consolidate_import_job(
                company=job.company,
                job=job,
                mapping=proposal.selected_mapping,
            )
            return {
                "company_id": company_id,
                "job_id": job_id,
                "status": consolidated.status,
            }
        return {"company_id": company_id, "job_id": job_id, "status": ImportStatus.REVIEW.value}
    except ValidationDomainError as exc:
        elapsed_ms = max(1, int((time.perf_counter() - started) * 1000))
        job.status = ImportStatus.FAILED.value
        job.error_message = exc.message
        job.processing_duration_ms = elapsed_ms
        job.save(update_fields=["status", "error_message", "processing_duration_ms", "updated_at"])
        return {"company_id": company_id, "job_id": job_id, "status": job.status}


@shared_task(bind=True, name="reminders.dispatch_weekly_reminders")
def dispatch_weekly_reminders(self, now_iso: str | None = None) -> dict[str, int]:
    """Evaluates and sends weekly spreadsheet update reminders in configured TIME_ZONE."""
    tz = ZoneInfo(settings.TIME_ZONE)
    if now_iso:
        parsed = datetime.fromisoformat(now_iso)
        now_local = parsed.replace(tzinfo=tz) if parsed.tzinfo is None else parsed.astimezone(tz)
    else:
        now_local = datetime.now(tz)

    counts = {"sent": 0, "skipped_up_to_date": 0, "failed": 0, "skipped": 0}
    notifier = DjangoEmailNotificationAdapter()
    import_url = f"{settings.FRONTEND_APP_URL}/importacoes"

    prefs = ReminderPreference.objects.select_related("company").filter(enabled=True)
    for pref in prefs:
        company = pref.company
        last_local = (
            company.last_consolidated_at.astimezone(tz)
            if company.last_consolidated_at is not None
            else None
        )
        iso = now_local.isocalendar()
        already_logged = ReminderDispatchLog.objects.for_company(company.id).filter(
            iso_year=int(iso.year),
            iso_week=int(iso.week),
        ).exists()

        decision = evaluate_weekly_reminder(
            enabled=pref.enabled,
            weekday=pref.weekday,
            now_local=now_local,
            last_consolidated_local=last_local,
            already_logged_this_week=already_logged,
        )
        if decision.action == "skip":
            counts["skipped"] += 1
            continue

        if decision.action == "skip_fresh":
            try:
                ReminderDispatchLog.objects.create(
                    company_id=company.id,
                    iso_year=decision.iso_year,
                    iso_week=decision.iso_week,
                    status="skipped_up_to_date",
                    detail="consolidated_within_6_days",
                )
                counts["skipped_up_to_date"] += 1
            except IntegrityError:
                counts["skipped"] += 1
            continue

        owner = (
            CompanyMembership.objects.select_related("user")
            .filter(company_id=company.id)
            .order_by("created_at")
            .first()
        )
        if owner is None or not owner.user.email:
            continue

        try:
            with transaction.atomic():
                log_entry = ReminderDispatchLog.objects.create(
                    company_id=company.id,
                    iso_year=decision.iso_year,
                    iso_week=decision.iso_week,
                    status="sent",
                )
                receipt = notifier.send(
                    NotificationMessage(
                        company_id=company.id,
                        recipient=owner.user.email,
                        subject=f"Lembrete semanal: atualize a planilha de {company.name}",
                        body=(
                            f"Olá, {owner.user.name}.\n\n"
                            "Hora de enviar a planilha semanal para manter suas projeções "
                            "de caixa atualizadas.\n"
                            f"Acesse: {import_url}\n"
                        ),
                        channel="email",
                    )
                )
                if receipt.status != "sent":
                    log_entry.status = "failed"
                    log_entry.detail = receipt.reason[:200]
                    log_entry.save(update_fields=["status", "detail"])
                    counts["failed"] += 1
                else:
                    counts["sent"] += 1
        except IntegrityError:
            counts["skipped"] += 1

    return counts
