from __future__ import annotations

import csv
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.io_utils import read_jsonl
from app.quality.parsing_quality import summarize_manifest
from app.settings import paths


def read_csv_rows(path: Path) -> list[dict]:
    if not path.exists():
        return []
    with path.open("r", encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))


def main() -> None:
    p = paths()
    manifest = read_csv_rows(p.parsing_report_dir / "parse_manifest.csv")
    chunks = read_jsonl(p.parsed_dir / "chunks.jsonl")
    tables = read_jsonl(p.parsed_dir / "tables.jsonl")
    summary = summarize_manifest(manifest)
    by_source = Counter(row.get("source_type") or "<unknown>" for row in manifest)

    lines = [
        "# Parsing Quality Report",
        "",
        "## Summary",
        "",
        f"- Files parsed: {summary['file_count']}",
        f"- Chunks produced: {len(chunks)}",
        f"- Tables extracted: {len(tables)}",
        f"- Total extracted text chars: {summary['total_text_chars']}",
        f"- Median text chars per non-empty file: {summary['median_text_chars']}",
        "",
        "## Statuses",
        "",
        "| Status | Files |",
        "|---|---:|",
    ]
    for key, value in Counter(summary["statuses"]).most_common():
        lines.append(f"| {key} | {value} |")

    lines.extend(["", "## Quality Labels", "", "| Label | Files |", "|---|---:|"])
    for key, value in Counter(summary["quality_labels"]).most_common():
        lines.append(f"| {key} | {value} |")

    lines.extend(["", "## Source Sections", "", "| Source section | Files |", "|---|---:|"])
    for key, value in by_source.most_common():
        lines.append(f"| {key} | {value} |")

    problem_rows = [
        row for row in manifest if row.get("quality_label") in {"failed", "empty", "low_text", "low_text_pdf", "unsupported"}
    ]
    lines.extend(["", "## Files To Inspect", "", "| File | Label | Parser | Error |", "|---|---|---|---|"])
    for row in problem_rows[:50]:
        lines.append(
            f"| {Path(row.get('local_path', '')).name} | {row.get('quality_label')} | {row.get('parser')} | {row.get('errors', '')} |"
        )

    lines.extend([
        "",
        "## Quality Method",
        "",
        "Current automatic quality checks are intentionally simple:",
        "",
        "- `ok`: parser returned at least 500 chars of text, or enough text for a useful chunk.",
        "- `low_text_pdf`: PDF parsed but text is very short; likely scan/image PDF or bad extraction.",
        "- `empty`: parser succeeded but no text was extracted.",
        "- `failed`: parser raised an exception.",
        "- `unsupported`: extension is not parsed by the current pipeline.",
        "",
        "Recommended manual audit: open 5-10 files from each label, compare source pages with extracted text previews in `data/parsed/documents.jsonl`, and mark parser fixes needed.",
    ])
    report_path = p.parsing_report_dir / "parsing_quality_report.md"
    report_path.write_text("\n".join(lines), encoding="utf-8")
    print(f"Wrote {report_path}")


if __name__ == "__main__":
    main()
