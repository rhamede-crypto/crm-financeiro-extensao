from __future__ import annotations

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from rest_framework.test import APIClient


@pytest.mark.django_db
def test_etl_generates_contacts_preserves_ids_on_reprocess_and_isolates_tenants(
    tmp_path, settings
) -> None:
    settings.MEDIA_ROOT = tmp_path / "media"
    settings.CELERY_TASK_ALWAYS_EAGER = True

    client_a = APIClient()
    client_a.post(
        "/api/v1/auth/register",
        {"name": "A", "email": "crma@example.test", "password": "Sintetico-123"},
        format="json",
    )
    client_a.post("/api/v1/company", {"name": "Empresa CRM A"}, format="json")

    client_b = APIClient()
    client_b.post(
        "/api/v1/auth/register",
        {"name": "B", "email": "crmb@example.test", "password": "Sintetico-123"},
        format="json",
    )
    client_b.post("/api/v1/company", {"name": "Empresa CRM B"}, format="json")

    receivable_csv = (
        b"id,data,valor,descricao,cliente,cnpj,telefone,email,status\n"
        b"F-1,2026-10-01,800.00,Venda 1,Mercado Horizonte,12.345.678/0001-90,"
        b"(11) 98765-4321,financeiro@horizonte.test,Aberto\n"
    )
    payable_csv = (
        b"id,data,valor,descricao,fornecedor,status\n"
        b"P-1,2026-10-02,420.00,Caixas,Distribuidora Aurora,Pago\n"
    )
    client_a.post(
        "/api/v1/imports",
        {"type": "receivable", "file": SimpleUploadedFile("rec.csv", receivable_csv, "text/csv")},
        format="multipart",
    )
    client_a.post(
        "/api/v1/imports",
        {"type": "payable", "file": SimpleUploadedFile("pay.csv", payable_csv, "text/csv")},
        format="multipart",
    )

    contacts_a = client_a.get("/api/v1/contacts").json()
    assert len(contacts_a) == 2
    cust = client_a.get("/api/v1/contacts?query=horizonte&type=customer").json()
    assert len(cust) == 1
    cust_id = cust[0]["id"]

    # Reprocessing F-1 as Pago preserves the exact same Contact UUID
    reprocess_csv = (
        b"id,data,valor,descricao,cliente,cnpj,telefone,email,status\n"
        b"F-1,2026-10-01,800.00,Venda 1,Mercado Horizonte,12.345.678/0001-90,"
        b"(11) 98765-4321,financeiro@horizonte.test,Pago\n"
    )
    client_a.post(
        "/api/v1/imports",
        {"type": "receivable", "file": SimpleUploadedFile("rec2.csv", reprocess_csv, "text/csv")},
        format="multipart",
    )
    assert client_a.get("/api/v1/contacts?type=customer").json()[0]["id"] == cust_id

    # Homonym with different CNPJ creates a second contact marked needsReview=True
    homonym_csv = (
        b"id,data,valor,descricao,cliente,cnpj,status\n"
        b"F-2,2026-10-05,300.00,Venda 2,Mercado Horizonte,98.765.432/0001-10,Aberto\n"
    )
    client_a.post(
        "/api/v1/imports",
        {"type": "receivable", "file": SimpleUploadedFile("hom.csv", homonym_csv, "text/csv")},
        format="multipart",
    )
    customers_a = client_a.get("/api/v1/contacts?type=customer").json()
    assert len(customers_a) == 2
    assert all(item["needsReview"] is True for item in customers_a)

    # Tenant isolation: Company B cannot list or inspect Company A's contact
    assert client_b.get("/api/v1/contacts").json() == []
    assert client_b.get(f"/api/v1/contacts/{cust_id}").status_code == 404
