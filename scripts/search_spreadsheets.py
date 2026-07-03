from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Iterable


sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.index.spreadsheet_store import SpreadsheetStore, read_sheet_preview  # noqa: E402


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Search rows in parsed Excel CSV exports.")
    parser.add_argument("query", help="Lexical query to match against workbook metadata and CSV rows.")
    parser.add_argument("--documents", default="data/parsed/documents.jsonl", help="Path to parsed documents.jsonl.")
    parser.add_argument("--doc-id", action="append", dest="doc_ids", default=[], help="Limit search to a parsed document id.")
    parser.add_argument("--sheet-name", default=None, help="Limit search to sheets whose name contains this value.")
    parser.add_argument("--top-k", type=int, default=20, help="Number of rows or sheets to return.")
    parser.add_argument("--min-term-matches", type=int, default=1, help="Minimum query terms that must match a row.")
    parser.add_argument("--max-sheets", type=int, default=None, help="Stop after scanning this many matching sheets.")
    parser.add_argument("--max-rows-per-sheet", type=int, default=None, help="Stop reading each CSV after this many rows.")
    parser.add_argument("--sheets-only", action="store_true", default=False, help="Rank workbook sheets, but do not scan CSV rows.")
    parser.add_argument("--preview-rows", type=int, default=0, help="Print first N CSV rows for each sheets-only result.")
    parser.add_argument("--json", action="store_true", default=False, help="Print machine-readable JSON.")
    return parser.parse_args()


def resolve_project_path(root: Path, value: str) -> Path:
    path = Path(value)
    return path if path.is_absolute() else root / path


def compact_cells(cells: Iterable[str], *, max_chars: int = 800) -> str:
    text = " | ".join(cell for cell in cells if cell)
    if len(text) <= max_chars:
        return text
    return text[: max_chars - 3].rstrip() + "..."


def print_sheet_results(store: SpreadsheetStore, args: argparse.Namespace) -> None:
    hits = store.search_sheets(
        args.query,
        top_k=args.top_k,
        doc_ids=args.doc_ids,
        sheet_name=args.sheet_name,
    )
    if args.json:
        payload = [hit.as_dict() for hit in hits]
        if args.preview_rows > 0:
            for item, hit in zip(payload, hits):
                item["preview"] = read_sheet_preview(hit.sheet.csv_path, n_rows=args.preview_rows)
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return
    for hit in hits:
        sheet = hit.sheet
        print(f"{hit.rank}. score={hit.score:.6f} doc_id={sheet.doc_id} sheet={sheet.sheet_index}:{sheet.sheet_name}")
        print(f"   file_name={sheet.file_name}")
        print(f"   rows={sheet.rows} columns={sheet.columns} csv_path={sheet.csv_path}")
        if hit.matched_terms:
            print(f"   matched_terms={', '.join(hit.matched_terms)}")
        if args.preview_rows > 0:
            for row_index, row in enumerate(read_sheet_preview(sheet.csv_path, n_rows=args.preview_rows), start=1):
                print(f"   preview[{row_index}] {compact_cells(row)}")


def print_row_results(store: SpreadsheetStore, args: argparse.Namespace) -> None:
    hits = store.search_rows(
        args.query,
        top_k=args.top_k,
        doc_ids=args.doc_ids,
        sheet_name=args.sheet_name,
        min_term_matches=args.min_term_matches,
        max_sheets=args.max_sheets,
        max_rows_per_sheet=args.max_rows_per_sheet,
    )
    if args.json:
        print(json.dumps([hit.as_dict() for hit in hits], ensure_ascii=False, indent=2))
        return
    for hit in hits:
        sheet = hit.sheet
        print(
            f"{hit.rank}. score={hit.score:.6f} doc_id={sheet.doc_id} "
            f"sheet={sheet.sheet_index}:{sheet.sheet_name} row={hit.row_number}"
        )
        print(f"   file_name={sheet.file_name}")
        print(f"   csv_path={sheet.csv_path}")
        if hit.matched_terms:
            print(f"   matched_terms={', '.join(hit.matched_terms)}")
        print(f"   row={compact_cells(hit.row)}")


def main() -> int:
    args = parse_args()
    root = Path(__file__).resolve().parents[1]
    documents_path = resolve_project_path(root, args.documents)
    store = SpreadsheetStore(documents_path, root=root)
    if args.sheets_only:
        print_sheet_results(store, args)
    else:
        print_row_results(store, args)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
