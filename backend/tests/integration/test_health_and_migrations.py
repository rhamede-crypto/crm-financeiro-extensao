from __future__ import annotations

import pytest
from django.core.management import call_command
from rest_framework.test import APIClient


@pytest.mark.django_db
def test_health_endpoint_reports_ok_with_eager_broker(settings) -> None:
    settings.CELERY_TASK_ALWAYS_EAGER = True
    client = APIClient()
    response = client.get("/api/v1/health")
    assert response.status_code == 200
    assert response.json() == {
        "status": "ok",
        "dependencies": {
            "database": {"ok": True, "detail": ""},
            "broker": {"ok": True, "detail": "eager"},
        },
    }


@pytest.mark.django_db
def test_migrations_are_in_sync_with_models() -> None:
    call_command("makemigrations", check=True, dry_run=True)
