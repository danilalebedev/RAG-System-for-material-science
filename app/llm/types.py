from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Iterable, Literal, Protocol


ProviderName = Literal["yandex", "routerai", "local"]
ProviderStatus = Literal["primary", "fallback", "local"]


@dataclass(frozen=True)
class LLMResponse:
    text: str
    provider: ProviderName
    model: str
    status: ProviderStatus
    used_evidence: bool = False
    fallback_reason: str | None = None
    warnings: tuple[str, ...] = ()
    usage: dict[str, Any] = field(default_factory=dict)

    def metadata(self) -> dict[str, Any]:
        return {
            "provider": self.provider,
            "model": self.model,
            "status": self.status,
            "fallback_reason": self.fallback_reason,
            "used_evidence": self.used_evidence,
            "warnings": list(self.warnings),
            "usage": self.usage,
        }


class LLMClient(Protocol):
    provider: ProviderName
    model: str

    def generate(
        self,
        messages: Iterable[dict[str, str]],
        *,
        max_tokens: int = 512,
        temperature: float = 0.2,
        used_evidence: bool = False,
    ) -> LLMResponse:
        ...


class LLMProviderError(RuntimeError):
    def __init__(
        self,
        *,
        provider: str,
        reason: str,
        message: str,
        status_code: int | None = None,
        fallback_allowed: bool = True,
    ) -> None:
        self.provider = provider
        self.reason = reason
        self.status_code = status_code
        self.fallback_allowed = fallback_allowed
        super().__init__(compact_error(message))

    def safe_summary(self) -> str:
        status = f" HTTP {self.status_code}" if self.status_code is not None else ""
        return f"{self.provider}{status} {self.reason}: {compact_error(str(self))}"


def compact_error(value: Any, *, max_chars: int = 300, secrets: Iterable[str] = ()) -> str:
    text = re.sub(r"\s+", " ", str(value or "")).strip()
    for secret in secrets:
        if secret:
            text = text.replace(secret, "[redacted]")
    if len(text) > max_chars:
        text = text[: max_chars - 3].rstrip() + "..."
    return text


def extract_openai_chat_text(data: dict[str, Any]) -> tuple[str, dict[str, Any]]:
    choices = data.get("choices")
    if not isinstance(choices, list) or not choices:
        raise LLMProviderError(
            provider="unknown",
            reason="invalid_response",
            message="chat completion response does not contain choices",
            fallback_allowed=True,
        )
    first = choices[0] if isinstance(choices[0], dict) else {}
    message = first.get("message") if isinstance(first.get("message"), dict) else {}
    content = message.get("content")
    if content is None:
        content = first.get("text")
    text = str(content or "").strip()
    if not text:
        raise LLMProviderError(
            provider="unknown",
            reason="empty_response",
            message="chat completion response returned empty content",
            fallback_allowed=True,
        )
    usage = data.get("usage") if isinstance(data.get("usage"), dict) else {}
    return text, usage
