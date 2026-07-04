from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.query.local_orchestrator import LocalKnowledgeConfig, default_config, run_local_knowledge


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run local raw/summary/table/graph orchestration without calling an LLM.")
    parser.add_argument("query_parts", nargs="*", help="Question text. Alternative: --query.")
    parser.add_argument("--query", help="Question text.")
    parser.add_argument("--top-k-raw", type=int, default=5)
    parser.add_argument("--top-k-summary", type=int, default=5)
    parser.add_argument("--top-k-tables", type=int, default=4)
    parser.add_argument("--top-k-graph", type=int, default=8)
    parser.add_argument("--max-scan-rows", type=int, default=20_000, help="0 scans all chunks.")
    parser.add_argument("--no-raw", action="store_true")
    parser.add_argument("--no-summaries", action="store_true")
    parser.add_argument("--no-tables", action="store_true")
    parser.add_argument("--no-graph", action="store_true")
    parser.add_argument("--no-rewrite", action="store_true")
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--context", action="store_true", help="Print the combined evidence context after the brief.")
    return parser.parse_args()


def resolve_query(args: argparse.Namespace) -> str:
    query = args.query or " ".join(args.query_parts)
    query = query.strip()
    if not query:
        raise SystemExit("Query is required. Pass it as an argument or with --query.")
    return query


def main() -> int:
    args = parse_args()
    root = Path(__file__).resolve().parents[1]
    base = default_config(root)
    config = LocalKnowledgeConfig(
        project_root=base.project_root,
        chunks_path=base.chunks_path,
        publications_dir=base.publications_dir,
        graph_nodes_path=base.graph_nodes_path,
        graph_edges_path=base.graph_edges_path,
        table_roots=base.table_roots,
        documents_path=base.documents_path,
        tables_path=base.tables_path,
        top_k_raw=args.top_k_raw,
        top_k_summary=args.top_k_summary,
        top_k_tables=args.top_k_tables,
        top_k_graph=args.top_k_graph,
        max_scan_rows=args.max_scan_rows,
        include_raw=not args.no_raw,
        include_summaries=not args.no_summaries,
        include_tables=not args.no_tables,
        include_graph=not args.no_graph,
    )
    bundle = run_local_knowledge(resolve_query(args), config=config, use_query_rewrite=not args.no_rewrite)
    if args.json:
        print(json.dumps(bundle.as_dict(), ensure_ascii=False, indent=2, default=str))
        return 0
    print(bundle.brief)
    if args.context:
        print("\n# Combined Evidence Context\n")
        print(bundle.context)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
