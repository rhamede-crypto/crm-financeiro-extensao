from __future__ import annotations

from datetime import timedelta

import pytest
from django.core import mail
from django.core.files.uploadedfile import SimpleUploadedFile
from django.utils import timezone
from rest_framework.test import APIClient

from adapters.persistence.models import CollectionDispatch


@pytest.mark.django_db
def test_collection_preview_send_idempotency_failures_and_isolation(
    tmp_path, settings, monkeypatch
) -> None:
    settings.MEDIA_ROOT = tmp_path / "media"
    settings.CELERY_TASK_ALWAYS_EAGER = True
    settings.EMAIL_BACKEND = "django.core.mail.backends.locmem.EmailBackend"
    settings.EMAIL_HOST = "mailpit"

    client_a = APIClient()
    client_a.post(
        "/api/v1/auth/register",
        {"name": "Cob", "email": "coba@example.test", "password": "Sintetico-123"},
        format="json",
    )
    client_a.post("/api/v1/company", {"name": "Empresa A"}, format="json")

    client_b = APIClient()
    client_b.post(
        "/api/v1/auth/register",
        {"name": "Cob B", "email": "cobb@example.test", "password": "Sintetico-123"},
        format="json",
    )
    client_b.post("/api/v1/company", {"name": "Empresa B"}, format="json")

    due = (timezone.localdate() - timedelta(days=5)).isoformat()
    csv_data = (
        "id,data,valor,descricao,cliente,email,status,vencimento\n"
        f"F-018,{due},8450.00,Fatura F-018,Mercado Horizonte,fin@horizonte.test,Aberto,{due}\n"
        f"F-019,{due},300.00,Fatura F-019,Sem Email,,Aberto,{due}\n"
    ).encode("utf-8")
    client_a.post(
        "/api/v1/imports",
        {"type": "receivable", "file": SimpleUploadedFile("cob.csv", csv_data, "text/csv")},
        format="multipart",
    )

    with_email_id = client_a.get("/api/v1/contacts?query=horizonte").json()[0]["id"]
    no_email_id = client_a.get("/api/v1/contacts?query=sem").json()[0]["id"]

    # Missing recipient returns available=False
    unavail = client_a.post(
        f"/api/v1/contacts/{no_email_id}/collections/preview",
        {"tone": "friendly"},
        format="json",
    )
    assert unavail.status_code == 200
    assert unavail.json()["available"] is False

    # 3 tones work and cite verified invoice amount
    for tone in ("friendly", "firm", "negotiation"):
        prev = client_a.post(
            f"/api/v1/contacts/{with_email_id}/collections/preview",
            {"tone": tone},
            format="json",
        )
        assert prev.status_code == 200
        assert prev.json()["available"] is True
        assert "8.450,00" in prev.json()["text"]

    # Send with Idempotency-Key sends exactly 1 email
    send_payload = {
        "tone": "negotiation",
        "text": "Mensagem editada para Mercado Horizonte.",
        "channel": "email",
    }
    send1 = client_a.post(
        f"/api/v1/contacts/{with_email_id}/collections/send",
        send_payload,
        format="json",
        HTTP_IDEMPOTENCY_KEY="col-1",
    )
    assert send1.status_code == 200
    assert send1.json()["status"] == "sent"
    assert len(mail.outbox) == 1

    replay = client_a.post(
        f"/api/v1/contacts/{with_email_id}/collections/send",
        send_payload,
        format="json",
        HTTP_IDEMPOTENCY_KEY="col-1",
    )
    assert replay.status_code == 200
    assert replay.json() == send1.json()
    assert len(mail.outbox) == 1
    assert CollectionDispatch.unscoped.count() == 1

    # Tenant isolation: Company B gets 404
    assert (
        client_b.post(
            f"/api/v1/contacts/{with_email_id}/collections/preview",
            {"tone": "friendly"},
            format="json",
        ).status_code
        == 404
    )

    # Provider failure is recorded safely
    def boom(*args, **kwargs):
        raise RuntimeError("smtp error")

    monkeypatch.setattr("django.core.mail.EmailMessage.send", boom)
    failed = client_a.post(
        f"/api/v1/contacts/{with_email_id}/collections/send",
        {"tone": "firm", "text": "Segunda tentativa.", "channel": "email"},
        format="json",
        HTTP_IDEMPOTENCY_KEY="col-2",
    )
    assert failed.status_code == 200
    assert failed.json()["status"] == "failed"
    assert failed.json()["reason"] == "RuntimeError"
