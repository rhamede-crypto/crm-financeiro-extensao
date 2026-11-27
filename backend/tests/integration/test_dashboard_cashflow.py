from __future__ import annotations

from datetime import timedelta

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from django.utils import timezone
from rest_framework.test import APIClient


@pytest.mark.django_db
def test_dashboard_endpoint_returns_projections_and_month_end_alert(tmp_path, settings) -> None:
    settings.MEDIA_ROOT = tmp_path / "media"
    settings.CELERY_TASK_ALWAYS_EAGER = True

    client = APIClient()
    client.post(
        "/api/v1/auth/register",
        {"name": "Fin", "email": "fin@example.test", "password": "Sintetico-123"},
        format="json",
    )
    client.post(
        "/api/v1/company",
        {"name": "Empresa Caixa", "initialBalance": "500.00"},
        format="json",
    )

    today = timezone.localdate()
    in_5_days = (today + timedelta(days=5)).isoformat()
    csv_bytes = (
        "id,data,valor,descricao,cliente,status,vencimento\n"
        f"CP-1,{today.isoformat()},900.00,Fornecedor X,Aurora,Aberto,{in_5_days}\n"
    ).encode("utf-8")

    up = client.post(
        "/api/v1/imports",
        {"type": "payable", "file": SimpleUploadedFile("pagar.csv", csv_bytes, "text/csv")},
        format="multipart",
    )
    assert up.status_code == 202
    assert up.json()["status"] == "completed"

    dash = client.get("/api/v1/dashboard")
    assert dash.status_code == 200
    body = dash.json()
    assert body["negativeDate"] == in_5_days
    assert body["projections"][0]["amount"] == "-400.00"
    assert body["updatedAt"] is not None
    assert body["referenceDate"] == today.isoformat()
