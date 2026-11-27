from __future__ import annotations

import json

from core.ports.ai import AIRequest, AIResponse


class LocalDeterministicAIProvider:
    """Zero-secret deterministic AI adapter used as primary local mode and resilient fallback."""

    name = "local_deterministic"

    def generate(self, request: AIRequest) -> AIResponse:
        if request.prompt_key == "column_mapping":
            content = json.dumps({"mappings": {}, "notes": "Mapeamento heurístico local."})
        elif request.prompt_key == "cost_anomaly_recommendation":
            content = (
                "Revisar contrato, comparar cotações e renegociar preço unitário "
                "antes do próximo pedido."
            )
        elif request.prompt_key == "collection_message":
            content = "Olá! Gostaríamos de confirmar a previsão de pagamento dos títulos em aberto."
        elif request.prompt_key == "promise_extraction":
            content = json.dumps({"suggestion": None})
        else:
            content = (
                "Análise baseada apenas nos indicadores financeiros consolidados da empresa."
            )
        return AIResponse(content=content, provider=self.name, used_fallback=False)
