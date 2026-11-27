from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class TablePreview:
    columns: list[dict[str, str]]
    preview: list[list[str]]
    rows: list[list[str]]


def extract_table_preview(table: list[list[str]]) -> TablePreview:
    """Extracts header descriptors and a minimized 4-row preview without external dependencies."""
    header, *data_rows = table
    columns = [
        {"id": str(idx), "label": str(label or f"Coluna {idx + 1}").strip() or f"Coluna {idx + 1}"}
        for idx, label in enumerate(header)
    ]
    preview = [
        [str(row[idx] if idx < len(row) else "")[:120] for idx in range(len(columns))]
        for row in data_rows[:4]
    ]
    return TablePreview(columns=columns, preview=preview, rows=data_rows)
