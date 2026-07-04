from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from dotenv import load_dotenv

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.index.embeddings import apply_retrieval_profile, load_retrieval_config  # noqa: E402
from app.index.vector_store import load_manifest  # noqa: E402
from app.rag.validation import SearchCase, run_validation, write_validation_outputs  # noqa: E402


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Validate generated RAG indexes and search relevance.")
    parser.add_argument("--config", default="config/retrieval/default.json")
    parser.add_argument("--profile", default=None, help="Retrieval profile from config.profiles, e.g. routerai_bge_m3.")
    parser.add_argument("--index-dir", default=None)
    parser.add_argument("--lexical-dir", default=None)
    parser.add_argument("--chunks", default=None)
    parser.add_argument("--mode", choices=["hybrid", "dense", "lexical"], default="hybrid")
    parser.add_argument("--top-k", type=int, default=5)
    parser.add_argument("--allow-network", action="store_true", default=False)
    parser.add_argument("--sample-size", type=int, default=4096)
    parser.add_argument("--full-vector-scan", action="store_true", default=False)
    parser.add_argument("--report-json", default="data/indexes/retrieval_validation_report.json")
    parser.add_argument("--results-jsonl", default="data/indexes/retrieval_test_results.jsonl")
    parser.add_argument(
        "--case",
        action="append",
        default=[],
        help="Custom relevance case: query|term1,term2,term3|min_unique_terms|min_top1_terms",
    )
    return parser.parse_args()


def resolve_project_path(root: Path, value: str | None, fallback: str) -> Path:
    raw = value or fallback
    path = Path(raw)
    return path if path.is_absolute() else root / path


def parse_case(value: str) -> SearchCase:
    parts = value.split("|")
    if len(parts) < 2:
        raise ValueError("--case must use query|term1,term2[,term3]|min_unique_terms|min_top1_terms")
    query = parts[0].strip()
    terms = tuple(term.strip() for term in parts[1].split(",") if term.strip())
    min_unique_terms = int(parts[2]) if len(parts) >= 3 and parts[2] else 2
    min_top1_terms = int(parts[3]) if len(parts) >= 4 and parts[3] else 1
    if not query or not terms:
        raise ValueError("--case query and expected terms must be non-empty")
    return SearchCase(query=query, expected_terms=terms, min_unique_terms=min_unique_terms, min_top1_terms=min_top1_terms)


def main() -> int:
    args = parse_args()
    root = Path(__file__).resolve().parents[1]
    load_dotenv(root / ".env")
    config_path = resolve_project_path(root, args.config, args.config)
    retrieval_config = apply_retrieval_profile(load_retrieval_config(config_path), args.profile)
    index_dir = resolve_project_path(root, args.index_dir, retrieval_config.get("chunk_index_dir", "data/indexes/chunks"))
    lexical_dir = resolve_project_path(root, args.lexical_dir, retrieval_config.get("lexical_index_dir", "data/indexes/lexical"))
    manifest = load_manifest(index_dir)
    chunks_path = resolve_project_path(
        root,
        args.chunks,
        str(manifest.get("source_chunks_path") or retrieval_config.get("chunks_path") or "data/parsed/chunks.jsonl"),
    )
    cases = [parse_case(value) for value in args.case] if args.case else None
    report = run_validation(
        root=root,
        config_path=config_path,
        index_dir=index_dir,
        lexical_dir=lexical_dir,
        chunks_path=chunks_path,
        cases=cases,
        mode=args.mode,
        top_k=args.top_k,
        allow_network=args.allow_network,
        sample_size=args.sample_size,
        full_vector_scan=args.full_vector_scan,
    )
    report_json = resolve_project_path(root, args.report_json, args.report_json)
    results_jsonl = resolve_project_path(root, args.results_jsonl, args.results_jsonl)
    write_validation_outputs(report=report, report_json=report_json, results_jsonl=results_jsonl)
    print(
        json.dumps(
            {
                "status": report["status"],
                "report_json": str(report_json),
                "results_jsonl": str(results_jsonl),
                "issue_count": len(report["issues"]),
                "failed_queries": [
                    row["query"] for row in report["search_cases"] if row["status"] != "pass"
                ],
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0 if report["status"] == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())
