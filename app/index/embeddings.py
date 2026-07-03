from __future__ import annotations

import hashlib
import json
import math
import re
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

import numpy as np
import requests


TOKEN_RE = re.compile(r"[\w.+#%-]+", re.UNICODE)
FOLDER_ID_RE = re.compile(r"emb://[^/]+/")
WHITESPACE_RE = re.compile(r"\s+")


class EmbeddingClient(Protocol):
    model_uri: str
    backend: str
    dimension: int | None

    def embed_text(self, text: str) -> list[float]:
        ...


@dataclass(frozen=True)
class EmbeddingConfig:
    endpoint: str
    auth_scheme: str
    doc_model_uri_template: str
    query_model_uri_template: str
    fallback_doc_model_uri_template: str
    fallback_query_model_uri_template: str
    request_timeout_seconds: int = 60
    max_retries: int = 4
    retry_backoff_seconds: float = 2.0
    max_input_chars: int = 2800
    rate_limit_sleep_seconds: float = 30.0

    @classmethod
    def from_mapping(cls, mapping: dict[str, Any]) -> "EmbeddingConfig":
        return cls(
            endpoint=str(mapping["endpoint"]),
            auth_scheme=str(mapping.get("auth_scheme") or "Api-Key"),
            doc_model_uri_template=str(mapping["doc_model_uri_template"]),
            query_model_uri_template=str(mapping["query_model_uri_template"]),
            fallback_doc_model_uri_template=str(mapping["fallback_doc_model_uri_template"]),
            fallback_query_model_uri_template=str(mapping["fallback_query_model_uri_template"]),
            request_timeout_seconds=int(mapping.get("request_timeout_seconds") or 60),
            max_retries=int(mapping.get("max_retries") or 4),
            retry_backoff_seconds=float(mapping.get("retry_backoff_seconds") or 2.0),
            max_input_chars=int(mapping.get("max_input_chars") or 2800),
            rate_limit_sleep_seconds=float(mapping.get("rate_limit_sleep_seconds") or 30.0),
        )

    def model_uri(self, *, folder_id: str, kind: str, fallback: bool = False) -> str:
        if kind not in {"doc", "query"}:
            raise ValueError(f"unknown embedding model kind: {kind}")
        if fallback:
            template = self.fallback_doc_model_uri_template if kind == "doc" else self.fallback_query_model_uri_template
        else:
            template = self.doc_model_uri_template if kind == "doc" else self.query_model_uri_template
        return template.format(folder_id=folder_id)


def load_retrieval_config(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


def redact_model_uri(model_uri: str) -> str:
    return FOLDER_ID_RE.sub("emb://<folder_id>/", model_uri)


class YandexEmbeddingClient:
    backend = "yandex"

    def __init__(
        self,
        *,
        api_key: str,
        folder_id: str,
        config: EmbeddingConfig,
        kind: str,
        fallback: bool = False,
        session: requests.Session | None = None,
    ) -> None:
        self.api_key = api_key
        self.folder_id = folder_id
        self.config = config
        self.model_uri = config.model_uri(folder_id=folder_id, kind=kind, fallback=fallback)
        self.session = session or requests.Session()
        self.dimension: int | None = None

    def embed_text(self, text: str) -> list[float]:
        text = prepare_embedding_text(text, max_chars=self.config.max_input_chars)
        payload = {"modelUri": self.model_uri, "text": text}
        headers = {
            "Authorization": f"{self.config.auth_scheme} {self.api_key}",
            "Content-Type": "application/json",
        }
        last_error: Exception | None = None
        for attempt in range(self.config.max_retries + 1):
            try:
                response = self.session.post(
                    self.config.endpoint,
                    headers=headers,
                    json=payload,
                    timeout=self.config.request_timeout_seconds,
                )
                if response.status_code == 429:
                    raise RateLimitError(f"HTTP 429: {response.text[:500]}")
                if response.status_code in {500, 502, 503, 504}:
                    raise RuntimeError(f"transient HTTP {response.status_code}: {response.text[:500]}")
                if response.status_code >= 400:
                    raise RuntimeError(f"HTTP {response.status_code}: {response.text[:500]}")
                response.raise_for_status()
                vector = parse_embedding_response(response.json())
                self.dimension = len(vector)
                return vector
            except Exception as exc:  # noqa: BLE001 - CLI keeps cache and exits clearly after retries.
                last_error = exc
                if attempt >= self.config.max_retries:
                    break
                if isinstance(exc, RateLimitError):
                    time.sleep(self.config.rate_limit_sleep_seconds)
                else:
                    time.sleep(self.config.retry_backoff_seconds * (attempt + 1))
        raise RuntimeError(f"Yandex embedding request failed: {last_error}")


def parse_embedding_response(payload: dict[str, Any]) -> list[float]:
    candidates = [
        payload.get("embedding"),
        (payload.get("result") or {}).get("embedding") if isinstance(payload.get("result"), dict) else None,
        (payload.get("result") or {}).get("vector") if isinstance(payload.get("result"), dict) else None,
    ]
    for candidate in candidates:
        if isinstance(candidate, list) and candidate:
            return [float(value) for value in candidate]
    raise RuntimeError(f"embedding response has no vector fields: {list(payload)[:10]}")


class RateLimitError(RuntimeError):
    pass


class LocalHashEmbeddingClient:
    backend = "local-hash"

    def __init__(self, *, dimension: int = 384, model_name: str = "local-hash-v1") -> None:
        if dimension <= 0:
            raise ValueError("dimension must be positive")
        self.dimension = dimension
        self.model_uri = f"{model_name}:{dimension}"

    def embed_text(self, text: str) -> list[float]:
        vector = np.zeros(self.dimension, dtype=np.float32)
        tokens = [token.lower().replace("ё", "е") for token in TOKEN_RE.findall(text)]
        for token in tokens:
            add_token(vector, token, weight=1.0)
            if len(token) >= 5:
                for start in range(0, len(token) - 2):
                    add_token(vector, token[start : start + 3], weight=0.35)
        norm = float(np.linalg.norm(vector))
        if norm > 0:
            vector /= norm
        return vector.astype(np.float32).tolist()


def prepare_embedding_text(text: str, *, max_chars: int) -> str:
    prepared = WHITESPACE_RE.sub(" ", str(text or "")).strip()
    if max_chars <= 0 or len(prepared) <= max_chars:
        return prepared
    cutoff = max(prepared.rfind(". ", 0, max_chars), prepared.rfind("; ", 0, max_chars), prepared.rfind(" ", 0, max_chars))
    if cutoff < max_chars // 2:
        cutoff = max_chars
    return prepared[:cutoff].strip()


def embedding_input_text(client: EmbeddingClient, text: str) -> str:
    if isinstance(client, YandexEmbeddingClient):
        return prepare_embedding_text(text, max_chars=client.config.max_input_chars)
    return text


def add_token(vector: np.ndarray, token: str, *, weight: float) -> None:
    digest = hashlib.blake2b(token.encode("utf-8", errors="ignore"), digest_size=8).digest()
    value = int.from_bytes(digest, "little", signed=False)
    index = value % vector.shape[0]
    sign = -1.0 if value & (1 << 63) else 1.0
    vector[index] += sign * weight * math.log1p(len(token))


def build_embedding_client(
    *,
    backend: str,
    retrieval_config: dict[str, Any],
    kind: str,
    fallback_model: bool,
    api_key: str | None = None,
    folder_id: str | None = None,
) -> EmbeddingClient:
    if backend == "local-hash":
        local_config = retrieval_config.get("local_hash") or {}
        return LocalHashEmbeddingClient(dimension=int(local_config.get("dimension") or 384))
    if backend != "yandex":
        raise ValueError(f"unsupported embedding backend: {backend}")
    if not api_key or not folder_id:
        raise RuntimeError("YANDEX_API_KEY and YANDEX_FOLDER_ID must be set for yandex embeddings")
    return YandexEmbeddingClient(
        api_key=api_key,
        folder_id=folder_id,
        config=EmbeddingConfig.from_mapping(retrieval_config["embedding"]),
        kind=kind,
        fallback=fallback_model,
    )
