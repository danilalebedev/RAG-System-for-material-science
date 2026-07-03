from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Iterator


@dataclass(frozen=True)
class ChunkRecord:
    row_id: int
    chunk_id: str
    doc_id: str
    chunk_index: int | None
    text: str
    text_chars: int
    source_path: str
    local_path: str

    @classmethod
    def from_row(cls, row_id: int, row: dict[str, Any]) -> "ChunkRecord":
        text = str(row.get("text") or "")
        chunk_index = row.get("chunk_index")
        try:
            parsed_chunk_index = int(chunk_index) if chunk_index is not None else None
        except (TypeError, ValueError):
            parsed_chunk_index = None
        return cls(
            row_id=row_id,
            chunk_id=str(row.get("chunk_id") or ""),
            doc_id=str(row.get("doc_id") or ""),
            chunk_index=parsed_chunk_index,
            text=text,
            text_chars=int(row.get("text_chars") or len(text)),
            source_path=str(row.get("source_path") or ""),
            local_path=str(row.get("local_path") or ""),
        )

    def metadata(self) -> dict[str, Any]:
        return {
            "row_id": self.row_id,
            "chunk_id": self.chunk_id,
            "doc_id": self.doc_id,
            "chunk_index": self.chunk_index,
            "text_chars": self.text_chars,
            "source_path": self.source_path,
            "local_path": self.local_path,
        }


def iter_chunk_records(path: Path, *, limit: int | None = None) -> Iterator[ChunkRecord]:
    count = 0
    with path.open("r", encoding="utf-8") as f:
        for row_id, line in enumerate(f):
            if limit is not None and count >= limit:
                break
            line = line.strip()
            if not line:
                continue
            row = json.loads(line)
            record = ChunkRecord.from_row(row_id=count, row=row)
            if not record.chunk_id or not record.doc_id or not record.text:
                continue
            yield record
            count += 1


def selected_chunks_digest(records: Iterable[ChunkRecord]) -> str:
    digest = hashlib.sha256()
    for record in records:
        digest.update(record.chunk_id.encode("utf-8", errors="ignore"))
        digest.update(b"\0")
        digest.update(record.text.encode("utf-8", errors="ignore"))
        digest.update(b"\n")
    return digest.hexdigest()


def cache_key(model_uri: str, record: ChunkRecord, *, embedding_text: str | None = None) -> str:
    payload = f"{model_uri}\n{record.chunk_id}\n{embedding_text if embedding_text is not None else record.text}"
    return hashlib.sha256(payload.encode("utf-8", errors="ignore")).hexdigest()


def load_chunk_texts(path: Path, chunk_ids: set[str]) -> dict[str, str]:
    if not chunk_ids:
        return {}
    texts: dict[str, str] = {}
    with path.open("r", encoding="utf-8") as f:
        for line in f:
            if not line.strip():
                continue
            row = json.loads(line)
            chunk_id = str(row.get("chunk_id") or "")
            if chunk_id in chunk_ids:
                texts[chunk_id] = str(row.get("text") or "")
                if len(texts) == len(chunk_ids):
                    break
    return texts
