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

from app.index.embeddings import apply_retrieval_profile, embed_texts, embedding_input_text, build_embedding_client, load_retrieval_config, redact_model_uri  # noqa: E402
from app.index.summaries import iter_summary_records, summary_cache_key  # noqa: E402
from app.index.vector_store import CACHE_FILE, append_embedding_cache, load_embedding_cache, save_vector_index  # noqa: E402


SUMMARY_INPUTS = {
    "document": ("document_summaries.jsonl", "data/indexes/document_summaries", "document_summary"),
    "procedure": ("procedure_summaries.jsonl", "data/indexes/procedure_summaries", "procedure_summary"),
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build vector indexes over publication document/procedure summaries.")
    parser.add_argument("--config", default="config/retrieval/default.json")
    parser.add_argument("--profile", default=None, help="Retrieval profile from config.profiles, e.g. routerai_bge_m3.")
    parser.add_argument("--publications-dir", default=None)
    parser.add_argument("--kind", choices=["document", "procedure", "both"], default="both")
    parser.add_argument("--document-index-dir", default=None)
    parser.add_argument("--procedure-index-dir", default=None)
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--resume", action="store_true", default=False)
    parser.add_argument("--rebuild", action="store_true", default=False)
    parser.add_argument("--batch-size", type=int, default=None)
    parser.add_argument("--embedding-batch-size", type=int, default=None)
    parser.add_argument("--model", choices=["doc", "fallback"], default=None)
    parser.add_argument("--embedding-backend", choices=["yandex", "local-hash", "routerai"], default=None)
    parser.add_argument("--sleep-seconds", type=float, default=None)
    parser.add_argument("--progress-jsonl", default=None)
    parser.add_argument("--progress-every", type=int, default=100)
    parser.add_argument("--no-progress-bar", action="store_true", default=False)
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


def append_progress(path: Path, row: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8", newline="\n") as f:
        f.write(json.dumps(row, ensure_ascii=False, default=str) + "\n")


def build_summary_vector_index(
    *,
    source_path: Path,
    index_dir: Path,
    summary_kind: str,
    retrieval_config: dict[str, Any],
    backend: str,
    model: str,
    limit: int | None,
    resume: bool,
    batch_size: int,
    embedding_batch_size: int,
    sleep_seconds: float,
    progress_jsonl: Path | None = None,
    progress_every: int = 100,
    progress_bar: bool = True,
) -> dict[str, Any]:
    if not source_path.exists():
        raise FileNotFoundError(f"summary source not found: {source_path}")
    client = build_embedding_client(
        backend=backend,
        retrieval_config=retrieval_config,
        kind="doc",
        fallback_model=model == "fallback",
        api_key=os.getenv("YANDEX_API_KEY"),
        folder_id=os.getenv("YANDEX_FOLDER_ID"),
    )
    cache_path = index_dir / CACHE_FILE
    cache = load_embedding_cache(cache_path) if resume else {}
    vectors: list[list[float]] = []
    vector_slots: list[list[float] | None] = []
    metadata: list[dict[str, Any]] = []
    pending: list[tuple[int, Any, str, str]] = []
    digest = hashlib.sha256()
    cache_hits = 0
    api_calls = 0
    started_at = time.monotonic()
    records = iter_summary_records(source_path, kind=summary_kind, limit=limit)
    progress = tqdm(records, desc=f"embedding {summary_kind}", unit="summary", disable=not progress_bar)

    def flush_pending() -> None:
        nonlocal api_calls
        if not pending:
            return
        pending_batch = pending[:]
        pending.clear()
        raw_texts = [item[1].text for item in pending_batch]
        batch_vectors = embed_texts(client, raw_texts)
        if len(batch_vectors) != len(pending_batch):
            raise RuntimeError(f"embedding batch returned {len(batch_vectors)} vectors for {len(pending_batch)} inputs")
        created_at = datetime.now(timezone.utc).isoformat()
        for (slot_index, record, key, _embedding_text), vector in zip(pending_batch, batch_vectors, strict=True):
            append_embedding_cache(
                cache_path,
                {
                    "cache_key": key,
                    "summary_id": record.summary_id,
                    "doc_id": record.doc_id,
                    "publication_id": record.publication_id,
                    "kind": record.kind,
                    "model_uri": redact_model_uri(client.model_uri),
                    "backend": client.backend,
                    "embedding": vector,
                    "created_at": created_at,
                },
            )
            cache[key] = vector
            vector_slots[slot_index] = vector
            api_calls += 1
            if sleep_seconds > 0:
                time.sleep(sleep_seconds)

    for index, record in enumerate(progress, start=1):
        digest.update(record.kind.encode("utf-8", errors="ignore"))
        digest.update(b"\0")
        digest.update(record.summary_id.encode("utf-8", errors="ignore"))
        digest.update(b"\0")
        digest.update(record.text.encode("utf-8", errors="ignore"))
        digest.update(b"\n")
        embedding_text = embedding_input_text(client, record.text)
        key = summary_cache_key(client.model_uri, record, embedding_text=embedding_text)
        vector = cache.get(key)
        vector_slots.append(None)
        if vector is None:
            pending.append((len(vector_slots) - 1, record, key, embedding_text))
            if len(pending) >= max(1, embedding_batch_size):
                flush_pending()
        else:
            cache_hits += 1
            vector_slots[-1] = vector
        metadata.append(record.metadata())
        if batch_size > 0 and index % batch_size == 0:
            progress.set_postfix({"cache_hits": cache_hits, "new": api_calls})
        if progress_jsonl and progress_every > 0 and index % progress_every == 0:
            append_progress(
                progress_jsonl,
                {
                    "event": "progress",
                    "summary_kind": summary_kind,
                    "processed_summaries": index,
                    "cache_hits": cache_hits,
                    "new_embeddings": api_calls,
                    "elapsed_seconds": round(time.monotonic() - started_at, 3),
                    "rate_summaries_per_second": round(index / max(time.monotonic() - started_at, 0.001), 3),
                    "rate_new_embeddings_per_second": round(api_calls / max(time.monotonic() - started_at, 0.001), 3),
                    "built_at": datetime.now(timezone.utc).isoformat(),
                },
            )
    flush_pending()
    vectors = [vector for vector in vector_slots if vector is not None]
    if not vectors:
        raise RuntimeError(f"no summary records selected from {source_path}")
    if len(vectors) != len(metadata):
        raise RuntimeError(f"vector count {len(vectors)} does not match metadata count {len(metadata)}")
    manifest = {
        "built_at": datetime.now(timezone.utc).isoformat(),
        "source_summary_path": str(source_path),
        "source_summary_size_bytes": source_path.stat().st_size,
        "selected_rows_sha256": digest.hexdigest(),
        "summary_kind": summary_kind,
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
        append_progress(progress_jsonl, {"event": "complete", "summary_kind": summary_kind, **manifest})
    return manifest


def main() -> int:
    args = parse_args()
    root = Path(__file__).resolve().parents[1]
    load_dotenv(root / ".env", encoding="utf-8-sig")
    retrieval_config = apply_retrieval_profile(load_retrieval_config(root / args.config), args.profile)
    backend = args.embedding_backend or str((retrieval_config.get("embedding") or {}).get("backend") or "yandex")
    model = args.model or str((retrieval_config.get("embedding") or {}).get("default_model") or "doc")
    build_config = retrieval_config.get("build") or {}
    batch_size = args.batch_size if args.batch_size is not None else int(build_config.get("batch_size") or 50)
    embedding_batch_size = args.embedding_batch_size if args.embedding_batch_size is not None else int(build_config.get("embedding_batch_size") or 1)
    sleep_seconds = args.sleep_seconds if args.sleep_seconds is not None else float(build_config.get("sleep_seconds") or 0.0)
    if backend == "routerai" and args.model is None:
        model = "doc"
    publications_dir = resolve_project_path(root, args.publications_dir, retrieval_config.get("summary_publications_dir", args.publications_dir))
    progress_jsonl = resolve_project_path(root, args.progress_jsonl, args.progress_jsonl) if args.progress_jsonl else None
    selected_kinds = ("document", "procedure") if args.kind == "both" else (args.kind,)
    index_dirs = {
        "document": resolve_project_path(root, args.document_index_dir, retrieval_config.get("document_summary_index_dir", SUMMARY_INPUTS["document"][1])),
        "procedure": resolve_project_path(root, args.procedure_index_dir, retrieval_config.get("procedure_summary_index_dir", SUMMARY_INPUTS["procedure"][1])),
    }
    outputs: dict[str, Any] = {}
    for kind in selected_kinds:
        source_name, _, summary_kind = SUMMARY_INPUTS[kind]
        index_dir = index_dirs[kind]
        if args.rebuild:
            safe_rmtree(index_dir, root=root)
        outputs[kind] = build_summary_vector_index(
            source_path=publications_dir / source_name,
            index_dir=index_dir,
            summary_kind=summary_kind,
            retrieval_config=retrieval_config,
            backend=backend,
            model=model,
            limit=args.limit,
            resume=args.resume and not args.rebuild,
            batch_size=batch_size,
            embedding_batch_size=embedding_batch_size,
            sleep_seconds=sleep_seconds,
            progress_jsonl=progress_jsonl,
            progress_every=args.progress_every,
            progress_bar=not args.no_progress_bar,
        )
    print(json.dumps(outputs, ensure_ascii=False, indent=2, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
