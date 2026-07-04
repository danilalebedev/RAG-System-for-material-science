from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.index.chunks import iter_chunk_records
from app.index.embeddings import LocalHashEmbeddingClient
from app.index.lexical import build_lexical_index
from app.index.vector_store import save_vector_index
from app.rag.validation import SearchCase, run_validation
from scripts import search_cli


class FakeTextStream:
    def __init__(self) -> None:
        self.calls: list[dict[str, str]] = []

    def reconfigure(self, **kwargs: str) -> None:
        self.calls.append(kwargs)


def write_retrieval_config(path: Path, chunks_path: Path, index_dir: Path, lexical_dir: Path) -> None:
    payload = {
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
        "local_hash": {"dimension": 64},
        "search": {"top_k": 3, "dense_top_k": 3, "lexical_top_k": 3, "rrf_k": 60, "snippet_chars": 300},
    }
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")


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


def build_fixture_index(tmp_path: Path) -> tuple[Path, Path, Path, Path]:
    chunks_path = tmp_path / "chunks.jsonl"
    index_dir = tmp_path / "chunks_index"
    lexical_dir = tmp_path / "lexical"
    config_path = tmp_path / "retrieval.json"
    write_chunks(chunks_path)
    records = list(iter_chunk_records(chunks_path))
    client = LocalHashEmbeddingClient(dimension=64)
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
    write_retrieval_config(config_path, chunks_path, index_dir, lexical_dir)
    return config_path, chunks_path, index_dir, lexical_dir


def test_validation_agent_passes_relevant_search_cases(tmp_path: Path) -> None:
    config_path, chunks_path, index_dir, lexical_dir = build_fixture_index(tmp_path)
    report = run_validation(
        root=tmp_path,
        config_path=config_path,
        index_dir=index_dir,
        lexical_dir=lexical_dir,
        chunks_path=chunks_path,
        cases=[
            SearchCase(
                query="никелевые концентраты обжиг",
                expected_terms=("никел", "концентрат", "обжиг"),
                min_unique_terms=2,
                min_top1_terms=1,
                min_results=1,
            )
        ],
        top_k=2,
    )

    assert report["status"] == "pass"
    assert report["artifacts"]["metadata_count"] == 3
    assert report["search_cases"][0]["status"] == "pass"
    assert report["search_cases"][0]["top_results"][0]["chunk_id"] == "chunk_nickel"


def test_validation_agent_fails_irrelevant_search_case(tmp_path: Path) -> None:
    config_path, chunks_path, index_dir, lexical_dir = build_fixture_index(tmp_path)
    report = run_validation(
        root=tmp_path,
        config_path=config_path,
        index_dir=index_dir,
        lexical_dir=lexical_dir,
        chunks_path=chunks_path,
        cases=[
            SearchCase(
                query="никелевые концентраты обжиг",
                expected_terms=("золото", "телеком", "цемент"),
                min_unique_terms=2,
                min_top1_terms=1,
                min_results=1,
            )
        ],
        top_k=2,
    )

    assert report["status"] == "fail"
    assert report["search_cases"][0]["status"] == "fail"
    assert any(issue["code"] == "low_term_coverage" for issue in report["issues"])


def test_validation_agent_reports_dense_query_embedding_failure(tmp_path: Path) -> None:
    config_path, chunks_path, index_dir, lexical_dir = build_fixture_index(tmp_path)
    manifest_path = index_dir / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["embedding_backend"] = "yandex"
    manifest["model_selection"] = "fallback"
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False), encoding="utf-8")
    report = run_validation(
        root=tmp_path,
        config_path=config_path,
        index_dir=index_dir,
        lexical_dir=lexical_dir,
        chunks_path=chunks_path,
        cases=[
            SearchCase(
                query="РЅРёРєРµР»РµРІС‹Рµ РєРѕРЅС†РµРЅС‚СЂР°С‚С‹ РѕР±Р¶РёРі",
                expected_terms=("РЅРёРєРµР»", "РєРѕРЅС†РµРЅС‚СЂР°С‚", "РѕР±Р¶РёРі"),
                min_unique_terms=2,
                min_top1_terms=1,
                min_results=1,
            )
        ],
        top_k=2,
        allow_network=True,
        mode="dense",
    )

    assert report["status"] == "fail"
    assert any(issue["code"] == "search_failed" for issue in report["issues"])


def test_validation_agent_hybrid_offline_degrades_to_lexical(tmp_path: Path) -> None:
    config_path, chunks_path, index_dir, lexical_dir = build_fixture_index(tmp_path)
    manifest_path = index_dir / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["embedding_backend"] = "yandex"
    manifest["model_selection"] = "fallback"
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False), encoding="utf-8")

    report = run_validation(
        root=tmp_path,
        config_path=config_path,
        index_dir=index_dir,
        lexical_dir=lexical_dir,
        chunks_path=chunks_path,
        cases=[
            SearchCase(
                query="никелевые концентраты обжиг",
                expected_terms=("никел", "концентрат", "обжиг"),
                min_unique_terms=2,
                min_top1_terms=1,
                min_results=1,
            )
        ],
        top_k=2,
        allow_network=False,
        mode="hybrid",
    )

    assert report["status"] == "pass"
    assert report["search_cases"][0]["diagnostics"]["dense_status"] == "skipped_offline"


def test_search_cli_configures_utf8_stdio(monkeypatch: pytest.MonkeyPatch) -> None:
    stdout = FakeTextStream()
    stderr = FakeTextStream()
    monkeypatch.setattr(search_cli.sys, "stdout", stdout)
    monkeypatch.setattr(search_cli.sys, "stderr", stderr)

    search_cli.configure_stdio()

    assert stdout.calls == [{"encoding": "utf-8", "errors": "replace"}]
    assert stderr.calls == [{"encoding": "utf-8", "errors": "replace"}]
