from __future__ import annotations

from datetime import timedelta

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from django.utils import timezone
from rest_framework.test import APIClient


@pytest.mark.django_db
def test_pipeline_deals_lifecycle_optimistic_concurrency_and_settlement_reconciliation(
    tmp_path, settings
) -> None:
    settings.MEDIA_ROOT = tmp_path / "media"
    settings.CELERY_TASK_ALWAYS_EAGER = True
    settings.EMAIL_BACKEND = "django.core.mail.backends.locmem.EmailBackend"
    settings.EMAIL_HOST = "mailpit"

    client_a = APIClient()
    client_a.post(
        "/api/v1/auth/register",
        {"name": "Gestora", "email": "pipea@example.test", "password": "Sintetico-123"},
        format="json",
    )
    client_a.post("/api/v1/company", {"name": "Empresa Pipeline A"}, format="json")

    client_b = APIClient()
    client_b.post(
        "/api/v1/auth/register",
        {"name": "Outro", "email": "pipeb@example.test", "password": "Sintetico-123"},
        format="json",
    )
    client_b.post("/api/v1/company", {"name": "Empresa Pipeline B"}, format="json")

    due = (timezone.localdate() - timedelta(days=7)).isoformat()
    csv_open = (
        "id,data,valor,descricao,cliente,email,status,vencimento\n"
        f"F-018,{due},8450.00,Fatura F-018,Mercado Horizonte,fin@horizonte.test,Aberto,{due}\n"
    ).encode("utf-8")
    client_a.post(
        "/api/v1/imports",
        {"type": "receivable", "file": SimpleUploadedFile("pipe.csv", csv_open, "text/csv")},
        format="multipart",
    )

    deals = client_a.get("/api/v1/deals").json()
    assert len(deals) == 1
    deal = deals[0]
    assert deal["stage"] == "identified"
    assert deal["version"] == 1
    deal_id = deal["id"]
    contact_id = deal["contactId"]

    # Sending collection advances identified -> contacted automatically
    send_res = client_a.post(
        f"/api/v1/contacts/{contact_id}/collections/send",
        {"tone": "friendly", "text": "Lembrete amigavel.", "channel": "email"},
        format="json",
    )
    assert send_res.status_code == 200
    assert send_res.json()["status"] == "sent"

    after_send = client_a.get("/api/v1/deals").json()[0]
    assert after_send["stage"] == "contacted"
    assert after_send["version"] == 2

    # Move to negotiating with expected version=2 -> succeeds (version=3)
    moved = client_a.patch(
        f"/api/v1/deals/{deal_id}",
        {"stage": "negotiating", "version": 2},
        format="json",
    )
    assert moved.status_code == 200
    assert moved.json()["stage"] == "negotiating"
    assert moved.json()["version"] == 3
    assert moved.json()["transitions"][0]["author"] == "Gestora"
    assert moved.json()["transitions"][0]["previousStage"] == "contacted"

    # Stale version=2 triggers 409 conflict
    stale = client_a.patch(
        f"/api/v1/deals/{deal_id}",
        {"stage": "promised", "version": 2},
        format="json",
    )
    assert stale.status_code == 409

    # Company B cannot read or move Company A's deal
    assert client_b.get("/api/v1/deals").json() == []
    assert (
        client_b.patch(
            f"/api/v1/deals/{deal_id}",
            {"stage": "paid", "version": 3},
            format="json",
        ).status_code
        == 404
    )

    # Settling F-018 in ETL reconciles deal automatically to 'paid' and blocks rollback
    csv_paid = (
        "id,data,valor,descricao,cliente,email,status,vencimento\n"
        f"F-018,{due},8450.00,Fatura F-018,Mercado Horizonte,fin@horizonte.test,Pago,{due}\n"
    ).encode("utf-8")
    client_a.post(
        "/api/v1/imports",
        {"type": "receivable", "file": SimpleUploadedFile("paid.csv", csv_paid, "text/csv")},
        format="multipart",
    )

    reconciled = client_a.get("/api/v1/deals").json()[0]
    assert reconciled["stage"] == "paid"
    assert reconciled["version"] == 4

    rollback = client_a.patch(
        f"/api/v1/deals/{deal_id}",
        {"stage": "negotiating", "version": 4},
        format="json",
    )
    assert rollback.status_code == 409
