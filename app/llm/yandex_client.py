from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any, Iterable


DEFAULT_YANDEX_BASE_URL = "https://ai.api.cloud.yandex.net/v1"
DEFAULT_YANDEX_MODEL = "yandexgpt/latest"


@dataclass(frozen=True)
class YandexLLMConfig:
    api_key: str
    folder_id: str
    model: str = DEFAULT_YANDEX_MODEL
    base_url: str = DEFAULT_YANDEX_BASE_URL

    @classmethod
    def from_env(cls, *, load_dotenv_file: bool = True) -> "YandexLLMConfig":
        if load_dotenv_file:
            try:
                from dotenv import load_dotenv
            except ModuleNotFoundError as exc:
                raise RuntimeError(
                    "python-dotenv is required to load .env. "
                    "Install project dependencies from requirements.txt."
                ) from exc
            load_dotenv()

        missing = [name for name in ("YANDEX_API_KEY", "YANDEX_FOLDER_ID") if not os.getenv(name)]
        if missing:
            raise RuntimeError(
                "Missing required Yandex AI Studio environment variables: "
                + ", ".join(missing)
            )

        return cls(
            api_key=os.environ["YANDEX_API_KEY"],
            folder_id=os.environ["YANDEX_FOLDER_ID"],
            model=os.getenv("YANDEX_MODEL", DEFAULT_YANDEX_MODEL),
            base_url=os.getenv("YANDEX_BASE_URL", DEFAULT_YANDEX_BASE_URL),
        )

    def model_uri(self, model: str | None = None) -> str:
        selected_model = model or self.model
        if selected_model.startswith("gpt://"):
            return selected_model
        return f"gpt://{self.folder_id}/{selected_model}"


class YandexLLMClient:
    def __init__(self, config: YandexLLMConfig | None = None) -> None:
        try:
            from openai import OpenAI
        except ModuleNotFoundError as exc:
            raise RuntimeError(
                "openai package is required for Yandex AI Studio OpenAI-compatible API. "
                "Install project dependencies from requirements.txt."
            ) from exc

        self.config = config or YandexLLMConfig.from_env()
        self._client = OpenAI(
            api_key=self.config.api_key,
            project=self.config.folder_id,
            base_url=self.config.base_url,
        )

    def chat(
        self,
        messages: Iterable[dict[str, str]],
        *,
        model: str | None = None,
        max_tokens: int = 512,
        temperature: float = 0.2,
        **kwargs: Any,
    ) -> Any:
        return self._client.chat.completions.create(
            model=self.config.model_uri(model),
            messages=list(messages),
            max_tokens=max_tokens,
            temperature=temperature,
            **kwargs,
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
        messages: list[dict[str, str]] = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        if context:
            messages.append(
                {
                    "role": "user",
                    "content": (
                        "Используй контекст ниже. Если данных недостаточно, "
                        "скажи об этом явно.\n\n"
                        f"Контекст:\n{context}\n\nВопрос: {question}"
                    ),
                }
            )
        else:
            messages.append({"role": "user", "content": question})

        response = self.chat(
            messages,
            model=model,
            max_tokens=max_tokens,
            temperature=temperature,
        )
        return response.choices[0].message.content or ""
