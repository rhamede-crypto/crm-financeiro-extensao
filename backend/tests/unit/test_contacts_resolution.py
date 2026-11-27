from __future__ import annotations

from core.services.contacts import (
    ContactCandidate,
    normalize_document,
    normalize_phone,
    resolve_contact_match,
)


def test_normalize_document_and_phone() -> None:
    assert normalize_document("12.345.678/0001-90") == "12345678000190"
    assert normalize_document("123.456.789-00") == "12345678900"
    assert normalize_document("abc") == ""
    assert normalize_phone("+55 (11) 98765-4321") == "11987654321"
    assert normalize_phone("(11) 3456-7890") == "1134567890"


def test_contact_match_uses_cnpj_phone_and_flags_homonyms_for_review() -> None:
    existing = [
        ContactCandidate(
            id="c-1",
            contact_type="customer",
            name="Joao Silva",
            normalized_name="joao silva",
            normalized_document="11122233344",
            normalized_phone="11999990000",
            email="",
        )
    ]

    # Same CNPJ matches even with slight name variation
    by_doc = resolve_contact_match(
        existing,
        contact_type="customer",
        name="Joao Silva",
        document="111.222.333-44",
        phone="",
    )
    assert by_doc.action == "reuse"
    assert by_doc.matched_contact.id == "c-1"
    assert by_doc.needs_review is False

    # Same name but different CPF -> homonym! Creates separate contact flagged for review
    homonym = resolve_contact_match(
        existing,
        contact_type="customer",
        name="Joao Silva",
        document="999.888.777-66",
        phone="11911112222",
    )
    assert homonym.action == "create"
    assert homonym.needs_review is True
    assert homonym.review_reason == "homonym_detected"
    assert homonym.flag_existing_review.id == "c-1"
