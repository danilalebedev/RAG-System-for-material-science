from __future__ import annotations

import re
import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

from app.index.chunks import ChunkRecord


LEXICAL_DB_FILE = "chunks.sqlite"
TOKEN_RE = re.compile(r"[\w.+#%-]+", re.UNICODE)


@dataclass(frozen=True)
class LexicalHit:
    row_id: int
    chunk_id: str
    doc_id: str
    source_path: str
    score: float


def build_lexical_index(index_dir: Path, records: Iterable[ChunkRecord]) -> int:
    index_dir.mkdir(parents=True, exist_ok=True)
    db_path = index_dir / LEXICAL_DB_FILE
    if db_path.exists():
        db_path.unlink()
    conn = sqlite3.connect(db_path)
    try:
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute(
            """
            CREATE VIRTUAL TABLE chunks USING fts5(
                chunk_id UNINDEXED,
                doc_id UNINDEXED,
                source_path UNINDEXED,
                text,
                tokenize = 'unicode61 remove_diacritics 0'
            )
            """
        )
        count = 0
        for record in records:
            conn.execute(
                "INSERT INTO chunks(rowid, chunk_id, doc_id, source_path, text) VALUES (?, ?, ?, ?, ?)",
                (record.row_id + 1, record.chunk_id, record.doc_id, record.source_path, record.text),
            )
            count += 1
            if count % 1000 == 0:
                conn.commit()
        conn.commit()
        return count
    finally:
        conn.close()


def fts_query(query: str, *, max_terms: int = 16) -> str:
    terms = []
    seen: set[str] = set()
    for token in TOKEN_RE.findall(query.lower().replace("ё", "е")):
        token = token.strip(".+#%-_")
        if len(token) < 2 or token in seen:
            continue
        seen.add(token)
        terms.append(token.replace('"', '""'))
        if len(terms) >= max_terms:
            break
    return " OR ".join(f'"{term}"' for term in terms)


class LexicalIndex:
    def __init__(self, index_dir: Path) -> None:
        self.db_path = index_dir / LEXICAL_DB_FILE

    def exists(self) -> bool:
        return self.db_path.exists()

    def search(self, query: str, *, top_k: int) -> list[LexicalHit]:
        if top_k <= 0 or not self.db_path.exists():
            return []
        match = fts_query(query)
        if not match:
            return []
        conn = sqlite3.connect(self.db_path)
        try:
            rows = conn.execute(
                """
                SELECT rowid - 1 AS row_id, chunk_id, doc_id, source_path, bm25(chunks) AS rank
                FROM chunks
                WHERE chunks MATCH ?
                ORDER BY rank
                LIMIT ?
                """,
                (match, top_k),
            ).fetchall()
        finally:
            conn.close()
        hits: list[LexicalHit] = []
        for row_id, chunk_id, doc_id, source_path, rank in rows:
            rank_value = float(rank)
            score = -rank_value if rank_value < 0 else 1.0 / (1.0 + rank_value)
            hits.append(
                LexicalHit(
                    row_id=int(row_id),
                    chunk_id=str(chunk_id),
                    doc_id=str(doc_id),
                    source_path=str(source_path),
                    score=score,
                )
            )
        return hits
