from __future__ import annotations

import json
import uuid
from typing import Any

from django.db import transaction
from django.utils import timezone

from adapters.persistence.models import Company, Contact, FinancialEntry, ImportJobRecord
from adapters.storage.local_storage import TenantLocalFileStorage
from core.domain.exceptions import StateConflictError, ValidationDomainError
from core.domain.value_objects import ImportStatus, normalize_ascii_text
from core.services.contacts import (
    ContactCandidate,
    infer_contact_type,
    normalize_document,
    normalize_phone,
    resolve_contact_match,
)
from core.services.etl import (
    CANONICAL_FIELDS,
    NormalizedRow,
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


def _sync_contacts_for_rows(
    *,
    company: Company,
    rows: list[NormalizedRow],
) -> dict[int, uuid.UUID]:
    existing_db = list(Contact.objects.for_company(company.id))
    candidates: list[ContactCandidate] = [
        ContactCandidate(
            id=c.id,
            contact_type=c.contact_type,
            name=c.name,
            normalized_name=c.normalized_name,
            normalized_document=c.normalized_document,
            normalized_phone=c.normalized_phone,
            email=c.email,
            needs_review=c.needs_review,
            review_reason=c.review_reason,
        )
        for c in existing_db
    ]
    db_by_id = {c.id: c for c in existing_db}
    new_contacts: list[Contact] = []
    dirty_ids: set[uuid.UUID] = set()
    row_contact_map: dict[int, uuid.UUID] = {}
    lookup_cache: dict[tuple[str, str, str, str], uuid.UUID] = {}

    for row in rows:
        if not row.party_name.strip():
            continue
        ctype = infer_contact_type(row.entry_type, row.amount)
        norm_doc = normalize_document(row.party_document)
        norm_phone = normalize_phone(row.party_phone)
        cache_key = (ctype, row.normalized_party, norm_doc, norm_phone)
        if cache_key in lookup_cache and not row.party_email:
            row_contact_map[row.row_index] = lookup_cache[cache_key]
            continue

        outcome = resolve_contact_match(
            candidates,
            contact_type=ctype,
            name=row.party_name,
            document=row.party_document,
            phone=row.party_phone,
        )

        if outcome.flag_existing_review is not None:
            flagged = outcome.flag_existing_review
            flagged.needs_review = True
            flagged.review_reason = outcome.review_reason
            existing_model = db_by_id.get(flagged.id)
            if existing_model is not None:
                existing_model.needs_review = True
                existing_model.review_reason = outcome.review_reason
                dirty_ids.add(existing_model.id)

        if outcome.action == "reuse" and outcome.matched_contact is not None:
            cand = outcome.matched_contact
            model = db_by_id.get(cand.id)
            if model is not None:
                changed = False
                if norm_doc and not model.normalized_document:
                    model.document = row.party_document
                    model.normalized_document = norm_doc
                    cand.normalized_document = norm_doc
                    changed = True
                if norm_phone and not model.normalized_phone:
                    model.phone = row.party_phone
                    model.normalized_phone = norm_phone
                    cand.normalized_phone = norm_phone
                    changed = True
                if row.party_email and not model.email:
                    model.email = row.party_email
                    cand.email = row.party_email
                    changed = True
                if outcome.needs_review and not model.needs_review:
                    model.needs_review = True
                    model.review_reason = outcome.review_reason
                    cand.needs_review = True
                    cand.review_reason = outcome.review_reason
                    changed = True
                if changed:
                    dirty_ids.add(model.id)
            row_contact_map[row.row_index] = cand.id
            lookup_cache[cache_key] = cand.id
            continue

        new_id = uuid.uuid4()
        new_model = Contact(
            id=new_id,
            company_id=company.id,
            name=row.party_name.strip()[:160],
            normalized_name=row.normalized_party[:160],
            contact_type=ctype,
            document=row.party_document[:32],
            normalized_document=norm_doc,
            phone=row.party_phone[:32],
            normalized_phone=norm_phone,
            email=row.party_email[:254],
            needs_review=outcome.needs_review,
            review_reason=outcome.review_reason,
        )
        new_contacts.append(new_model)
        db_by_id[new_id] = new_model
        candidates.append(
            ContactCandidate(
                id=new_id,
                contact_type=ctype,
                name=new_model.name,
                normalized_name=new_model.normalized_name,
                normalized_document=norm_doc,
                normalized_phone=norm_phone,
                email=new_model.email,
                needs_review=outcome.needs_review,
                review_reason=outcome.review_reason,
            )
        )
        row_contact_map[row.row_index] = new_id
        lookup_cache[cache_key] = new_id

    if new_contacts:
        Contact.objects.bulk_create(new_contacts, batch_size=500)
    created_ids = {c.id for c in new_contacts}
    to_update = [db_by_id[cid] for cid in dirty_ids if cid not in created_ids]
    if to_update:
        Contact.objects.bulk_update(
            to_update,
            [
                "document",
                "normalized_document",
                "phone",
                "normalized_phone",
                "email",
                "needs_review",
                "review_reason",
                "updated_at",
            ],
            batch_size=500,
        )
    return row_contact_map


def consolidate_import_job(
    *,
    company: Company,
    job: ImportJobRecord,
    mapping: dict[str, str],
    resolutions: dict[str, str] | None = None,
) -> ImportJobRecord:
    """Atomically consolidates normalized rows with deduplication and contact generation."""
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

        touched_rows = list(dedup.to_create) + [row for _, row in dedup.to_update]
        row_contact_map = _sync_contacts_for_rows(company=locked_company, rows=touched_rows)

        if dedup.to_create:
            new_models = [
                FinancialEntry(
                    company_id=locked_company.id,
                    import_job=locked_job,
                    contact_id=row_contact_map.get(row.row_index),
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
                if obj.contact_id is None and row.row_index in row_contact_map:
                    obj.contact_id = row_contact_map[row.row_index]
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
                    "contact",
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
