from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterator


SUMMARY_TEXT_FIELDS = (
    "title",
    "summary",
    "main_topic",
    "key_findings",
    "materials",
    "processes",
    "equipment",
    "properties",
    "experimental_protocols",
    "technology_solutions",
    "process_parameters",
    "analysis_results",
    "observed_effects",
    "numerical_results",
    "facilities_or_geography",
    "geography",
    "source_type",
    "source_path",
)


@dataclass(frozen=True)
class SummaryRecord:
    row_id: int
    summary_id: str
    kind: str
    doc_id: str
    publication_id: str
    title: str
    source_path: str
    text: str
    text_chars: int

    @classmethod
    def from_row(cls, row_id: int, kind: str, row: dict[str, Any]) -> "SummaryRecord":
        text = summary_embedding_text(row)
        return cls(
            row_id=row_id,
            summary_id=summary_id(row, kind),
            kind=kind,
            doc_id=str(row.get("doc_id") or ""),
            publication_id=str(row.get("publication_id") or ""),
            title=compact_text(row.get("title") or row.get("main_topic") or row.get("source_path"), 240),
            source_path=str(row.get("source_path") or row.get("local_path") or ""),
            text=text,
            text_chars=len(text),
        )

    def metadata(self) -> dict[str, Any]:
        return {
            "row_id": self.row_id,
            "summary_id": self.summary_id,
            "kind": self.kind,
            "doc_id": self.doc_id,
            "publication_id": self.publication_id,
            "title": self.title,
            "source_path": self.source_path,
            "text_chars": self.text_chars,
        }


def compact_text(value: Any, max_chars: int | None = None) -> str:
    text = re.sub(r"\s+", " ", str(value or "")).strip()
    if max_chars is not None and len(text) > max_chars:
        return text[: max_chars - 3].rstrip() + "..."
    return text


def flatten_text(value: Any) -> Iterator[str]:
    if value in (None, "", [], {}):
        return
    if isinstance(value, dict):
        preferred = value.get("name") or value.get("label") or value.get("value") or value.get("text")
        if preferred:
            yield from flatten_text(preferred)
            return
        for key, item in value.items():
            for flattened in flatten_text(item):
                yield f"{key}: {flattened}"
        return
    if isinstance(value, list):
        for item in value:
            yield from flatten_text(item)
        return
    yield str(value)


def summary_embedding_text(row: dict[str, Any]) -> str:
    parts: list[str] = []
    for field_name in SUMMARY_TEXT_FIELDS:
        value = row.get(field_name)
        if value in (None, "", [], {}):
            continue
        if isinstance(value, (dict, list)):
            flattened = "; ".join(compact_text(item, 500) for item in flatten_text(value))
            if flattened:
                parts.append(f"{field_name}: {flattened}")
        else:
            parts.append(f"{field_name}: {compact_text(value, 2000)}")
    if not parts:
        parts.append(json.dumps(row, ensure_ascii=False, default=str))
    return "\n".join(parts)


def summary_id(row: dict[str, Any], kind: str) -> str:
    value = (
        row.get("document_summary_id")
        or row.get("procedure_summary_id")
        or row.get("summary_id")
        or row.get("id")
    )
    if value:
        return str(value)
    doc_id = str(row.get("doc_id") or "")
    publication_id = str(row.get("publication_id") or "")
    digest = hashlib.sha256(json.dumps(row, ensure_ascii=False, sort_keys=True, default=str).encode("utf-8")).hexdigest()[:16]
    return f"{kind}_{doc_id or publication_id or digest}"


def iter_summary_records(path: Path, *, kind: str, limit: int | None = None) -> Iterator[SummaryRecord]:
    count = 0
    with path.open("r", encoding="utf-8") as f:
        for line in f:
            if limit is not None and count >= limit:
                break
            line = line.strip()
            if not line:
                continue
            row = json.loads(line)
            record = SummaryRecord.from_row(count, kind, row)
            if not record.summary_id or not record.text:
                continue
            yield record
            count += 1


def summary_cache_key(model_uri: str, record: SummaryRecord, *, embedding_text: str | None = None) -> str:
    payload = f"{model_uri}\n{record.kind}\n{record.summary_id}\n{embedding_text if embedding_text is not None else record.text}"
    return hashlib.sha256(payload.encode("utf-8", errors="ignore")).hexdigest()
