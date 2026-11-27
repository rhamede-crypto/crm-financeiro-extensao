from __future__ import annotations

from datetime import date
from decimal import Decimal

from core.services.etl import deduplicate_entries, normalize_mapped_rows


def test_normalize_mapped_rows_handles_br_formats_and_counts_rejected() -> None:
    columns = [
        {"id": "0", "label": "id"},
        {"id": "1", "label": "data"},
        {"id": "2", "label": "valor"},
        {"id": "3", "label": "descricao"},
        {"id": "4", "label": "cliente"},
        {"id": "5", "label": "status"},
        {"id": "6", "label": "vencimento"},
    ]
    mapping = {
        "reference": "0",
        "date": "1",
        "amount": "2",
        "description": "3",
        "party": "4",
        "status": "5",
        "due": "6",
    }
    rows = [
        ["F-1", "12/01/2026", "R$ 1.250,50", "Venda 1", "Mercado Horizonte", "Pago", "12/02/2026"],
        ["F-2", "data-ruim", "100.00", "Invalida", "Cliente", "Aberto", ""],
    ]
    normalized, rejected = normalize_mapped_rows(
        rows=rows,
        columns=columns,
        mapping=mapping,
        import_type="receivable",
    )
    assert rejected == 1
    assert len(normalized) == 1
    assert normalized[0].entry_date == date(2026, 1, 12)
    assert normalized[0].due_date == date(2026, 2, 12)
    assert normalized[0].amount == Decimal("1250.50")
    assert normalized[0].settled is True


def test_deduplicate_entries_updates_by_reference_and_flags_ambiguous_similar_rows() -> None:
    columns = [
        {"id": "0", "label": "id"},
        {"id": "1", "label": "data"},
        {"id": "2", "label": "valor"},
        {"id": "3", "label": "descricao"},
        {"id": "4", "label": "cliente"},
        {"id": "5", "label": "status"},
    ]
    mapping = {
        "reference": "0",
        "date": "1",
        "amount": "2",
        "description": "3",
        "party": "4",
        "status": "5",
    }
    initial, _ = normalize_mapped_rows(
        rows=[
            ["CR-1", "2026-10-01", "500.00", "Mensalidade", "Cliente A", "Aberto"],
            ["", "2026-10-02", "80.00", "Cafe", "Balcao", "Pago"],
        ],
        columns=columns,
        mapping=mapping,
        import_type="receivable",
    )
    existing_records = [
        {
            "id": f"id-{i}",
            "entry_type": r.entry_type,
            "reference": r.reference,
            "signature": r.equivalence_signature(),
            "state": r.state_tuple(),
        }
        for i, r in enumerate(initial)
    ]

    incoming, _ = normalize_mapped_rows(
        rows=[
            ["CR-1", "2026-10-01", "500.00", "Mensalidade", "Cliente A", "Pago"],
            ["", "2026-10-02", "80.00", "Cafe", "Balcao", "Pago"],
        ],
        columns=columns,
        mapping=mapping,
        import_type="receivable",
    )

    first_pass = deduplicate_entries(existing_records=existing_records, incoming_rows=incoming)
    assert len(first_pass.ambiguities) == 1
    assert first_pass.ambiguities[0]["id"] == "1"

    resolved_new = deduplicate_entries(
        existing_records=existing_records,
        incoming_rows=incoming,
        resolutions={"1": "new"},
    )
    assert resolved_new.ambiguities == []
    assert resolved_new.summary == {"created": 1, "updated": 1, "unchanged": 0, "rejected": 0}
