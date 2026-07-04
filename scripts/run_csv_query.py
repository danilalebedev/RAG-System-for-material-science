from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.query.csv_corpus import format_table_context, search_tables


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Search parsed CSV/XLS/XLSX tables and return compact context.")
    parser.add_argument("query")
    parser.add_argument("--root", action="append", default=["data/parsed/spreadsheets_csv"], help="Table root to scan.")
    parser.add_argument("--documents", default="data/parsed/documents.jsonl")
    parser.add_argument("--tables", default="data/parsed/tables.jsonl")
    parser.add_argument("--top-k", type=int, default=8)
    parser.add_argument("--top-rows", type=int, default=3)
    parser.add_argument("--max-rows-per-table", type=int, default=500)
    parser.add_argument("--sample-rows", type=int, default=50)
    parser.add_argument("--max-context-chars", type=int, default=10_000)
    parser.add_argument("--json", action="store_true")
    return parser.parse_args()


def resolve(root: Path, value: str) -> Path:
    path = Path(value)
    return path if path.is_absolute() else root / path


def main() -> int:
    args = parse_args()
    project_root = Path(__file__).resolve().parents[1]
    hits = search_tables(
        args.query,
        roots=[resolve(project_root, value) for value in args.root],
        documents_path=resolve(project_root, args.documents),
        tables_path=resolve(project_root, args.tables),
        project_root=project_root,
        top_k=args.top_k,
        top_rows=args.top_rows,
        max_rows_per_table=args.max_rows_per_table,
        sample_rows=args.sample_rows,
    )
    if args.json:
        print(json.dumps([hit.as_dict() for hit in hits], ensure_ascii=False, indent=2, default=str))
        return 0
    print(format_table_context(hits, max_chars=args.max_context_chars))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

