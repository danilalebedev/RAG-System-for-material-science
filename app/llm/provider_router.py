from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

from app.llm.routerai_client import RouterAILLMClient, RouterAILLMConfig
from app.llm.types import LLMClient, LLMProviderError, LLMResponse
from app.llm.yandex_client import YandexLLMClient, YandexLLMConfig, build_messages


LOCAL_FALLBACK_MODEL = "deterministic-local-brief"


@dataclass(frozen=True)
class ProviderRouterConfig:
    yandex_enabled: bool = True
    routerai_enabled: bool = True
    primary_provider: str = "yandex"


class ProviderRouter:
    def __init__(
        self,
        *,
        yandex_client: LLMClient | None = None,
        routerai_client: LLMClient | None = None,
        yandex_init_error: LLMProviderError | None = None,
        routerai_init_error: LLMProviderError | None = None,
        config: ProviderRouterConfig | None = None,
    ) -> None:
        self.yandex_client = yandex_client
        self.routerai_client = routerai_client
        self.yandex_init_error = yandex_init_error
        self.routerai_init_error = routerai_init_error
        self.config = config or ProviderRouterConfig()

    @classmethod
    def from_env(cls, *, root: Path | None = None) -> "ProviderRouter":
        dotenv_path = root / ".env" if root is not None else None
        yandex_client: YandexLLMClient | None = None
        routerai_client: RouterAILLMClient | None = None
        yandex_error: LLMProviderError | None = None
        routerai_error: LLMProviderError | None = None

        try:
            yandex_client = YandexLLMClient(YandexLLMConfig.from_env(dotenv_path=dotenv_path))
        except LLMProviderError as exc:
            yandex_error = exc

        try:
            routerai_client = RouterAILLMClient(RouterAILLMConfig.from_env(dotenv_path=dotenv_path))
        except LLMProviderError as exc:
            routerai_error = exc

        primary_provider = os.getenv("LLM_PRIMARY_PROVIDER", "yandex").strip().lower()
        if primary_provider not in {"yandex", "routerai"}:
            primary_provider = "yandex"
        return cls(
            yandex_client=yandex_client,
            routerai_client=routerai_client,
            yandex_init_error=yandex_error,
            routerai_init_error=routerai_error,
            config=ProviderRouterConfig(primary_provider=primary_provider),
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
    ) -> LLMResponse:
        return self.generate(
            build_messages(question, system_prompt=system_prompt, context=context),
            question=question,
            context=context,
            model=model,
            max_tokens=max_tokens,
            temperature=temperature,
            used_evidence=bool(context),
        )

    def generate(
        self,
        messages: Iterable[dict[str, str]],
        *,
        question: str = "",
        context: str | None = None,
        model: str | None = None,
        max_tokens: int = 512,
        temperature: float = 0.2,
        used_evidence: bool = False,
    ) -> LLMResponse:
        materialized_messages = list(messages)
        warnings: list[str] = []
        fallback_reason: str | None = None

        if self.config.primary_provider == "routerai" and self.routerai_client is not None:
            try:
                result = self.routerai_client.generate(
                    materialized_messages,
                    max_tokens=max_tokens,
                    temperature=temperature,
                    used_evidence=used_evidence,
                )
                return LLMResponse(
                    text=result.text,
                    provider="routerai",
                    model=result.model,
                    status="primary",
                    used_evidence=used_evidence,
                    usage=result.usage,
                )
            except LLMProviderError as exc:
                fallback_reason = exc.reason
                warnings.append(exc.safe_summary())
        elif self.config.primary_provider == "routerai" and self.routerai_init_error is not None:
            fallback_reason = self.routerai_init_error.reason
            warnings.append(self.routerai_init_error.safe_summary())

        yandex_error = self._initial_yandex_error()
        if yandex_error is None and self.yandex_client is not None:
            try:
                return self.yandex_client.generate(
                    materialized_messages,
                    model=model,
                    max_tokens=max_tokens,
                    temperature=temperature,
                    used_evidence=used_evidence,
                )
            except LLMProviderError as exc:
                yandex_error = exc

        if yandex_error is not None:
            fallback_reason = yandex_error.reason
            warnings.append(yandex_error.safe_summary())
            if yandex_error.fallback_allowed and self.routerai_client is not None:
                try:
                    result = self.routerai_client.generate(
                        materialized_messages,
                        max_tokens=max_tokens,
                        temperature=temperature,
                        used_evidence=used_evidence,
                    )
                    return LLMResponse(
                        text=result.text,
                        provider="routerai",
                        model=result.model,
                        status="fallback",
                        used_evidence=used_evidence,
                        fallback_reason=fallback_reason,
                        warnings=tuple(warnings),
                        usage=result.usage,
                    )
                except LLMProviderError as exc:
                    warnings.append(exc.safe_summary())
            elif yandex_error.fallback_allowed and self.routerai_init_error is not None:
                warnings.append(self.routerai_init_error.safe_summary())

        return deterministic_local_response(
            question=question or last_user_message(materialized_messages),
            context=context,
            used_evidence=used_evidence,
            fallback_reason=fallback_reason or "remote_provider_unavailable",
            warnings=warnings,
        )

    def _initial_yandex_error(self) -> LLMProviderError | None:
        if self.yandex_client is not None:
            return None
        return self.yandex_init_error or LLMProviderError(
            provider="yandex",
            reason="not_configured",
            message="Yandex provider is not configured",
            fallback_allowed=True,
        )


def deterministic_local_response(
    *,
    question: str,
    context: str | None,
    used_evidence: bool,
    fallback_reason: str,
    warnings: list[str],
) -> LLMResponse:
    text = deterministic_local_brief(question=question, context=context)
    return LLMResponse(
        text=text,
        provider="local",
        model=LOCAL_FALLBACK_MODEL,
        status="local",
        used_evidence=used_evidence,
        fallback_reason=fallback_reason,
        warnings=tuple(warnings),
        usage={},
    )


def deterministic_local_brief(*, question: str, context: str | None) -> str:
    question = " ".join(str(question or "").split())
    if not context:
        return (
            "Удаленные LLM-провайдеры недоступны, а retrieval-контекст не был передан. "
            f"Детерминированный ответ не может подтвердить факты по вопросу: {question}"
        )

    lines = [line.strip() for line in context.splitlines() if line.strip()]
    selected: list[str] = []
    for line in lines:
        if line.startswith("[") or len(selected) < 4:
            selected.append(line[:500])
        if len(selected) >= 6:
            break
    evidence = "\n".join(f"- {line}" for line in selected)
    return (
        "Удаленные LLM-провайдеры недоступны. Ниже детерминированная выжимка из retrieved evidence; "
        "ее нужно считать черновиком без генеративного обобщения.\n\n"
        f"Вопрос: {question}\n\n"
        f"Evidence:\n{evidence}"
    )


def last_user_message(messages: Iterable[dict[str, str]]) -> str:
    for message in reversed(list(messages)):
        if message.get("role") == "user":
            return message.get("content") or ""
    return ""
