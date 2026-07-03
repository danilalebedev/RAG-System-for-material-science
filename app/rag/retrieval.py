from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable

from app.index.chunks import load_chunk_texts
from app.index.lexical import LexicalHit, LexicalIndex
from app.index.vector_store import VectorHit, VectorIndex, load_metadata


@dataclass
class RetrievalResult:
    rank: int
    score: float
    chunk_id: str
    doc_id: str
    chunk_index: int | None
    source_path: str
    local_path: str
    text: str
    components: dict[str, float] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        return {
            "rank": self.rank,
            "score": round(self.score, 6),
            "chunk_id": self.chunk_id,
            "doc_id": self.doc_id,
            "chunk_index": self.chunk_index,
            "source_path": self.source_path,
            "local_path": self.local_path,
            "text": self.text,
            "components": {key: round(value, 6) for key, value in self.components.items()},
        }


def dense_search(index_dir: Path, query_vector: Iterable[float], *, top_k: int, batch_size: int = 8192) -> list[VectorHit]:
    return VectorIndex(index_dir).search(query_vector, top_k=top_k, batch_size=batch_size)


def lexical_search(index_dir: Path, query: str, *, top_k: int) -> list[LexicalHit]:
    return LexicalIndex(index_dir).search(query, top_k=top_k)


def reciprocal_rank_fusion(
    *,
    dense_hits: list[VectorHit],
    lexical_hits: list[LexicalHit],
    rrf_k: int = 60,
    top_k: int = 10,
) -> list[tuple[int, float, dict[str, float]]]:
    fused: dict[int, float] = {}
    components: dict[int, dict[str, float]] = {}
    for rank, hit in enumerate(dense_hits, start=1):
        fused[hit.row_id] = fused.get(hit.row_id, 0.0) + 1.0 / (rrf_k + rank)
        components.setdefault(hit.row_id, {})["dense"] = hit.score
    for rank, hit in enumerate(lexical_hits, start=1):
        fused[hit.row_id] = fused.get(hit.row_id, 0.0) + 1.0 / (rrf_k + rank)
        components.setdefault(hit.row_id, {})["lexical"] = hit.score
    ranked = sorted(fused.items(), key=lambda item: item[1], reverse=True)[:top_k]
    return [(row_id, score, components.get(row_id, {})) for row_id, score in ranked]


def materialize_results(
    *,
    ranked_rows: list[tuple[int, float, dict[str, float]]],
    index_dir: Path,
    chunks_path: Path,
    snippet_chars: int,
) -> list[RetrievalResult]:
    metadata = {int(row["row_id"]): row for row in load_metadata(index_dir)}
    chunk_ids = {str(metadata[row_id].get("chunk_id") or "") for row_id, _, _ in ranked_rows if row_id in metadata}
    texts = load_chunk_texts(chunks_path, chunk_ids)
    results: list[RetrievalResult] = []
    for rank, (row_id, score, components) in enumerate(ranked_rows, start=1):
        row = metadata.get(row_id)
        if not row:
            continue
        chunk_id = str(row.get("chunk_id") or "")
        text = texts.get(chunk_id, "")
        if snippet_chars > 0 and len(text) > snippet_chars:
            text = text[: snippet_chars - 3].rstrip() + "..."
        results.append(
            RetrievalResult(
                rank=rank,
                score=score,
                chunk_id=chunk_id,
                doc_id=str(row.get("doc_id") or ""),
                chunk_index=row.get("chunk_index"),
                source_path=str(row.get("source_path") or ""),
                local_path=str(row.get("local_path") or ""),
                text=text,
                components=components,
            )
        )
    return results
