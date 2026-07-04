from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any, Iterable

import requests

from app.llm.types import LLMProviderError, LLMResponse, compact_error, extract_openai_chat_text


DEFAULT_ROUTERAI_BASE_URL = "https://routerai.ru/api/v1"
DEFAULT_ROUTERAI_MODEL = "deepseek/deepseek-chat-v3.1"
DEFAULT_TIMEOUT_SECONDS = 60.0


@dataclass(frozen=True)
class RouterAILLMConfig:
    api_key: str
    model: str = DEFAULT_ROUTERAI_MODEL
    base_url: str = DEFAULT_ROUTERAI_BASE_URL
    timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS

    @classmethod
    def from_env(cls, *, load_dotenv_file: bool = True, dotenv_path: str | os.PathLike[str] | None = None) -> "RouterAILLMConfig":
        if load_dotenv_file:
            try:
                from dotenv import load_dotenv
            except ModuleNotFoundError as exc:
                raise RuntimeError(
                    "python-dotenv is required to load .env. "
                    "Install project dependencies from requirements.txt."
                ) from exc
            load_dotenv(dotenv_path, encoding="utf-8-sig")

        if not os.getenv("ROUTERAI_API_KEY"):
            raise LLMProviderError(
                provider="routerai",
                reason="missing_credentials",
                message="Missing required RouterAI environment variable: ROUTERAI_API_KEY",
                fallback_allowed=False,
            )
        return cls(
            api_key=os.environ["ROUTERAI_API_KEY"],
            model=os.getenv("ROUTERAI_CHAT_MODEL", DEFAULT_ROUTERAI_MODEL),
            base_url=os.getenv("ROUTERAI_BASE_URL", DEFAULT_ROUTERAI_BASE_URL),
            timeout_seconds=float(os.getenv("ROUTERAI_TIMEOUT_SECONDS", str(DEFAULT_TIMEOUT_SECONDS))),
        )

    def chat_completions_url(self) -> str:
        return self.base_url.rstrip("/") + "/chat/completions"


class RouterAILLMClient:
    provider = "routerai"

    def __init__(self, config: RouterAILLMConfig | None = None) -> None:
        self.config = config or RouterAILLMConfig.from_env()
        self.model = self.config.model

    def generate(
        self,
        messages: Iterable[dict[str, str]],
        *,
        max_tokens: int = 512,
        temperature: float = 0.2,
        used_evidence: bool = False,
        **kwargs: Any,
    ) -> LLMResponse:
        payload = {
            "model": self.config.model,
            "messages": list(messages),
            "max_tokens": max_tokens,
            "temperature": temperature,
            **kwargs,
        }
        headers = {
            "Authorization": f"Bearer {self.config.api_key}",
            "Content-Type": "application/json",
        }
        try:
            response = requests.post(
                self.config.chat_completions_url(),
                headers=headers,
                json=payload,
                timeout=self.config.timeout_seconds,
            )
        except requests.Timeout as exc:
            raise LLMProviderError(
                provider=self.provider,
                reason="timeout",
                message=str(exc),
                fallback_allowed=False,
            ) from exc
        except requests.RequestException as exc:
            raise LLMProviderError(
                provider=self.provider,
                reason="network_error",
                message=str(exc),
                fallback_allowed=False,
            ) from exc

        if response.status_code >= 400:
            raise LLMProviderError(
                provider=self.provider,
                reason=classify_routerai_reason(response),
                message=compact_error(response.text, max_chars=500, secrets=[self.config.api_key]) or response.reason,
                status_code=response.status_code,
                fallback_allowed=False,
            )

        try:
            data = response.json()
            text, usage = extract_openai_chat_text(data)
        except LLMProviderError as exc:
            raise LLMProviderError(
                provider=self.provider,
                reason=exc.reason,
                message=str(exc),
                fallback_allowed=False,
            ) from exc
        except ValueError as exc:
            raise LLMProviderError(
                provider=self.provider,
                reason="invalid_json",
                message=str(exc),
                fallback_allowed=False,
            ) from exc

        return LLMResponse(
            text=text,
            provider=self.provider,
            model=self.config.model,
            status="fallback",
            used_evidence=used_evidence,
            usage=usage,
        )


def classify_routerai_reason(response: requests.Response) -> str:
    if response.status_code in {401, 403}:
        return "permission_denied"
    if response.status_code in {408, 409, 425, 429, 500, 502, 503, 504}:
        return "transient_or_rate_limited"
    body = compact_error(response.text, max_chars=500).casefold()
    if response.status_code in {400, 404} and "model" in body:
        return "model_error"
    return "http_error"
