from __future__ import annotations

import re
from dataclasses import dataclass
from decimal import Decimal
from typing import Any

from core.domain.value_objects import normalize_ascii_text

DIGITS_RE = re.compile(r"\D+")


def normalize_document(raw: str | None) -> str:
    digits = DIGITS_RE.sub("", str(raw or ""))
    if len(digits) in {11, 14}:
        return digits
    return ""


def normalize_phone(raw: str | None) -> str:
    digits = DIGITS_RE.sub("", str(raw or ""))
    if len(digits) in {12, 13} and digits.startswith("55"):
        digits = digits[2:]
    if len(digits) in {10, 11}:
        return digits
    return ""


def infer_contact_type(entry_type: str, amount: Decimal) -> str:
    if entry_type == "payable" or (entry_type == "settled" and amount < Decimal("0.00")):
        return "supplier"
    return "customer"


@dataclass
class ContactCandidate:
    id: Any
    contact_type: str
    name: str
    normalized_name: str
    normalized_document: str
    normalized_phone: str
    email: str
    needs_review: bool = False
    review_reason: str = ""


@dataclass(frozen=True, slots=True)
class ContactMatchOutcome:
    action: str  # "reuse" | "create"
    matched_contact: ContactCandidate | None
    needs_review: bool
    review_reason: str
    flag_existing_review: ContactCandidate | None = None


def resolve_contact_match(
    existing_contacts: list[ContactCandidate],
    *,
    contact_type: str,
    name: str,
    document: str,
    phone: str,
) -> ContactMatchOutcome:
    """Matches by normalized document/phone first, flagging homonyms and collisions for review."""
    norm_name = normalize_ascii_text(name)
    norm_doc = normalize_document(document)
    norm_phone = normalize_phone(phone)
    same_type = [c for c in existing_contacts if c.contact_type == contact_type]

    if norm_doc:
        doc_matches = [c for c in same_type if c.normalized_document == norm_doc]
        if doc_matches:
            target = doc_matches[0]
            if norm_name and target.normalized_name and target.normalized_name != norm_name:
                return ContactMatchOutcome(
                    action="reuse",
                    matched_contact=target,
                    needs_review=True,
                    review_reason="document_name_collision",
                )
            return ContactMatchOutcome(
                action="reuse",
                matched_contact=target,
                needs_review=False,
                review_reason="",
            )

    if norm_phone:
        phone_matches = [c for c in same_type if c.normalized_phone == norm_phone]
        if phone_matches:
            target = phone_matches[0]
            if (
                norm_doc
                and target.normalized_document
                and target.normalized_document != norm_doc
            ):
                return ContactMatchOutcome(
                    action="create",
                    matched_contact=None,
                    needs_review=True,
                    review_reason="phone_document_collision",
                    flag_existing_review=target,
                )
            if norm_name and target.normalized_name and target.normalized_name != norm_name:
                return ContactMatchOutcome(
                    action="create",
                    matched_contact=None,
                    needs_review=True,
                    review_reason="phone_name_collision",
                    flag_existing_review=target,
                )
            return ContactMatchOutcome(
                action="reuse",
                matched_contact=target,
                needs_review=False,
                review_reason="",
            )

    name_matches = [c for c in same_type if c.normalized_name == norm_name]
    if not name_matches:
        return ContactMatchOutcome(
            action="create",
            matched_contact=None,
            needs_review=False,
            review_reason="",
        )

    if len(name_matches) > 1:
        return ContactMatchOutcome(
            action="create",
            matched_contact=None,
            needs_review=True,
            review_reason="homonym_detected",
        )

    candidate = name_matches[0]
    doc_conflict = bool(
        norm_doc and candidate.normalized_document and candidate.normalized_document != norm_doc
    )
    phone_conflict = bool(
        norm_phone and candidate.normalized_phone and candidate.normalized_phone != norm_phone
    )
    if doc_conflict or phone_conflict:
        return ContactMatchOutcome(
            action="create",
            matched_contact=None,
            needs_review=True,
            review_reason="homonym_detected",
            flag_existing_review=candidate,
        )

    return ContactMatchOutcome(
        action="reuse",
        matched_contact=candidate,
        needs_review=False,
        review_reason="",
    )
