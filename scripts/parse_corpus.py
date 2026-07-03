from __future__ import annotations

import argparse
import multiprocessing as mp
import pickle
import sys
from pathlib import Path
from uuid import uuid4

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tqdm import tqdm

from app.io_utils import read_jsonl, safe_filename, write_csv, write_jsonl
from app.parsing.chunking import chunk_text
from app.parsing.parsers import ParsedDocument, parse_document, parsed_document_to_row, stable_id
from app.quality.parsing_quality import quality_label
from app.settings import load_config, paths


DEFAULT_TIMEOUT_EXTENSIONS: set[str] = set()


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


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--start-index", type=int, default=0, help="Zero-based file offset for focused parsing/debugging.")
    parser.add_argument("--all-raw", action="store_true", help="Parse every file under data/raw instead of download manifest.")
    parser.add_argument("--per-file-timeout-seconds", type=int, default=60)
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
    manifest_by_local = {
        row.get("local_path"): row for row in manifest_rows
    }
    if args.all_raw or not manifest_rows:
        files = iter_local_files(p.raw_dir)
    else:
        files = [Path(row["local_path"]) for row in manifest_rows if row.get("local_path") and Path(row["local_path"]).exists()]
    if args.start_index:
        files = files[args.start_index :]
    if args.limit:
        files = files[: args.limit]

    documents: list[dict] = []
    chunks: list[dict] = []
    tables: list[dict] = []
    parse_manifest: list[dict] = []

    chunk_cfg = cfg["chunking"]
    for file_path in tqdm(files, desc="parse", unit="file"):
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
        documents.append({**doc_row, "text_preview": parsed.text[:1000]})
        parse_manifest.append(doc_row)

        for i, chunk in enumerate(
            chunk_text(
                parsed.text,
                target_chars=int(chunk_cfg["target_chars"]),
                overlap_chars=int(chunk_cfg["overlap_chars"]),
                min_chars=int(chunk_cfg["min_chars"]),
            ),
            start=1,
        ):
            chunk_id = stable_id(f"{doc_row['doc_id']}:{i}:{chunk[:80]}")
            chunks.append({
                "chunk_id": chunk_id,
                "doc_id": doc_row["doc_id"],
                "chunk_index": i,
                "text": chunk,
                "text_chars": len(chunk),
                "source_path": doc_row.get("source_path", ""),
                "local_path": doc_row["local_path"],
            })

        for table in parsed.tables:
            tables.append({
                "table_id": table.table_id,
                "doc_id": doc_row["doc_id"],
                "page_or_sheet": table.page_or_sheet,
                "text": table.text,
                "row_count": len(table.rows),
                "local_path": doc_row["local_path"],
            })

    write_jsonl(p.parsed_dir / "documents.jsonl", documents)
    write_jsonl(p.parsed_dir / "chunks.jsonl", chunks)
    write_jsonl(p.parsed_dir / "tables.jsonl", tables)
    write_csv(p.parsing_report_dir / "parse_manifest.csv", parse_manifest)
    print(f"Parsed files: {len(parse_manifest)}")
    print(f"Chunks: {len(chunks)}")
    print(f"Tables: {len(tables)}")
    print(f"Manifest: {p.parsing_report_dir / 'parse_manifest.csv'}")


if __name__ == "__main__":
    main()
