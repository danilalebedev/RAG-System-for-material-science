from __future__ import annotations

from collections.abc import Iterable

import pytest

from app.llm.provider_router import ProviderRouter, ProviderRouterConfig
from app.llm.types import LLMProviderError, LLMResponse, compact_error
from app.web_search.deep_search import RouterCompletionClient


class FakeClient:
    def __init__(self, *, provider: str, model: str, response_text: str = "ok", error: LLMProviderError | None = None) -> None:
        self.provider = provider
        self.model = model
        self.response_text = response_text
        self.error = error
        self.calls = 0

    def generate(
        self,
        messages: Iterable[dict[str, str]],
        *,
        max_tokens: int = 512,
        temperature: float = 0.2,
        used_evidence: bool = False,
        **_: object,
    ) -> LLMResponse:
        self.calls += 1
        if self.error is not None:
            raise self.error
        return LLMResponse(
            text=self.response_text,
            provider=self.provider,  # type: ignore[arg-type]
            model=self.model,
            status="primary" if self.provider == "yandex" else "fallback",
            used_evidence=used_evidence,
        )


def test_provider_router_uses_yandex_first_without_routerai_call() -> None:
    yandex = FakeClient(provider="yandex", model="gpt://folder/yandexgpt/latest", response_text="yandex ok")
    routerai = FakeClient(provider="routerai", model="deepseek/deepseek-chat-v3.1", response_text="router ok")
    router = ProviderRouter(yandex_client=yandex, routerai_client=routerai)

    response = router.ask("question", context="evidence")

    assert response.provider == "yandex"
    assert response.status == "primary"
    assert response.fallback_reason is None
    assert response.used_evidence is True
    assert yandex.calls == 1
    assert routerai.calls == 0


def test_provider_router_falls_back_to_routerai_on_yandex_permission_error() -> None:
    yandex = FakeClient(
        provider="yandex",
        model="gpt://folder/yandexgpt/latest",
        error=LLMProviderError(
            provider="yandex",
            reason="permission_denied",
            message="HTTP 403: model access denied",
            status_code=403,
            fallback_allowed=True,
        ),
    )
    routerai = FakeClient(provider="routerai", model="deepseek/deepseek-chat-v3.1", response_text="router answer")
    router = ProviderRouter(yandex_client=yandex, routerai_client=routerai)

    response = router.ask("question")

    assert response.provider == "routerai"
    assert response.status == "fallback"
    assert response.fallback_reason == "permission_denied"
    assert response.text == "router answer"
    assert yandex.calls == 1
    assert routerai.calls == 1
    assert response.warnings


def test_provider_router_can_use_routerai_as_primary_without_yandex_call() -> None:
    yandex = FakeClient(provider="yandex", model="gpt://folder/yandexgpt/latest", response_text="yandex ok")
    routerai = FakeClient(provider="routerai", model="deepseek/deepseek-chat-v3.1", response_text="router primary")
    router = ProviderRouter(
        yandex_client=yandex,
        routerai_client=routerai,
        config=ProviderRouterConfig(primary_provider="routerai"),
    )

    response = router.ask("question", context="evidence")

    assert response.provider == "routerai"
    assert response.status == "primary"
    assert response.text == "router primary"
    assert response.used_evidence is True
    assert yandex.calls == 0
    assert routerai.calls == 1


def test_provider_router_returns_local_brief_when_both_remote_providers_fail() -> None:
    yandex = FakeClient(
        provider="yandex",
        model="gpt://folder/yandexgpt/latest",
        error=LLMProviderError(provider="yandex", reason="timeout", message="timeout", fallback_allowed=True),
    )
    routerai = FakeClient(
        provider="routerai",
        model="deepseek/deepseek-chat-v3.1",
        error=LLMProviderError(provider="routerai", reason="timeout", message="timeout", fallback_allowed=False),
    )
    router = ProviderRouter(yandex_client=yandex, routerai_client=routerai)

    response = router.ask("What is known?", context="[1] Nickel evidence line\nMore evidence")

    assert response.provider == "local"
    assert response.status == "local"
    assert response.fallback_reason == "timeout"
    assert response.used_evidence is True
    assert "Nickel evidence line" in response.text
    assert len(response.warnings) == 2


def test_provider_router_does_not_call_routerai_for_nonfallback_yandex_error() -> None:
    yandex = FakeClient(
        provider="yandex",
        model="gpt://folder/yandexgpt/latest",
        error=LLMProviderError(provider="yandex", reason="invalid_request", message="bad prompt", fallback_allowed=False),
    )
    routerai = FakeClient(provider="routerai", model="deepseek/deepseek-chat-v3.1", response_text="router answer")
    router = ProviderRouter(yandex_client=yandex, routerai_client=routerai)

    response = router.ask("question")

    assert response.provider == "local"
    assert response.fallback_reason == "invalid_request"
    assert routerai.calls == 0


def test_compact_error_redacts_secret_fragments() -> None:
    assert "secret-token" not in compact_error("failed with secret-token", secrets=["secret-token"])


class FakeRouter:
    def __init__(self, response: LLMResponse) -> None:
        self.response = response
        self.calls: list[dict[str, object]] = []

    def generate(
        self,
        messages: Iterable[dict[str, str]],
        *,
        question: str = "",
        max_tokens: int = 512,
        temperature: float = 0.2,
        used_evidence: bool = False,
        **_: object,
    ) -> LLMResponse:
        self.calls.append(
            {
                "messages": list(messages),
                "question": question,
                "max_tokens": max_tokens,
                "temperature": temperature,
                "used_evidence": used_evidence,
            }
        )
        return self.response


def test_router_completion_client_returns_routerai_metadata() -> None:
    router = FakeRouter(
        LLMResponse(
            text='{"document_summary": {"summary": "ok"}}',
            provider="routerai",
            model="deepseek/deepseek-chat-v3.1",
            status="fallback",
            used_evidence=True,
        )
    )
    client = RouterCompletionClient(router)  # type: ignore[arg-type]

    text, metadata = client.complete("extract")

    assert text.startswith("{")
    assert metadata["provider"] == "routerai"
    assert metadata["model"] == "deepseek/deepseek-chat-v3.1"
    assert router.calls[0]["used_evidence"] is True


def test_router_completion_client_rejects_local_fallback_for_deep_search() -> None:
    router = FakeRouter(
        LLMResponse(
            text="local brief",
            provider="local",
            model="deterministic-local-brief",
            status="local",
            used_evidence=True,
        )
    )
    client = RouterCompletionClient(router)  # type: ignore[arg-type]

    with pytest.raises(RuntimeError, match="structured deep-search extraction"):
        client.complete("extract")
