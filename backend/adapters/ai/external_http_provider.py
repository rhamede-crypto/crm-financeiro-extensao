from __future__ import annotations

import json
import urllib.request

from core.ports.ai import AIRequest, AIResponse


class ExternalHTTPProvider:
    """OpenAI/Gemini-compatible HTTPS adapter with strict timeout enforcement."""

    name = "external_https"

    def __init__(self, *, endpoint_url: str, api_key: str, model: str) -> None:
        self.endpoint_url = endpoint_url.strip()
        self.api_key = api_key.strip()
        self.model = model.strip() or "gemini-2.5-flash"

    def generate(self, request: AIRequest) -> AIResponse:
        if not self.endpoint_url.lower().startswith("https://"):
            raise ValueError("External AI endpoint must use HTTPS.")
        if not self.api_key:
            raise ValueError("External AI API key not configured.")

        payload = {
            "model": self.model,
            "max_tokens": request.max_output_tokens,
            "messages": [
                {"role": "system", "content": request.system_instruction},
                {"role": "user", "content": request.rendered_prompt},
            ],
        }
        req = urllib.request.Request(
            self.endpoint_url,
            data=json.dumps(payload).encode("utf-8"),
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {self.api_key}",
            },
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=request.timeout_seconds) as resp:
            data = json.loads(resp.read().decode("utf-8"))

        choices = data.get("choices") or []
        if choices and isinstance(choices[0], dict):
            content = str(choices[0].get("message", {}).get("content", "")).strip()
        else:
            content = str(data.get("text", "")).strip()
        if not content:
            raise ValueError("Empty response from external AI provider.")
        return AIResponse(content=content, provider=self.name, used_fallback=False)
