from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import date
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from typing import Any

from core.ports.ai import AIRequest

TWO_PLACES = Decimal("0.01")

_ISO_DATE_RE = re.compile(r"\b(\d{4})-(\d{2})-(\d{2})\b")
_BR_DATE_RE = re.compile(r"\b(\d{1,2})/(\d{1,2})/(\d{4})\b")
_BRL_CURRENCY_RE = re.compile(
    r"r\$\s*(\d{1,3}(?:\.\d{3})*,\d{1,2}|\d+,\d{1,2}|\d{1,3}(?:\.\d{3})+|\d+(?:\.\d{1,2})?)",
    flags=re.IGNORECASE,
)
_BRL_THOUSANDS_DECIMAL_RE = re.compile(r"\b(\d{1,3}(?:\.\d{3})+,\d{1,2})\b")
_DECIMAL_COMMA_RE = re.compile(r"\b(\d+,\d{1,2})\b")
_DECIMAL_DOT_RE = re.compile(r"\b(\d+\.\d{2})\b")
_PAYMENT_KEYWORD_AMOUNT_RE = re.compile(
    r"(?:pagar|paga|pagamento|prometeu|quitar|transferir|pix|valor|em|ate|até)\s+"
    r"(?:de\s+)?(?:r\$\s*)?(\d{1,3}(?:\.\d{3})+|\d+(?:[.,]\d{1,2})?)",
    flags=re.IGNORECASE,
)


@dataclass(frozen=True, slots=True)
class PromiseSuggestion:
    title: str
    amount: Decimal
    promise_date: date

    def to_dict(self) -> dict[str, str]:
        return {
            "title": self.title,
            "amount": f"{self.amount:.2f}",
            "date": self.promise_date.isoformat(),
        }


def _parse_date_match(text: str) -> date | None:
    iso_match = _ISO_DATE_RE.search(text)
    if iso_match:
        year, month, day = (int(part) for part in iso_match.groups())
        try:
            return date(year, month, day)
        except ValueError:
            pass

    br_match = _BR_DATE_RE.search(text)
    if br_match:
        day, month, year = (int(part) for part in br_match.groups())
        try:
            return date(year, month, day)
        except ValueError:
            pass

    return None


def _normalize_numeric_token(raw: str) -> Decimal | None:
    token = raw.strip()
    if not token:
        return None
    if "," in token and "." in token:
        normalized = token.replace(".", "").replace(",", ".")
    elif "," in token:
        normalized = token.replace(",", ".")
    elif re.fullmatch(r"\d{1,3}(?:\.\d{3})+", token):
        normalized = token.replace(".", "")
    else:
        normalized = token

    try:
        value = Decimal(normalized).quantize(TWO_PLACES, rounding=ROUND_HALF_UP)
    except (InvalidOperation, ValueError):
        return None
    if value <= Decimal("0.00"):
        return None
    return value


def _parse_positive_amount(text: str) -> Decimal | None:
    # Remove explicit dates so digits like 2026 or 20.04 are not confused with currency amounts.
    without_dates = _ISO_DATE_RE.sub(" ", text)
    without_dates = _BR_DATE_RE.sub(" ", without_dates)

    for pattern in (
        _BRL_CURRENCY_RE,
        _BRL_THOUSANDS_DECIMAL_RE,
        _DECIMAL_COMMA_RE,
        _DECIMAL_DOT_RE,
        _PAYMENT_KEYWORD_AMOUNT_RE,
    ):
        for match in pattern.finditer(without_dates):
            parsed = _normalize_numeric_token(match.group(1))
            if parsed is not None:
                return parsed
    return None


def _default_title(text: str) -> str:
    cleaned = re.sub(r"\s+", " ", text).strip()
    if not cleaned:
        return "Promessa de pagamento"
    if len(cleaned) <= 90:
        return cleaned
    return f"{cleaned[:87].rstrip()}..."


def _refine_with_ai(
    *,
    ai_port: Any | None,
    text: str,
    fallback: PromiseSuggestion,
    reference_date: date,
) -> PromiseSuggestion:
    if ai_port is None:
        return fallback
    try:
        if hasattr(ai_port, "generate"):
            response = ai_port.generate(
                AIRequest(
                    prompt_key="promise_extraction",
                    rendered_prompt=(
                        f"Data referencia: {reference_date.isoformat()}\n"
                        f"Nota: {text}"
                    ),
                    system_instruction=(
                        "Extraia titulo curto, valor decimal positivo e data YYYY-MM-DD "
                        "em JSON sem inventar dados."
                    ),
                    max_output_tokens=160,
                    timeout_seconds=6.0,
                    contains_sensitive_data=True,
                )
            )
        else:
            return fallback
        data = json.loads(response.content.strip())
        if not isinstance(data, dict):
            return fallback
        title = str(data.get("title") or "").strip()[:160] or fallback.title
        raw_amount = Decimal(str(data.get("amount"))).quantize(TWO_PLACES, rounding=ROUND_HALF_UP)
        raw_date = date.fromisoformat(str(data.get("date")))
        if raw_amount <= Decimal("0.00"):
            return fallback
        return PromiseSuggestion(title=title, amount=raw_amount, promise_date=raw_date)
    except Exception:
        return fallback


def extract_promise_suggestion(
    text: str,
    *,
    reference_date: date,
    ai_port: Any | None = None,
) -> PromiseSuggestion | None:
    """Extracts a structured payment promise suggestion from a CRM note, if present."""
    if not text or not text.strip():
        return None
    if re.search(r"-\s*(?:r\$\s*)?\d+(?:[.,]\d{1,2})?", text, flags=re.IGNORECASE):
        # Guard against negative amounts explicitly written in text when no positive R$ exists
        if not _BRL_CURRENCY_RE.search(text):
            return None

    promise_date = _parse_date_match(text)
    amount = _parse_positive_amount(text)
    if promise_date is None or amount is None:
        return None

    suggestion = PromiseSuggestion(
        title=_default_title(text),
        amount=amount,
        promise_date=promise_date,
    )
    return _refine_with_ai(
        ai_port=ai_port,
        text=text,
        fallback=suggestion,
        reference_date=reference_date,
    )
