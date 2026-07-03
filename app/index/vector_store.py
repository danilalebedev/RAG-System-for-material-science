from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

import numpy as np


VECTOR_FILE = "vector.npy"
METADATA_FILE = "metadata.jsonl"
MANIFEST_FILE = "manifest.json"
CACHE_FILE = "embedding_cache.jsonl"


def normalize_vector(vector: Iterable[float]) -> np.ndarray:
    array = np.asarray(list(vector), dtype=np.float32)
    norm = float(np.linalg.norm(array))
    if norm > 0:
        array = array / norm
    return array.astype(np.float32)


def normalize_matrix(vectors: list[Iterable[float]]) -> np.ndarray:
    if not vectors:
        return np.empty((0, 0), dtype=np.float32)
    matrix = np.asarray(vectors, dtype=np.float32)
    norms = np.linalg.norm(matrix, axis=1)
    nonzero = norms > 0
    matrix[nonzero] = matrix[nonzero] / norms[nonzero, None]
    return matrix.astype(np.float32)


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, default=str) + "\n", encoding="utf-8")


def write_metadata(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="\n") as f:
        for row in rows:
            f.write(json.dumps(row, ensure_ascii=False, default=str) + "\n")


def save_vector_index(index_dir: Path, vectors: list[Iterable[float]], metadata: list[dict[str, Any]], manifest: dict[str, Any]) -> None:
    index_dir.mkdir(parents=True, exist_ok=True)
    matrix = normalize_matrix(vectors)
    if matrix.shape[0] != len(metadata):
        raise ValueError(f"vector rows ({matrix.shape[0]}) do not match metadata rows ({len(metadata)})")
    vector_tmp = index_dir / "vector.tmp.npy"
    np.save(vector_tmp, matrix)
    vector_tmp.replace(index_dir / VECTOR_FILE)
    write_metadata(index_dir / METADATA_FILE, metadata)
    write_json(index_dir / MANIFEST_FILE, {**manifest, "chunk_count": len(metadata), "dimension": int(matrix.shape[1] if matrix.ndim == 2 else 0)})


def load_metadata(index_dir: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    path = index_dir / METADATA_FILE
    if not path.exists():
        return rows
    with path.open("r", encoding="utf-8") as f:
        for line in f:
            if line.strip():
                rows.append(json.loads(line))
    return rows


def load_manifest(index_dir: Path) -> dict[str, Any]:
    path = index_dir / MANIFEST_FILE
    if not path.exists():
        return {}
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


def load_embedding_cache(path: Path) -> dict[str, list[float]]:
    cache: dict[str, list[float]] = {}
    if not path.exists():
        return cache
    with path.open("r", encoding="utf-8") as f:
        for line in f:
            if not line.strip():
                continue
            row = json.loads(line)
            key = str(row.get("cache_key") or "")
            vector = row.get("embedding")
            if key and isinstance(vector, list):
                cache[key] = [float(value) for value in vector]
    return cache


def append_embedding_cache(path: Path, row: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8", newline="\n") as f:
        f.write(json.dumps(row, ensure_ascii=False, default=str) + "\n")


@dataclass(frozen=True)
class VectorHit:
    row_id: int
    score: float


class VectorIndex:
    def __init__(self, index_dir: Path) -> None:
        self.index_dir = index_dir
        self.matrix = np.load(index_dir / VECTOR_FILE, mmap_mode="r")

    def search(self, query_vector: Iterable[float], *, top_k: int, batch_size: int = 8192) -> list[VectorHit]:
        if top_k <= 0 or self.matrix.shape[0] == 0:
            return []
        query = normalize_vector(query_vector)
        if query.shape[0] != self.matrix.shape[1]:
            raise ValueError(f"query dimension {query.shape[0]} does not match index dimension {self.matrix.shape[1]}")
        keep = min(top_k, self.matrix.shape[0])
        best_scores: np.ndarray | None = None
        best_rows: np.ndarray | None = None
        for start in range(0, self.matrix.shape[0], batch_size):
            end = min(start + batch_size, self.matrix.shape[0])
            scores = np.asarray(self.matrix[start:end] @ query, dtype=np.float32)
            batch_keep = min(keep, scores.shape[0])
            if batch_keep == scores.shape[0]:
                batch_indices = np.arange(scores.shape[0])
            else:
                batch_indices = np.argpartition(scores, -batch_keep)[-batch_keep:]
            batch_scores = scores[batch_indices]
            batch_rows = batch_indices + start
            if best_scores is None:
                best_scores = batch_scores
                best_rows = batch_rows
            else:
                best_scores = np.concatenate([best_scores, batch_scores])
                best_rows = np.concatenate([best_rows, batch_rows])
            if best_scores.shape[0] > keep:
                indices = np.argpartition(best_scores, -keep)[-keep:]
                best_scores = best_scores[indices]
                best_rows = best_rows[indices]
        if best_scores is None or best_rows is None:
            return []
        order = np.argsort(-best_scores)
        return [VectorHit(row_id=int(best_rows[index]), score=float(best_scores[index])) for index in order[:keep]]
