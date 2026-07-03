from __future__ import annotations

import argparse
import csv
import ctypes
import gc
import json
import multiprocessing as mp
import pickle
import shutil
import sys
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from subprocess import DEVNULL, TimeoutExpired, run
from uuid import uuid4

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tqdm import tqdm

from app.io_utils import read_jsonl, safe_filename, write_csv
from app.parsing.chunking import iter_chunks
from app.parsing.parsers import ParsedDocument, parse_document, parsed_document_to_row, stable_id
from app.quality.parsing_quality import quality_label
from app.settings import load_config, paths


DEFAULT_TIMEOUT_EXTENSIONS = {".doc", ".xls"}


@dataclass(frozen=True)
class ResourceSample:
    cpu_percent: float | None
    memory_percent: float | None
    disk_active_percent: float | None
    disk_used_percent: float | None

    def as_dict(self) -> dict[str, float | None | str]:
        return {
            "timestamp": datetime.now().isoformat(timespec="seconds"),
            "cpu_percent": self.cpu_percent,
            "memory_percent": self.memory_percent,
            "disk_active_percent": self.disk_active_percent,
            "disk_used_percent": self.disk_used_percent,
        }


class MEMORYSTATUSEX(ctypes.Structure):
    _fields_ = [
        ("dwLength", ctypes.c_ulong),
        ("dwMemoryLoad", ctypes.c_ulong),
        ("ullTotalPhys", ctypes.c_ulonglong),
        ("ullAvailPhys", ctypes.c_ulonglong),
        ("ullTotalPageFile", ctypes.c_ulonglong),
        ("ullAvailPageFile", ctypes.c_ulonglong),
        ("ullTotalVirtual", ctypes.c_ulonglong),
        ("ullAvailVirtual", ctypes.c_ulonglong),
        ("sullAvailExtendedVirtual", ctypes.c_ulonglong),
    ]


class ResourceGuard:
    def __init__(
        self,
        *,
        root: Path,
        max_cpu_percent: float,
        max_memory_percent: float,
        max_disk_active_percent: float,
        max_disk_used_percent: float,
        check_interval_seconds: float,
        sleep_seconds: float,
        log_path: Path,
        enabled: bool,
    ) -> None:
        self.root = root
        self.max_cpu_percent = max_cpu_percent
        self.max_memory_percent = max_memory_percent
        self.max_disk_active_percent = max_disk_active_percent
        self.max_disk_used_percent = max_disk_used_percent
        self.check_interval_seconds = check_interval_seconds
        self.sleep_seconds = sleep_seconds
        self.log_path = log_path
        self.enabled = enabled
        self.last_check_at = 0.0
        self.last_sample: ResourceSample | None = None

    def wait_if_needed(self, *, force: bool = False) -> ResourceSample | None:
        if not self.enabled:
            return None
        now = time.monotonic()
        if not force and now - self.last_check_at < self.check_interval_seconds:
            return self.last_sample
        while True:
            self.last_check_at = time.monotonic()
            sample = self.sample()
            self.last_sample = sample
            self.write_log(sample)
            reasons = self.over_limit_reasons(sample)
            if not reasons:
                return sample
            print(f"resource guard: {'; '.join(reasons)}; sleeping {self.sleep_seconds:.0f}s", flush=True)
            time.sleep(self.sleep_seconds)

    def sample(self) -> ResourceSample:
        cpu_percent, disk_percent = cpu_and_disk_active_percent()
        return ResourceSample(
            cpu_percent=cpu_percent,
            memory_percent=memory_percent(),
            disk_active_percent=disk_percent,
            disk_used_percent=disk_used_percent(self.root),
        )

    def over_limit_reasons(self, sample: ResourceSample) -> list[str]:
        reasons: list[str] = []
        if sample.cpu_percent is not None and sample.cpu_percent > self.max_cpu_percent:
            reasons.append(f"cpu {sample.cpu_percent:.1f}% > {self.max_cpu_percent:.1f}%")
        if sample.memory_percent is not None and sample.memory_percent > self.max_memory_percent:
            reasons.append(f"memory {sample.memory_percent:.1f}% > {self.max_memory_percent:.1f}%")
        if sample.disk_active_percent is not None and sample.disk_active_percent > self.max_disk_active_percent:
            reasons.append(f"disk active {sample.disk_active_percent:.1f}% > {self.max_disk_active_percent:.1f}%")
        if sample.disk_used_percent is not None and sample.disk_used_percent > self.max_disk_used_percent:
            reasons.append(f"disk used {sample.disk_used_percent:.1f}% > {self.max_disk_used_percent:.1f}%")
        return reasons

    def write_log(self, sample: ResourceSample) -> None:
        self.log_path.parent.mkdir(parents=True, exist_ok=True)
        with self.log_path.open("a", encoding="utf-8", newline="\n") as f:
            f.write(json.dumps(sample.as_dict(), ensure_ascii=False) + "\n")


def memory_percent() -> float | None:
    status = MEMORYSTATUSEX()
    status.dwLength = ctypes.sizeof(MEMORYSTATUSEX)
    if not ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(status)):
        return None
    return float(status.dwMemoryLoad)


def disk_used_percent(root: Path) -> float | None:
    try:
        usage = shutil.disk_usage(root)
    except OSError:
        return None
    return usage.used / usage.total * 100 if usage.total else None


def cpu_and_disk_active_percent() -> tuple[float | None, float | None]:
    try:
        result = run(
            [
                "typeperf",
                r"\Processor(_Total)\% Processor Time",
                r"\PhysicalDisk(_Total)\% Disk Time",
                "-sc",
                "1",
            ],
            capture_output=True,
            text=True,
            check=False,
            timeout=10,
            stdin=DEVNULL,
        )
    except (OSError, TimeoutExpired):
        return None, None
    if result.returncode != 0:
        return None, None
    rows = list(csv.reader(line for line in result.stdout.splitlines() if line.startswith('"')))
    for row in reversed(rows):
        if len(row) < 3 or row[0].startswith("(PDH-CSV"):
            continue
        try:
            cpu = float(row[1].replace(",", "."))
            disk = float(row[2].replace(",", "."))
        except ValueError:
            continue
        return min(max(cpu, 0.0), 100.0), min(max(disk, 0.0), 100.0)
    return None, None


def _parse_worker(file_path: str, result_path: str) -> None:
    parsed = parse_document(Path(file_path))
    with Path(result_path).open("wb") as f:
        pickle.dump(parsed, f, protocol=pickle.HIGHEST_PROTOCOL)


def parse_document_with_timeout(file_path: Path, timeout_seconds: int, tmp_dir: Path) -> ParsedDocument:
    if timeout_seconds <= 0:
        return parse_document(file_path)

    tmp_dir.mkdir(parents=True, exist_ok=True)
    result_path = tmp_dir / f"{stable_id(str(file_path))}-{uuid4().hex}.pickle"
    ctx = mp.get_context("spawn")
    process = ctx.Process(target=_parse_worker, args=(str(file_path), str(result_path)))
    process.start()
    process.join(timeout_seconds)

    if process.is_alive():
        process.terminate()
        process.join(timeout=5)
        if process.is_alive():
            process.kill()
            process.join(timeout=5)
        return ParsedDocument(
            str(file_path),
            parser=file_path.suffix.lower().lstrip(".") or "unknown",
            status="failed",
            errors=[f"parse timeout after {timeout_seconds} seconds"],
        )

    try:
        if process.exitcode != 0:
            return ParsedDocument(
                str(file_path),
                parser=file_path.suffix.lower().lstrip(".") or "unknown",
                status="failed",
                errors=[f"parser worker exited with code {process.exitcode}"],
            )
        if not result_path.exists():
            return ParsedDocument(
                str(file_path),
                parser=file_path.suffix.lower().lstrip(".") or "unknown",
                status="failed",
                errors=["parser worker produced no result"],
            )
        with result_path.open("rb") as f:
            return pickle.load(f)
    finally:
        result_path.unlink(missing_ok=True)


def parse_document_guarded(
    file_path: Path,
    timeout_seconds: int,
    timeout_extensions: set[str],
    tmp_dir: Path,
) -> ParsedDocument:
    if file_path.suffix.lower() in timeout_extensions:
        return parse_document_with_timeout(file_path, timeout_seconds, tmp_dir)
    return parse_document(file_path)


def iter_local_files(root: Path) -> list[Path]:
    return sorted(path for path in root.rglob("*") if path.is_file())


def count_jsonl_rows(path: Path) -> int:
    if not path.exists():
        return 0
    count = 0
    with path.open("r", encoding="utf-8") as f:
        for line in f:
            if line.strip():
                count += 1
    return count


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--start-index", type=int, default=0, help="Zero-based file offset for focused parsing/debugging.")
    parser.add_argument("--all-raw", action="store_true", help="Parse every file under data/raw instead of download manifest.")
    parser.add_argument("--per-file-timeout-seconds", type=int, default=60)
    parser.add_argument("--no-progress", action="store_true", help="Disable tqdm progress output.")
    parser.add_argument("--resume", action="store_true", help="Append missing documents to existing parsed JSONL files.")
    parser.add_argument("--max-cpu-percent", type=float, default=75.0)
    parser.add_argument("--max-memory-percent", type=float, default=75.0)
    parser.add_argument("--max-disk-active-percent", type=float, default=75.0)
    parser.add_argument("--max-disk-used-percent", type=float, default=95.0)
    parser.add_argument("--resource-check-interval-seconds", type=float, default=20.0)
    parser.add_argument("--resource-sleep-seconds", type=float, default=15.0)
    parser.add_argument("--disable-resource-guard", action="store_true")
    parser.add_argument("--resource-log", type=Path, default=Path("logs/parsing_resource_monitor.jsonl"))
    parser.add_argument("--write-buffer-mb", type=int, default=16)
    parser.add_argument("--flush-every-documents", type=int, default=250)
    parser.add_argument("--status-every-documents", type=int, default=25)
    parser.add_argument("--clean-full-texts", action="store_true", help="Remove old data/parsed/full_texts/*.txt before a fresh run.")
    parser.add_argument("--clean-spreadsheet-csv", action="store_true", help="Remove old data/parsed/spreadsheets_csv before a fresh run.")
    parser.add_argument(
        "--timeout-extensions",
        default=",".join(sorted(DEFAULT_TIMEOUT_EXTENSIONS)),
        help="Comma-separated extensions parsed in a worker process with per-file timeout.",
    )
    args = parser.parse_args()

    cfg = load_config()
    p = paths()
    timeout_extensions = {
        ext.strip().lower() if ext.strip().startswith(".") else f".{ext.strip().lower()}"
        for ext in args.timeout_extensions.split(",")
        if ext.strip()
    }
    parser_tmp_dir = p.interim_dir / "parser_tmp"
    manifest_rows = read_jsonl(p.interim_dir / "download_manifest.jsonl")
    derived_rows = read_jsonl(p.interim_dir / "derived_manifest.jsonl")
    derived_sources = read_jsonl(p.interim_dir / "derived_sources.jsonl")
    replaced_local_paths = {
        row.get("local_path")
        for row in derived_sources
        if row.get("local_path") and str(row.get("derive_status", "")).lower() not in {"failed", "not_needed"}
    }
    manifest_rows = [
        row
        for row in manifest_rows
        if not row.get("local_path") or row.get("local_path") not in replaced_local_paths
    ]
    manifest_rows.extend(derived_rows)
    manifest_by_local = {
        row.get("local_path"): row for row in manifest_rows
    }
    if args.all_raw or not manifest_rows:
        files = iter_local_files(p.raw_dir)
    else:
        files = [Path(row["local_path"]) for row in manifest_rows if row.get("local_path") and Path(row["local_path"]).exists()]
    if args.start_index:
        files = files[args.start_index :]
    total_candidates = len(files)

    parse_manifest: list[dict] = []
    existing_local_paths: set[str] = set()
    documents_path = p.parsed_dir / "documents.jsonl"
    chunks_path = p.parsed_dir / "chunks.jsonl"
    tables_path = p.parsed_dir / "tables.jsonl"
    if args.resume and documents_path.exists():
        for row in read_jsonl(documents_path):
            local_path = row.get("local_path")
            if local_path:
                existing_local_paths.add(str(local_path))
            parse_manifest.append({key: value for key, value in row.items() if key != "text_preview"})
        files = [file_path for file_path in files if str(file_path) not in existing_local_paths]
    if args.limit:
        files = files[: args.limit]
    remaining_to_process = len(files)

    document_count = len(parse_manifest)
    chunk_count = count_jsonl_rows(chunks_path) if args.resume else 0
    table_count = count_jsonl_rows(tables_path) if args.resume else 0

    chunk_cfg = cfg["chunking"]
    p.parsed_dir.mkdir(parents=True, exist_ok=True)
    p.full_texts_dir.mkdir(parents=True, exist_ok=True)
    if args.clean_full_texts and not args.resume:
        resolved_full_texts = p.full_texts_dir.resolve()
        resolved_root = p.root.resolve()
        resolved_full_texts.relative_to(resolved_root)
        for full_text in resolved_full_texts.glob("*.txt"):
            full_text.unlink()
    if args.clean_spreadsheet_csv and not args.resume:
        resolved_spreadsheets = p.spreadsheet_csv_dir.resolve()
        resolved_root = p.root.resolve()
        resolved_spreadsheets.relative_to(resolved_root)
        for child in resolved_spreadsheets.iterdir():
            if child.is_dir():
                shutil.rmtree(child)
            elif child.is_file():
                child.unlink()
    file_mode = "a" if args.resume else "w"
    resource_log = args.resource_log if args.resource_log.is_absolute() else p.root / args.resource_log
    guard = ResourceGuard(
        root=p.root,
        max_cpu_percent=args.max_cpu_percent,
        max_memory_percent=args.max_memory_percent,
        max_disk_active_percent=args.max_disk_active_percent,
        max_disk_used_percent=args.max_disk_used_percent,
        check_interval_seconds=args.resource_check_interval_seconds,
        sleep_seconds=args.resource_sleep_seconds,
        log_path=resource_log,
        enabled=not args.disable_resource_guard,
    )
    print(
        "Parse plan: "
        f"candidates={total_candidates}, already_done={len(existing_local_paths)}, remaining={remaining_to_process}, "
        f"resource_guard={'on' if not args.disable_resource_guard else 'off'}, "
        f"max_cpu={args.max_cpu_percent:.1f}%, max_memory={args.max_memory_percent:.1f}%, "
        f"max_disk_active={args.max_disk_active_percent:.1f}%",
        flush=True,
    )
    guard.wait_if_needed(force=True)
    buffer_size = max(1, args.write_buffer_mb) * 1024 * 1024
    processed_this_run = 0
    with (
        documents_path.open(file_mode, encoding="utf-8", newline="\n", buffering=buffer_size) as documents_file,
        chunks_path.open(file_mode, encoding="utf-8", newline="\n", buffering=buffer_size) as chunks_file,
        tables_path.open(file_mode, encoding="utf-8", newline="\n", buffering=buffer_size) as tables_file,
    ):
        for file_path in tqdm(files, desc="parse", unit="file", disable=args.no_progress):
            guard.wait_if_needed()
            source = manifest_by_local.get(str(file_path), {})
            parsed = parse_document_guarded(
                file_path,
                timeout_seconds=args.per_file_timeout_seconds,
                timeout_extensions=timeout_extensions,
                tmp_dir=parser_tmp_dir,
            )
            doc_row = parsed_document_to_row(parsed, extra={
                "source_path": source.get("path", ""),
                "source_type": source.get("top_folder", ""),
                "source_mime_type": source.get("mime_type", ""),
                "source_size": source.get("size", file_path.stat().st_size),
            })
            doc_row["quality_label"] = quality_label(doc_row)
            full_text_name = f"{doc_row['doc_id']}__{safe_filename(file_path.stem)}.txt"
            full_text_path = p.full_texts_dir / full_text_name
            full_text_path.write_text(parsed.text, encoding="utf-8", newline="\n")
            doc_row["full_text_path"] = str(full_text_path)
            documents_file.write(json.dumps({**doc_row, "text_preview": parsed.text[:1000]}, ensure_ascii=False, default=str) + "\n")
            document_count += 1
            processed_this_run += 1
            parse_manifest.append(doc_row)

            for i, chunk in enumerate(
                iter_chunks(
                    parsed.text,
                    target_chars=int(chunk_cfg["target_chars"]),
                    overlap_chars=int(chunk_cfg["overlap_chars"]),
                    min_chars=int(chunk_cfg["min_chars"]),
                ),
                start=1,
            ):
                chunk_id = stable_id(f"{doc_row['doc_id']}:{i}:{chunk[:80]}")
                chunks_file.write(json.dumps({
                    "chunk_id": chunk_id,
                    "doc_id": doc_row["doc_id"],
                    "chunk_index": i,
                    "text": chunk,
                    "text_chars": len(chunk),
                    "source_path": doc_row.get("source_path", ""),
                    "local_path": doc_row["local_path"],
                }, ensure_ascii=False, default=str) + "\n")
                chunk_count += 1

            for table in parsed.tables:
                tables_file.write(json.dumps({
                    "table_id": table.table_id,
                    "doc_id": doc_row["doc_id"],
                    "page_or_sheet": table.page_or_sheet,
                    "text": table.text,
                    "row_count": len(table.rows),
                    "local_path": doc_row["local_path"],
                }, ensure_ascii=False, default=str) + "\n")
                table_count += 1

            del parsed
            gc.collect()

            if args.flush_every_documents > 0 and processed_this_run % args.flush_every_documents == 0:
                documents_file.flush()
                chunks_file.flush()
                tables_file.flush()
            if args.status_every_documents > 0 and processed_this_run % args.status_every_documents == 0:
                sample = guard.wait_if_needed(force=True)
                sample_text = ""
                if sample is not None:
                    sample_text = (
                        f", cpu={sample.cpu_percent}, memory={sample.memory_percent}, "
                        f"disk_active={sample.disk_active_percent}, "
                        f"disk_used={sample.disk_used_percent:.1f}%"
                        if sample.disk_used_percent is not None
                        else ""
                    )
                print(
                    f"parsed {processed_this_run}/{remaining_to_process} this run; total={document_count}; "
                    f"chunks={chunk_count}; tables={table_count}{sample_text}",
                    flush=True,
                )

    write_csv(p.parsing_report_dir / "parse_manifest.csv", parse_manifest)
    print(f"Parsed files: {document_count}")
    print(f"Chunks: {chunk_count}")
    print(f"Tables: {table_count}")
    print(f"Manifest: {p.parsing_report_dir / 'parse_manifest.csv'}")


if __name__ == "__main__":
    main()
