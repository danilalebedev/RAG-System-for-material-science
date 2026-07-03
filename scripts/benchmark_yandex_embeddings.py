from __future__ import annotations

import argparse
import json
import os
import statistics
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import requests
from dotenv import load_dotenv

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.index.chunks import iter_chunk_records  # noqa: E402
from app.index.embeddings import EmbeddingConfig, load_retrieval_config, prepare_embedding_text, redact_model_uri  # noqa: E402


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Benchmark Yandex embedding throughput without writing index cache.")
    parser.add_argument("--config", default="config/retrieval/default.json")
    parser.add_argument("--chunks", default=None)
    parser.add_argument("--rates", default="1,2,3,4,5,6,8,10")
    parser.add_argument("--duration-seconds", type=float, default=20.0)
    parser.add_argument("--cooldown-seconds", type=float, default=5.0)
    parser.add_argument("--sample-texts", type=int, default=500)
    parser.add_argument("--start-offset", type=int, default=0)
    parser.add_argument("--output-json", default="data/indexes/yandex_embedding_benchmark.json")
    return parser.parse_args()


def resolve_project_path(root: Path, value: str | None, fallback: str) -> Path:
    raw = value or fallback
    path = Path(raw)
    return path if path.is_absolute() else root / path


def load_sample_texts(path: Path, *, max_chars: int, max_terms: int, limit: int, start_offset: int) -> list[str]:
    texts: list[str] = []
    for index, record in enumerate(iter_chunk_records(path)):
        if index < start_offset:
            continue
        texts.append(prepare_embedding_text(record.text, max_chars=max_chars, max_terms=max_terms))
        if len(texts) >= limit:
            break
    if not texts:
        raise RuntimeError(f"no sample texts loaded from {path}")
    return texts


def request_embedding(
    *,
    session: requests.Session,
    endpoint: str,
    headers: dict[str, str],
    model_uri: str,
    text: str,
    timeout_seconds: int,
) -> dict[str, Any]:
    started = time.monotonic()
    try:
        response = session.post(
            endpoint,
            headers=headers,
            json={"modelUri": model_uri, "text": text},
            timeout=timeout_seconds,
        )
        elapsed = time.monotonic() - started
        error = None
        if response.status_code >= 400:
            try:
                payload = response.json()
                error = (payload.get("error") or payload.get("message") or "")[:200]
            except Exception:  # noqa: BLE001 - benchmark should keep measuring.
                error = response.text[:200]
        return {"status": response.status_code, "elapsed": elapsed, "error": error}
    except Exception as exc:  # noqa: BLE001 - benchmark should keep measuring.
        return {"status": "exception", "elapsed": time.monotonic() - started, "error": str(exc)[:200]}


def benchmark_rate(
    *,
    rate: float,
    duration_seconds: float,
    texts: list[str],
    endpoint: str,
    headers: dict[str, str],
    model_uri: str,
    timeout_seconds: int,
) -> dict[str, Any]:
    session = requests.Session()
    interval = 1.0 / rate
    end_at = time.monotonic() + duration_seconds
    next_at = time.monotonic()
    results: list[dict[str, Any]] = []
    text_index = 0
    while time.monotonic() < end_at:
        now = time.monotonic()
        if now < next_at:
            time.sleep(next_at - now)
        result = request_embedding(
            session=session,
            endpoint=endpoint,
            headers=headers,
            model_uri=model_uri,
            text=texts[text_index % len(texts)],
            timeout_seconds=timeout_seconds,
        )
        results.append(result)
        text_index += 1
        next_at += interval
    return summarize_results(rate, duration_seconds, results)


def summarize_results(rate: float, duration_seconds: float, results: list[dict[str, Any]]) -> dict[str, Any]:
    counts: dict[str, int] = {}
    for result in results:
        key = str(result["status"])
        counts[key] = counts.get(key, 0) + 1
    elapsed_values = [float(result["elapsed"]) for result in results]
    ok_count = counts.get("200", 0)
    error_samples = [
        {"status": result["status"], "error": result["error"]}
        for result in results
        if result.get("error")
    ][:5]
    return {
        "target_rps": rate,
        "duration_seconds": duration_seconds,
        "sent": len(results),
        "ok": ok_count,
        "counts": counts,
        "ok_rps": round(ok_count / duration_seconds, 4),
        "success_ratio": round(ok_count / len(results), 4) if results else 0.0,
        "latency_avg_seconds": round(statistics.mean(elapsed_values), 4) if elapsed_values else None,
        "latency_p95_seconds": round(percentile(elapsed_values, 0.95), 4) if elapsed_values else None,
        "error_samples": error_samples,
    }


def percentile(values: list[float], q: float) -> float:
    ordered = sorted(values)
    if not ordered:
        return 0.0
    index = min(len(ordered) - 1, max(0, round((len(ordered) - 1) * q)))
    return ordered[index]


def main() -> int:
    args = parse_args()
    root = Path(__file__).resolve().parents[1]
    load_dotenv(root / ".env")
    retrieval_config = load_retrieval_config(root / args.config)
    embedding_config = EmbeddingConfig.from_mapping(retrieval_config["embedding"])
    api_key = os.getenv("YANDEX_API_KEY")
    folder_id = os.getenv("YANDEX_FOLDER_ID")
    if not api_key or not folder_id:
        raise RuntimeError("YANDEX_API_KEY and YANDEX_FOLDER_ID must be set in .env")
    chunks_path = resolve_project_path(root, args.chunks, retrieval_config.get("chunks_path", "data/parsed/chunks.jsonl"))
    texts = load_sample_texts(
        chunks_path,
        max_chars=embedding_config.max_input_chars,
        max_terms=embedding_config.max_input_terms,
        limit=args.sample_texts,
        start_offset=args.start_offset,
    )
    model_uri = embedding_config.model_uri(folder_id=folder_id, kind="doc", fallback=True)
    headers = {
        "Authorization": f"{embedding_config.auth_scheme} {api_key}",
        "Content-Type": "application/json",
    }
    rates = [float(item.strip()) for item in args.rates.split(",") if item.strip()]
    rows = []
    for index, rate in enumerate(rates):
        if index > 0 and args.cooldown_seconds > 0:
            time.sleep(args.cooldown_seconds)
        row = benchmark_rate(
            rate=rate,
            duration_seconds=args.duration_seconds,
            texts=texts,
            endpoint=embedding_config.endpoint,
            headers=headers,
            model_uri=model_uri,
            timeout_seconds=embedding_config.request_timeout_seconds,
        )
        rows.append(row)
        print(json.dumps(row, ensure_ascii=False), flush=True)
    best = max(rows, key=lambda row: row["ok_rps"]) if rows else {}
    report = {
        "created_at": datetime.now(timezone.utc).isoformat(),
        "endpoint": embedding_config.endpoint,
        "model_uri": redact_model_uri(model_uri),
        "duration_seconds": args.duration_seconds,
        "cooldown_seconds": args.cooldown_seconds,
        "sample_texts": len(texts),
        "rates": rows,
        "best": best,
    }
    output_path = resolve_project_path(root, args.output_json, args.output_json)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(report, ensure_ascii=False, indent=2, default=str) + "\n", encoding="utf-8")
    print(json.dumps({"output_json": str(output_path), "best": best}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
