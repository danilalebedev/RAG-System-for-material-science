from __future__ import annotations

import hashlib
import json
import math
import os
import random
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
    max_input_terms: int = 1400
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
            max_input_terms=int(mapping.get("max_input_terms") or 1400),
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


def apply_retrieval_profile(config: dict[str, Any], profile: str | None) -> dict[str, Any]:
    if not profile:
        return config
    profiles = config.get("profiles") or {}
    if profile not in profiles:
        raise ValueError(f"unknown retrieval profile: {profile}")
    profile_config = dict(profiles[profile] or {})
    merged = dict(config)
    embedding = dict(merged.get("embedding") or {})
    for key in (
        "chunks_path",
        "chunk_index_dir",
        "lexical_index_dir",
        "summary_publications_dir",
        "document_summary_index_dir",
        "procedure_summary_index_dir",
    ):
        if key in profile_config:
            merged[key] = profile_config[key]
    if profile_config.get("embedding_backend"):
        embedding["backend"] = profile_config["embedding_backend"]
    if profile_config.get("default_model"):
        embedding["default_model"] = profile_config["default_model"]
    merged["embedding"] = embedding
    merged["active_profile"] = profile
    return merged


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
        prepared_text = prepare_embedding_text(text, max_chars=self.config.max_input_chars, max_terms=self.config.max_input_terms)
        headers = {
            "Authorization": f"{self.config.auth_scheme} {self.api_key}",
            "Content-Type": "application/json",
        }
        last_error: Exception | None = None
        for attempt in range(self.config.max_retries + 1):
            payload = {"modelUri": self.model_uri, "text": prepared_text}
            try:
                response = self.session.post(
                    self.config.endpoint,
                    headers=headers,
                    json=payload,
                    timeout=self.config.request_timeout_seconds,
                )
                if response.status_code == 429:
                    retry_after = retry_after_seconds(response)
                    raise RateLimitError(f"HTTP 429: {response.text[:500]}", retry_after=retry_after)
                if response.status_code == 400 and is_token_limit_error(response.text) and len(prepared_text) > 400:
                    prepared_text = shrink_embedding_text(prepared_text)
                    continue
                if response.status_code in {500, 502, 503, 504}:
                    raise TransientEmbeddingError(f"transient HTTP {response.status_code}: {response.text[:500]}")
                if response.status_code >= 400:
                    raise NonRetryableEmbeddingError(f"HTTP {response.status_code}: {response.text[:500]}")
                response.raise_for_status()
                vector = parse_embedding_response(response.json())
                self.dimension = len(vector)
                return vector
            except NonRetryableEmbeddingError:
                raise
            except (requests.RequestException, RuntimeError, RateLimitError) as exc:
                last_error = exc
                if attempt >= self.config.max_retries:
                    break
                if isinstance(exc, RateLimitError):
                    sleep_seconds = exc.retry_after or self.config.rate_limit_sleep_seconds
                    time.sleep(sleep_seconds + random.uniform(0.0, 0.25))
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


def parse_openai_embeddings_response(payload: dict[str, Any], *, expected_count: int) -> list[list[float]]:
    data = payload.get("data")
    if not isinstance(data, list):
        raise RuntimeError(f"embedding response has no data list: {list(payload)[:10]}")
    indexed_vectors: list[tuple[int, list[float]]] = []
    for position, item in enumerate(data):
        if not isinstance(item, dict):
            raise RuntimeError("embedding response contains non-object item")
        vector = item.get("embedding")
        if not isinstance(vector, list) or not vector:
            raise RuntimeError("embedding response item has no embedding vector")
        index = item.get("index")
        indexed_vectors.append((int(index) if isinstance(index, int) else position, [float(value) for value in vector]))
    indexed_vectors.sort(key=lambda item: item[0])
    vectors = [vector for _, vector in indexed_vectors]
    if len(vectors) != expected_count:
        raise RuntimeError(f"embedding response count {len(vectors)} does not match requested count {expected_count}")
    return vectors


def redact_secret(text: str, secret: str | None) -> str:
    if not secret:
        return text
    return text.replace(secret, "<redacted>")


class RateLimitError(RuntimeError):
    def __init__(self, message: str, *, retry_after: float | None = None) -> None:
        super().__init__(message)
        self.retry_after = retry_after


class TransientEmbeddingError(RuntimeError):
    pass


class NonRetryableEmbeddingError(RuntimeError):
    pass


def retry_after_seconds(response: requests.Response) -> float | None:
    value = response.headers.get("Retry-After")
    if not value:
        return None
    try:
        return max(0.0, float(value))
    except ValueError:
        return None


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


@dataclass(frozen=True)
class RouterAIEmbeddingConfig:
    api_key: str
    model: str = "baai/bge-m3"
    base_url: str = "https://routerai.ru/api/v1"
    timeout_seconds: float = 60.0
    max_retries: int = 4
    retry_backoff_seconds: float = 2.0
    max_input_chars: int = 1700
    max_input_terms: int = 1000

    @classmethod
    def from_mapping(cls, mapping: dict[str, Any], *, api_key: str) -> "RouterAIEmbeddingConfig":
        return cls(
            api_key=api_key,
            model=str(mapping.get("model") or "baai/bge-m3"),
            base_url=str(mapping.get("base_url") or "https://routerai.ru/api/v1"),
            timeout_seconds=float(mapping.get("timeout_seconds") or 60.0),
            max_retries=int(mapping.get("max_retries") or 4),
            retry_backoff_seconds=float(mapping.get("retry_backoff_seconds") or 2.0),
            max_input_chars=int(mapping.get("max_input_chars") or 1700),
            max_input_terms=int(mapping.get("max_input_terms") or 1000),
        )

    def embeddings_url(self) -> str:
        return self.base_url.rstrip("/") + "/embeddings"


class RouterAIEmbeddingClient:
    backend = "routerai"
    supports_batch = True

    def __init__(self, config: RouterAIEmbeddingConfig, *, session: requests.Session | None = None) -> None:
        self.config = config
        self.model_uri = f"routerai://{config.model}"
        self.session = session or requests.Session()
        self.dimension: int | None = None

    def embed_text(self, text: str) -> list[float]:
        return self.embed_texts([text])[0]

    def embed_texts(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []
        prepared_texts = [
            prepare_embedding_text(text, max_chars=self.config.max_input_chars, max_terms=self.config.max_input_terms)
            for text in texts
        ]
        headers = {
            "Authorization": f"Bearer {self.config.api_key}",
            "Content-Type": "application/json",
        }
        payload = {
            "model": self.config.model,
            "input": prepared_texts,
            "encoding_format": "float",
        }
        last_error: Exception | None = None
        for attempt in range(self.config.max_retries + 1):
            try:
                response = self.session.post(
                    self.config.embeddings_url(),
                    headers=headers,
                    json=payload,
                    timeout=self.config.timeout_seconds,
                )
                if response.status_code == 429:
                    raise RateLimitError(
                        f"HTTP 429: {redact_secret(response.text[:500], self.config.api_key)}",
                        retry_after=retry_after_seconds(response),
                    )
                if response.status_code in {500, 502, 503, 504}:
                    raise TransientEmbeddingError(
                        f"transient HTTP {response.status_code}: {redact_secret(response.text[:500], self.config.api_key)}"
                    )
                if response.status_code >= 400:
                    raise NonRetryableEmbeddingError(
                        f"HTTP {response.status_code}: {redact_secret(response.text[:500], self.config.api_key)}"
                    )
                response.raise_for_status()
                vectors = parse_openai_embeddings_response(response.json(), expected_count=len(prepared_texts))
                if vectors:
                    self.dimension = len(vectors[0])
                return vectors
            except NonRetryableEmbeddingError:
                raise
            except (requests.RequestException, RuntimeError, RateLimitError) as exc:
                last_error = exc
                if attempt >= self.config.max_retries:
                    break
                if isinstance(exc, RateLimitError):
                    sleep_seconds = exc.retry_after if exc.retry_after is not None else self.config.retry_backoff_seconds * (attempt + 1)
                else:
                    sleep_seconds = self.config.retry_backoff_seconds * (attempt + 1)
                time.sleep(sleep_seconds + random.uniform(0.0, 0.25))
        raise RuntimeError(f"RouterAI embedding request failed: {redact_secret(str(last_error), self.config.api_key)}")


def prepare_embedding_text(text: str, *, max_chars: int, max_terms: int | None = None) -> str:
    prepared = WHITESPACE_RE.sub(" ", str(text or "")).strip()
    if max_terms and max_terms > 0:
        terms = prepared.split()
        if len(terms) > max_terms:
            prepared = " ".join(terms[:max_terms])
    if max_chars <= 0 or len(prepared) <= max_chars:
        return prepared
    cutoff = max(prepared.rfind(". ", 0, max_chars), prepared.rfind("; ", 0, max_chars), prepared.rfind(" ", 0, max_chars))
    if cutoff < max_chars // 2:
        cutoff = max_chars
    return prepared[:cutoff].strip()


def shrink_embedding_text(text: str) -> str:
    target = max(400, int(len(text) * 0.75))
    return prepare_embedding_text(text, max_chars=target, max_terms=None)


def is_token_limit_error(text: str) -> bool:
    lowered = text.lower()
    return "number of input tokens" in lowered and "no more than" in lowered


def embedding_input_text(client: EmbeddingClient, text: str) -> str:
    if isinstance(client, YandexEmbeddingClient):
        return prepare_embedding_text(
            text,
            max_chars=client.config.max_input_chars,
            max_terms=client.config.max_input_terms,
        )
    if isinstance(client, RouterAIEmbeddingClient):
        return prepare_embedding_text(
            text,
            max_chars=client.config.max_input_chars,
            max_terms=client.config.max_input_terms,
        )
    return text


def embed_texts(client: EmbeddingClient, texts: list[str]) -> list[list[float]]:
    if hasattr(client, "embed_texts"):
        return getattr(client, "embed_texts")(texts)
    return [client.embed_text(text) for text in texts]


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
    if backend == "routerai":
        router_config = dict(retrieval_config.get("routerai") or {})
        embedding_config = retrieval_config.get("embedding") or {}
        router_config.setdefault("max_input_chars", embedding_config.get("max_input_chars") or 1700)
        router_config.setdefault("max_input_terms", embedding_config.get("max_input_terms") or 1000)
        router_config.setdefault("api_key", os.getenv("ROUTERAI_API_KEY"))
        router_config.setdefault("model", os.getenv("ROUTERAI_EMBEDDING_MODEL") or "baai/bge-m3")
        router_config.setdefault("base_url", os.getenv("ROUTERAI_BASE_URL") or "https://routerai.ru/api/v1")
        router_config.setdefault("timeout_seconds", os.getenv("ROUTERAI_TIMEOUT_SECONDS") or 60.0)
        if not router_config.get("api_key"):
            raise RuntimeError("ROUTERAI_API_KEY must be set for routerai embeddings")
        return RouterAIEmbeddingClient(
            RouterAIEmbeddingConfig.from_mapping(router_config, api_key=str(router_config["api_key"]))
        )
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
