from __future__ import annotations

from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import pytest
from django.core import mail
from rest_framework.test import APIClient

from adapters.persistence.models import Company, ReminderDispatchLog
from adapters.queue.tasks import dispatch_weekly_reminders


@pytest.mark.django_db
def test_reminders_preferences_dispatch_dedup_freshness_and_safe_failure(
    settings, monkeypatch
) -> None:
    settings.EMAIL_BACKEND = "django.core.mail.backends.locmem.EmailBackend"
    settings.EMAIL_HOST = "mailpit"
    settings.TIME_ZONE = "America/Sao_Paulo"
    settings.FRONTEND_APP_URL = "http://127.0.0.1:5173"

    client = APIClient()
    client.post(
        "/api/v1/auth/register",
        {"name": "Dono", "email": "dono@example.test", "password": "Sintetico-123"},
        format="json",
    )
    client.post("/api/v1/company", {"name": "Mercado Lembrete"}, format="json")

    get_res = client.get("/api/v1/reminders")
    assert get_res.status_code == 200
    assert get_res.json() == {
        "available": True,
        "channel": "E-mail",
        "enabled": False,
        "weekday": "monday",
        "lastConsolidated": None,
    }

    put_res = client.put(
        "/api/v1/reminders",
        {"enabled": True, "weekday": "friday"},
        format="json",
    )
    assert put_res.status_code == 200
    assert put_res.json()["enabled"] is True
    assert put_res.json()["weekday"] == "friday"

    # Wrong weekday -> skipped
    thursday = "2026-10-29T09:00:00-03:00"
    assert dispatch_weekly_reminders.run(now_iso=thursday)["skipped"] == 1
    assert len(mail.outbox) == 0

    # Target weekday (Friday) -> sends email with /importacoes link and logs once
    friday = "2026-10-30T09:00:00-03:00"
    res1 = dispatch_weekly_reminders.run(now_iso=friday)
    assert res1["sent"] == 1
    assert len(mail.outbox) == 1
    assert "http://127.0.0.1:5173/importacoes" in mail.outbox[0].body
    assert mail.outbox[0].to == ["dono@example.test"]

    # Re-running on same ISO week does NOT duplicate email
    res2 = dispatch_weekly_reminders.run(now_iso=friday)
    assert res2["skipped"] == 1
    assert len(mail.outbox) == 1

    # Freshly consolidated company on next week is skipped with skipped_up_to_date
    company = Company.objects.get(name="Mercado Lembrete")
    tz = ZoneInfo("America/Sao_Paulo")
    next_friday = datetime(2026, 11, 6, 9, 0, tzinfo=tz)
    company.last_consolidated_at = next_friday - timedelta(days=2)
    company.save(update_fields=["last_consolidated_at"])

    res3 = dispatch_weekly_reminders.run(now_iso=next_friday.isoformat())
    assert res3["skipped_up_to_date"] == 1
    assert ReminderDispatchLog.objects.for_company(company.id).filter(
        status="skipped_up_to_date"
    ).exists()

    # SMTP failure is recorded safely on another week
    third_friday = datetime(2026, 11, 13, 9, 0, tzinfo=tz)

    def boom(*args, **kwargs):
        raise ConnectionError("smtp down")

    monkeypatch.setattr("django.core.mail.EmailMessage.send", boom)
    res4 = dispatch_weekly_reminders.run(now_iso=third_friday.isoformat())
    assert res4["failed"] == 1
    failed_log = ReminderDispatchLog.objects.for_company(company.id).get(
        iso_year=2026, iso_week=46
    )
    assert failed_log.status == "failed"
    assert failed_log.detail == "ConnectionError"
