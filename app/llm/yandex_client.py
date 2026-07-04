from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any, Iterable

import requests

from app.llm.types import LLMProviderError, LLMResponse, compact_error, extract_openai_chat_text


DEFAULT_YANDEX_BASE_URL = "https://ai.api.cloud.yandex.net/v1"
DEFAULT_YANDEX_MODEL = "yandexgpt/latest"
DEFAULT_TIMEOUT_SECONDS = 60.0


@dataclass(frozen=True)
class YandexLLMConfig:
    api_key: str
    folder_id: str
    model: str = DEFAULT_YANDEX_MODEL
    base_url: str = DEFAULT_YANDEX_BASE_URL
    timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS

    @classmethod
    def from_env(cls, *, load_dotenv_file: bool = True, dotenv_path: str | os.PathLike[str] | None = None) -> "YandexLLMConfig":
        if load_dotenv_file:
            try:
                from dotenv import load_dotenv
            except ModuleNotFoundError as exc:
                raise RuntimeError(
                    "python-dotenv is required to load .env. "
                    "Install project dependencies from requirements.txt."
                ) from exc
            load_dotenv(dotenv_path, encoding="utf-8-sig")

        missing = [name for name in ("YANDEX_API_KEY", "YANDEX_FOLDER_ID") if not os.getenv(name)]
        if missing:
            raise LLMProviderError(
                provider="yandex",
                reason="missing_credentials",
                message="Missing required Yandex AI Studio environment variables: " + ", ".join(missing),
                fallback_allowed=True,
            )

        return cls(
            api_key=os.environ["YANDEX_API_KEY"],
            folder_id=os.environ["YANDEX_FOLDER_ID"],
            model=os.getenv("YANDEX_MODEL", DEFAULT_YANDEX_MODEL),
            base_url=os.getenv("YANDEX_BASE_URL", DEFAULT_YANDEX_BASE_URL),
            timeout_seconds=float(os.getenv("YANDEX_TIMEOUT_SECONDS", str(DEFAULT_TIMEOUT_SECONDS))),
        )

    def model_uri(self, model: str | None = None) -> str:
        selected_model = model or self.model
        if selected_model.startswith("gpt://"):
            return selected_model
        return f"gpt://{self.folder_id}/{selected_model}"

    def chat_completions_url(self) -> str:
        return self.base_url.rstrip("/") + "/chat/completions"


class YandexLLMClient:
    provider = "yandex"

    def __init__(self, config: YandexLLMConfig | None = None) -> None:
        self.config = config or YandexLLMConfig.from_env()
        self.model = self.config.model_uri()

    def generate(
        self,
        messages: Iterable[dict[str, str]],
        *,
        model: str | None = None,
        max_tokens: int = 512,
        temperature: float = 0.2,
        used_evidence: bool = False,
        **kwargs: Any,
    ) -> LLMResponse:
        selected_model = self.config.model_uri(model)
        payload = {
            "model": selected_model,
            "messages": list(messages),
            "max_tokens": max_tokens,
            "temperature": temperature,
            **kwargs,
        }
        headers = {
            "Authorization": f"Bearer {self.config.api_key}",
            "OpenAI-Project": self.config.folder_id,
            "X-Folder-Id": self.config.folder_id,
            "Content-Type": "application/json",
            "x-data-logging-enabled": "false",
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
                fallback_allowed=True,
            ) from exc
        except requests.RequestException as exc:
            raise LLMProviderError(
                provider=self.provider,
                reason="network_error",
                message=str(exc),
                fallback_allowed=True,
            ) from exc

        if response.status_code >= 400:
            raise classify_yandex_http_error(response, api_key=self.config.api_key)

        try:
            data = response.json()
            text, usage = extract_openai_chat_text(data)
        except LLMProviderError as exc:
            raise LLMProviderError(
                provider=self.provider,
                reason=exc.reason,
                message=str(exc),
                fallback_allowed=True,
            ) from exc
        except ValueError as exc:
            raise LLMProviderError(
                provider=self.provider,
                reason="invalid_json",
                message=str(exc),
                fallback_allowed=True,
            ) from exc

        return LLMResponse(
            text=text,
            provider=self.provider,
            model=selected_model,
            status="primary",
            used_evidence=used_evidence,
            usage=usage,
        )

    def chat(
        self,
        messages: Iterable[dict[str, str]],
        *,
        model: str | None = None,
        max_tokens: int = 512,
        temperature: float = 0.2,
        **kwargs: Any,
    ) -> LLMResponse:
        return self.generate(
            messages,
            model=model,
            max_tokens=max_tokens,
            temperature=temperature,
            **kwargs,
        )

    def ask_result(
        self,
        question: str,
        *,
        system_prompt: str | None = None,
        context: str | None = None,
        model: str | None = None,
        max_tokens: int = 512,
        temperature: float = 0.2,
    ) -> LLMResponse:
        return self.generate(
            build_messages(question, system_prompt=system_prompt, context=context),
            model=model,
            max_tokens=max_tokens,
            temperature=temperature,
            used_evidence=bool(context),
        )

    def ask(
        self,
        question: str,
        *,
        system_prompt: str | None = None,
        context: str | None = None,
        model: str | None = None,
        max_tokens: int = 512,
        temperature: float = 0.2,
    ) -> str:
        return self.ask_result(
            question,
            system_prompt=system_prompt,
            context=context,
            model=model,
            max_tokens=max_tokens,
            temperature=temperature,
        ).text

    def complete(self, prompt: str) -> tuple[str, dict[str, Any]]:
        result = self.generate([{"role": "user", "content": prompt}], temperature=0.1, max_tokens=1200)
        return result.text, result.usage


def build_messages(
    question: str,
    *,
    system_prompt: str | None = None,
    context: str | None = None,
) -> list[dict[str, str]]:
    messages: list[dict[str, str]] = []
    if system_prompt:
        messages.append({"role": "system", "content": system_prompt})
    if context:
        messages.append(
            {
                "role": "user",
                "content": (
                    "Используй контекст ниже. Если данных недостаточно, скажи об этом явно.\n\n"
                    f"Контекст:\n{context}\n\nВопрос: {question}"
                ),
            }
        )
    else:
        messages.append({"role": "user", "content": question})
    return messages


def classify_yandex_http_error(response: requests.Response, *, api_key: str = "") -> LLMProviderError:
    body = compact_error(response.text, max_chars=500, secrets=[api_key])
    lowered = body.casefold()
    status = response.status_code
    reason = "http_error"
    fallback_allowed = False
    if status in {401, 403}:
        reason = "permission_denied"
        fallback_allowed = True
    elif status in {408, 409, 425, 429, 500, 502, 503, 504}:
        reason = "transient_or_rate_limited"
        fallback_allowed = True
    elif status in {400, 404} and any(marker in lowered for marker in ("model", "gpt://", "modeluri", "not found")):
        reason = "model_error"
        fallback_allowed = True
    return LLMProviderError(
        provider="yandex",
        reason=reason,
        message=body or response.reason,
        status_code=status,
        fallback_allowed=fallback_allowed,
    )
