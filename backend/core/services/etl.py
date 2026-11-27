from __future__ import annotations

import json
import re
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import Any

from core.domain.value_objects import normalize_ascii_text
from core.ports.ai import AIRequest
from core.services.privacy import PIISanitizer, sanitize_untrusted_text

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

DATE_CELL_RE = re.compile(r"^(\d{4}-\d{2}-\d{2}|\d{1,2}[/.-]\d{1,2}[/.-]\d{4})$")


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
        cleaned = item.strip().replace("R$", "").replace(" ", "")
        if "," in cleaned:
            cleaned = cleaned.replace(".", "").replace(",", ".")
        try:
            Decimal(cleaned)
            valid += 1
        except InvalidOperation:
            pass
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

    # Optional AI assistance for unmapped fields over minimized/masked headers
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
