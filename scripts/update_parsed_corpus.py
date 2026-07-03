from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.settings import paths


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Reproducible dataset update and parsing entrypoint.")
    parser.add_argument("--mode", choices=("incremental", "fresh"), default="incremental")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--skip-inventory", action="store_true")
    parser.add_argument("--skip-download", action="store_true")
    parser.add_argument("--skip-derived", action="store_true")
    parser.add_argument("--skip-parse", action="store_true")
    parser.add_argument("--skip-repair", action="store_true")
    parser.add_argument("--skip-report", action="store_true")
    parser.add_argument("--package", action="store_true", help="Create artifacts/parsed_corpus_full.zip after parsing.")
    parser.add_argument("--max-files", type=int, default=0, help="Download only a seed subset; default downloads all files.")
    parser.add_argument("--overwrite-download", action="store_true")
    parser.add_argument("--batch-size", type=int, default=10)
    parser.add_argument("--max-batches", type=int, default=0, help="0 means no batch limit.")
    parser.add_argument("--max-cpu-percent", type=float, default=70.0)
    parser.add_argument("--max-memory-percent", type=float, default=70.0)
    parser.add_argument("--max-disk-active-percent", type=float, default=70.0)
    parser.add_argument("--resource-check-interval-seconds", type=float, default=5.0)
    parser.add_argument("--resource-sleep-seconds", type=float, default=10.0)
    parser.add_argument("--sleep-between-batches", type=float, default=5.0)
    parser.add_argument("--write-buffer-mb", type=int, default=4)
    return parser.parse_args()


def run_step(command: list[str], *, dry_run: bool, cwd: Path) -> None:
    printable = " ".join(f'"{part}"' if " " in part else part for part in command)
    print(f"$ {printable}", flush=True)
    if dry_run:
        return
    result = subprocess.run(command, cwd=cwd, text=True, check=False)
    if result.returncode != 0:
        raise SystemExit(f"Command failed with exit code {result.returncode}: {printable}")


def main() -> None:
    args = parse_args()
    p = paths()
    python = sys.executable

    if not args.skip_inventory:
        run_step([python, str(p.root / "scripts" / "inventory_yandex_disk.py")], dry_run=args.dry_run, cwd=p.root)

    if not args.skip_download:
        download_command = [python, str(p.root / "scripts" / "download_dataset.py")]
        if args.max_files:
            download_command.extend(["--max-files", str(args.max_files)])
        else:
            download_command.append("--all")
        if args.overwrite_download:
            download_command.append("--overwrite")
        run_step(download_command, dry_run=args.dry_run, cwd=p.root)

    if not args.skip_derived:
        run_step([python, str(p.root / "scripts" / "prepare_derived_files.py")], dry_run=args.dry_run, cwd=p.root)

    if not args.skip_parse:
        parse_command = [
            python,
            str(p.root / "scripts" / "run_parse_batches.py"),
            "--batch-size",
            str(args.batch_size),
            "--max-batches",
            str(args.max_batches),
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
            "--sleep-between-batches",
            str(args.sleep_between_batches),
            "--write-buffer-mb",
            str(args.write_buffer_mb),
        ]
        if args.mode == "fresh":
            parse_command.append("--fresh")
        run_step(parse_command, dry_run=args.dry_run, cwd=p.root)

    if not args.skip_repair:
        run_step([python, str(p.root / "scripts" / "reparse_problem_documents.py")], dry_run=args.dry_run, cwd=p.root)

    if not args.skip_report:
        run_step([python, str(p.root / "scripts" / "build_parsing_report.py")], dry_run=args.dry_run, cwd=p.root)

    if args.package:
        run_step(
            [
                python,
                str(p.root / "scripts" / "package_parsed_artifacts.py"),
                "--output",
                str(p.root / "artifacts" / "parsed_corpus_full.zip"),
            ],
            dry_run=args.dry_run,
            cwd=p.root,
        )


if __name__ == "__main__":
    main()
