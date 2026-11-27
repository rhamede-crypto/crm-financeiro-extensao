from __future__ import annotations

from datetime import timedelta

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from django.utils import timezone
from rest_framework.test import APIClient


@pytest.mark.django_db
def test_dashboard_ranking_returns_top_overdue_and_updates_on_settlement(
    tmp_path, settings
) -> None:
    settings.MEDIA_ROOT = tmp_path / "media"
    settings.CELERY_TASK_ALWAYS_EAGER = True

    client = APIClient()
    client.post(
        "/api/v1/auth/register",
        {"name": "Cob", "email": "cob@example.test", "password": "Sintetico-123"},
        format="json",
    )
    client.post(
        "/api/v1/company",
        {"name": "Empresa Cobranca", "initialBalance": "-1000.00"},
        format="json",
    )

    today = timezone.localdate()
    d5 = (today - timedelta(days=5)).isoformat()
    d10 = (today - timedelta(days=10)).isoformat()

    csv_open = (
        "id,data,valor,descricao,cliente,status,vencimento\n"
        f"CR-1,{d10},800.00,Fatura 1,Mercado Horizonte,Aberto,{d10}\n"
        f"CR-2,{d5},200.00,Fatura 2,Padaria Sul,Aberto,{d5}\n"
    ).encode("utf-8")
    up1 = client.post(
        "/api/v1/imports",
        {"type": "receivable", "file": SimpleUploadedFile("r1.csv", csv_open, "text/csv")},
        format="multipart",
    )
    assert up1.status_code == 202

    dash1 = client.get("/api/v1/dashboard").json()
    assert len(dash1["ranking"]) == 2
    assert dash1["ranking"][0]["name"] == "Mercado Horizonte"
    assert dash1["ranking"][0]["amount"] == "800.00"
    assert dash1["ranking"][0]["days"] == 10

    # Settle CR-1 -> Mercado Horizonte leaves the delinquency ranking
    csv_paid = (
        "id,data,valor,descricao,cliente,status,vencimento\n"
        f"CR-1,{d10},800.00,Fatura 1,Mercado Horizonte,Pago,{d10}\n"
    ).encode("utf-8")
    client.post(
        "/api/v1/imports",
        {"type": "receivable", "file": SimpleUploadedFile("r2.csv", csv_paid, "text/csv")},
        format="multipart",
    )
    dash2 = client.get("/api/v1/dashboard").json()
    assert [row["name"] for row in dash2["ranking"]] == ["Padaria Sul"]
