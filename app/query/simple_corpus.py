from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterator


TOKEN_RE = re.compile(r"[A-Za-zА-Яа-яЁё0-9][A-Za-zА-Яа-яЁё0-9_+.-]*")


@dataclass(frozen=True)
class EvidenceChunk:
    rank: int
    score: float
    chunk_id: str
    doc_id: str
    text: str
    source_path: str = ""
    local_path: str = ""


def tokenize(text: str) -> list[str]:
    return [token.lower() for token in TOKEN_RE.findall(text) if len(token) > 1]


def iter_jsonl(path: Path, *, max_rows: int = 0) -> Iterator[dict[str, Any]]:
    if not path.exists():
        return
    with path.open("r", encoding="utf-8") as f:
        for index, line in enumerate(f, start=1):
            if max_rows and index > max_rows:
                break
            line = line.strip()
            if not line:
                continue
            yield json.loads(line)


def score_text(query_terms: set[str], text: str) -> float:
    if not query_terms:
        return 0.0
    text_terms = tokenize(text)
    if not text_terms:
        return 0.0
    counts: dict[str, int] = {}
    for term in text_terms:
        if term in query_terms:
            counts[term] = counts.get(term, 0) + 1
    if not counts:
        return 0.0
    coverage = len(counts) / len(query_terms)
    frequency = sum(min(count, 3) for count in counts.values()) / max(len(text_terms), 1)
    return coverage * 10.0 + frequency


def retrieve_chunks(
    question: str,
    chunks_path: Path,
    *,
    top_k: int = 5,
    max_rows: int = 20_000,
) -> list[EvidenceChunk]:
    query_terms = set(tokenize(question))
    candidates: list[EvidenceChunk] = []
    for row in iter_jsonl(chunks_path, max_rows=max_rows):
        text = str(row.get("text", ""))
        score = score_text(query_terms, text)
        if score <= 0:
            continue
        candidates.append(
            EvidenceChunk(
                rank=0,
                score=score,
                chunk_id=str(row.get("chunk_id", "")),
                doc_id=str(row.get("doc_id", "")),
                text=text,
                source_path=str(row.get("source_path", "")),
                local_path=str(row.get("local_path", "")),
            )
        )
    candidates.sort(key=lambda item: item.score, reverse=True)
    return [
        EvidenceChunk(
            rank=index,
            score=item.score,
            chunk_id=item.chunk_id,
            doc_id=item.doc_id,
            text=item.text,
            source_path=item.source_path,
            local_path=item.local_path,
        )
        for index, item in enumerate(candidates[:top_k], start=1)
    ]


def format_evidence_context(
    chunks: list[EvidenceChunk],
    *,
    max_chars: int = 12_000,
) -> str:
    parts: list[str] = []
    used_chars = 0
    for chunk in chunks:
        header = (
            f"[{chunk.rank}] doc_id={chunk.doc_id}; "
            f"chunk_id={chunk.chunk_id}; source_path={chunk.source_path}"
        )
        available = max_chars - used_chars - len(header) - 2
        if available <= 0:
            break
        text = chunk.text[:available]
        parts.append(f"{header}\n{text}")
        used_chars += len(header) + len(text) + 2
    return "\n\n".join(parts)

