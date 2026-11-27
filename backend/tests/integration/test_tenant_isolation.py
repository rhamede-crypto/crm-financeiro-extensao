from __future__ import annotations

import uuid
from decimal import Decimal

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from rest_framework.test import APIClient

from adapters.persistence.models import (
    Company,
    CompanyMembership,
    ImportJobRecord,
    StoredImportFile,
    User,
)
from adapters.queue.tasks import verify_company_job_scope
from adapters.storage.local_storage import TenantLocalFileStorage
from core.domain.exceptions import ResourceNotFoundError, TenantAccessDeniedError


@pytest.fixture
def two_tenants(tmp_path, settings):
    settings.MEDIA_ROOT = tmp_path / "media"
    settings.CELERY_TASK_ALWAYS_EAGER = True

    user_a = User.objects.create_user(
        email="empresa-a@example.test",
        name="Pessoa A",
        password="Sintetico-123",
    )
    company_a = Company.objects.create(
        name="Empresa Sintética A",
        segment="comercio_local",
        initial_balance=Decimal("1000.00"),
    )
    CompanyMembership.objects.create(user=user_a, company=company_a, role="owner")

    user_b = User.objects.create_user(
        email="empresa-b@example.test",
        name="Pessoa B",
        password="Sintetico-123",
    )
    company_b = Company.objects.create(
        name="Empresa Sintética B",
        segment="restaurante",
        initial_balance=Decimal("500.00"),
    )
    CompanyMembership.objects.create(user=user_b, company=company_b, role="owner")

    return {
        "user_a": user_a,
        "company_a": company_a,
        "user_b": user_b,
        "company_b": company_b,
    }


@pytest.mark.django_db
def test_authenticated_user_without_company_receives_403() -> None:
    user_without_company = User.objects.create_user(
        email="sem-empresa@example.test",
        name="Sem Empresa",
        password="Sintetico-123",
    )
    client = APIClient()
    client.force_authenticate(user=user_without_company)

    session_res = client.get("/api/v1/session")
    assert session_res.status_code == 200
    assert session_res.json()["company"] is None

    imports_res = client.get("/api/v1/imports")
    assert imports_res.status_code == 403
    assert imports_res.json()["code"] == "company_required"


@pytest.mark.django_db
def test_two_companies_cannot_list_read_edit_or_import_across_tenants(two_tenants) -> None:
    client_a = APIClient()
    client_a.force_authenticate(user=two_tenants["user_a"])

    client_b = APIClient()
    client_b.force_authenticate(user=two_tenants["user_b"])

    csv_file = SimpleUploadedFile(
        "empresa-a.csv",
        b"id,data,valor,descricao\nA-1,2026-10-01,100.00,Venda A\n",
        content_type="text/csv",
    )
    upload_a = client_a.post(
        "/api/v1/imports",
        {"type": "receivable", "file": csv_file},
        format="multipart",
        HTTP_IDEMPOTENCY_KEY="upload-a-1",
    )
    assert upload_a.status_code == 202
    job_a_id = upload_a.json()["id"]
    job_a_status = upload_a.json()["status"]
    assert job_a_status in {"processing", "review", "completed"}

    # Retrying with the same Idempotency-Key replays the same result without duplicating jobs.
    replay_a = client_a.post(
        "/api/v1/imports",
        {
            "type": "receivable",
            "file": SimpleUploadedFile(
                "empresa-a.csv",
                b"id,data,valor,descricao\nA-1,2026-10-01,100.00,Venda A\n",
                content_type="text/csv",
            ),
        },
        format="multipart",
        HTTP_IDEMPOTENCY_KEY="upload-a-1",
    )
    assert replay_a.status_code == 202
    assert replay_a.json()["id"] == job_a_id
    assert ImportJobRecord.objects.for_company(two_tenants["company_a"].id).count() == 1

    # Empresa B cannot list Empresa A's jobs.
    list_b = client_b.get("/api/v1/imports")
    assert list_b.status_code == 200
    assert list_b.json() == []

    # Empresa B cannot read Empresa A's job even with the known UUID.
    read_b = client_b.get(f"/api/v1/imports/{job_a_id}")
    assert read_b.status_code == 404
    assert read_b.json()["message"] == "Importação não encontrada."

    # Empresa B cannot cancel/edit Empresa A's job even with the known UUID.
    cancel_b = client_b.post(f"/api/v1/imports/{job_a_id}/cancel")
    assert cancel_b.status_code == 404
    assert ImportJobRecord.unscoped.get(id=job_a_id).status == job_a_status

    # Empresa B cannot import on behalf of Empresa A by forging company_id in the payload.
    forged_upload = client_b.post(
        "/api/v1/imports",
        {
            "type": "payable",
            "company": str(two_tenants["company_a"].id),
            "company_id": str(two_tenants["company_a"].id),
            "file": SimpleUploadedFile(
                "empresa-b.csv",
                b"id,data,valor,descricao\nB-1,2026-10-02,50.00,Compra B\n",
                content_type="text/csv",
            ),
        },
        format="multipart",
        HTTP_IDEMPOTENCY_KEY="upload-a-1",
    )
    assert forged_upload.status_code == 202
    job_b_id = forged_upload.json()["id"]
    assert job_b_id != job_a_id
    assert ImportJobRecord.objects.for_company(two_tenants["company_a"].id).count() == 1
    assert ImportJobRecord.objects.for_company(two_tenants["company_b"].id).count() == 1


@pytest.mark.django_db
def test_storage_and_celery_worker_enforce_company_scope(two_tenants) -> None:
    company_a = two_tenants["company_a"]
    company_b = two_tenants["company_b"]

    storage = TenantLocalFileStorage()
    key_a = storage.save_bytes(company_a.id, "imports/lote/segredo.csv", b"dados-empresa-a")
    assert str(company_a.id) in key_a
    assert storage.exists(company_a.id, "imports/lote/segredo.csv")
    assert not storage.exists(company_b.id, "imports/lote/segredo.csv")

    with pytest.raises(ResourceNotFoundError):
        storage.read_bytes(company_b.id, "imports/lote/segredo.csv")

    stored = StoredImportFile.objects.create(
        company_id=company_a.id,
        original_filename="segredo.csv",
        storage_key=key_a,
        size_bytes=15,
        sha256="0" * 64,
    )
    job_a = ImportJobRecord.objects.create(
        id=uuid.uuid4(),
        company_id=company_a.id,
        stored_file=stored,
        created_by=two_tenants["user_a"],
        import_type="receivable",
        filename="segredo.csv",
        status="queued",
    )

    with pytest.raises(TenantAccessDeniedError):
        verify_company_job_scope.run(str(company_b.id), str(job_a.id))

    job_a.refresh_from_db()
    assert job_a.status == "queued"

    with pytest.raises(TenantAccessDeniedError):
        ImportJobRecord.objects.for_company(None)
