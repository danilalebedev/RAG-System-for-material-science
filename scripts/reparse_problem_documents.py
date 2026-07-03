from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.io_utils import read_jsonl, safe_filename, write_csv, write_jsonl
from app.parsing.chunking import iter_chunks
from app.parsing.parsers import parse_document, parsed_document_to_row, stable_id
from app.quality.parsing_quality import quality_label
from app.settings import load_config, paths


DEFAULT_STATUSES = {"failed", "unsupported"}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Reparse selected documents and patch parsed JSONL artifacts.")
    parser.add_argument("--statuses", default=",".join(sorted(DEFAULT_STATUSES)))
    return parser.parse_args()


def rewrite_filtering_doc_ids(source: Path, target: Path, excluded_doc_ids: set[str]) -> int:
    kept = 0
    with source.open("r", encoding="utf-8") as src, target.open("w", encoding="utf-8", newline="\n") as dst:
        for line in src:
            if not line.strip():
                continue
            row = json.loads(line)
            if row.get("doc_id") in excluded_doc_ids:
                continue
            dst.write(json.dumps(row, ensure_ascii=False, default=str) + "\n")
            kept += 1
    return kept


def append_jsonl(path: Path, rows: list[dict]) -> int:
    with path.open("a", encoding="utf-8", newline="\n") as f:
        for row in rows:
            f.write(json.dumps(row, ensure_ascii=False, default=str) + "\n")
    return len(rows)


def main() -> None:
    args = parse_args()
    selected_statuses = {value.strip() for value in args.statuses.split(",") if value.strip()}
    cfg = load_config()
    chunk_cfg = cfg["chunking"]
    p = paths()

    documents_path = p.parsed_dir / "documents.jsonl"
    chunks_path = p.parsed_dir / "chunks.jsonl"
    tables_path = p.parsed_dir / "tables.jsonl"
    documents = read_jsonl(documents_path)
    selected = [row for row in documents if row.get("status") in selected_statuses]
    if not selected:
        print("No documents selected for reparse.")
        return

    replacement_documents: dict[str, dict] = {}
    replacement_chunks: list[dict] = []
    replacement_tables: list[dict] = []
    for old_row in selected:
        file_path = Path(str(old_row["local_path"]))
        parsed = parse_document(file_path)
        doc_row = parsed_document_to_row(
            parsed,
            extra={
                "source_path": old_row.get("source_path", ""),
                "source_type": old_row.get("source_type", ""),
                "source_mime_type": old_row.get("source_mime_type", ""),
                "source_size": old_row.get("source_size", file_path.stat().st_size if file_path.exists() else 0),
            },
        )
        doc_row["quality_label"] = quality_label(doc_row)
        full_text_name = f"{doc_row['doc_id']}__{safe_filename(file_path.stem)}.txt"
        full_text_path = p.full_texts_dir / full_text_name
        full_text_path.write_text(parsed.text, encoding="utf-8", newline="\n")
        doc_row["full_text_path"] = str(full_text_path)
        replacement_documents[doc_row["doc_id"]] = {**doc_row, "text_preview": parsed.text[:1000]}

        for i, chunk in enumerate(
            iter_chunks(
                parsed.text,
                target_chars=int(chunk_cfg["target_chars"]),
                overlap_chars=int(chunk_cfg["overlap_chars"]),
                min_chars=int(chunk_cfg["min_chars"]),
            ),
            start=1,
        ):
            replacement_chunks.append(
                {
                    "chunk_id": stable_id(f"{doc_row['doc_id']}:{i}:{chunk[:80]}"),
                    "doc_id": doc_row["doc_id"],
                    "chunk_index": i,
                    "text": chunk,
                    "text_chars": len(chunk),
                    "source_path": doc_row.get("source_path", ""),
                    "local_path": doc_row["local_path"],
                }
            )

        for table in parsed.tables:
            replacement_tables.append(
                {
                    "table_id": table.table_id,
                    "doc_id": doc_row["doc_id"],
                    "page_or_sheet": table.page_or_sheet,
                    "text": table.text,
                    "row_count": len(table.rows),
                    "local_path": doc_row["local_path"],
                }
            )

    selected_doc_ids = set(replacement_documents)
    patched_documents = [
        replacement_documents.get(row["doc_id"], row)
        for row in documents
    ]
    write_jsonl(documents_path, patched_documents)

    tmp_chunks = chunks_path.with_suffix(".jsonl.tmp")
    tmp_tables = tables_path.with_suffix(".jsonl.tmp")
    rewrite_filtering_doc_ids(chunks_path, tmp_chunks, selected_doc_ids)
    rewrite_filtering_doc_ids(tables_path, tmp_tables, selected_doc_ids)
    os.replace(tmp_chunks, chunks_path)
    os.replace(tmp_tables, tables_path)
    append_jsonl(chunks_path, replacement_chunks)
    append_jsonl(tables_path, replacement_tables)

    parse_manifest = [
        {key: value for key, value in row.items() if key != "text_preview"}
        for row in patched_documents
    ]
    write_csv(p.parsing_report_dir / "parse_manifest.csv", parse_manifest)
    print(f"Reparsed documents: {len(selected)}")
    print(f"Replacement chunks: {len(replacement_chunks)}")
    print(f"Replacement tables: {len(replacement_tables)}")


if __name__ == "__main__":
    main()
