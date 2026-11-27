from __future__ import annotations

from datetime import timedelta

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from django.utils import timezone
from rest_framework.test import APIClient


@pytest.mark.django_db
def test_supplier_cost_history_alerts_and_agreements_workflow(tmp_path, settings) -> None:
    settings.MEDIA_ROOT = tmp_path / "media"
    settings.CELERY_TASK_ALWAYS_EAGER = True

    client = APIClient()
    client.post(
        "/api/v1/auth/register",
        {"name": "Compras", "email": "forn@example.test", "password": "Sintetico-123"},
        format="json",
    )
    client.post("/api/v1/company", {"name": "Empresa Fornecedores"}, format="json")

    today = timezone.localdate()
    prev_day = (today - timedelta(days=80)).isoformat()
    curr_day = (today - timedelta(days=15)).isoformat()

    payable_csv = (
        "id,data,valor,descricao,fornecedor,unidade,preco unitario,status\n"
        f"P-1,{prev_day},3800.00,Caixas papelao,Distribuidora Aurora,caixa,38.00,Pago\n"
        f"P-2,{curr_day},4620.00,Caixas papelao,Distribuidora Aurora,caixa,46.20,Pago\n"
    ).encode("utf-8")
    receivable_csv = (
        "id,data,valor,descricao,cliente,status\n"
        f"R-1,{prev_day},10000.00,Vendas,Cliente A,Pago\n"
        f"R-2,{curr_day},10000.00,Vendas,Cliente A,Pago\n"
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

    sup_id = client.get("/api/v1/contacts?type=supplier").json()[0]["id"]
    cust_id = client.get("/api/v1/contacts?type=customer").json()[0]["id"]

    # Agreement on customer must fail with 422
    bad_ag = client.post(
        f"/api/v1/contacts/{cust_id}/agreements",
        {"date": today.isoformat(), "terms": "Nao permitido"},
        format="json",
    )
    assert bad_ag.status_code == 422

    detail_before = client.get(f"/api/v1/contacts/{sup_id}").json()
    assert detail_before["hasComparablePrices"] is True
    assert len(detail_before["alerts"]) == 1
    alert_id = detail_before["alerts"][0]["id"]

    ag = client.post(
        f"/api/v1/contacts/{sup_id}/agreements",
        {
            "date": today.isoformat(),
            "terms": "Manter preco em R$ 40,00 por caixa.",
            "alertId": alert_id,
        },
        format="json",
    )
    assert ag.status_code == 201
    assert ag.json()["alertId"] == alert_id

    detail_after = client.get(f"/api/v1/contacts/{sup_id}").json()
    assert len(detail_after["agreements"]) == 1
    assert detail_after["agreements"][0]["terms"] == "Manter preco em R$ 40,00 por caixa."
