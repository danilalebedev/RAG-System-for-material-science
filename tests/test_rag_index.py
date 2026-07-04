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
    RouterAIEmbeddingClient,
    RouterAIEmbeddingConfig,
    YandexEmbeddingClient,
    apply_retrieval_profile,
    prepare_embedding_text,
)
from app.index.lexical import LexicalIndex, build_lexical_index
from app.index.summaries import iter_summary_records
from app.index.vector_store import save_vector_index
from app.rag.retrieval import dense_search, hybrid_search, materialize_results, reciprocal_rank_fusion


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


def test_routerai_embedding_client_parses_openai_compatible_batch() -> None:
    class FakeSession:
        def __init__(self) -> None:
            self.payloads: list[dict[str, object]] = []

        def post(self, *_: object, **kwargs: object) -> requests.Response:
            self.payloads.append(kwargs["json"])  # type: ignore[index]
            response = requests.Response()
            response.status_code = 200
            response._content = json.dumps(  # noqa: SLF001
                {
                    "data": [
                        {"index": 0, "embedding": [1.0, 0.0, 0.0]},
                        {"index": 1, "embedding": [0.0, 1.0, 0.0]},
                    ]
                }
            ).encode("utf-8")
            response.encoding = "utf-8"
            return response

    session = FakeSession()
    client = RouterAIEmbeddingClient(
        RouterAIEmbeddingConfig(api_key="fake-router-key", model="baai/bge-m3", max_input_chars=32),
        session=session,  # type: ignore[arg-type]
    )

    vectors = client.embed_texts(["nickel concentrate", "copper ore"])

    assert vectors == [[1.0, 0.0, 0.0], [0.0, 1.0, 0.0]]
    assert client.dimension == 3
    assert session.payloads[0]["model"] == "baai/bge-m3"
    assert session.payloads[0]["input"] == ["nickel concentrate", "copper ore"]


def test_routerai_embedding_client_redacts_secret_from_http_errors() -> None:
    class FakeSession:
        def post(self, *_: object, **__: object) -> requests.Response:
            response = requests.Response()
            response.status_code = 401
            response._content = b"bad key fake-router-key"  # noqa: SLF001
            response.encoding = "utf-8"
            return response

    client = RouterAIEmbeddingClient(
        RouterAIEmbeddingConfig(api_key="fake-router-key", model="baai/bge-m3"),
        session=FakeSession(),  # type: ignore[arg-type]
    )

    with pytest.raises(NonRetryableEmbeddingError) as exc_info:
        client.embed_text("nickel")

    assert "fake-router-key" not in str(exc_info.value)
    assert "<redacted>" in str(exc_info.value)


def test_apply_retrieval_profile_selects_routerai_index_dirs() -> None:
    config = {
        "chunk_index_dir": "data/indexes/chunks",
        "lexical_index_dir": "data/indexes/lexical",
        "document_summary_index_dir": "data/indexes/document_summaries",
        "procedure_summary_index_dir": "data/indexes/procedure_summaries",
        "embedding": {"backend": "yandex", "default_model": "fallback"},
        "profiles": {
            "routerai_bge_m3": {
                "chunk_index_dir": "data/indexes/chunks_routerai_bge_m3",
                "lexical_index_dir": "data/indexes/lexical_routerai_bge_m3",
                "document_summary_index_dir": "data/indexes/document_summaries_routerai_bge_m3",
                "procedure_summary_index_dir": "data/indexes/procedure_summaries_routerai_bge_m3",
                "embedding_backend": "routerai",
                "default_model": "doc",
            }
        },
    }

    profiled = apply_retrieval_profile(config, "routerai_bge_m3")

    assert profiled["chunk_index_dir"].endswith("chunks_routerai_bge_m3")
    assert profiled["lexical_index_dir"].endswith("lexical_routerai_bge_m3")
    assert profiled["document_summary_index_dir"].endswith("document_summaries_routerai_bge_m3")
    assert profiled["procedure_summary_index_dir"].endswith("procedure_summaries_routerai_bge_m3")
    assert profiled["embedding"]["backend"] == "routerai"
    assert profiled["embedding"]["default_model"] == "doc"
    assert profiled["active_profile"] == "routerai_bge_m3"


def test_prepare_embedding_text_truncates_yandex_input() -> None:
    text = ("слово " * 1000).strip()
    prepared = prepare_embedding_text(text, max_chars=120)
    assert len(prepared) <= 120
    assert prepared.endswith("слово")


def write_ranking_chunks(path: Path) -> None:
    rows = [
        {
            "chunk_id": "chunk_gold_ore",
            "doc_id": "doc_gold",
            "chunk_index": 1,
            "text": "Gold ore and Au extraction are discussed for precious metals.",
            "source_path": "/source/gold.pdf",
            "local_path": "C:/data/gold.pdf",
        },
        {
            "chunk_id": "chunk_nickel_ore",
            "doc_id": "doc_nickel",
            "chunk_index": 1,
            "text": "Nickel ore Ni resources include никелевая руда, никелевые руды and flotation concentrate tests.",
            "source_path": "/source/nickel_ore.pdf",
            "local_path": "C:/data/nickel_ore.pdf",
        },
    ]
    with path.open("w", encoding="utf-8", newline="\n") as f:
        for row in rows:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")


def local_retrieval_config(chunks_path: Path, index_dir: Path, lexical_dir: Path, *, dimension: int = 64) -> dict[str, object]:
    return {
        "chunks_path": str(chunks_path),
        "chunk_index_dir": str(index_dir),
        "lexical_index_dir": str(lexical_dir),
        "embedding": {
            "backend": "local-hash",
            "endpoint": "unused",
            "auth_scheme": "Api-Key",
            "doc_model_uri_template": "unused",
            "query_model_uri_template": "unused",
            "fallback_doc_model_uri_template": "unused",
            "fallback_query_model_uri_template": "unused",
        },
        "local_hash": {"dimension": dimension},
        "search": {
            "top_k": 5,
            "dense_top_k": 5,
            "lexical_top_k": 5,
            "summary_top_k": 5,
            "rrf_k": 60,
            "snippet_chars": 500,
            "weights": {"domain": 0.12, "phrase": 0.08, "field": 0.04, "summary_lexical": 0.9, "summary_vector": 0.9},
        },
    }


def build_local_indexes(chunks_path: Path, index_dir: Path, lexical_dir: Path, *, dimension: int = 64) -> LocalHashEmbeddingClient:
    records = list(iter_chunk_records(chunks_path))
    client = LocalHashEmbeddingClient(dimension=dimension)
    save_vector_index(
        index_dir,
        [client.embed_text(record.text) for record in records],
        [record.metadata() for record in records],
        {
            "embedding_backend": client.backend,
            "embedding_model_uri": client.model_uri,
            "model_selection": "doc",
            "source_chunks_path": str(chunks_path),
        },
    )
    build_lexical_index(lexical_dir, records)
    return client


def test_hybrid_candidate_schema_boosts_nickel_ore_over_gold(tmp_path: Path) -> None:
    chunks_path = tmp_path / "chunks.jsonl"
    index_dir = tmp_path / "chunks_index"
    lexical_dir = tmp_path / "lexical"
    write_ranking_chunks(chunks_path)
    build_local_indexes(chunks_path, index_dir, lexical_dir)

    results, diagnostics = hybrid_search(
        query="никелевая руда",
        retrieval_config=local_retrieval_config(chunks_path, index_dir, lexical_dir),
        index_dir=index_dir,
        lexical_dir=lexical_dir,
        chunks_path=chunks_path,
        top_k=2,
        allow_network=False,
        include_summaries=False,
    )

    assert diagnostics.query.search_query == "никелевая руда"
    assert results[0].doc_id == "doc_nickel"
    payload = results[0].as_dict()
    assert payload["candidate_id"] == "raw_chunk:chunk_nickel_ore"
    assert payload["source_type"] == "raw_chunk"
    assert {"dense", "lexical", "domain", "phrase"}.intersection(payload["score_components"])
    assert payload["why"]
    assert all(result.doc_id != "doc_gold" or result.rank > 1 for result in results)


def test_hybrid_offline_skips_yandex_dense_and_keeps_lexical_results(tmp_path: Path) -> None:
    chunks_path = tmp_path / "chunks.jsonl"
    index_dir = tmp_path / "chunks_index"
    lexical_dir = tmp_path / "lexical"
    write_ranking_chunks(chunks_path)
    build_local_indexes(chunks_path, index_dir, lexical_dir)
    manifest_path = index_dir / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["embedding_backend"] = "yandex"
    manifest["model_selection"] = "fallback"
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False), encoding="utf-8")

    results, diagnostics = hybrid_search(
        query="никелевая руда",
        retrieval_config=local_retrieval_config(chunks_path, index_dir, lexical_dir),
        index_dir=index_dir,
        lexical_dir=lexical_dir,
        chunks_path=chunks_path,
        top_k=2,
        allow_network=False,
        include_summaries=False,
    )

    assert diagnostics.dense_status == "skipped_offline"
    assert results
    assert results[0].components.get("lexical", 0) > 0
    assert "dense" not in results[0].components


def test_summary_lexical_and_vector_are_separate_candidate_streams(tmp_path: Path) -> None:
    chunks_path = tmp_path / "chunks.jsonl"
    index_dir = tmp_path / "chunks_index"
    lexical_dir = tmp_path / "lexical"
    summary_path = tmp_path / "document_summaries.jsonl"
    summary_index_dir = tmp_path / "document_summary_index"
    write_ranking_chunks(chunks_path)
    build_local_indexes(chunks_path, index_dir, lexical_dir)
    summary_row = {
        "document_summary_id": "docsum_nickel",
        "doc_id": "doc_summary",
        "publication_id": "pub_summary",
        "title": "Nickel ore flotation",
        "summary": "Nickel ore Ni flotation produces a nickel concentrate.",
        "materials": ["nickel ore"],
        "processes": ["flotation"],
        "confidence": 0.9,
    }
    summary_path.write_text(json.dumps(summary_row, ensure_ascii=False) + "\n", encoding="utf-8")
    summary_records = list(iter_summary_records(summary_path, kind="document_summary"))
    client = LocalHashEmbeddingClient(dimension=64)
    save_vector_index(
        summary_index_dir,
        [client.embed_text(record.text) for record in summary_records],
        [record.metadata() for record in summary_records],
        {
            "embedding_backend": client.backend,
            "embedding_model_uri": client.model_uri,
            "model_selection": "doc",
            "source_summary_path": str(summary_path),
        },
    )

    results, diagnostics = hybrid_search(
        query="никелевая руда",
        retrieval_config=local_retrieval_config(chunks_path, index_dir, lexical_dir),
        index_dir=index_dir,
        lexical_dir=lexical_dir,
        chunks_path=chunks_path,
        top_k=5,
        allow_network=False,
        publications_dir=tmp_path,
        document_summary_index_dir=summary_index_dir,
        include_summaries=True,
    )

    summary_results = [result for result in results if result.source_type == "document_summary"]
    assert summary_results
    assert any("summary_lexical" in result.components for result in summary_results)
    assert any("summary_vector" in result.components for result in summary_results)
    assert diagnostics.streams["summary_lexical"] == 1
    assert diagnostics.streams["document_summary_vector"] == 1
