from __future__ import annotations

import argparse
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.io_utils import read_jsonl
from app.settings import paths
from scripts.parse_corpus import ResourceGuard


def expected_files() -> list[Path]:
    p = paths()
    manifest_rows = read_jsonl(p.interim_dir / "download_manifest.jsonl")
    derived_rows = read_jsonl(p.interim_dir / "derived_manifest.jsonl")
    derived_sources = read_jsonl(p.interim_dir / "derived_sources.jsonl")
    replaced_local_paths = {
        row.get("local_path")
        for row in derived_sources
        if row.get("local_path") and str(row.get("derive_status", "")).lower() not in {"failed", "not_needed"}
    }
    rows = [
        row
        for row in manifest_rows
        if not row.get("local_path") or row.get("local_path") not in replaced_local_paths
    ]
    rows.extend(derived_rows)
    return [Path(row["local_path"]) for row in rows if row.get("local_path") and Path(row["local_path"]).exists()]


def parsed_local_paths() -> set[str]:
    p = paths()
    return {
        str(row.get("local_path"))
        for row in read_jsonl(p.parsed_dir / "documents.jsonl")
        if row.get("local_path")
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run corpus parsing in small resource-friendly batches.")
    parser.add_argument("--fresh", action="store_true", help="Start from scratch and clean generated parsed artifacts.")
    parser.add_argument("--batch-size", type=int, default=10)
    parser.add_argument("--max-batches", type=int, default=0)
    parser.add_argument("--max-cpu-percent", type=float, default=70.0)
    parser.add_argument("--max-memory-percent", type=float, default=70.0)
    parser.add_argument("--max-disk-active-percent", type=float, default=70.0)
    parser.add_argument("--resource-check-interval-seconds", type=float, default=10.0)
    parser.add_argument("--resource-sleep-seconds", type=float, default=20.0)
    parser.add_argument("--sleep-between-batches", type=float, default=5.0)
    parser.add_argument("--per-file-timeout-seconds", type=int, default=60)
    parser.add_argument("--write-buffer-mb", type=int, default=4)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    p = paths()
    guard = ResourceGuard(
        root=p.root,
        max_cpu_percent=args.max_cpu_percent,
        max_memory_percent=args.max_memory_percent,
        max_disk_active_percent=args.max_disk_active_percent,
        max_disk_used_percent=95.0,
        check_interval_seconds=args.resource_check_interval_seconds,
        sleep_seconds=args.resource_sleep_seconds,
        log_path=p.root / "logs" / "parsing_batch_resource_monitor.jsonl",
        enabled=True,
    )
    expected = expected_files()
    expected_count = len(expected)
    print(f"Batch parse target: {expected_count} files", flush=True)

    batch_index = 0
    first_run = True
    while True:
        done_count = 0 if args.fresh and first_run else len(parsed_local_paths())
        remaining = expected_count - done_count
        if remaining <= 0:
            print(f"Batch parse complete: {done_count}/{expected_count}", flush=True)
            break
        if args.max_batches and batch_index >= args.max_batches:
            print(f"Batch limit reached: {done_count}/{expected_count}", flush=True)
            break

        batch_index += 1
        current_batch = min(args.batch_size, remaining)
        guard.wait_if_needed(force=True)
        command = [
            sys.executable,
            str(p.root / "scripts" / "parse_corpus.py"),
            "--limit",
            str(current_batch),
            "--no-progress",
            "--max-cpu-percent",
            str(args.max_cpu_percent),
            "--max-memory-percent",
            str(args.max_memory_percent),
            "--max-disk-active-percent",
            str(args.max_disk_active_percent),
            "--resource-check-interval-seconds",
            str(args.resource_check_interval_seconds),
            "--resource-sleep-seconds",
            str(args.resource_sleep_seconds),
            "--status-every-documents",
            str(current_batch),
            "--flush-every-documents",
            str(current_batch),
            "--write-buffer-mb",
            str(args.write_buffer_mb),
            "--per-file-timeout-seconds",
            str(args.per_file_timeout_seconds),
        ]
        if not (args.fresh and first_run):
            command.append("--resume")
        if args.fresh and first_run:
            command.extend(["--clean-full-texts", "--clean-spreadsheet-csv"])

        print(f"Batch {batch_index}: done={done_count}, remaining={remaining}, size={current_batch}", flush=True)
        result = subprocess.run(command, cwd=p.root, text=True, check=False)
        if result.returncode != 0:
            raise SystemExit(f"Batch {batch_index} failed with exit code {result.returncode}")
        first_run = False
        if args.sleep_between_batches > 0:
            time.sleep(args.sleep_between_batches)


if __name__ == "__main__":
    main()
