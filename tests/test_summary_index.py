from __future__ import annotations

import json
from pathlib import Path

from app.index.summaries import iter_summary_records, summary_cache_key


def write_summary_rows(path: Path) -> None:
    rows = [
        {
            "document_summary_id": "docsum_1",
            "doc_id": "doc_1",
            "publication_id": "pub_1",
            "title": "Nickel ore review",
            "summary": "Nickel ore leaching improves recovery under pressure.",
            "materials": ["nickel ore"],
            "processes": ["pressure leaching"],
            "process_parameters": [{"temperature": "220 C", "pressure": "3 MPa"}],
            "source_path": "/source/nickel.pdf",
        }
    ]
    with path.open("w", encoding="utf-8", newline="\n") as f:
        for row in rows:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")


def test_summary_records_keep_stable_metadata_and_domain_text(tmp_path: Path) -> None:
    path = tmp_path / "document_summaries.jsonl"
    write_summary_rows(path)

    records = list(iter_summary_records(path, kind="document_summary"))

    assert len(records) == 1
    record = records[0]
    assert record.summary_id == "docsum_1"
    assert record.doc_id == "doc_1"
    assert "Nickel ore leaching" in record.text
    assert "temperature" in record.text
    assert record.metadata()["source_path"] == "/source/nickel.pdf"


def test_summary_cache_key_changes_with_model_and_text(tmp_path: Path) -> None:
    path = tmp_path / "document_summaries.jsonl"
    write_summary_rows(path)
    record = next(iter_summary_records(path, kind="document_summary"))

    key_a = summary_cache_key("emb://folder/model-a", record, embedding_text=record.text)
    key_b = summary_cache_key("emb://folder/model-b", record, embedding_text=record.text)
    key_c = summary_cache_key("emb://folder/model-a", record, embedding_text=record.text + " extra")

    assert key_a != key_b
    assert key_a != key_c
