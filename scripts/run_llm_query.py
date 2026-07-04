from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any

from dotenv import load_dotenv

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.index.embeddings import apply_retrieval_profile, load_retrieval_config
from app.llm.provider_router import ProviderRouter
from app.query.csv_corpus import format_table_context, search_tables
from app.query.simple_corpus import format_evidence_context, retrieve_chunks
from app.rag.retrieval import RetrievalDiagnostics, hybrid_search
from app.settings import paths


SYSTEM_PROMPT = """Ты помощник RAG-системы по научно-техническому корпусу.
Отвечай только по предоставленному контексту.
Если данных недостаточно, скажи об этом явно.
Ссылайся на evidence в формате [1], [2] для текста и [T1], [T2] для таблиц.
Не выдумывай источники, числа и названия документов."""


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Ask Yandex-first LLM router over local RAG evidence and optional table context.")
    parser.add_argument("question_parts", nargs="*", help="Question text. Alternative: --question.")
    parser.add_argument("--question", help="Question text.")
    parser.add_argument("--no-corpus", action="store_true", help="Skip local corpus retrieval and call LLM directly.")
    parser.add_argument("--retrieval", choices=["auto", "indexed", "scan"], default="auto")
    parser.add_argument("--search-mode", choices=["hybrid", "dense", "lexical"], default="hybrid")
    parser.add_argument("--offline", action="store_true", help="Skip Yandex query embeddings and use local retrieval streams.")
    parser.add_argument("--config", default="config/retrieval/default.json")
    parser.add_argument("--profile", default=None, help="Retrieval profile from config.profiles, e.g. routerai_bge_m3.")
    parser.add_argument("--index-dir", default=None)
    parser.add_argument("--lexical-dir", default=None)
    parser.add_argument("--chunks-path", type=Path)
    parser.add_argument("--top-k", type=int, default=5)
    parser.add_argument("--dense-top-k", type=int, default=50)
    parser.add_argument("--lexical-top-k", type=int, default=50)
    parser.add_argument("--max-scan-rows", type=int, default=20_000, help="0 scans all chunks.")
    parser.add_argument("--include-tables", action="store_true")
    parser.add_argument("--include-graph", action="store_true")
    parser.add_argument("--table-root", action="append", default=["data/parsed/spreadsheets_csv"])
    parser.add_argument("--table-top-k", type=int, default=4)
    parser.add_argument("--table-top-rows", type=int, default=3)
    parser.add_argument("--max-table-rows", type=int, default=500)
    parser.add_argument("--max-context-chars", type=int, default=12_000)
    parser.add_argument("--max-table-context-chars", type=int, default=8_000)
    parser.add_argument("--max-tokens", type=int, default=900)
    parser.add_argument("--temperature", type=float, default=0.2)
    parser.add_argument("--model", help="Override YANDEX_MODEL for the primary Yandex call.")
    parser.add_argument("--json", action="store_true", help="Print answer/evidence payload as JSON.")
    return parser.parse_args()


def resolve_question(args: argparse.Namespace) -> str:
    question = args.question or " ".join(args.question_parts)
    question = question.strip()
    if not question:
        raise SystemExit("Question is required. Pass it as an argument or with --question.")
    return question


def resolve_project_path(root: Path, value: str | Path | None, fallback: str) -> Path:
    raw = Path(value) if value is not None else Path(fallback)
    return raw if raw.is_absolute() else root / raw


def indexed_results(
    question: str,
    *,
    root: Path,
    retrieval_config: dict[str, Any],
    index_dir: Path,
    lexical_dir: Path,
    chunks_path: Path,
    search_mode: str,
    top_k: int,
    dense_top_k: int,
    lexical_top_k: int,
    offline: bool,
    include_graph: bool,
) -> tuple[list[Any], RetrievalDiagnostics | None]:
    search_config = retrieval_config.get("search") or {}
    snippet_chars = int(search_config.get("snippet_chars") or 700)
    results, diagnostics = hybrid_search(
        query=question,
        retrieval_config=retrieval_config,
        index_dir=index_dir,
        lexical_dir=lexical_dir,
        chunks_path=chunks_path,
        mode=search_mode,  # type: ignore[arg-type]
        top_k=top_k,
        dense_top_k=dense_top_k,
        lexical_top_k=lexical_top_k,
        snippet_chars=snippet_chars,
        allow_network=not offline,
        model="auto",
        api_key=os.getenv("YANDEX_API_KEY"),
        folder_id=os.getenv("YANDEX_FOLDER_ID"),
        root=root,
        publications_dir=resolve_project_path(root, None, retrieval_config.get("summary_publications_dir", "data/processed/publications")),
        document_summary_index_dir=resolve_project_path(root, None, retrieval_config.get("document_summary_index_dir", "data/indexes/document_summaries")),
        procedure_summary_index_dir=resolve_project_path(root, None, retrieval_config.get("procedure_summary_index_dir", "data/indexes/procedure_summaries")),
        table_roots=(root / "data" / "parsed" / "spreadsheets_csv",),
        documents_path=root / "data" / "parsed" / "documents.jsonl",
        tables_path=root / "data" / "parsed" / "tables.jsonl",
        graph_nodes_path=root / "data" / "index" / "knowledge_graph_nodes.jsonl",
        graph_edges_path=root / "data" / "index" / "knowledge_graph_edges.jsonl",
        include_summaries=True,
        include_tables=False,
        include_graph=include_graph,
    )
    return results, diagnostics


def format_indexed_context(results: list[Any], *, max_chars: int) -> str:
    parts: list[str] = []
    used = 0
    for result in results:
        block = (
            f"[{result.rank}] source_type={getattr(result, 'source_type', 'raw_chunk')}; "
            f"doc_id={result.doc_id}; candidate_id={getattr(result, 'candidate_id', result.chunk_id)}; "
            f"source_path={result.source_path}\n"
            f"{result.text}"
        )
        if used + len(block) + 2 > max_chars:
            break
        parts.append(block)
        used += len(block) + 2
    return "\n\n".join(parts)


def table_context(question: str, *, root: Path, args: argparse.Namespace) -> tuple[str, list[dict[str, Any]]]:
    hits = search_tables(
        question,
        roots=[resolve_project_path(root, value, value) for value in args.table_root],
        documents_path=root / "data" / "parsed" / "documents.jsonl",
        tables_path=root / "data" / "parsed" / "tables.jsonl",
        project_root=root,
        top_k=args.table_top_k,
        top_rows=args.table_top_rows,
        max_rows_per_table=args.max_table_rows,
    )
    return format_table_context(hits, max_chars=args.max_table_context_chars), [hit.as_dict() for hit in hits]


def main() -> int:
    args = parse_args()
    root = Path(__file__).resolve().parents[1]
    load_dotenv(root / ".env", encoding="utf-8-sig")
    question = resolve_question(args)
    project_paths = paths()
    chunks_path = args.chunks_path or project_paths.parsed_dir / "chunks.jsonl"

    text_context = None
    text_evidence: list[dict[str, Any]] = []
    retrieval_diagnostics: dict[str, Any] = {}
    retrieval_used = "none"
    if not args.no_corpus:
        config_path = resolve_project_path(root, args.config, args.config)
        retrieval_config = apply_retrieval_profile(load_retrieval_config(config_path), args.profile)
        index_dir = resolve_project_path(root, args.index_dir, retrieval_config.get("chunk_index_dir", "data/indexes/chunks"))
        lexical_dir = resolve_project_path(root, args.lexical_dir, retrieval_config.get("lexical_index_dir", "data/indexes/lexical"))

        results = []
        if args.retrieval in {"auto", "indexed"}:
            try:
                results, diagnostics = indexed_results(
                    question,
                    root=root,
                    retrieval_config=retrieval_config,
                    index_dir=index_dir,
                    lexical_dir=lexical_dir,
                    chunks_path=chunks_path,
                    search_mode=args.search_mode,
                    top_k=args.top_k,
                    dense_top_k=args.dense_top_k,
                    lexical_top_k=args.lexical_top_k,
                    offline=args.offline,
                    include_graph=args.include_graph,
                )
                retrieval_diagnostics = diagnostics.as_dict() if diagnostics else {}
                retrieval_used = "indexed" if results else "indexed-empty"
                if args.retrieval == "indexed" and not results:
                    raise SystemExit("No indexed retrieval results. Build indexes or use --retrieval scan.")
            except Exception as exc:  # noqa: BLE001 - auto mode must fall back to local scan.
                retrieval_diagnostics = {"indexed_error": str(exc)[:500], "offline": args.offline}
                if args.retrieval == "indexed":
                    raise
                retrieval_used = "indexed-error"
                results = []

        if not results and args.retrieval in {"auto", "scan"}:
            scan_hits = retrieve_chunks(question, chunks_path, top_k=args.top_k, max_rows=args.max_scan_rows)
            text_context = format_evidence_context(scan_hits, max_chars=args.max_context_chars)
            text_evidence = [
                {
                    "rank": hit.rank,
                    "score": hit.score,
                    "doc_id": hit.doc_id,
                    "chunk_id": hit.chunk_id,
                    "source_path": hit.source_path,
                }
                for hit in scan_hits
            ]
            retrieval_used = "scan"
        elif results:
            text_context = format_indexed_context(results, max_chars=args.max_context_chars)
            text_evidence = [result.as_dict() for result in results]

    tables_context = ""
    table_evidence: list[dict[str, Any]] = []
    if args.include_tables:
        tables_context, table_evidence = table_context(question, root=root, args=args)

    context_parts = [part for part in (text_context, tables_context) if part]
    combined_context = "\n\n".join(context_parts) if context_parts else None
    router = ProviderRouter.from_env(root=root)
    llm_response = router.ask(
        question,
        system_prompt=SYSTEM_PROMPT if combined_context else None,
        context=combined_context,
        model=args.model,
        max_tokens=args.max_tokens,
        temperature=args.temperature,
    )
    answer = llm_response.text

    if args.json:
        print(
            json.dumps(
                {
                    "answer": answer,
                    "llm": llm_response.metadata(),
                    "retrieval_used": retrieval_used,
                    "retrieval_diagnostics": retrieval_diagnostics,
                    "text_evidence": text_evidence,
                    "table_evidence": table_evidence,
                },
                ensure_ascii=False,
                indent=2,
                default=str,
            )
        )
        return 0

    print(answer)
    print(
        "\nLLM provider:"
        f" provider={llm_response.provider}"
        f" model={llm_response.model}"
        f" status={llm_response.status}"
        f" fallback_reason={llm_response.fallback_reason or 'none'}"
        f" used_evidence={str(llm_response.used_evidence).lower()}"
    )
    if retrieval_diagnostics:
        print(
            "Retrieval:"
            f" used={retrieval_used}"
            f" dense_status={retrieval_diagnostics.get('dense_status', 'n/a')}"
            f" streams={retrieval_diagnostics.get('streams', {})}"
        )
    if llm_response.warnings:
        print("LLM warnings:")
        for warning in llm_response.warnings:
            print(f"- {warning}")
    if text_evidence:
        print("\nEvidence:")
        for item in text_evidence:
            print(
                f"[{item.get('rank')}] score={float(item.get('score') or 0):.3f} "
                f"doc_id={item.get('doc_id')} chunk_id={item.get('chunk_id')} source={item.get('source_path')}"
            )
    if table_evidence:
        print("\nTable evidence:")
        for item in table_evidence:
            summary = item.get("summary") or {}
            print(f"[T{item.get('rank')}] score={item.get('score')} path={summary.get('path')} sheet={summary.get('sheet')}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
