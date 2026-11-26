from __future__ import annotations

from dataclasses import dataclass

from core.domain.exceptions import ResourceNotFoundError, ValidationDomainError


@dataclass(frozen=True, slots=True)
class PromptUsageLimits:
    max_input_chars: int
    max_output_tokens: int
    timeout_seconds: float


@dataclass(frozen=True, slots=True)
class PromptTemplate:
    key: str
    version: str
    system_instruction: str
    user_template: str
    limits: PromptUsageLimits

    def render(self, **variables: str) -> str:
        try:
            rendered = self.user_template.format(**variables)
        except KeyError as exc:
            raise ValidationDomainError(
                f"Variável obrigatória ausente no template '{self.key}': {exc.args[0]}.",
                code="prompt_render_error",
            ) from exc
        if len(rendered) > self.limits.max_input_chars:
            return rendered[: self.limits.max_input_chars]
        return rendered


class PromptRegistry:
    """Central catalog of versioned prompt templates stored in the domain core."""

    _TEMPLATES: dict[str, PromptTemplate] = {
        "column_mapping": PromptTemplate(
            key="column_mapping",
            version="v1",
            system_instruction=(
                "Classifique os cabeçalhos minimizados da planilha nos campos financeiros "
                "canônicos sem inventar valores."
            ),
            user_template=(
                "Tipo de importação: {import_type}\n"
                "Cabeçalhos: {headers}\n"
                "Amostra minimizada: {sample_rows}"
            ),
            limits=PromptUsageLimits(
                max_input_chars=6000,
                max_output_tokens=600,
                timeout_seconds=8.0,
            ),
        ),
        "cost_anomaly_recommendation": PromptTemplate(
            key="cost_anomaly_recommendation",
            version="v1",
            system_instruction=(
                "Sugira uma ação objetiva de renegociação com base apenas nas métricas "
                "determinísticas fornecidas."
            ),
            user_template=(
                "Categoria: {category}\n"
                "Variação bimestral (%): {change_pct}\n"
                "Resumo de preços/gastos: {summary}"
            ),
            limits=PromptUsageLimits(
                max_input_chars=3000,
                max_output_tokens=250,
                timeout_seconds=8.0,
            ),
        ),
        "ceo_chat": PromptTemplate(
            key="ceo_chat",
            version="v1",
            system_instruction=(
                "Responda perguntas financeiras citando exclusivamente os indicadores "
                "calculados em código para a empresa autenticada. Quando faltarem dados, "
                "indique insuficiência de dados."
            ),
            user_template="Indicadores da empresa:\n{metrics_context}\n\nPergunta: {question}",
            limits=PromptUsageLimits(
                max_input_chars=8000,
                max_output_tokens=500,
                timeout_seconds=10.0,
            ),
        ),
        "collection_message": PromptTemplate(
            key="collection_message",
            version="v1",
            system_instruction=(
                "Redija uma mensagem curta de cobrança no tom solicitado usando apenas "
                "os valores e vencimentos confirmados."
            ),
            user_template=(
                "Tom: {tone}\n"
                "Referência do cliente: {contact_label}\n"
                "Total em aberto: {total_amount}\n"
                "Vencimento principal: {due_date}"
            ),
            limits=PromptUsageLimits(
                max_input_chars=2500,
                max_output_tokens=300,
                timeout_seconds=8.0,
            ),
        ),
        "promise_extraction": PromptTemplate(
            key="promise_extraction",
            version="v1",
            system_instruction=(
                "Extraia título, valor decimal e data YYYY-MM-DD de promessa de pagamento "
                "a partir da nota fornecida, se houver."
            ),
            user_template="Nota da timeline: {note_text}",
            limits=PromptUsageLimits(
                max_input_chars=3500,
                max_output_tokens=200,
                timeout_seconds=6.0,
            ),
        ),
    }

    @classmethod
    def get(cls, key: str) -> PromptTemplate:
        if key not in cls._TEMPLATES:
            raise ResourceNotFoundError(
                f"Template de prompt '{key}' não encontrado.",
                code="prompt_not_found",
            )
        return cls._TEMPLATES[key]

    @classmethod
    def list_keys(cls) -> tuple[str, ...]:
        return tuple(cls._TEMPLATES.keys())
