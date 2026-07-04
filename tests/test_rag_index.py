from __future__ import annotations

import json
from pathlib import Path

import pytest
import requests

from app.index.chunks import iter_chunk_records
from app.index.embeddings import (
    EmbeddingConfig,
    LocalHashEmbeddingClient,
    NonRetryableEmbeddingError,
    YandexEmbeddingClient,
    prepare_embedding_text,
)
from app.index.lexical import LexicalIndex, build_lexical_index
from app.index.vector_store import save_vector_index
from app.rag.retrieval import dense_search, materialize_results, reciprocal_rank_fusion


def write_chunks(path: Path) -> None:
    rows = [
        {
            "chunk_id": "chunk_nickel",
            "doc_id": "doc_1",
            "chunk_index": 1,
            "text": "Никелевые концентраты проходят обжиг перед плавкой.",
            "source_path": "/source/nickel.pdf",
            "local_path": "C:/data/nickel.pdf",
        },
        {
            "chunk_id": "chunk_water",
            "doc_id": "doc_2",
            "chunk_index": 1,
            "text": "Очистка воды от сульфатов использует мембранные методы.",
            "source_path": "/source/water.pdf",
            "local_path": "C:/data/water.pdf",
        },
        {
            "chunk_id": "chunk_copper",
            "doc_id": "doc_3",
            "chunk_index": 1,
            "text": "Медные руды обогащаются флотацией.",
            "source_path": "/source/copper.pdf",
            "local_path": "C:/data/copper.pdf",
        },
    ]
    with path.open("w", encoding="utf-8", newline="\n") as f:
        for row in rows:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")


def test_local_vector_and_lexical_retrieval_over_chunks(tmp_path: Path) -> None:
    chunks_path = tmp_path / "chunks.jsonl"
    index_dir = tmp_path / "chunks_index"
    lexical_dir = tmp_path / "lexical"
    write_chunks(chunks_path)

    records = list(iter_chunk_records(chunks_path))
    client = LocalHashEmbeddingClient(dimension=64)
    vectors = [client.embed_text(record.text) for record in records]
    metadata = [record.metadata() for record in records]
    save_vector_index(
        index_dir,
        vectors,
        metadata,
        {"embedding_backend": client.backend, "embedding_model_uri": client.model_uri, "source_chunks_path": str(chunks_path)},
    )
    build_lexical_index(lexical_dir, records)

    dense_hits = dense_search(index_dir, client.embed_text("никелевые концентраты обжиг"), top_k=3)
    lexical_hits = LexicalIndex(lexical_dir).search("никелевые концентраты обжиг", top_k=3)
    ranked = reciprocal_rank_fusion(dense_hits=dense_hits, lexical_hits=lexical_hits, top_k=2)
    results = materialize_results(ranked_rows=ranked, index_dir=index_dir, chunks_path=chunks_path, snippet_chars=200)

    assert results
    assert results[0].chunk_id == "chunk_nickel"
    assert results[0].doc_id == "doc_1"
    assert "обжиг" in results[0].text


def test_yandex_client_does_not_retry_non_retryable_http_errors(monkeypatch: pytest.MonkeyPatch) -> None:
    class FakeSession:
        def __init__(self) -> None:
            self.calls = 0

        def post(self, *_: object, **__: object) -> requests.Response:
            self.calls += 1
            response = requests.Response()
            response.status_code = 403
            response._content = b'{"error":"Permission denied","code":7}'  # noqa: SLF001
            response.encoding = "utf-8"
            return response

    sleeps: list[float] = []
    monkeypatch.setattr("app.index.embeddings.time.sleep", sleeps.append)
    session = FakeSession()
    config = EmbeddingConfig(
        endpoint="https://example.invalid/textEmbedding",
        auth_scheme="Api-Key",
        doc_model_uri_template="emb://{folder_id}/text-search-doc/latest",
        query_model_uri_template="emb://{folder_id}/text-search-query/latest",
        fallback_doc_model_uri_template="emb://{folder_id}/text-search-doc/latest",
        fallback_query_model_uri_template="emb://{folder_id}/text-search-query/latest",
        max_retries=20,
    )
    client = YandexEmbeddingClient(
        api_key="fake-key",
        folder_id="fake-folder",
        config=config,
        kind="query",
        fallback=True,
        session=session,  # type: ignore[arg-type]
    )

    with pytest.raises(NonRetryableEmbeddingError):
        client.embed_text("nickel concentrate roasting")

    assert session.calls == 1
    assert sleeps == []


def test_prepare_embedding_text_truncates_yandex_input() -> None:
    text = ("слово " * 1000).strip()
    prepared = prepare_embedding_text(text, max_chars=120)
    assert len(prepared) <= 120
    assert prepared.endswith("слово")
