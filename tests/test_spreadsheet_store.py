from __future__ import annotations

import csv
import json
from pathlib import Path

from app.index.spreadsheet_store import SpreadsheetStore, query_terms, read_sheet_preview


def write_jsonl(path: Path, rows: list[dict[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="\n") as file:
        for row in rows:
            file.write(json.dumps(row, ensure_ascii=False) + "\n")


def write_csv(path: Path, rows: list[list[str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as file:
        writer = csv.writer(file)
        writer.writerows(rows)


def build_fixture(root: Path) -> Path:
    documents_path = root / "data" / "parsed" / "documents.jsonl"
    csv_path = root / "data" / "parsed" / "spreadsheets_csv" / "doc_prices" / "001__prices.csv"
    write_csv(
        csv_path,
        [
            ["metal", "year", "value"],
            ["Nickel", "2012", "17.5"],
            ["Copper", "2012", "8.1"],
            ["Nickel", "2011", "16.9"],
        ],
    )
    write_jsonl(
        documents_path,
        [
            {
                "doc_id": "doc_prices",
                "file_name": "metal_prices.xlsx",
                "extension": ".xlsx",
                "parser": "openpyxl-csv-export",
                "status": "ok",
                "local_path": "C:/source/metal_prices.xlsx",
                "source_path": "/source/metal_prices.xlsx",
                "metadata_json": json.dumps(
                    {
                        "sheets": [
                            {
                                "sheet_index": 1,
                                "sheet_name": "prices",
                                "rows": 4,
                                "columns": 3,
                                "csv_path": "data/parsed/spreadsheets_csv/doc_prices/001__prices.csv",
                                "csv_size": csv_path.stat().st_size,
                                "preview_rows": 4,
                                "preview_columns": 3,
                            }
                        ]
                    }
                ),
            },
            {
                "doc_id": "doc_text",
                "file_name": "report.pdf",
                "extension": ".pdf",
                "parser": "pymupdf",
                "status": "ok",
                "metadata_json": "{}",
            },
        ],
    )
    return documents_path


def test_spreadsheet_store_loads_sheets_and_preview(tmp_path: Path) -> None:
    documents_path = build_fixture(tmp_path)
    store = SpreadsheetStore(documents_path, root=tmp_path)

    sheets = list(store.iter_sheets())

    assert len(sheets) == 1
    assert sheets[0].doc_id == "doc_prices"
    assert sheets[0].sheet_name == "prices"
    assert sheets[0].csv_path.exists()
    assert read_sheet_preview(sheets[0].csv_path, n_rows=2) == [
        ["metal", "year", "value"],
        ["Nickel", "2012", "17.5"],
    ]


def test_spreadsheet_store_searches_rows_by_query_terms(tmp_path: Path) -> None:
    documents_path = build_fixture(tmp_path)
    store = SpreadsheetStore(documents_path, root=tmp_path)

    hits = store.search_rows("nickel 2012", top_k=3)

    assert hits
    assert hits[0].row_number == 2
    assert hits[0].sheet.doc_id == "doc_prices"
    assert hits[0].matched_terms == ("nickel", "2012")
    assert hits[0].row_text() == "Nickel | 2012 | 17.5"


def test_spreadsheet_store_filters_by_doc_id(tmp_path: Path) -> None:
    documents_path = build_fixture(tmp_path)
    store = SpreadsheetStore(documents_path, root=tmp_path)

    assert store.search_rows("nickel", doc_ids=["missing"]) == []
    assert store.search_rows("nickel", doc_ids=["doc_prices"])[0].sheet.doc_id == "doc_prices"


def test_query_terms_deduplicates_and_normalizes() -> None:
    assert query_terms("Nickel nickel 2012") == ["nickel", "2012"]
