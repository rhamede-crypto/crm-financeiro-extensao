from __future__ import annotations

import logging

from django.conf import settings

from core.ports.ai import AIPort, AIRequest, AIResponse
from core.prompts.registry import PromptRegistry
from core.services.privacy import (
    ExternalProviderPolicy,
    PIISanitizer,
    ZeroRetentionPolicyGuard,
    sanitize_untrusted_text,
)

from .external_http_provider import ExternalHTTPProvider
from .local_provider import LocalDeterministicAIProvider

logger = logging.getLogger(__name__)


class ResilientAIGateway:
    """Enforces PII masking, zero-retention guardrails, timeouts, and deterministic fallback."""

    def __init__(
        self,
        *,
        local_provider: AIPort | None = None,
        external_provider: AIPort | None = None,
        policy: ExternalProviderPolicy | None = None,
    ) -> None:
        self.local_provider = local_provider or LocalDeterministicAIProvider()
        self.policy = policy or ExternalProviderPolicy(
            provider_name=getattr(settings, "AI_PROVIDER", "local"),
            endpoint_url=getattr(settings, "AI_EXTERNAL_API_URL", ""),
            non_training_approved=getattr(settings, "AI_EXTERNAL_NON_TRAINING_APPROVED", False),
            retention_zero_approved=getattr(settings, "AI_EXTERNAL_RETENTION_ZERO_APPROVED", False),
        )
        self.external_provider = external_provider
        if self.external_provider is None and self.policy.provider_name != "local":
            self.external_provider = ExternalHTTPProvider(
                endpoint_url=self.policy.endpoint_url,
                api_key=getattr(settings, "AI_EXTERNAL_API_KEY", ""),
                model=getattr(settings, "AI_EXTERNAL_MODEL", "gemini-2.5-flash"),
            )

    def run_prompt(
        self,
        prompt_key: str,
        *,
        variables: dict[str, str],
        known_names: tuple[str, ...] = (),
        contains_sensitive_data: bool = True,
    ) -> AIResponse:
        template = PromptRegistry.get(prompt_key)
        safe_vars = {
            k: sanitize_untrusted_text(v, max_chars=template.limits.max_input_chars)
            for k, v in variables.items()
        }
        rendered = template.render(**safe_vars)
        sanitized = PIISanitizer.mask_text(rendered, known_names=known_names)

        request = AIRequest(
            prompt_key=prompt_key,
            rendered_prompt=sanitized.masked_text,
            system_instruction=template.system_instruction,
            max_output_tokens=template.limits.max_output_tokens,
            timeout_seconds=template.limits.timeout_seconds,
            contains_sensitive_data=contains_sensitive_data,
        )

        allowed, reason = ZeroRetentionPolicyGuard.can_send_to_external(
            self.policy,
            contains_sensitive_data=contains_sensitive_data,
        )
        if not allowed or self.external_provider is None:
            if self.policy.provider_name not in ("", "local"):
                logger.info("AI external provider blocked (%s); using local fallback.", reason)
            response = self.local_provider.generate(request)
            return AIResponse(
                content=PIISanitizer.unmask_text(response.content, sanitized.token_map),
                provider=response.provider,
                used_fallback=self.policy.provider_name not in ("", "local"),
            )

        try:
            response = self.external_provider.generate(request)
            return AIResponse(
                content=PIISanitizer.unmask_text(response.content, sanitized.token_map),
                provider=response.provider,
                used_fallback=False,
            )
        except Exception as exc:
            logger.warning(
                "AI external provider failed (%s); falling back to local.",
                type(exc).__name__,
            )
            fallback = self.local_provider.generate(request)
            return AIResponse(
                content=PIISanitizer.unmask_text(fallback.content, sanitized.token_map),
                provider=fallback.provider,
                used_fallback=True,
            )
