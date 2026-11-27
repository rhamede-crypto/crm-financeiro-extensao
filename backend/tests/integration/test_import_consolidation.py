from __future__ import annotations

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from rest_framework.test import APIClient

from adapters.persistence.models import FinancialEntry


def _setup_client(tmp_path, settings) -> APIClient:
    settings.MEDIA_ROOT = tmp_path / "media"
    settings.CELERY_TASK_ALWAYS_EAGER = True
    client = APIClient()
    client.post(
        "/api/v1/auth/register",
        {"name": "Cons", "email": "cons@example.test", "password": "Sintetico-123"},
        format="json",
    )
    client.post("/api/v1/company", {"name": "Empresa Consolidacao"}, format="json")
    return client


@pytest.mark.django_db
def test_manual_review_confirm_baixa_e_reenvio_idempotente(tmp_path, settings) -> None:
    client = _setup_client(tmp_path, settings)

    # 1. File with unknown column triggers review
    review_csv = (
        b"id,data,Cobrado,descricao,cliente,status,vencimento\n"
        b"CR-01,2026-10-01,845.00,Fatura F-01,Mercado Horizonte,Aberto,2026-10-30\n"
    )
    up1 = client.post(
        "/api/v1/imports",
        {"type": "receivable", "file": SimpleUploadedFile("rev.csv", review_csv, "text/csv")},
        format="multipart",
    )
    assert up1.status_code == 202
    assert up1.json()["status"] == "review"
    job1_id = up1.json()["id"]

    # Duplicate mapping rejected with 422
    bad_confirm = client.post(
        f"/api/v1/imports/{job1_id}/confirm",
        {
            "mapping": {
                "reference": "0",
                "date": "1",
                "amount": "1",
                "description": "3",
                "party": "4",
                "status": "5",
                "due": "6",
            }
        },
        format="json",
    )
    assert bad_confirm.status_code == 422

    # Valid confirmation consolidates entry
    mapping_ok = {
        "reference": "0",
        "date": "1",
        "amount": "2",
        "description": "3",
        "party": "4",
        "status": "5",
        "due": "6",
    }
    confirm1 = client.post(
        f"/api/v1/imports/{job1_id}/confirm",
        {"mapping": mapping_ok, "resolutions": {}},
        format="json",
        HTTP_IDEMPOTENCY_KEY="confirm-1",
    )
    assert confirm1.status_code == 200
    assert confirm1.json()["status"] == "completed"
    assert confirm1.json()["summary"] == {
        "created": 1,
        "updated": 0,
        "unchanged": 0,
        "rejected": 0,
    }

    # Replay with same Idempotency-Key returns same completed result without 409
    confirm_replay = client.post(
        f"/api/v1/imports/{job1_id}/confirm",
        {"mapping": mapping_ok, "resolutions": {}},
        format="json",
        HTTP_IDEMPOTENCY_KEY="confirm-1",
    )
    assert confirm_replay.status_code == 200
    assert confirm_replay.json()["summary"]["created"] == 1

    # 2. Settling CR-01 updates same record (Aberto -> Pago) instead of duplicating
    settled_csv = (
        b"id,data,valor,descricao,cliente,status,vencimento\n"
        b"CR-01,2026-10-01,845.00,Fatura F-01,Mercado Horizonte,Pago,2026-10-30\n"
    )
    up2 = client.post(
        "/api/v1/imports",
        {"type": "receivable", "file": SimpleUploadedFile("baixa.csv", settled_csv, "text/csv")},
        format="multipart",
    )
    assert up2.status_code == 202
    assert up2.json()["status"] == "completed"
    assert up2.json()["summary"]["updated"] == 1
    assert FinancialEntry.unscoped.count() == 1
    assert FinancialEntry.unscoped.first().settled is True

    # 3. Identical resend yields unchanged=1
    up3 = client.post(
        "/api/v1/imports",
        {"type": "receivable", "file": SimpleUploadedFile("reenvio.csv", settled_csv, "text/csv")},
        format="multipart",
    )
    assert up3.status_code == 202
    assert up3.json()["status"] == "completed"
    assert up3.json()["summary"]["unchanged"] == 1
    assert FinancialEntry.unscoped.count() == 1


@pytest.mark.django_db
def test_ambiguity_without_reference_preserves_legitimate_similar_entries(
    tmp_path, settings
) -> None:
    client = _setup_client(tmp_path, settings)

    base_csv = b"data,valor,descricao,cliente\n2026-10-05,50.00,Venda Balcao,Consumidor\n"
    up1 = client.post(
        "/api/v1/imports",
        {"type": "settled", "file": SimpleUploadedFile("dia1.csv", base_csv, "text/csv")},
        format="multipart",
    )
    assert up1.json()["status"] == "completed"
    assert up1.json()["summary"]["created"] == 1

    # Sending similar row without reference stops at review with ambiguity
    up2 = client.post(
        "/api/v1/imports",
        {"type": "settled", "file": SimpleUploadedFile("dia1_bis.csv", base_csv, "text/csv")},
        format="multipart",
    )
    assert up2.json()["status"] == "review"
    assert len(up2.json()["ambiguities"]) == 1
    job2_id = up2.json()["id"]

    # Confirming with resolution='new' keeps both legitimate entries
    resolved = client.post(
        f"/api/v1/imports/{job2_id}/confirm",
        {
            "mapping": {
                "reference": "",
                "date": "0",
                "amount": "1",
                "description": "2",
                "party": "3",
                "status": "",
                "due": "",
            },
            "resolutions": {"0": "new"},
        },
        format="json",
    )
    assert resolved.status_code == 200
    assert resolved.json()["status"] == "completed"
    assert resolved.json()["summary"]["created"] == 1
    assert FinancialEntry.unscoped.count() == 2
