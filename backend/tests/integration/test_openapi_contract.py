from __future__ import annotations

from pathlib import Path

import pytest
import yaml
from django.conf import settings
from rest_framework.test import APIClient


@pytest.mark.django_db
def test_openapi_contract_document_has_required_conventions() -> None:
    contract_path = Path(settings.BASE_DIR) / "contracts" / "openapi.v1.yaml"
    spec = yaml.safe_load(contract_path.read_text(encoding="utf-8"))

    assert spec["info"]["version"] == "1.0.0"
    schemas = spec["components"]["schemas"]
    assert set(schemas["ImportStatus"]["enum"]) == {
        "queued",
        "processing",
        "review",
        "completed",
        "failed",
        "canceled",
    }
    assert schemas["MoneyDecimal"]["example"] == "8450.00"
    assert schemas["CivilDate"]["example"] == "2026-10-30"
    assert set(schemas["ErrorEnvelope"]["required"]) == {"message", "errors"}

    for expected_path in [
        "/health",
        "/session",
        "/auth/register",
        "/auth/login",
        "/auth/logout",
        "/company",
        "/imports/options",
        "/imports",
        "/imports/{id}",
        "/imports/{id}/confirm",
        "/imports/{id}/cancel",
        "/dashboard",
        "/chat",
        "/reminders",
        "/contacts",
        "/contacts/{id}",
        "/contacts/{id}/agreements",
        "/contacts/{id}/timeline",
        "/contacts/{id}/timeline/notes",
        "/contacts/{id}/timeline/{noteId}/confirm",
        "/contacts/{id}/collections/preview",
        "/contacts/{id}/collections/send",
        "/deals",
        "/deals/{id}",
    ]:
        assert expected_path in spec["paths"]


@pytest.mark.django_db
def test_schema_and_docs_endpoints_are_published() -> None:
    client = APIClient()
    json_schema = client.get("/api/v1/schema")
    assert json_schema.status_code == 200
    assert json_schema.json()["info"]["version"] == "1.0.0"

    yaml_schema = client.get("/api/v1/schema?format=yaml")
    assert yaml_schema.status_code == 200
    assert "openapi: 3.1.0" in yaml_schema.content.decode("utf-8")

    docs = client.get("/api/v1/docs")
    assert docs.status_code == 200


@pytest.mark.django_db
def test_session_sets_csrf_cookie_and_returns_401_envelope_when_logged_out() -> None:
    client = APIClient()
    response = client.get("/api/v1/session")
    assert response.status_code == 401
    assert "csrftoken" in response.cookies
    assert response.json() == {
        "message": "Sua sessão expirou.",
        "errors": {},
        "code": "authentication_required",
    }
