from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from dotenv import load_dotenv
from tqdm import tqdm

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.index.chunks import cache_key, iter_chunk_records  # noqa: E402
from app.index.embeddings import embedding_input_text, build_embedding_client, load_retrieval_config, redact_model_uri  # noqa: E402
from app.index.lexical import build_lexical_index  # noqa: E402
from app.index.vector_store import (  # noqa: E402
    CACHE_FILE,
    append_embedding_cache,
    load_embedding_cache,
    save_vector_index,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build RAG indexes over parsed source chunks.")
    parser.add_argument("--config", default="config/retrieval/default.json")
    parser.add_argument("--chunks", default=None)
    parser.add_argument("--index-dir", default=None)
    parser.add_argument("--lexical-dir", default=None)
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--resume", action="store_true", default=False)
    parser.add_argument("--rebuild", action="store_true", default=False)
    parser.add_argument("--batch-size", type=int, default=None, help="Checkpoint interval for embedding cache progress.")
    parser.add_argument("--model", choices=["doc", "fallback"], default=None)
    parser.add_argument("--embedding-backend", choices=["yandex", "local-hash"], default=None)
    parser.add_argument("--sleep-seconds", type=float, default=None)
    parser.add_argument("--progress-jsonl", default=None)
    parser.add_argument("--progress-every", type=int, default=250)
    parser.add_argument("--no-progress-bar", action="store_true", default=False)
    parser.add_argument("--skip-vector", action="store_true", default=False)
    parser.add_argument("--skip-lexical", action="store_true", default=False)
    return parser.parse_args()


def resolve_project_path(root: Path, value: str | None, fallback: str) -> Path:
    raw = value or fallback
    path = Path(raw)
    return path if path.is_absolute() else root / path


def safe_rmtree(path: Path, *, root: Path) -> None:
    resolved = path.resolve()
    root_resolved = root.resolve()
    if resolved == root_resolved or root_resolved not in resolved.parents:
        raise RuntimeError(f"refusing to remove path outside project root: {resolved}")
    if path.exists():
        shutil.rmtree(path)


def build_vector_index(
    *,
    chunks_path: Path,
    index_dir: Path,
    retrieval_config: dict[str, Any],
    backend: str,
    model: str,
    limit: int | None,
    resume: bool,
    batch_size: int,
    sleep_seconds: float,
    progress_jsonl: Path | None = None,
    progress_every: int = 250,
    progress_bar: bool = True,
) -> dict[str, Any]:
    api_key = os.getenv("YANDEX_API_KEY")
    folder_id = os.getenv("YANDEX_FOLDER_ID")
    client = build_embedding_client(
        backend=backend,
        retrieval_config=retrieval_config,
        kind="doc",
        fallback_model=model == "fallback",
        api_key=api_key,
        folder_id=folder_id,
    )
    cache_path = index_dir / CACHE_FILE
    cache = load_embedding_cache(cache_path) if resume else {}
    vectors: list[list[float]] = []
    metadata: list[dict[str, Any]] = []
    digest = hashlib.sha256()
    cache_hits = 0
    api_calls = 0
    started_at = time.monotonic()
    records = iter_chunk_records(chunks_path, limit=limit)
    progress = tqdm(records, desc="embedding chunks", unit="chunk", disable=not progress_bar)
    for index, record in enumerate(progress, start=1):
        digest.update(record.chunk_id.encode("utf-8", errors="ignore"))
        digest.update(b"\0")
        digest.update(record.text.encode("utf-8", errors="ignore"))
        digest.update(b"\n")
        embedding_text = embedding_input_text(client, record.text)
        key = cache_key(client.model_uri, record, embedding_text=embedding_text)
        vector = cache.get(key)
        if vector is None:
            vector = client.embed_text(record.text)
            append_embedding_cache(
                cache_path,
                {
                    "cache_key": key,
                    "chunk_id": record.chunk_id,
                    "doc_id": record.doc_id,
                    "model_uri": redact_model_uri(client.model_uri),
                    "backend": client.backend,
                    "embedding": vector,
                    "created_at": datetime.now(timezone.utc).isoformat(),
                },
            )
            cache[key] = vector
            api_calls += 1
            if sleep_seconds > 0:
                time.sleep(sleep_seconds)
        else:
            cache_hits += 1
        vectors.append(vector)
        metadata.append(record.metadata())
        if batch_size > 0 and index % batch_size == 0:
            progress.set_postfix({"cache_hits": cache_hits, "new": api_calls})
        if progress_jsonl and progress_every > 0 and index % progress_every == 0:
            append_progress(
                progress_jsonl,
                {
                    "event": "progress",
                    "processed_chunks": index,
                    "cache_hits": cache_hits,
                    "new_embeddings": api_calls,
                    "elapsed_seconds": round(time.monotonic() - started_at, 3),
                    "rate_chunks_per_second": round(index / max(time.monotonic() - started_at, 0.001), 3),
                    "built_at": datetime.now(timezone.utc).isoformat(),
                },
            )
    if not vectors:
        raise RuntimeError(f"no chunks selected from {chunks_path}")
    manifest = {
        "built_at": datetime.now(timezone.utc).isoformat(),
        "source_chunks_path": str(chunks_path),
        "source_chunks_size_bytes": chunks_path.stat().st_size if chunks_path.exists() else None,
        "selected_rows_sha256": digest.hexdigest(),
        "limit": limit,
        "embedding_backend": client.backend,
        "embedding_model_uri": redact_model_uri(client.model_uri),
        "model_selection": model,
        "cache_path": str(cache_path),
        "cache_hits": cache_hits,
        "new_embeddings": api_calls,
    }
    save_vector_index(index_dir, vectors, metadata, manifest)
    if progress_jsonl:
        append_progress(progress_jsonl, {"event": "complete", **manifest})
    return manifest


def build_lexical(
    *,
    chunks_path: Path,
    lexical_dir: Path,
    limit: int | None,
) -> dict[str, Any]:
    count = build_lexical_index(lexical_dir, iter_chunk_records(chunks_path, limit=limit))
    manifest = {
        "built_at": datetime.now(timezone.utc).isoformat(),
        "source_chunks_path": str(chunks_path),
        "limit": limit,
        "chunk_count": count,
        "backend": "sqlite-fts5",
    }
    lexical_dir.mkdir(parents=True, exist_ok=True)
    (lexical_dir / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return manifest


def append_progress(path: Path, row: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8", newline="\n") as f:
        f.write(json.dumps(row, ensure_ascii=False, default=str) + "\n")


def main() -> int:
    args = parse_args()
    root = Path(__file__).resolve().parents[1]
    load_dotenv(root / ".env")
    retrieval_config = load_retrieval_config(root / args.config)
    chunks_path = resolve_project_path(root, args.chunks, retrieval_config.get("chunks_path", "data/parsed/chunks.jsonl"))
    index_dir = resolve_project_path(root, args.index_dir, retrieval_config.get("chunk_index_dir", "data/indexes/chunks"))
    lexical_dir = resolve_project_path(root, args.lexical_dir, retrieval_config.get("lexical_index_dir", "data/indexes/lexical"))
    backend = args.embedding_backend or str((retrieval_config.get("embedding") or {}).get("backend") or "yandex")
    model = args.model or str((retrieval_config.get("embedding") or {}).get("default_model") or "doc")
    build_config = retrieval_config.get("build") or {}
    batch_size = args.batch_size if args.batch_size is not None else int(build_config.get("batch_size") or 50)
    sleep_seconds = args.sleep_seconds if args.sleep_seconds is not None else float(build_config.get("sleep_seconds") or 0.0)

    if args.rebuild:
        if not args.skip_vector:
            safe_rmtree(index_dir, root=root)
        if not args.skip_lexical:
            safe_rmtree(lexical_dir, root=root)

    outputs: dict[str, Any] = {}
    if not args.skip_vector:
        outputs["vector"] = build_vector_index(
            chunks_path=chunks_path,
            index_dir=index_dir,
            retrieval_config=retrieval_config,
            backend=backend,
            model=model,
            limit=args.limit,
            resume=args.resume and not args.rebuild,
            batch_size=batch_size,
            sleep_seconds=sleep_seconds,
            progress_jsonl=resolve_project_path(root, args.progress_jsonl, args.progress_jsonl) if args.progress_jsonl else None,
            progress_every=args.progress_every,
            progress_bar=not args.no_progress_bar,
        )
    if not args.skip_lexical:
        outputs["lexical"] = build_lexical(chunks_path=chunks_path, lexical_dir=lexical_dir, limit=args.limit)
    print(json.dumps(outputs, ensure_ascii=False, indent=2, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
