from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any

from dotenv import load_dotenv

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.index.embeddings import build_embedding_client, load_retrieval_config
from app.index.lexical import LexicalIndex
from app.index.vector_store import load_manifest
from app.llm.yandex_client import YandexLLMClient
from app.query.csv_corpus import format_table_context, search_tables
from app.query.simple_corpus import format_evidence_context, retrieve_chunks
from app.rag.retrieval import dense_search, lexical_search, materialize_results, reciprocal_rank_fusion
from app.settings import paths


SYSTEM_PROMPT = """Ты помощник RAG-системы по научно-техническому корпусу.
Отвечай только по предоставленному контексту.
Если данных недостаточно, скажи об этом явно.
Ссылайся на evidence в формате [1], [2] для текста и [T1], [T2] для таблиц.
Не выдумывай источники, числа и названия документов."""


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Ask YandexGPT over local RAG evidence and optional table context.")
    parser.add_argument("question_parts", nargs="*", help="Question text. Alternative: --question.")
    parser.add_argument("--question", help="Question text.")
    parser.add_argument("--no-corpus", action="store_true", help="Skip local corpus retrieval and call LLM directly.")
    parser.add_argument("--retrieval", choices=["auto", "indexed", "scan"], default="auto")
    parser.add_argument("--search-mode", choices=["hybrid", "dense", "lexical"], default="hybrid")
    parser.add_argument("--config", default="config/retrieval/default.json")
    parser.add_argument("--index-dir", default=None)
    parser.add_argument("--lexical-dir", default=None)
    parser.add_argument("--chunks-path", type=Path)
    parser.add_argument("--top-k", type=int, default=5)
    parser.add_argument("--dense-top-k", type=int, default=50)
    parser.add_argument("--lexical-top-k", type=int, default=50)
    parser.add_argument("--max-scan-rows", type=int, default=20_000, help="0 scans all chunks.")
    parser.add_argument("--include-tables", action="store_true")
    parser.add_argument("--table-root", action="append", default=["data/parsed/spreadsheets_csv"])
    parser.add_argument("--table-top-k", type=int, default=4)
    parser.add_argument("--table-top-rows", type=int, default=3)
    parser.add_argument("--max-table-rows", type=int, default=500)
    parser.add_argument("--max-context-chars", type=int, default=12_000)
    parser.add_argument("--max-table-context-chars", type=int, default=8_000)
    parser.add_argument("--max-tokens", type=int, default=900)
    parser.add_argument("--temperature", type=float, default=0.2)
    parser.add_argument("--model", help="Override YANDEX_MODEL for this call.")
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
    config_path: Path,
    index_dir: Path,
    lexical_dir: Path,
    chunks_path: Path,
    search_mode: str,
    top_k: int,
    dense_top_k: int,
    lexical_top_k: int,
) -> list[Any]:
    retrieval_config = load_retrieval_config(config_path)
    search_config = retrieval_config.get("search") or {}
    snippet_chars = int(search_config.get("snippet_chars") or 700)
    rrf_k = int(search_config.get("rrf_k") or 60)
    vector_batch_size = int(search_config.get("vector_batch_size") or 8192)
    manifest = load_manifest(index_dir)

    dense_hits = []
    lexical_hits = []
    if search_mode in {"hybrid", "dense"} and manifest:
        backend = str(manifest.get("embedding_backend") or (retrieval_config.get("embedding") or {}).get("backend") or "yandex")
        model = "fallback" if manifest.get("model_selection") == "fallback" else "query"
        client = build_embedding_client(
            backend=backend,
            retrieval_config=retrieval_config,
            kind="query",
            fallback_model=model == "fallback",
            api_key=os.getenv("YANDEX_API_KEY"),
            folder_id=os.getenv("YANDEX_FOLDER_ID"),
        )
        dense_hits = dense_search(
            index_dir,
            client.embed_text(question),
            top_k=dense_top_k if search_mode == "hybrid" else top_k,
            batch_size=vector_batch_size,
        )
    if search_mode in {"hybrid", "lexical"}:
        lexical_index = LexicalIndex(lexical_dir)
        if lexical_index.exists():
            lexical_hits = lexical_search(
                lexical_dir,
                question,
                top_k=lexical_top_k if search_mode == "hybrid" else top_k,
            )

    if search_mode == "dense":
        ranked_rows = [(hit.row_id, hit.score, {"dense": hit.score}) for hit in dense_hits[:top_k]]
    elif search_mode == "lexical":
        ranked_rows = [(hit.row_id, hit.score, {"lexical": hit.score}) for hit in lexical_hits[:top_k]]
    else:
        ranked_rows = reciprocal_rank_fusion(dense_hits=dense_hits, lexical_hits=lexical_hits, rrf_k=rrf_k, top_k=top_k)

    if not ranked_rows:
        return []
    return materialize_results(
        ranked_rows=ranked_rows,
        index_dir=index_dir,
        chunks_path=chunks_path,
        snippet_chars=snippet_chars,
    )


def format_indexed_context(results: list[Any], *, max_chars: int) -> str:
    parts: list[str] = []
    used = 0
    for result in results:
        block = (
            f"[{result.rank}] doc_id={result.doc_id}; chunk_id={result.chunk_id}; source_path={result.source_path}\n"
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
    load_dotenv(root / ".env")
    question = resolve_question(args)
    project_paths = paths()
    chunks_path = args.chunks_path or project_paths.parsed_dir / "chunks.jsonl"

    text_context = None
    text_evidence: list[dict[str, Any]] = []
    retrieval_used = "none"
    if not args.no_corpus:
        config_path = resolve_project_path(root, args.config, args.config)
        retrieval_config = load_retrieval_config(config_path)
        index_dir = resolve_project_path(root, args.index_dir, retrieval_config.get("chunk_index_dir", "data/indexes/chunks"))
        lexical_dir = resolve_project_path(root, args.lexical_dir, retrieval_config.get("lexical_index_dir", "data/indexes/lexical"))

        results = []
        if args.retrieval in {"auto", "indexed"}:
            results = indexed_results(
                question,
                root=root,
                config_path=config_path,
                index_dir=index_dir,
                lexical_dir=lexical_dir,
                chunks_path=chunks_path,
                search_mode=args.search_mode,
                top_k=args.top_k,
                dense_top_k=args.dense_top_k,
                lexical_top_k=args.lexical_top_k,
            )
            retrieval_used = "indexed" if results else "indexed-empty"
            if args.retrieval == "indexed" and not results:
                raise SystemExit("No indexed retrieval results. Build indexes or use --retrieval scan.")

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
    client = YandexLLMClient()
    answer = client.ask(
        question,
        system_prompt=SYSTEM_PROMPT if combined_context else None,
        context=combined_context,
        model=args.model,
        max_tokens=args.max_tokens,
        temperature=args.temperature,
    )

    if args.json:
        print(
            json.dumps(
                {
                    "answer": answer,
                    "retrieval_used": retrieval_used,
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
