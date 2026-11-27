from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import date, datetime
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from typing import Any

from core.domain.value_objects import normalize_ascii_text
from core.ports.ai import AIRequest
from core.services.privacy import PIISanitizer, sanitize_untrusted_text

TWO_PLACES = Decimal("0.01")
SETTLED_STATUS_TOKENS = {
    "pago",
    "recebido",
    "baixado",
    "quitado",
    "paid",
    "liquidado",
    "efetivado",
}

CANONICAL_FIELDS: tuple[dict[str, Any], ...] = (
    {"id": "reference", "label": "Identificador de origem", "required": False},
    {"id": "date", "label": "Data", "required": True},
    {"id": "amount", "label": "Valor", "required": True},
    {"id": "description", "label": "Descrição", "required": True},
    {"id": "party", "label": "Cliente ou fornecedor", "required": False},
    {"id": "status", "label": "Status", "required": False},
    {"id": "due", "label": "Vencimento", "required": False},
)

EXACT_ALIASES: dict[str, tuple[str, ...]] = {
    "reference": (
        "id",
        "identificador",
        "referencia",
        "codigo",
        "cod",
        "documento",
        "doc",
        "nosso numero",
        "nf",
        "numero",
    ),
    "date": (
        "data",
        "emissao",
        "competencia",
        "data emissao",
        "data de emissao",
        "dt emissao",
        "data lancamento",
        "dt lancamento",
        "data pagamento",
        "dt",
    ),
    "amount": (
        "valor",
        "total",
        "quantia",
        "valor total",
        "valor r$",
        "vlr",
        "montante",
        "valor liquido",
        "valor original",
        "vlr liquido",
        "preco",
    ),
    "description": (
        "descricao",
        "historico",
        "lancamento",
        "discriminacao",
        "detalhes",
        "referente a",
        "titulo",
        "item",
    ),
    "party": (
        "cliente",
        "fornecedor",
        "contato",
        "contraparte",
        "sacado",
        "pagador",
        "favorecido",
        "razao social",
        "nome cliente",
        "nome fornecedor",
        "empresa",
    ),
    "status": (
        "status",
        "situacao",
        "estado",
        "situacao atual",
    ),
    "due": (
        "vencimento",
        "data de vencimento",
        "data vencimento",
        "dt vencimento",
        "vencto",
        "vcto",
        "data vencto",
    ),
}

APPROXIMATE_ALIASES: dict[str, tuple[str, ...]] = {
    "reference": ("id", "identificador", "referencia", "doc"),
    "date": ("data", "emissao", "competencia"),
    "amount": ("valor", "total", "quantia", "vlr"),
    "description": ("descricao", "historico", "lancamento"),
    "party": ("cliente", "fornecedor", "contato", "contraparte", "sacado", "favorecido"),
    "status": ("status", "situacao"),
    "due": ("vencimento", "vencto", "vcto"),
}

AUX_COLUMN_ALIASES: dict[str, tuple[str, ...]] = {
    "category": ("categoria", "centro de custo", "grupo"),
    "paid_amount": ("valor pago", "pago parcial", "valor baixado", "amortizado"),
    "unit_name": ("unidade", "un", "unid"),
    "unit_price": ("preco unitario", "valor unitario", "vlr unitario"),
    "document": ("cnpj", "cpf", "cpf cnpj", "documento contato", "cnpj cpf"),
    "phone": ("telefone", "celular", "whatsapp", "fone"),
    "email": ("email", "e mail", "email contato"),
}

DATE_CELL_RE = re.compile(r"^(\d{4}-\d{2}-\d{2}|\d{1,2}[/.-]\d{1,2}[/.-]\d{4})$")
LOCAL_DATE_RE = re.compile(r"^(\d{1,2})[/.-](\d{1,2})[/.-](\d{4})$")


@dataclass(frozen=True, slots=True)
class TablePreview:
    columns: list[dict[str, str]]
    preview: list[list[str]]
    rows: list[list[str]]


@dataclass(frozen=True, slots=True)
class MappingProposalResult:
    columns: list[dict[str, str]]
    fields: list[dict[str, Any]]
    mapping: dict[str, dict[str, str]]
    selected_mapping: dict[str, str]
    preview: list[list[str]]
    needs_review: bool


@dataclass(frozen=True, slots=True)
class NormalizedRow:
    row_index: int
    entry_type: str
    reference: str
    entry_date: date
    due_date: date | None
    amount: Decimal
    paid_amount: Decimal
    description: str
    normalized_description: str
    party_name: str
    normalized_party: str
    category: str
    unit_name: str
    unit_price: Decimal | None
    settled: bool
    party_document: str = ""
    party_phone: str = ""
    party_email: str = ""

    def equivalence_signature(self) -> tuple[str, str, str, str, str]:
        return (
            self.entry_type,
            self.entry_date.isoformat(),
            f"{self.amount:.2f}",
            self.normalized_description,
            self.normalized_party,
        )

    def state_tuple(self) -> tuple[Any, ...]:
        return (
            self.entry_date,
            self.due_date,
            self.amount,
            self.paid_amount,
            self.description,
            self.normalized_description,
            self.party_name,
            self.normalized_party,
            self.category,
            self.unit_name,
            self.unit_price,
            self.settled,
        )


@dataclass(frozen=True, slots=True)
class DeduplicationResult:
    to_create: list[NormalizedRow]
    to_update: list[tuple[Any, NormalizedRow]]
    ambiguities: list[dict[str, Any]]
    summary: dict[str, int]


def extract_table_preview(table: list[list[str]]) -> TablePreview:
    """Extracts header descriptors and a minimized 4-row preview without external dependencies."""
    header, *data_rows = table
    columns = [
        {
            "id": str(idx),
            "label": str(label or f"Coluna {idx + 1}").strip() or f"Coluna {idx + 1}",
        }
        for idx, label in enumerate(header)
    ]
    preview = [
        [str(row[idx] if idx < len(row) else "")[:120] for idx in range(len(columns))]
        for row in data_rows[:4]
    ]
    return TablePreview(columns=columns, preview=preview, rows=data_rows)


def _clean_header(label: str) -> str:
    text = normalize_ascii_text(label)
    text = re.sub(r"[^a-z0-9$]+", " ", text)
    return " ".join(text.split())


def _looks_like_amount(samples: list[str]) -> bool:
    non_empty = [s for s in samples if s.strip()]
    if not non_empty:
        return False
    valid = 0
    for item in non_empty:
        if parse_money_decimal(item) is not None:
            valid += 1
    return valid >= max(1, len(non_empty) // 2)


def _looks_like_date(samples: list[str]) -> bool:
    non_empty = [s for s in samples if s.strip()]
    if not non_empty:
        return False
    return sum(1 for item in non_empty if DATE_CELL_RE.match(item.strip())) >= max(
        1, len(non_empty) // 2
    )


def _sample_column_values(preview: list[list[str]], col_idx: int) -> list[str]:
    return [row[col_idx] for row in preview if col_idx < len(row)]


def propose_column_mapping(
    table: list[list[str]],
    *,
    import_type: str = "receivable",
    ai_port: Any | None = None,
) -> MappingProposalResult:
    """Proposes semantic column mappings with per-field confidence and human-review flag."""
    extracted = extract_table_preview(table)
    columns = extracted.columns
    fields = [dict(item) for item in CANONICAL_FIELDS]
    normalized_labels = {col["id"]: _clean_header(col["label"]) for col in columns}

    used_columns: set[str] = set()
    proposal: dict[str, dict[str, str]] = {}

    for field in fields:
        fid = field["id"]
        exact_set = set(EXACT_ALIASES[fid])
        approx_tokens = APPROXIMATE_ALIASES[fid]

        exact_matches = [
            col["id"]
            for col in columns
            if col["id"] not in used_columns and normalized_labels[col["id"]] in exact_set
        ]
        if len(exact_matches) == 1:
            chosen = exact_matches[0]
            used_columns.add(chosen)
            proposal[fid] = {"column": chosen, "confidence": "high"}
            continue

        approx_matches = [
            col["id"]
            for col in columns
            if col["id"] not in used_columns
            and any(token in normalized_labels[col["id"]] for token in approx_tokens)
        ]
        if len(approx_matches) == 1:
            chosen = approx_matches[0]
            used_columns.add(chosen)
            proposal[fid] = {"column": chosen, "confidence": "low"}
            continue

        proposal[fid] = {"column": "", "confidence": "low"}

    missing_fields = [f["id"] for f in fields if not proposal[f["id"]]["column"]]
    if ai_port is not None and missing_fields:
        ai_suggestions = _query_ai_for_missing_columns(
            ai_port=ai_port,
            import_type=import_type,
            columns=columns,
            preview=extracted.preview,
            used_columns=used_columns,
        )
        for fid in missing_fields:
            col_id = str(ai_suggestions.get(fid, ""))
            if col_id and col_id not in used_columns and any(c["id"] == col_id for c in columns):
                samples = _sample_column_values(extracted.preview, int(col_id))
                if fid == "amount" and not _looks_like_amount(samples):
                    continue
                if fid in {"date", "due"} and not _looks_like_date(samples):
                    continue
                used_columns.add(col_id)
                proposal[fid] = {"column": col_id, "confidence": "low"}

    selected = {fid: item["column"] for fid, item in proposal.items()}
    review_needed = any(
        (field["required"] and not proposal[field["id"]]["column"])
        or (proposal[field["id"]]["column"] and proposal[field["id"]]["confidence"] != "high")
        for field in fields
    )

    return MappingProposalResult(
        columns=columns,
        fields=fields,
        mapping=proposal,
        selected_mapping=selected,
        preview=extracted.preview,
        needs_review=review_needed,
    )


def _query_ai_for_missing_columns(
    *,
    ai_port: Any,
    import_type: str,
    columns: list[dict[str, str]],
    preview: list[list[str]],
    used_columns: set[str],
) -> dict[str, str]:
    available_cols = [
        {"id": col["id"], "label": sanitize_untrusted_text(col["label"], max_chars=80)}
        for col in columns
        if col["id"] not in used_columns
    ]
    minimized_rows = [
        [
            PIISanitizer.mask_text(sanitize_untrusted_text(cell, max_chars=40)).masked_text
            for cell in r
        ]
        for r in preview[:2]
    ]
    try:
        if hasattr(ai_port, "run_prompt"):
            response = ai_port.run_prompt(
                "column_mapping",
                variables={
                    "import_type": import_type,
                    "headers": json.dumps(available_cols, ensure_ascii=False),
                    "sample_rows": json.dumps(minimized_rows, ensure_ascii=False),
                },
                contains_sensitive_data=True,
            )
        else:
            response = ai_port.generate(
                AIRequest(
                    prompt_key="column_mapping",
                    rendered_prompt=json.dumps(
                        {"headers": available_cols, "sample_rows": minimized_rows},
                        ensure_ascii=False,
                    ),
                    system_instruction="Map spreadsheet columns",
                    max_output_tokens=300,
                    timeout_seconds=8.0,
                    contains_sensitive_data=True,
                )
            )
        parsed = json.loads(response.content)
        mappings = parsed.get("mappings", {})
        if isinstance(mappings, dict):
            return {str(k): str(v) for k, v in mappings.items()}
    except Exception:
        return {}
    return {}


def parse_civil_date(raw: Any) -> date | None:
    if isinstance(raw, datetime):
        return raw.date()
    if isinstance(raw, date):
        return raw
    text = str(raw or "").strip()
    if not text:
        return None
    local = LOCAL_DATE_RE.match(text)
    if local:
        day, month, year = int(local.group(1)), int(local.group(2)), int(local.group(3))
        try:
            return date(year, month, day)
        except ValueError:
            return None
    iso_candidate = text[:10] if len(text) >= 10 else text
    try:
        return date.fromisoformat(iso_candidate)
    except ValueError:
        return None


def parse_money_decimal(raw: Any) -> Decimal | None:
    if isinstance(raw, Decimal):
        if not raw.is_finite() or abs(raw) > Decimal("100000000.00"):
            return None
        return raw.quantize(TWO_PLACES, rounding=ROUND_HALF_UP)

    text = str(raw or "").strip().replace("R$", "").replace("r$", "").replace(" ", "")
    if not text:
        return None
    if "," in text and "." in text:
        if text.rfind(",") > text.rfind("."):
            text = text.replace(".", "").replace(",", ".")
        else:
            text = text.replace(",", "")
    elif "," in text:
        text = text.replace(".", "").replace(",", ".")

    if not re.match(r"^-?\d+(\.\d{1,4})?$", text):
        return None
    try:
        dec = Decimal(text).quantize(TWO_PLACES, rounding=ROUND_HALF_UP)
    except InvalidOperation:
        return None
    if not dec.is_finite() or abs(dec) > Decimal("100000000.00"):
        return None
    return dec


def _detect_auxiliary_columns(columns: list[dict[str, str]]) -> dict[str, int]:
    found: dict[str, int] = {}
    for col in columns:
        cleaned = _clean_header(col["label"])
        idx = int(col["id"])
        for aux_key, aliases in AUX_COLUMN_ALIASES.items():
            if aux_key not in found and cleaned in aliases:
                found[aux_key] = idx
    return found


def _read_cell(row: list[str], col_id: str | int | None) -> str:
    if col_id in (None, ""):
        return ""
    idx = int(col_id)
    return str(row[idx]).strip() if 0 <= idx < len(row) else ""


def normalize_mapped_rows(
    *,
    rows: list[list[str]],
    columns: list[dict[str, str]],
    mapping: dict[str, str],
    import_type: str,
) -> tuple[list[NormalizedRow], int]:
    aux = _detect_auxiliary_columns(columns)
    valid: list[NormalizedRow] = []
    rejected = 0

    for idx, row in enumerate(rows):
        entry_date = parse_civil_date(_read_cell(row, mapping.get("date")))
        amount = parse_money_decimal(_read_cell(row, mapping.get("amount")))
        description = _read_cell(row, mapping.get("description"))[:255]
        if entry_date is None or amount is None or not description:
            rejected += 1
            continue

        reference = _read_cell(row, mapping.get("reference"))[:120]
        due_date = parse_civil_date(_read_cell(row, mapping.get("due")))
        party_name = _read_cell(row, mapping.get("party"))[:160]
        status_norm = normalize_ascii_text(_read_cell(row, mapping.get("status")))
        settled = status_norm in SETTLED_STATUS_TOKENS or import_type == "settled"

        paid_raw = parse_money_decimal(_read_cell(row, aux.get("paid_amount")))
        if settled:
            paid_amount = abs(amount)
        elif paid_raw is not None and paid_raw >= Decimal("0.00"):
            paid_amount = min(abs(amount), paid_raw)
        else:
            paid_amount = Decimal("0.00")

        category = _read_cell(row, aux.get("category"))[:80]
        unit_name = _read_cell(row, aux.get("unit_name"))[:40]
        unit_price = parse_money_decimal(_read_cell(row, aux.get("unit_price")))
        party_document = _read_cell(row, aux.get("document"))[:32]
        party_phone = _read_cell(row, aux.get("phone"))[:32]
        party_email = _read_cell(row, aux.get("email"))[:254].lower()

        valid.append(
            NormalizedRow(
                row_index=idx,
                entry_type=import_type,
                reference=reference,
                entry_date=entry_date,
                due_date=due_date,
                amount=amount,
                paid_amount=paid_amount,
                description=description,
                normalized_description=normalize_ascii_text(description)[:255],
                party_name=party_name,
                normalized_party=normalize_ascii_text(party_name)[:160],
                category=category,
                unit_name=unit_name,
                unit_price=unit_price,
                settled=settled,
                party_document=party_document,
                party_phone=party_phone,
                party_email=party_email,
            )
        )

    return valid, rejected


def deduplicate_entries(
    *,
    existing_records: list[dict[str, Any]],
    incoming_rows: list[NormalizedRow],
    rejected_count: int = 0,
    resolutions: dict[str, str] | None = None,
) -> DeduplicationResult:
    """Idempotently deduplicates incoming rows against existing tenant ledger entries."""
    res_map = resolutions or {}
    by_reference: dict[tuple[str, str], dict[str, Any]] = {}
    by_signature: dict[tuple[str, str, str, str, str], list[dict[str, Any]]] = {}

    for raw_rec in existing_records:
        rec = dict(raw_rec)
        if rec["reference"]:
            by_reference[(rec["entry_type"], rec["reference"])] = rec
        by_signature.setdefault(rec["signature"], []).append(rec)

    to_create: list[NormalizedRow] = []
    updated_by_id: dict[Any, NormalizedRow] = {}
    ambiguities: list[dict[str, Any]] = []
    summary = {"created": 0, "updated": 0, "unchanged": 0, "rejected": rejected_count}

    for item in incoming_rows:
        sig = item.equivalence_signature()
        if item.reference:
            existing = by_reference.get((item.entry_type, item.reference))
            if existing is None:
                placeholder = {
                    "id": None,
                    "entry_type": item.entry_type,
                    "reference": item.reference,
                    "signature": sig,
                    "state": item.state_tuple(),
                }
                by_reference[(item.entry_type, item.reference)] = placeholder
                by_signature.setdefault(sig, []).append(placeholder)
                to_create.append(item)
                summary["created"] += 1
            else:
                if existing["state"] == item.state_tuple():
                    summary["unchanged"] += 1
                else:
                    existing["state"] = item.state_tuple()
                    if existing["id"] is not None:
                        updated_by_id[existing["id"]] = item
                    summary["updated"] += 1
            continue

        # No reference: check equivalence signature
        matches = by_signature.get(sig, [])
        if matches:
            key = str(item.row_index)
            decision = res_map.get(key)
            if decision == "ignore":
                summary["unchanged"] += 1
                continue
            if decision != "new":
                ambiguities.append(
                    {
                        "id": key,
                        "row": item.row_index + 2,
                        "description": item.description,
                        "options": ["new", "ignore"],
                    }
                )
                continue

        placeholder = {
            "id": None,
            "entry_type": item.entry_type,
            "reference": "",
            "signature": sig,
            "state": item.state_tuple(),
        }
        by_signature.setdefault(sig, []).append(placeholder)
        to_create.append(item)
        summary["created"] += 1

    to_update = [(obj_id, row) for obj_id, row in updated_by_id.items()]
    return DeduplicationResult(
        to_create=to_create,
        to_update=to_update,
        ambiguities=ambiguities,
        summary=summary,
    )
