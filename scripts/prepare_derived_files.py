from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.io_utils import read_jsonl, safe_filename, write_csv, write_jsonl
from app.parsing.parsers import stable_id
from app.settings import paths


ARCHIVE_EXTENSIONS = {".zip", ".rar", ".001", ".7z"}
ARCHIVE_COMPANION_EXTENSIONS = {".002"}
DIRECT_PARSE_EXTENSIONS = {".pdf", ".docx", ".docm", ".doc", ".pptx", ".xlsx", ".xls", ".txt"}
MULTIPART_RAR_COMPANION_RE = re.compile(r"\.part(?!1\b)\d+\.rar$", re.IGNORECASE)


def find_7z() -> str:
    candidates = [
        shutil.which("7z"),
        shutil.which("7za"),
        r"C:\Program Files\7-Zip\7z.exe",
        r"C:\Program Files (x86)\7-Zip\7z.exe",
    ]
    for candidate in candidates:
        if candidate and Path(candidate).exists():
            return str(candidate)
    raise FileNotFoundError("7-Zip executable not found")


def run_command(args: list[str], timeout_seconds: int) -> tuple[bool, str]:
    try:
        result = subprocess.run(args, capture_output=True, text=True, timeout=timeout_seconds, check=False)
    except subprocess.TimeoutExpired:
        return False, f"timeout after {timeout_seconds} seconds"
    output = "\n".join(part for part in (result.stdout, result.stderr) if part)
    return result.returncode == 0, output.strip()


def is_archive(path: Path) -> bool:
    return path.suffix.lower() in ARCHIVE_EXTENSIONS


def is_archive_companion(path: Path) -> bool:
    return path.suffix.lower() in ARCHIVE_COMPANION_EXTENSIONS or bool(MULTIPART_RAR_COMPANION_RE.search(path.name))


def extract_archive(source: Path, output_dir: Path, seven_zip: str, timeout_seconds: int) -> tuple[bool, str]:
    output_dir.mkdir(parents=True, exist_ok=True)
    ok, output = run_command([seven_zip, "x", "-y", f"-o{output_dir}", str(source)], timeout_seconds)
    if not ok:
        return False, output
    try:
        resolved_output = output_dir.resolve()
        for extracted in output_dir.rglob("*"):
            extracted.resolve().relative_to(resolved_output)
    except ValueError:
        return False, "archive extraction attempted to write outside target directory"
    return True, output


def source_row_for_file(row: dict[str, Any], local_path: Path, relative_note: str) -> dict[str, Any]:
    original_path = row.get("path") or row.get("source_path") or ""
    source_path = f"{original_path}::{relative_note}" if relative_note else original_path
    return {
        "name": local_path.name,
        "path": source_path,
        "relative_path": str(local_path),
        "top_folder": row.get("top_folder") or row.get("source_type") or "",
        "type": "derived",
        "size": local_path.stat().st_size if local_path.exists() else 0,
        "size_mb": round((local_path.stat().st_size if local_path.exists() else 0) / 1024 / 1024, 3),
        "mime_type": "",
        "extension": local_path.suffix.lower(),
        "download_url": "",
        "created": "",
        "modified": "",
        "local_path": str(local_path),
        "download_status": "derived",
        "download_error": "",
        "derived_from_local_path": row.get("local_path", ""),
        "derived_from_source_path": original_path,
    }


def add_parseable_file(
    derived_rows: list[dict[str, Any]],
    source_row: dict[str, Any],
    local_path: Path,
    relative_note: str,
) -> None:
    if local_path.suffix.lower() in DIRECT_PARSE_EXTENSIONS and local_path.exists():
        derived_rows.append(source_row_for_file(source_row, local_path, relative_note))


def process_archive(
    row: dict[str, Any],
    source_path: Path,
    derived_root: Path,
    seven_zip: str,
    archive_timeout_seconds: int,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    archive_dir = derived_root / "extracted" / f"{stable_id(str(source_path))}__{safe_filename(source_path.stem)}"
    ok, output = extract_archive(source_path, archive_dir, seven_zip, archive_timeout_seconds)
    derived_rows: list[dict[str, Any]] = []
    source_status = {
        **row,
        "derive_status": "failed" if not ok else "extracted",
        "derived_count": 0,
        "derive_error": "" if ok else output,
    }
    if not ok:
        return derived_rows, source_status

    for extracted in sorted(path for path in archive_dir.rglob("*") if path.is_file()):
        suffix = extracted.suffix.lower()
        relative_note = extracted.relative_to(archive_dir).as_posix()
        if suffix in DIRECT_PARSE_EXTENSIONS:
            add_parseable_file(derived_rows, row, extracted, relative_note)

    source_status["derived_count"] = len(derived_rows)
    return derived_rows, source_status


def companion_source_status(row: dict[str, Any]) -> dict[str, Any]:
    return {**row, "derive_status": "companion_skipped", "derived_count": 0, "derive_error": "archive companion part"}


def flush_outputs(
    interim_dir: Path,
    derived_rows: list[dict[str, Any]],
    source_rows: list[dict[str, Any]],
) -> None:
    write_jsonl(interim_dir / "derived_manifest.jsonl", derived_rows)
    write_jsonl(interim_dir / "derived_sources.jsonl", source_rows)
    write_csv(interim_dir / "derived_manifest.csv", derived_rows)
    write_csv(interim_dir / "derived_sources.csv", source_rows)


def main() -> None:
    parser = argparse.ArgumentParser(description="Extract archives into parseable derived files without launching Office GUI apps.")
    parser.add_argument("--archive-timeout-seconds", type=int, default=240)
    args = parser.parse_args()

    p = paths()
    manifest_rows = read_jsonl(p.interim_dir / "download_manifest.jsonl")
    if not manifest_rows:
        raise SystemExit("download_manifest.jsonl is missing; run scripts/download_dataset.py first")

    derived_root = p.interim_dir / "derived"
    seven_zip = find_7z()

    derived_rows: list[dict[str, Any]] = []
    source_rows: list[dict[str, Any]] = []
    candidate_rows = [
        row
        for row in manifest_rows
        if row.get("local_path")
        and Path(row["local_path"]).exists()
        and (is_archive(Path(row["local_path"])) or is_archive_companion(Path(row["local_path"])))
    ]
    for index, row in enumerate(candidate_rows, start=1):
        local = row.get("local_path")
        source_path = Path(local)
        suffix = source_path.suffix.lower()
        print(f"[{index}/{len(candidate_rows)}] {suffix} {source_path.name}", flush=True)
        if is_archive_companion(source_path):
            source_rows.append(companion_source_status(row))
        elif is_archive(source_path):
            rows, status = process_archive(
                row,
                source_path,
                derived_root,
                seven_zip,
                args.archive_timeout_seconds,
            )
            derived_rows.extend(rows)
            source_rows.append(status)
        flush_outputs(p.interim_dir, derived_rows, source_rows)

    summary = {
        "source_records": len(source_rows),
        "derived_records": len(derived_rows),
        "derived_by_extension": {},
    }
    for row in derived_rows:
        ext = row.get("extension", "")
        summary["derived_by_extension"][ext] = summary["derived_by_extension"].get(ext, 0) + 1
    (p.interim_dir / "derived_summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
