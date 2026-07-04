from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any

from dotenv import load_dotenv

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.index.embeddings import apply_retrieval_profile, load_retrieval_config  # noqa: E402
from app.index.vector_store import load_manifest  # noqa: E402
from app.rag.retrieval import hybrid_search  # noqa: E402


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Search parsed source chunks through local RAG indexes.")
    parser.add_argument("query")
    parser.add_argument("--config", default="config/retrieval/default.json")
    parser.add_argument("--profile", default=None, help="Retrieval profile from config.profiles, e.g. routerai_bge_m3.")
    parser.add_argument("--index-dir", default=None)
    parser.add_argument("--lexical-dir", default=None)
    parser.add_argument("--chunks", default=None)
    parser.add_argument("--publications-dir", default=None)
    parser.add_argument("--document-summary-index-dir", default=None)
    parser.add_argument("--procedure-summary-index-dir", default=None)
    parser.add_argument("--table-root", action="append", default=None)
    parser.add_argument("--documents", default=None)
    parser.add_argument("--tables", default=None)
    parser.add_argument("--graph-nodes", default=None)
    parser.add_argument("--graph-edges", default=None)
    parser.add_argument("--top-k", type=int, default=None)
    parser.add_argument("--dense-top-k", type=int, default=None)
    parser.add_argument("--lexical-top-k", type=int, default=None)
    parser.add_argument("--summary-top-k", type=int, default=None)
    parser.add_argument("--table-top-k", type=int, default=None)
    parser.add_argument("--graph-top-k", type=int, default=None)
    parser.add_argument("--mode", choices=["hybrid", "dense", "lexical"], default="hybrid")
    parser.add_argument("--model", choices=["auto", "query", "fallback"], default="auto")
    parser.add_argument("--embedding-backend", choices=["yandex", "local-hash", "routerai"], default=None)
    parser.add_argument("--offline", action="store_true", default=False, help="Skip network-only dense embeddings and use local streams.")
    parser.add_argument("--no-summaries", action="store_true", default=False)
    parser.add_argument("--include-tables", action="store_true", default=False)
    parser.add_argument("--include-graph", action="store_true", default=False)
    parser.add_argument("--json", action="store_true", default=False)
    return parser.parse_args()


def resolve_project_path(root: Path, value: str | None, fallback: str) -> Path:
    raw = value or fallback
    path = Path(raw)
    return path if path.is_absolute() else root / path


def main() -> int:
    args = parse_args()
    root = Path(__file__).resolve().parents[1]
    load_dotenv(root / ".env", encoding="utf-8-sig")
    retrieval_config = apply_retrieval_profile(load_retrieval_config(root / args.config), args.profile)
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
    summary_top_k = args.summary_top_k if args.summary_top_k is not None else int(search_config.get("summary_top_k") or 30)
    table_top_k = args.table_top_k if args.table_top_k is not None else int(search_config.get("table_top_k") or 8)
    graph_top_k = args.graph_top_k if args.graph_top_k is not None else int(search_config.get("graph_top_k") or 8)
    snippet_chars = int(search_config.get("snippet_chars") or 700)
    backend = args.embedding_backend or str(manifest.get("embedding_backend") or (retrieval_config.get("embedding") or {}).get("backend") or "yandex")
    publications_dir = resolve_project_path(root, args.publications_dir, retrieval_config.get("summary_publications_dir", "data/processed/publications"))
    document_summary_index_dir = resolve_project_path(root, args.document_summary_index_dir, retrieval_config.get("document_summary_index_dir", "data/indexes/document_summaries"))
    procedure_summary_index_dir = resolve_project_path(root, args.procedure_summary_index_dir, retrieval_config.get("procedure_summary_index_dir", "data/indexes/procedure_summaries"))
    table_roots = [resolve_project_path(root, value, value) for value in (args.table_root or ["data/parsed/spreadsheets_csv"])]
    documents_path = resolve_project_path(root, args.documents, "data/parsed/documents.jsonl")
    tables_path = resolve_project_path(root, args.tables, "data/parsed/tables.jsonl")
    graph_nodes_path = resolve_project_path(root, args.graph_nodes, "data/index/knowledge_graph_nodes.jsonl")
    graph_edges_path = resolve_project_path(root, args.graph_edges, "data/index/knowledge_graph_edges.jsonl")

    try:
        results, diagnostics = hybrid_search(
            query=args.query,
            retrieval_config=retrieval_config,
            index_dir=index_dir,
            lexical_dir=lexical_dir,
            chunks_path=chunks_path,
            top_k=top_k,
            mode=args.mode,
            dense_top_k=dense_top_k,
            lexical_top_k=lexical_top_k,
            summary_top_k=summary_top_k,
            table_top_k=table_top_k,
            graph_top_k=graph_top_k,
            snippet_chars=snippet_chars,
            allow_network=not args.offline,
            embedding_backend=backend,
            model=args.model,
            api_key=os.getenv("YANDEX_API_KEY"),
            folder_id=os.getenv("YANDEX_FOLDER_ID"),
            root=root,
            publications_dir=publications_dir,
            document_summary_index_dir=document_summary_index_dir,
            procedure_summary_index_dir=procedure_summary_index_dir,
            table_roots=table_roots,
            documents_path=documents_path,
            tables_path=tables_path,
            graph_nodes_path=graph_nodes_path,
            graph_edges_path=graph_edges_path,
            include_summaries=not args.no_summaries,
            include_tables=args.include_tables,
            include_graph=args.include_graph,
        )
    except RuntimeError as exc:
        if args.json:
            print(json.dumps({"error": str(exc), "mode": args.mode, "offline": args.offline}, ensure_ascii=False, indent=2))
        else:
            print(f"search failed: {exc}", file=sys.stderr)
        return 2

    if args.json:
        print(json.dumps({"diagnostics": diagnostics.as_dict(), "results": [result.as_dict() for result in results]}, ensure_ascii=False, indent=2))
        return 0
    if diagnostics.warnings:
        print("warnings=" + " | ".join(diagnostics.warnings))
    print(f"query={diagnostics.query.search_query} dense_status={diagnostics.dense_status} streams={diagnostics.streams}")
    for result in results:
        print(f"{result.rank}. score={result.score:.6f} source_type={result.source_type} doc_id={result.doc_id} candidate_id={result.candidate_id}")
        print(f"   source_path={result.source_path}")
        if result.components:
            components = ", ".join(f"{key}={value:.6f}" for key, value in sorted(result.components.items()))
            print(f"   components={components}")
        if result.reasons:
            print(f"   why={'; '.join(result.reasons)}")
        print(f"   {result.text}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
