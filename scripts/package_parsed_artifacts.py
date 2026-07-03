from __future__ import annotations

import argparse
import json
import sys
import zipfile
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.settings import paths


JSONL_FILES = ("documents.jsonl", "chunks.jsonl", "tables.jsonl")
REPORT_FILES = (
    "parse_manifest.csv",
    "parsing_quality_report.md",
    "data_storage_guide.md",
    "quality_assessment_plan.md",
    "inventory_report.md",
)


def to_portable_path(value: str, root: Path) -> str:
    if not value:
        return value
    try:
        path = Path(value)
        if path.is_absolute():
            return str(path.relative_to(root)).replace("\\", "/")
    except ValueError:
        return value
    except OSError:
        return value
    return value.replace("\\", "/")


def portable_metadata(value: object, root: Path) -> object:
    if isinstance(value, dict):
        result: dict[str, object] = {}
        for key, item in value.items():
            if key in {"csv_path", "csv_export_dir"} and isinstance(item, str):
                result[key] = to_portable_path(item, root)
            else:
                result[key] = portable_metadata(item, root)
        return result
    if isinstance(value, list):
        return [portable_metadata(item, root) for item in value]
    return value


def write_portable_jsonl(zip_file: zipfile.ZipFile, source_path: Path, archive_path: str, root: Path) -> int:
    count = 0
    with source_path.open("r", encoding="utf-8") as source, zip_file.open(archive_path, "w") as target:
        for line in source:
            if not line.strip():
                continue
            row = json.loads(line)
            for key in ("local_path", "full_text_path"):
                if key in row:
                    row[key] = to_portable_path(str(row.get(key) or ""), root)
            if row.get("metadata_json"):
                try:
                    row["metadata_json"] = json.dumps(
                        portable_metadata(json.loads(str(row["metadata_json"])), root),
                        ensure_ascii=False,
                        default=str,
                    )
                except json.JSONDecodeError:
                    pass
            target.write((json.dumps(row, ensure_ascii=False, default=str) + "\n").encode("utf-8"))
            count += 1
    return count


def add_file(zip_file: zipfile.ZipFile, source_path: Path, archive_path: str) -> None:
    if source_path.exists() and source_path.is_file():
        zip_file.write(source_path, archive_path)


def build_readme(include_full_texts: bool, include_spreadsheet_csv: bool) -> str:
    full_text_note = (
        "- `data/parsed/full_texts/*.txt` included.\n"
        if include_full_texts
        else "- `data/parsed/full_texts/*.txt` omitted by `--no-full-texts`.\n"
    )
    spreadsheet_note = (
        "- `data/parsed/spreadsheets_csv/**/*.csv` included for full Excel sheet exports.\n"
        if include_spreadsheet_csv
        else "- `data/parsed/spreadsheets_csv/**/*.csv` omitted by `--no-spreadsheet-csv`.\n"
    )
    return (
        "# Parsed Corpus Artifact\n\n"
        "Unzip this archive into the repository root.\n\n"
        "Included paths:\n\n"
        "- `data/parsed/documents.jsonl`\n"
        "- `data/parsed/chunks.jsonl`\n"
        "- `data/parsed/tables.jsonl`\n"
        f"{full_text_note}"
        f"{spreadsheet_note}"
        "- `reports/parsing/*` quality reports when available.\n\n"
        "The JSONL files are made portable: absolute local Windows paths are rewritten to repo-relative paths.\n"
        "Raw source files are not included; use `source_path`, `doc_id`, and `chunk_id` for downstream work.\n"
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="Create a portable zip archive with parsed corpus artifacts.")
    parser.add_argument("--output", type=Path, default=None, help="Output zip path. Defaults to artifacts/parsed_corpus_<timestamp>.zip")
    parser.add_argument("--no-full-texts", action="store_true", help="Skip data/parsed/full_texts to create a lighter archive.")
    parser.add_argument("--no-spreadsheet-csv", action="store_true", help="Skip full Excel CSV exports to create a lighter archive.")
    args = parser.parse_args()

    p = paths()
    output = args.output
    if output is None:
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        output = p.root / "artifacts" / f"parsed_corpus_{stamp}.zip"
    output.parent.mkdir(parents=True, exist_ok=True)

    missing = [name for name in JSONL_FILES if not (p.parsed_dir / name).exists()]
    if missing:
        raise SystemExit(f"missing parsed files: {', '.join(missing)}")

    counts: dict[str, int] = {}
    with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=6) as zf:
        zf.writestr(
            "README_ARTIFACT.md",
            build_readme(
                include_full_texts=not args.no_full_texts,
                include_spreadsheet_csv=not args.no_spreadsheet_csv,
            ),
        )
        for name in JSONL_FILES:
            counts[name] = write_portable_jsonl(zf, p.parsed_dir / name, f"data/parsed/{name}", p.root)
        if not args.no_full_texts:
            for full_text in sorted(p.full_texts_dir.glob("*.txt")):
                zf.write(full_text, f"data/parsed/full_texts/{full_text.name}")
        if not args.no_spreadsheet_csv:
            for csv_file in sorted(p.spreadsheet_csv_dir.rglob("*.csv")):
                zf.write(csv_file, f"data/parsed/spreadsheets_csv/{csv_file.relative_to(p.spreadsheet_csv_dir).as_posix()}")
        for name in REPORT_FILES:
            add_file(zf, p.parsing_report_dir / name, f"reports/parsing/{name}")
        add_file(zf, p.root / "docs" / "parsing_data_layout.md", "docs/parsing_data_layout.md")

    size_mb = output.stat().st_size / 1024 / 1024
    print(f"Wrote {output}")
    print(f"Size MB: {size_mb:.2f}")
    for name, count in counts.items():
        print(f"{name}: {count}")


if __name__ == "__main__":
    main()
