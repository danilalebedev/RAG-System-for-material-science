from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any

from dotenv import load_dotenv

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.index.embeddings import build_embedding_client, load_retrieval_config  # noqa: E402
from app.index.lexical import LexicalIndex  # noqa: E402
from app.index.vector_store import load_manifest  # noqa: E402
from app.rag.retrieval import dense_search, lexical_search, materialize_results, reciprocal_rank_fusion  # noqa: E402


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Search parsed source chunks through local RAG indexes.")
    parser.add_argument("query")
    parser.add_argument("--config", default="config/retrieval/default.json")
    parser.add_argument("--index-dir", default=None)
    parser.add_argument("--lexical-dir", default=None)
    parser.add_argument("--chunks", default=None)
    parser.add_argument("--top-k", type=int, default=None)
    parser.add_argument("--dense-top-k", type=int, default=None)
    parser.add_argument("--lexical-top-k", type=int, default=None)
    parser.add_argument("--mode", choices=["hybrid", "dense", "lexical"], default="hybrid")
    parser.add_argument("--model", choices=["auto", "query", "fallback"], default="auto")
    parser.add_argument("--embedding-backend", choices=["yandex", "local-hash"], default=None)
    parser.add_argument("--json", action="store_true", default=False)
    return parser.parse_args()


def resolve_project_path(root: Path, value: str | None, fallback: str) -> Path:
    raw = value or fallback
    path = Path(raw)
    return path if path.is_absolute() else root / path


def query_vector(
    *,
    query: str,
    backend: str,
    retrieval_config: dict[str, Any],
    model: str,
) -> list[float]:
    client = build_embedding_client(
        backend=backend,
        retrieval_config=retrieval_config,
        kind="query",
        fallback_model=model == "fallback",
        api_key=os.getenv("YANDEX_API_KEY"),
        folder_id=os.getenv("YANDEX_FOLDER_ID"),
    )
    return client.embed_text(query)


def main() -> int:
    args = parse_args()
    root = Path(__file__).resolve().parents[1]
    load_dotenv(root / ".env")
    retrieval_config = load_retrieval_config(root / args.config)
    search_config = retrieval_config.get("search") or {}
    index_dir = resolve_project_path(root, args.index_dir, retrieval_config.get("chunk_index_dir", "data/indexes/chunks"))
    lexical_dir = resolve_project_path(root, args.lexical_dir, retrieval_config.get("lexical_index_dir", "data/indexes/lexical"))
    manifest = load_manifest(index_dir)
    chunks_path = resolve_project_path(
        root,
        args.chunks,
        str(manifest.get("source_chunks_path") or retrieval_config.get("chunks_path") or "data/parsed/chunks.jsonl"),
    )
    top_k = args.top_k if args.top_k is not None else int(search_config.get("top_k") or 10)
    dense_top_k = args.dense_top_k if args.dense_top_k is not None else int(search_config.get("dense_top_k") or 50)
    lexical_top_k = args.lexical_top_k if args.lexical_top_k is not None else int(search_config.get("lexical_top_k") or 50)
    snippet_chars = int(search_config.get("snippet_chars") or 700)
    rrf_k = int(search_config.get("rrf_k") or 60)
    vector_batch_size = int(search_config.get("vector_batch_size") or 8192)
    backend = args.embedding_backend or str(manifest.get("embedding_backend") or (retrieval_config.get("embedding") or {}).get("backend") or "yandex")
    query_model = args.model
    if query_model == "auto":
        query_model = "fallback" if manifest.get("model_selection") == "fallback" else "query"

    dense_hits = []
    lexical_hits = []
    if args.mode in {"hybrid", "dense"}:
        if not manifest:
            raise RuntimeError(f"vector manifest not found in {index_dir}; run scripts/build_indexes.py first")
        dense_hits = dense_search(
            index_dir,
            query_vector(query=args.query, backend=backend, retrieval_config=retrieval_config, model=query_model),
            top_k=dense_top_k if args.mode == "hybrid" else top_k,
            batch_size=vector_batch_size,
        )
    if args.mode in {"hybrid", "lexical"}:
        lexical_index = LexicalIndex(lexical_dir)
        if lexical_index.exists():
            lexical_hits = lexical_search(lexical_dir, args.query, top_k=lexical_top_k if args.mode == "hybrid" else top_k)
        elif args.mode == "lexical":
            raise RuntimeError(f"lexical index not found in {lexical_dir}; run scripts/build_indexes.py first")

    if args.mode == "dense":
        ranked_rows = [(hit.row_id, hit.score, {"dense": hit.score}) for hit in dense_hits[:top_k]]
    elif args.mode == "lexical":
        ranked_rows = [(hit.row_id, hit.score, {"lexical": hit.score}) for hit in lexical_hits[:top_k]]
    else:
        ranked_rows = reciprocal_rank_fusion(dense_hits=dense_hits, lexical_hits=lexical_hits, rrf_k=rrf_k, top_k=top_k)
    results = materialize_results(ranked_rows=ranked_rows, index_dir=index_dir, chunks_path=chunks_path, snippet_chars=snippet_chars)

    if args.json:
        print(json.dumps([result.as_dict() for result in results], ensure_ascii=False, indent=2))
        return 0
    for result in results:
        print(f"{result.rank}. score={result.score:.6f} doc_id={result.doc_id} chunk_id={result.chunk_id}")
        print(f"   source_path={result.source_path}")
        if result.components:
            components = ", ".join(f"{key}={value:.6f}" for key, value in sorted(result.components.items()))
            print(f"   components={components}")
        print(f"   {result.text}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
