from __future__ import annotations

from datetime import timedelta

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from django.utils import timezone
from rest_framework.test import APIClient

from adapters.persistence.models import FinancialEntry


@pytest.mark.django_db
def test_timeline_notes_promise_confirmation_cashflow_and_tenant_isolation(
    tmp_path, settings
) -> None:
    settings.MEDIA_ROOT = tmp_path / "media"
    settings.CELERY_TASK_ALWAYS_EAGER = True

    client_a = APIClient()
    client_a.post(
        "/api/v1/auth/register",
        {"name": "Gestor A", "email": "gestor-a@example.test", "password": "Sintetico-123"},
        format="json",
    )
    client_a.post(
        "/api/v1/company",
        {"name": "Empresa A", "initialBalance": "500.00"},
        format="json",
    )

    today = timezone.localdate()
    overdue_date = (today - timedelta(days=12)).isoformat()
    promise_date = (today + timedelta(days=10)).isoformat()

    receivable_csv = (
        "id,data,vencimento,valor,descricao,cliente,status\n"
        f"INV-1,{overdue_date},{overdue_date},1200.00,Consultoria mensal,Cliente Promessa,Aberto\n"
    ).encode("utf-8")
    client_a.post(
        "/api/v1/imports",
        {"type": "receivable", "file": SimpleUploadedFile("r.csv", receivable_csv, "text/csv")},
        format="multipart",
    )

    contact_id = client_a.get("/api/v1/contacts?type=customer").json()[0]["id"]
    dash_before = client_a.get("/api/v1/dashboard").json()
    assert dash_before["projections"][0]["amount"] == "500.00"
    assert dash_before["confirmedPromisesTotal"] == "0.00"

    # 1. Plain note without date/amount -> no suggestion
    plain = client_a.post(
        f"/api/v1/contacts/{contact_id}/timeline/notes",
        {"text": "Contato telefonico realizado com o financeiro."},
        format="json",
    )
    assert plain.status_code == 201
    assert plain.json()["suggestion"] is None
    assert plain.json()["author"] == "Gestor A"

    # 2. Note with promise details -> structured suggestion
    note_resp = client_a.post(
        f"/api/v1/contacts/{contact_id}/timeline/notes",
        {"text": f"Cliente prometeu pagar R$ 1.200,00 em {promise_date}."},
        format="json",
    )
    assert note_resp.status_code == 201
    note_data = note_resp.json()
    assert note_data["suggestion"] is not None
    assert note_data["suggestion"]["amount"] == "1200.00"
    assert note_data["suggestion"]["date"] == promise_date
    note_id = note_data["id"]

    # 3. Invalid confirm payload returns 422
    bad_confirm = client_a.post(
        f"/api/v1/contacts/{contact_id}/timeline/{note_id}/confirm",
        {"title": "Promessa", "amount": "-50.00", "date": promise_date},
        format="json",
        HTTP_IDEMPOTENCY_KEY="bad-promise-1",
    )
    assert bad_confirm.status_code == 422

    # 4. Confirm promise with Idempotency-Key
    confirm_payload = {
        "title": "Pagamento acordo INV-1",
        "amount": "1200.00",
        "date": promise_date,
    }
    confirmed = client_a.post(
        f"/api/v1/contacts/{contact_id}/timeline/{note_id}/confirm",
        confirm_payload,
        format="json",
        HTTP_IDEMPOTENCY_KEY="confirm-promise-1",
    )
    assert confirmed.status_code == 201
    assert confirmed.json()["kind"] == "promise"
    assert confirmed.json()["amount"] == "1200.00"

    # Same Idempotency-Key replays exact response without duplication
    replay = client_a.post(
        f"/api/v1/contacts/{contact_id}/timeline/{note_id}/confirm",
        confirm_payload,
        format="json",
        HTTP_IDEMPOTENCY_KEY="confirm-promise-1",
    )
    assert replay.status_code == 201
    assert replay.json()["id"] == confirmed.json()["id"]

    # New Idempotency-Key after suggestion was consumed returns 409
    conflict = client_a.post(
        f"/api/v1/contacts/{contact_id}/timeline/{note_id}/confirm",
        confirm_payload,
        format="json",
        HTTP_IDEMPOTENCY_KEY="confirm-promise-2",
    )
    assert conflict.status_code == 409

    # FinancialEntry.settled must remain False; Deal advances to 'promised'
    entry = FinancialEntry.objects.get(reference="INV-1")
    assert entry.settled is False
    deals = client_a.get("/api/v1/deals").json()
    assert len(deals) == 1
    assert deals[0]["stage"] == "promised"

    # Dashboard projects confirmed promise into 30d cashflow without altering realized balance
    dash_after = client_a.get("/api/v1/dashboard").json()
    assert dash_after["projections"][0]["amount"] == "1700.00"
    assert dash_after["confirmedPromisesTotal"] == "1200.00"

    # Timeline lists note, confirmed promise, and omits unsettled entries from payments
    tl = client_a.get(f"/api/v1/contacts/{contact_id}/timeline")
    assert tl.status_code == 200
    kinds = [item["kind"] for item in tl.json()]
    assert kinds == ["note", "note", "promise"]

    # 5. Re-import same reference as Paid -> avoids double counting promise + settlement
    paid_csv = (
        "id,data,vencimento,valor,descricao,cliente,status\n"
        f"INV-1,{today.isoformat()},{overdue_date},1200.00,"
        "Consultoria mensal,Cliente Promessa,Pago\n"
    ).encode("utf-8")
    client_a.post(
        "/api/v1/imports",
        {"type": "receivable", "file": SimpleUploadedFile("r2.csv", paid_csv, "text/csv")},
        format="multipart",
    )
    dash_paid = client_a.get("/api/v1/dashboard").json()
    assert dash_paid["projections"][0]["amount"] == "1700.00"
    assert dash_paid["confirmedPromisesTotal"] == "0.00"

    tl_after_pay = client_a.get(f"/api/v1/contacts/{contact_id}/timeline").json()
    assert any(item["kind"] == "payment" for item in tl_after_pay)

    # 6. Cross-tenant isolation: Company B gets 404 on Company A's contact timeline
    client_b = APIClient()
    client_b.post(
        "/api/v1/auth/register",
        {"name": "Gestor B", "email": "gestor-b@example.test", "password": "Sintetico-123"},
        format="json",
    )
    client_b.post("/api/v1/company", {"name": "Empresa B"}, format="json")
    assert client_b.get(f"/api/v1/contacts/{contact_id}/timeline").status_code == 404
    assert (
        client_b.post(
            f"/api/v1/contacts/{contact_id}/timeline/notes",
            {"text": "Tentativa indevida"},
            format="json",
        ).status_code
        == 404
    )
