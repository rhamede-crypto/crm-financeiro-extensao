from __future__ import annotations

from datetime import timedelta

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from django.utils import timezone
from rest_framework.test import APIClient


@pytest.mark.django_db
def test_customer_detail_exposes_ltv_average_score_and_partial_invoices(
    tmp_path, settings
) -> None:
    settings.MEDIA_ROOT = tmp_path / "media"
    settings.CELERY_TASK_ALWAYS_EAGER = True

    client = APIClient()
    client.post(
        "/api/v1/auth/register",
        {"name": "Metrics", "email": "metrics@example.test", "password": "Sintetico-123"},
        format="json",
    )
    client.post("/api/v1/company", {"name": "Empresa Metrics"}, format="json")

    today = timezone.localdate()
    d_paid = (today - timedelta(days=20)).isoformat()
    d_late = (today - timedelta(days=10)).isoformat()

    csv_data = (
        "id,data,valor,valor pago,descricao,cliente,status,vencimento\n"
        f"F-1,{d_paid},1000.00,1000.00,Fatura F-1,Mercado Horizonte,Pago,{d_paid}\n"
        f"F-2,{d_late},600.00,200.00,Fatura F-2,Mercado Horizonte,Aberto,{d_late}\n"
    ).encode("utf-8")

    client.post(
        "/api/v1/imports",
        {"type": "receivable", "file": SimpleUploadedFile("m.csv", csv_data, "text/csv")},
        format="multipart",
    )

    contact_id = client.get("/api/v1/contacts?type=customer").json()[0]["id"]
    detail = client.get(f"/api/v1/contacts/{contact_id}").json()

    assert detail["metrics"]["ltv"] == "1200.00"
    assert detail["metrics"]["average"] == "600.00"
    assert detail["metrics"]["score"] == "Atraso Recorrente"
    assert detail["metrics"]["openBalance"] == "400.00"
    assert len(detail["invoices"]) == 1
    assert detail["invoices"][0]["amount"] == "400.00"
    assert len(detail["history"]) == 2
