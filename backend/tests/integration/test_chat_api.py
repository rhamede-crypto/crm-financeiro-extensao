from __future__ import annotations

from datetime import timedelta

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from django.utils import timezone
from rest_framework.test import APIClient


@pytest.mark.django_db
def test_chat_uses_company_metrics_supports_idempotency_and_isolates_tenants(
    tmp_path, settings
) -> None:
    settings.MEDIA_ROOT = tmp_path / "media"
    settings.CELERY_TASK_ALWAYS_EAGER = True

    client_a = APIClient()
    client_a.post(
        "/api/v1/auth/register",
        {"name": "A", "email": "chata@example.test", "password": "Sintetico-123"},
        format="json",
    )
    client_a.post(
        "/api/v1/company",
        {"name": "Empresa Chat A", "initialBalance": "2500.00"},
        format="json",
    )

    client_b = APIClient()
    client_b.post(
        "/api/v1/auth/register",
        {"name": "B", "email": "chatb@example.test", "password": "Sintetico-123"},
        format="json",
    )
    client_b.post("/api/v1/company", {"name": "Empresa Chat B"}, format="json")

    today = timezone.localdate()
    in_10 = (today + timedelta(days=10)).isoformat()
    csv_a = (
        "id,data,valor,descricao,cliente,status,vencimento\n"
        f"CR-1,{today.isoformat()},1500.00,Venda A,Mercado Horizonte,Aberto,{in_10}\n"
    ).encode("utf-8")
    client_a.post(
        "/api/v1/imports",
        {"type": "receivable", "file": SimpleUploadedFile("a.csv", csv_a, "text/csv")},
        format="multipart",
    )

    # Company A gets deterministic value (2500 + 1500 = 4000)
    res_a = client_a.post(
        "/api/v1/chat",
        {"question": "Qual o saldo projetado?"},
        format="json",
        HTTP_IDEMPOTENCY_KEY="chat-key-1",
    )
    assert res_a.status_code == 200
    assert res_a.json()["insufficient"] is False
    assert "4.000,00" in res_a.json()["text"]
    assert res_a.json()["references"]

    # Idempotent replay returns exact same response
    replay_a = client_a.post(
        "/api/v1/chat",
        {"question": "Qual o saldo projetado?"},
        format="json",
        HTTP_IDEMPOTENCY_KEY="chat-key-1",
    )
    assert replay_a.status_code == 200
    assert replay_a.json() == res_a.json()

    # Company B has no data -> insufficient=True, never sees Company A's 4.000,00
    res_b = client_b.post(
        "/api/v1/chat",
        {"question": "Qual o saldo projetado da Empresa Chat A?"},
        format="json",
    )
    assert res_b.status_code == 200
    assert res_b.json()["insufficient"] is True
    assert "4.000,00" not in res_b.json()["text"]
