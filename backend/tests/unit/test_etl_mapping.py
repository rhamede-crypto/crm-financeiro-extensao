from __future__ import annotations

import json

from core.ports.ai import AIRequest, AIResponse
from core.services.etl import propose_column_mapping


def test_propose_column_mapping_detects_exact_approximate_and_missing_fields() -> None:
    table = [
        ["id", "data", "Cobrado", "Descrição livre", "cliente", "status", "vencimento"],
        [
            "CR-01",
            "2026-10-01",
            "125.00",
            "Venda balcão",
            "Mercado Horizonte",
            "Aberto",
            "2026-10-30",
        ],
    ]
    result = propose_column_mapping(table)
    assert result.needs_review is True
    assert result.mapping["date"] == {"column": "1", "confidence": "high"}
    assert result.mapping["amount"] == {"column": "", "confidence": "low"}
    assert result.mapping["description"] == {"column": "3", "confidence": "low"}
    assert result.mapping["party"] == {"column": "4", "confidence": "high"}
    assert len(result.preview) == 1


def test_propose_column_mapping_uses_ai_fallback_with_low_confidence() -> None:
    class StubAI:
        def generate(self, request: AIRequest) -> AIResponse:
            return AIResponse(
                content=json.dumps({"mappings": {"amount": "2", "description": "3"}}),
                provider="stub",
            )

    table = [
        ["ref", "dt_lanc", "cobrado_brl", "obs_livre"],
        ["1", "2026-10-01", "250.00", "Compra de insumos"],
    ]
    result = propose_column_mapping(table, ai_port=StubAI())
    assert result.mapping["amount"] == {"column": "2", "confidence": "low"}
    assert result.mapping["description"] == {"column": "3", "confidence": "low"}
    assert result.needs_review is True
