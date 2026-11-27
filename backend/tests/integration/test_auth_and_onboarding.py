from __future__ import annotations

import pytest
from rest_framework.test import APIClient


@pytest.mark.django_db
def test_register_onboarding_login_logout_and_session_lifecycle() -> None:
    client = APIClient()

    register_res = client.post(
        "/api/v1/auth/register",
        {
            "name": "Nicolas",
            "email": "Nicolas@Example.Test ",
            "password": "Sintetico-123",
        },
        format="json",
    )
    assert register_res.status_code == 201
    assert "csrftoken" in register_res.cookies
    assert register_res.json() == {
        "user": {"name": "Nicolas", "email": "nicolas@example.test"},
        "company": None,
    }

    # Duplicate email returns 422 with field error
    dup_res = client.post(
        "/api/v1/auth/register",
        {
            "name": "Outro",
            "email": "nicolas@example.test",
            "password": "Sintetico-123",
        },
        format="json",
    )
    assert dup_res.status_code == 422
    assert dup_res.json()["errors"]["email"] == ["E-mail já cadastrado."]

    # Onboarding persists segment, simplified tax regime, and decimal initial balance
    company_res = client.post(
        "/api/v1/company",
        {
            "name": "Bar do Centro",
            "segment": "bar",
            "taxRegime": "simples_nacional",
            "initialBalance": "12500.50",
        },
        format="json",
    )
    assert company_res.status_code == 201
    assert company_res.json() == {
        "user": {"name": "Nicolas", "email": "nicolas@example.test"},
        "company": {
            "name": "Bar do Centro",
            "segment": "bar",
            "taxRegime": "simples_nacional",
            "initialBalance": "12500.50",
        },
    }

    # Re-onboarding returns 409 conflict
    conflict_res = client.post(
        "/api/v1/company",
        {"name": "Outra Empresa"},
        format="json",
    )
    assert conflict_res.status_code == 409

    # Logout clears session
    logout_res = client.post("/api/v1/auth/logout")
    assert logout_res.status_code == 204
    assert client.get("/api/v1/session").status_code == 401
    assert client.get("/api/v1/imports").status_code == 401

    # Invalid login fails with 401
    bad_login = client.post(
        "/api/v1/auth/login",
        {"email": "nicolas@example.test", "password": "wrong-password"},
        format="json",
    )
    assert bad_login.status_code == 401

    # Valid login restores user and company
    good_login = client.post(
        "/api/v1/auth/login",
        {"email": "NICOLAS@example.test", "password": "Sintetico-123"},
        format="json",
    )
    assert good_login.status_code == 200
    assert good_login.json()["company"]["name"] == "Bar do Centro"
    assert client.get("/api/v1/imports").status_code == 200


@pytest.mark.django_db
def test_onboarding_validates_decimal_balance_and_defaults_and_isolates_companies() -> None:
    client_a = APIClient()
    client_a.post(
        "/api/v1/auth/register",
        {"name": "A", "email": "a@example.test", "password": "Sintetico-123"},
        format="json",
    )
    bad_balance = client_a.post(
        "/api/v1/company",
        {"name": "Empresa A", "segment": "clínica", "initialBalance": "abc"},
        format="json",
    )
    assert bad_balance.status_code == 422
    assert "initialBalance" in bad_balance.json()["errors"]

    ok_a = client_a.post(
        "/api/v1/company",
        {"name": "Clínica A", "segment": "clínica"},
        format="json",
    )
    assert ok_a.status_code == 201
    assert ok_a.json()["company"] == {
        "name": "Clínica A",
        "segment": "clinica",
        "taxRegime": "simples_nacional",
        "initialBalance": "0.00",
    }

    client_b = APIClient()
    client_b.post(
        "/api/v1/auth/register",
        {"name": "B", "email": "b@example.test", "password": "Sintetico-123"},
        format="json",
    )
    ok_b = client_b.post(
        "/api/v1/company",
        {"name": "Restaurante B", "segment": "restaurante", "taxRegime": "mei"},
        format="json",
    )
    assert ok_b.status_code == 201
    assert client_a.get("/api/v1/session").json()["company"]["name"] == "Clínica A"
    assert client_b.get("/api/v1/session").json()["company"]["name"] == "Restaurante B"
