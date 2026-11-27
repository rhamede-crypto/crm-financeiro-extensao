from __future__ import annotations

from datetime import timedelta

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from django.utils import timezone
from rest_framework.test import APIClient


@pytest.mark.django_db
def test_dashboard_exposes_cost_anomaly_alerts_and_insufficient_state(
    tmp_path, settings
) -> None:
    settings.MEDIA_ROOT = tmp_path / "media"
    settings.CELERY_TASK_ALWAYS_EAGER = True

    client = APIClient()
    client.post(
        "/api/v1/auth/register",
        {"name": "Custos", "email": "custos@example.test", "password": "Sintetico-123"},
        format="json",
    )
    client.post("/api/v1/company", {"name": "Empresa Custos"}, format="json")

    dash_empty = client.get("/api/v1/dashboard").json()
    assert dash_empty["costAlertsState"] == "insufficient_data"
    assert dash_empty["alerts"] == []

    today = timezone.localdate()
    prev_day = (today - timedelta(days=80)).isoformat()
    curr_day = (today - timedelta(days=15)).isoformat()

    payable_csv = (
        "id,data,valor,descricao,fornecedor,status\n"
        f"P-1,{prev_day},3800.00,Compra de caixas,Distribuidora Aurora,Pago\n"
        f"P-2,{curr_day},4620.80,Compra de caixas,Distribuidora Aurora,Pago\n"
    ).encode("utf-8")
    receivable_csv = (
        "id,data,valor,descricao,cliente,status\n"
        f"R-1,{prev_day},10000.00,Vendas,Clientes,Pago\n"
        f"R-2,{curr_day},10000.00,Vendas,Clientes,Pago\n"
    ).encode("utf-8")

    client.post(
        "/api/v1/imports",
        {"type": "payable", "file": SimpleUploadedFile("p.csv", payable_csv, "text/csv")},
        format="multipart",
    )
    client.post(
        "/api/v1/imports",
        {"type": "receivable", "file": SimpleUploadedFile("r.csv", receivable_csv, "text/csv")},
        format="multipart",
    )

    dash = client.get("/api/v1/dashboard").json()
    assert dash["costAlertsState"] == "ok"
    assert len(dash["alerts"]) == 1
    assert dash["alerts"][0]["supplier"] == "Distribuidora Aurora"
    assert dash["alerts"][0]["category"] == "Embalagens"
    assert dash["alerts"][0]["change"] == 21.6
    assert dash["alerts"][0]["recommendation"]
