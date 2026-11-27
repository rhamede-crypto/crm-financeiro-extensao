from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True, slots=True)
class AIRequest:
    prompt_key: str
    rendered_prompt: str
    system_instruction: str
    max_output_tokens: int
    timeout_seconds: float
    contains_sensitive_data: bool = False


@dataclass(frozen=True, slots=True)
class AIResponse:
    content: str
    provider: str
    used_fallback: bool = False


class AIPort(Protocol):
    def generate(self, request: AIRequest) -> AIResponse:
        ...
