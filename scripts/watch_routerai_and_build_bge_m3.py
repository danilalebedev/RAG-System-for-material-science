from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from dotenv import load_dotenv

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.index.embeddings import build_embedding_client, load_retrieval_config  # noqa: E402


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Wait for RouterAI embeddings access and build bge-m3 RAG indexes.")
    parser.add_argument("--config", default="config/retrieval/default.json")
    parser.add_argument("--interval-seconds", type=int, default=60)
    parser.add_argument("--embedding-batch-size", type=int, default=None)
    parser.add_argument("--log-dir", default="logs/routerai_bge_m3_build")
    parser.add_argument("--raw-index-dir", default="data/indexes/chunks_routerai_bge_m3")
    parser.add_argument("--lexical-dir", default="data/indexes/lexical_routerai_bge_m3")
    parser.add_argument("--document-summary-index-dir", default="data/indexes/document_summaries_routerai_bge_m3")
    parser.add_argument("--procedure-summary-index-dir", default="data/indexes/procedure_summaries_routerai_bge_m3")
    parser.add_argument("--skip-lexical", action="store_true", default=False)
    parser.add_argument("--skip-summaries", action="store_true", default=False)
    parser.add_argument("--no-progress-bar", action="store_true", default=False)
    return parser.parse_args()


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def project_path(root: Path, value: str) -> Path:
    path = Path(value)
    return path if path.is_absolute() else root / path


def append_jsonl(path: Path, row: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8", newline="\n") as f:
        f.write(json.dumps(row, ensure_ascii=False, default=str) + "\n")


def load_env(root: Path) -> None:
    load_dotenv(root / ".env", override=True, encoding="utf-8-sig")


def has_routerai_key(root: Path) -> bool:
    load_env(root)
    value = os.getenv("ROUTERAI_API_KEY")
    return bool(value and value.strip() and "YOUR_" not in value.upper())


def probe_routerai(root: Path, config_path: Path) -> dict[str, Any]:
    load_env(root)
    retrieval_config = load_retrieval_config(config_path)
    started = time.monotonic()
    client = build_embedding_client(
        backend="routerai",
        retrieval_config=retrieval_config,
        kind="query",
        fallback_model=False,
    )
    vector = client.embed_text("nickel concentrate roasting leaching")
    return {
        "backend": client.backend,
        "model_uri": client.model_uri,
        "dimension": len(vector),
        "elapsed_seconds": round(time.monotonic() - started, 3),
    }


def run_command(root: Path, log_dir: Path, name: str, command: list[str]) -> None:
    append_jsonl(log_dir / "status.jsonl", {"event": "command_start", "name": name, "command": safe_command(command), "checked_at": utc_now()})
    started = time.monotonic()
    stdout_path = log_dir / f"{name}_stdout.log"
    stderr_path = log_dir / f"{name}_stderr.log"
    with stdout_path.open("a", encoding="utf-8", newline="\n") as stdout, stderr_path.open("a", encoding="utf-8", newline="\n") as stderr:
        completed = subprocess.run(command, cwd=root, stdout=stdout, stderr=stderr, text=True, check=False)
    row = {
        "event": "command_complete" if completed.returncode == 0 else "command_failed",
        "name": name,
        "returncode": completed.returncode,
        "elapsed_seconds": round(time.monotonic() - started, 3),
        "stdout": str(stdout_path),
        "stderr": str(stderr_path),
        "checked_at": utc_now(),
    }
    append_jsonl(log_dir / "status.jsonl", row)
    if completed.returncode != 0:
        raise RuntimeError(f"{name} failed with exit code {completed.returncode}; see {stderr_path}")


def safe_command(command: list[str]) -> list[str]:
    return ["<python>" if index == 0 else item for index, item in enumerate(command)]


def main() -> int:
    args = parse_args()
    root = Path(__file__).resolve().parents[1]
    config_path = project_path(root, args.config)
    log_dir = project_path(root, args.log_dir)
    log_dir.mkdir(parents=True, exist_ok=True)
    (log_dir / "watcher.pid").write_text(
        json.dumps({"pid": os.getpid(), "started_at": utc_now()}, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    append_jsonl(log_dir / "status.jsonl", {"event": "watcher_start", "checked_at": utc_now()})

    while not has_routerai_key(root):
        append_jsonl(log_dir / "status.jsonl", {"event": "waiting_for_routerai_key", "checked_at": utc_now()})
        time.sleep(max(5, args.interval_seconds))

    try:
        probe = probe_routerai(root, config_path)
    except Exception as exc:  # noqa: BLE001 - watcher should produce a compact diagnostic.
        append_jsonl(log_dir / "status.jsonl", {"event": "probe_failed", "error": str(exc)[:500], "checked_at": utc_now()})
        return 2
    append_jsonl(log_dir / "status.jsonl", {"event": "probe_ok", **probe, "checked_at": utc_now()})

    venv_python = root / ".venv" / "Scripts" / "python.exe"
    python = str(venv_python if venv_python.exists() else Path(sys.executable))
    batch_size = str(args.embedding_batch_size or int((load_retrieval_config(config_path).get("build") or {}).get("embedding_batch_size") or 64))
    no_progress = ["--no-progress-bar"] if args.no_progress_bar else []

    lexical_dir = project_path(root, args.lexical_dir)
    lexical_ready = (lexical_dir / "chunks.sqlite").exists() and (lexical_dir / "manifest.json").exists()
    if not args.skip_lexical and lexical_ready:
        append_jsonl(log_dir / "status.jsonl", {"event": "lexical_skip_existing", "lexical_dir": str(lexical_dir), "checked_at": utc_now()})
    elif not args.skip_lexical:
        run_command(
            root,
            log_dir,
            "lexical",
            [
                python,
                "scripts/build_indexes.py",
                "--embedding-backend",
                "local-hash",
                "--model",
                "doc",
                "--index-dir",
                str(project_path(root, "data/indexes/routerai_lexical_dummy_vector")),
                "--lexical-dir",
                str(lexical_dir),
                "--skip-vector",
                "--rebuild",
                *no_progress,
            ],
        )

    run_command(
        root,
        log_dir,
        "raw_vector",
        [
            python,
            "scripts/build_indexes.py",
            "--embedding-backend",
            "routerai",
            "--model",
            "doc",
            "--index-dir",
            str(project_path(root, args.raw_index_dir)),
            "--lexical-dir",
            str(project_path(root, args.lexical_dir)),
            "--skip-lexical",
            "--resume",
            "--embedding-batch-size",
            batch_size,
            "--batch-size",
            "250",
            "--progress-jsonl",
            str(log_dir / "raw_progress.jsonl"),
            "--progress-every",
            "250",
            *no_progress,
        ],
    )

    if not args.skip_summaries:
        run_command(
            root,
            log_dir,
            "summary_vector",
            [
                python,
                "scripts/build_summary_indexes.py",
                "--embedding-backend",
                "routerai",
                "--model",
                "doc",
                "--kind",
                "both",
                "--document-index-dir",
                str(project_path(root, args.document_summary_index_dir)),
                "--procedure-index-dir",
                str(project_path(root, args.procedure_summary_index_dir)),
                "--resume",
                "--embedding-batch-size",
                batch_size,
                "--batch-size",
                "100",
                "--progress-jsonl",
                str(log_dir / "summary_progress.jsonl"),
                "--progress-every",
                "100",
                *no_progress,
            ],
        )

    append_jsonl(log_dir / "status.jsonl", {"event": "complete", "checked_at": utc_now()})
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
