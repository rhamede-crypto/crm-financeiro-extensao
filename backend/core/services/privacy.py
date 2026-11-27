from __future__ import annotations

import re
from dataclasses import dataclass

CPF_RE = re.compile(r"\b\d{3}\.?\d{3}\.?\d{3}-?\d{2}\b")
CNPJ_RE = re.compile(r"\b\d{2}\.?\d{3}\.?\d{3}/?\d{4}-?\d{2}\b")
EMAIL_RE = re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b")
PHONE_RE = re.compile(r"(?<!\d)(?:\+?55\s?)?(?:\(?\d{2}\)?\s?)?9?\d{4}-?\d{4}(?!\d)")
INJECTION_RE = re.compile(
    r"(?i)(ignore\s+(?:all\s+)?previous\s+instructions|system\s*:|<\|system\|>|<\|im_start\|>|"
    r"desconsidere\s+as\s+instrucoes|mostre\s+outra\s+empresa|switch\s+company|company_id\s*=)"
)


@dataclass(frozen=True, slots=True)
class SanitizationResult:
    masked_text: str
    token_map: dict[str, str]


class PIISanitizer:
    """Masks direct identifiers (CPF, CNPJ, email, phone) and pseudonymizes entity names."""

    @staticmethod
    def mask_text(
        text: str,
        *,
        known_names: tuple[str, ...] = (),
    ) -> SanitizationResult:
        token_map: dict[str, str] = {}
        masked = str(text or "")

        ordered_names = sorted(
            {n.strip() for n in known_names if n.strip()},
            key=len,
            reverse=True,
        )
        for index, name in enumerate(ordered_names, start=1):
            token = f"[CONTATO_{index:02d}]"
            pattern = re.compile(re.escape(name), re.IGNORECASE)
            if pattern.search(masked):
                masked = pattern.sub(token, masked)
                token_map[token] = name

        masked = CNPJ_RE.sub("[CNPJ_MASKED]", masked)
        masked = CPF_RE.sub("[CPF_MASKED]", masked)
        masked = EMAIL_RE.sub("[EMAIL_MASKED]", masked)
        masked = PHONE_RE.sub("[PHONE_MASKED]", masked)
        return SanitizationResult(masked_text=masked, token_map=token_map)

    @staticmethod
    def unmask_text(text: str, token_map: dict[str, str]) -> str:
        restored = text
        for token, original in token_map.items():
            restored = restored.replace(token, original)
        return restored


def sanitize_untrusted_text(text: str, *, max_chars: int = 2000) -> str:
    """Strips control characters and prompt-injection markers from untrusted user/file inputs."""
    cleaned = "".join(ch for ch in str(text or "") if ch == "\n" or ord(ch) >= 32)
    cleaned = INJECTION_RE.sub("[TRECHO_BLOQUEADO]", cleaned)
    return cleaned.strip()[:max_chars]


@dataclass(frozen=True, slots=True)
class ExternalProviderPolicy:
    provider_name: str
    endpoint_url: str
    non_training_approved: bool
    retention_zero_approved: bool


class ZeroRetentionPolicyGuard:
    """Ensures sensitive financial payloads never leave to unverified external AI providers."""

    @staticmethod
    def can_send_to_external(
        policy: ExternalProviderPolicy,
        *,
        contains_sensitive_data: bool,
    ) -> tuple[bool, str]:
        if policy.provider_name in ("", "local"):
            return False, "local_provider_active"
        if not policy.endpoint_url.lower().startswith("https://"):
            return False, "external_endpoint_requires_https"
        if contains_sensitive_data and not (
            policy.non_training_approved and policy.retention_zero_approved
        ):
            return False, "retention_zero_and_non_training_not_proven"
        return True, "ok"
