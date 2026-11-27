from __future__ import annotations

import json
from typing import Any

from django.db import transaction
from django.utils import timezone

from adapters.persistence.models import Company, FinancialEntry, ImportJobRecord
from adapters.storage.local_storage import TenantLocalFileStorage
from core.domain.exceptions import StateConflictError, ValidationDomainError
from core.domain.value_objects import ImportStatus, normalize_ascii_text
from core.services.etl import (
    CANONICAL_FIELDS,
    deduplicate_entries,
    normalize_mapped_rows,
)


def _relative_from_storage_key(company_id, storage_key: str) -> str:
    prefix = f"companies/{company_id}/"
    return storage_key[len(prefix) :] if storage_key.startswith(prefix) else storage_key


def validate_confirm_mapping(
    job: ImportJobRecord,
    mapping: dict[str, str],
) -> dict[str, str]:
    columns = job.columns_json or []
    known_ids = {str(col["id"]) for col in columns}
    cleaned = {str(k): str(v or "") for k, v in mapping.items()}
    used = [val for val in cleaned.values() if val]

    missing_required = any(
        field["required"] and cleaned.get(field["id"], "") not in known_ids
        for field in CANONICAL_FIELDS
    )
    unknown_col = any(col_id not in known_ids for col_id in used)
    duplicate_col = len(used) != len(set(used))

    if missing_required or unknown_col or duplicate_col:
        raise ValidationDomainError(
            "Associe uma coluna distinta a cada campo obrigatório.",
            fields={"mapping": ["Associe colunas válidas e distintas aos campos obrigatórios."]},
        )
    return cleaned


def consolidate_import_job(
    *,
    company: Company,
    job: ImportJobRecord,
    mapping: dict[str, str],
    resolutions: dict[str, str] | None = None,
) -> ImportJobRecord:
    """Atomically consolidates normalized rows with idempotent deduplication."""
    validated_mapping = validate_confirm_mapping(job, mapping)
    storage = TenantLocalFileStorage()
    rows_rel = _relative_from_storage_key(company.id, job.parsed_rows_storage_key)
    raw_rows: list[list[str]] = json.loads(storage.read_bytes(company.id, rows_rel).decode("utf-8"))

    incoming_rows, rejected_count = normalize_mapped_rows(
        rows=raw_rows,
        columns=job.columns_json or [],
        mapping=validated_mapping,
        import_type=job.import_type,
    )

    with transaction.atomic():
        locked_company = Company.objects.select_for_update().get(id=company.id)
        locked_job = (
            ImportJobRecord.objects.for_company(locked_company.id)
            .select_for_update()
            .get(id=job.id)
        )
        if locked_job.status == ImportStatus.COMPLETED.value:
            return locked_job
        if locked_job.status == ImportStatus.CANCELED.value:
            raise StateConflictError("A importação já mudou de estado.")

        existing_qs = FinancialEntry.objects.for_company(locked_company.id).filter(
            entry_type=locked_job.import_type
        )
        existing_by_id: dict[Any, FinancialEntry] = {}
        existing_records: list[dict[str, Any]] = []
        for entry in existing_qs:
            existing_by_id[entry.id] = entry
            existing_records.append(
                {
                    "id": entry.id,
                    "entry_type": entry.entry_type,
                    "reference": entry.reference,
                    "signature": (
                        entry.entry_type,
                        entry.entry_date.isoformat(),
                        f"{entry.amount:.2f}",
                        entry.normalized_description,
                        entry.normalized_party,
                    ),
                    "state": (
                        entry.entry_date,
                        entry.due_date,
                        entry.amount,
                        entry.paid_amount,
                        entry.description,
                        entry.normalized_description,
                        entry.party_name,
                        entry.normalized_party,
                        entry.category,
                        entry.unit_name,
                        entry.unit_price,
                        entry.settled,
                    ),
                }
            )

        dedup = deduplicate_entries(
            existing_records=existing_records,
            incoming_rows=incoming_rows,
            rejected_count=rejected_count,
            resolutions=resolutions,
        )

        locked_job.selected_mapping_json = validated_mapping
        if dedup.ambiguities:
            locked_job.status = ImportStatus.REVIEW.value
            locked_job.ambiguities_json = dedup.ambiguities
            locked_job.save(
                update_fields=["selected_mapping_json", "ambiguities_json", "status", "updated_at"]
            )
            return locked_job

        if dedup.to_create:
            new_models = [
                FinancialEntry(
                    company_id=locked_company.id,
                    import_job=locked_job,
                    entry_type=row.entry_type,
                    reference=row.reference,
                    entry_date=row.entry_date,
                    due_date=row.due_date,
                    amount=row.amount,
                    paid_amount=row.paid_amount,
                    description=row.description,
                    normalized_description=row.normalized_description
                    or normalize_ascii_text(row.description),
                    party_name=row.party_name,
                    normalized_party=row.normalized_party,
                    category=row.category,
                    unit_name=row.unit_name,
                    unit_price=row.unit_price,
                    settled=row.settled,
                )
                for row in dedup.to_create
            ]
            FinancialEntry.objects.bulk_create(new_models, batch_size=2000)

        if dedup.to_update:
            updated_models: list[FinancialEntry] = []
            for obj_id, row in dedup.to_update:
                obj = existing_by_id[obj_id]
                obj.import_job = locked_job
                obj.entry_date = row.entry_date
                obj.due_date = row.due_date
                obj.amount = row.amount
                obj.paid_amount = row.paid_amount
                obj.description = row.description
                obj.normalized_description = row.normalized_description
                obj.party_name = row.party_name
                obj.normalized_party = row.normalized_party
                obj.category = row.category
                obj.unit_name = row.unit_name
                obj.unit_price = row.unit_price
                obj.settled = row.settled
                updated_models.append(obj)
            FinancialEntry.objects.bulk_update(
                updated_models,
                [
                    "import_job",
                    "entry_date",
                    "due_date",
                    "amount",
                    "paid_amount",
                    "description",
                    "normalized_description",
                    "party_name",
                    "normalized_party",
                    "category",
                    "unit_name",
                    "unit_price",
                    "settled",
                    "updated_at",
                ],
                batch_size=2000,
            )

        locked_company.last_consolidated_at = timezone.now()
        locked_company.save(update_fields=["last_consolidated_at"])

        locked_job.status = ImportStatus.COMPLETED.value
        locked_job.ambiguities_json = []
        locked_job.summary_json = dedup.summary
        locked_job.save(
            update_fields=[
                "selected_mapping_json",
                "ambiguities_json",
                "summary_json",
                "status",
                "updated_at",
            ]
        )
        return locked_job
