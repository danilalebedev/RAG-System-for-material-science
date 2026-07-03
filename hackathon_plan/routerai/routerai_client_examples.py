"""
Minimal RouterAI examples for the hackathon prototype.

Requires:
    pip install openai python-dotenv
    set ROUTERAI_API_KEY=<your key>

These examples use RouterAI's OpenAI-compatible API, not OpenAI's API.
"""

from __future__ import annotations

import json
import os
from typing import Any

from openai import OpenAI


BASE_URL = os.getenv("ROUTERAI_BASE_URL", "https://routerai.ru/api/v1")


def client() -> OpenAI:
    return OpenAI(api_key=os.environ["ROUTERAI_API_KEY"], base_url=BASE_URL)


def ru_provider() -> dict[str, Any]:
    return {"country": "ru", "allow_fallbacks": False}


def chat_example() -> str:
    resp = client().chat.completions.create(
        model=os.getenv("ROUTERAI_CHAT_MODEL", "qwen/qwen3-30b-a3b-instruct-2507"),
        messages=[
            {"role": "system", "content": "Отвечай строго по источникам и кратко."},
            {"role": "user", "content": "Что такое GraphRAG в 3 предложениях?"},
        ],
        temperature=0,
        extra_body={"provider": ru_provider()},
    )
    return resp.choices[0].message.content or ""


def extraction_example(chunk_text: str) -> dict[str, Any]:
    prompt = {
        "task": "extract_material_experiments",
        "schema": {
            "experiments": [
                {
                    "material": {"raw_name": "string", "composition": []},
                    "processing": [],
                    "measurements": [],
                    "claims": [],
                }
            ]
        },
        "rules": [
            "Return only valid JSON.",
            "Do not add facts without direct evidence in the text.",
            "Keep original units in attrs if normalization is uncertain.",
        ],
        "text": chunk_text,
    }
    resp = client().chat.completions.create(
        model=os.getenv("ROUTERAI_EXTRACT_MODEL", "qwen/qwen3-30b-a3b-instruct-2507"),
        messages=[
            {"role": "system", "content": "Ты extractor научных фактов по материаловедению."},
            {"role": "user", "content": json.dumps(prompt, ensure_ascii=False)},
        ],
        temperature=0,
        response_format={"type": "json_object"},
        extra_body={"provider": ru_provider()},
    )
    return json.loads(resp.choices[0].message.content or "{}")


def embeddings_example(texts: list[str]) -> list[list[float]]:
    resp = client().embeddings.create(
        model=os.getenv("ROUTERAI_EMBED_MODEL", "baai/bge-m3"),
        input=texts,
    )
    return [item.embedding for item in resp.data]


if __name__ == "__main__":
    print(chat_example())
