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

from app.index.embeddings import build_embedding_client, load_retrieval_config, redact_model_uri  # noqa: E402


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Watch Yandex embedding availability and build summary vector indexes once it recovers.")
    parser.add_argument("--config", default="config/retrieval/default.json")
    parser.add_argument("--probe-text", default="никелевая руда и автоклавное выщелачивание")
    parser.add_argument("--probe-kind", choices=["query", "doc", "both"], default="both")
    parser.add_argument("--model", choices=["query", "doc", "fallback"], default="fallback")
    parser.add_argument("--interval-seconds", type=float, default=300.0)
    parser.add_argument("--max-attempts", type=int, default=0, help="0 means keep watching until success.")
    parser.add_argument("--status-jsonl", default="logs/yandex_summary_watch/status.jsonl")
    parser.add_argument("--no-build", action="store_true", default=False)
    parser.add_argument("--build-kind", choices=["document", "procedure", "both"], default="both")
    parser.add_argument("--build-limit", type=int, default=None)
    parser.add_argument("--build-progress-jsonl", default="logs/yandex_summary_watch/summary_index_progress.jsonl")
    parser.add_argument("--no-progress-bar", action="store_true", default=False)
    return parser.parse_args()


def resolve_project_path(root: Path, value: str | None, fallback: str) -> Path:
    raw = value or fallback
    path = Path(raw)
    return path if path.is_absolute() else root / path


def append_status(path: Path, row: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8", newline="\n") as f:
        f.write(json.dumps(row, ensure_ascii=False, default=str) + "\n")


def probe_once(
    *,
    retrieval_config: dict[str, Any],
    probe_text: str,
    probe_kind: str,
    model: str,
) -> tuple[bool, list[dict[str, Any]]]:
    api_key = os.getenv("YANDEX_API_KEY")
    folder_id = os.getenv("YANDEX_FOLDER_ID")
    if not api_key or not folder_id:
        return False, [{"kind": probe_kind, "ok": False, "error_type": "MissingCredentials", "message": "YANDEX_API_KEY or YANDEX_FOLDER_ID is not set"}]
    kinds = ("query", "doc") if probe_kind == "both" else (probe_kind,)
    results: list[dict[str, Any]] = []
    all_ok = True
    for kind in kinds:
        try:
            client = build_embedding_client(
                backend="yandex",
                retrieval_config=retrieval_config,
                kind=kind,
                fallback_model=model == "fallback",
                api_key=api_key,
                folder_id=folder_id,
            )
            vector = client.embed_text(probe_text)
            results.append(
                {
                    "kind": kind,
                    "ok": True,
                    "backend": client.backend,
                    "model_uri": redact_model_uri(client.model_uri),
                    "dimension": len(vector),
                }
            )
        except Exception as exc:  # noqa: BLE001 - watcher must persist external API failures.
            all_ok = False
            results.append(
                {
                    "kind": kind,
                    "ok": False,
                    "error_type": type(exc).__name__,
                    "message": str(exc)[:500],
                }
            )
    return all_ok, results


def run_summary_index_agent(
    *,
    root: Path,
    config: str,
    build_kind: str,
    build_limit: int | None,
    progress_jsonl: Path,
    no_progress_bar: bool,
) -> int:
    command = [
        sys.executable,
        str(root / "scripts" / "build_summary_indexes.py"),
        "--config",
        config,
        "--kind",
        build_kind,
        "--resume",
        "--model",
        "fallback",
        "--progress-jsonl",
        str(progress_jsonl),
    ]
    if build_limit is not None:
        command.extend(["--limit", str(build_limit)])
    if no_progress_bar:
        command.append("--no-progress-bar")
    completed = subprocess.run(command, cwd=root, check=False)  # noqa: S603
    return int(completed.returncode)


def main() -> int:
    args = parse_args()
    root = Path(__file__).resolve().parents[1]
    load_dotenv(root / ".env")
    retrieval_config = load_retrieval_config(root / args.config)
    status_jsonl = resolve_project_path(root, args.status_jsonl, args.status_jsonl)
    build_progress_jsonl = resolve_project_path(root, args.build_progress_jsonl, args.build_progress_jsonl)
    attempt = 0
    while True:
        attempt += 1
        ok, probe_results = probe_once(
            retrieval_config=retrieval_config,
            probe_text=args.probe_text,
            probe_kind=args.probe_kind,
            model=args.model,
        )
        status = {
            "event": "probe",
            "attempt": attempt,
            "ok": ok,
            "checked_at": datetime.now(timezone.utc).isoformat(),
            "results": probe_results,
        }
        append_status(status_jsonl, status)
        print(json.dumps(status, ensure_ascii=False, indent=2, default=str))
        if ok:
            if args.no_build:
                return 0
            append_status(status_jsonl, {"event": "summary_index_agent_started", "attempt": attempt, "started_at": datetime.now(timezone.utc).isoformat()})
            return_code = run_summary_index_agent(
                root=root,
                config=args.config,
                build_kind=args.build_kind,
                build_limit=args.build_limit,
                progress_jsonl=build_progress_jsonl,
                no_progress_bar=args.no_progress_bar,
            )
            append_status(
                status_jsonl,
                {
                    "event": "summary_index_agent_finished",
                    "attempt": attempt,
                    "return_code": return_code,
                    "finished_at": datetime.now(timezone.utc).isoformat(),
                },
            )
            return return_code
        if args.max_attempts and attempt >= args.max_attempts:
            return 1
        time.sleep(max(args.interval_seconds, 1.0))


if __name__ == "__main__":
    raise SystemExit(main())
