from __future__ import annotations

import sys
from collections import Counter, defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.ingest.yandex_disk import list_public_files
from app.io_utils import write_csv, write_jsonl
from app.settings import load_config, paths


def main() -> None:
    cfg = load_config()
    p = paths()
    files = list_public_files(cfg["public_dataset_url"])

    jsonl_path = p.interim_dir / "yandex_inventory.jsonl"
    csv_path = p.interim_dir / "yandex_inventory.csv"
    write_jsonl(jsonl_path, files)
    write_csv(csv_path, files)

    by_ext = Counter(row["extension"] or "<none>" for row in files)
    by_top = Counter(row["top_folder"] or "<root>" for row in files)
    bytes_by_ext: dict[str, int] = defaultdict(int)
    for row in files:
        bytes_by_ext[row["extension"] or "<none>"] += int(row["size"] or 0)

    report = [
        "# Yandex Disk Inventory",
        "",
        f"Files: {len(files)}",
        f"Total size: {sum(int(row['size'] or 0) for row in files) / 1024 / 1024:.2f} MB",
        "",
        "## By Top Folder",
        "",
        "| Folder | Files |",
        "|---|---:|",
    ]
    for key, value in by_top.most_common():
        report.append(f"| {key} | {value} |")
    report.extend(["", "## By Extension", "", "| Extension | Files | Size MB |", "|---|---:|---:|"])
    for key, value in by_ext.most_common():
        report.append(f"| {key} | {value} | {bytes_by_ext[key] / 1024 / 1024:.2f} |")
    report_path = p.parsing_report_dir / "inventory_report.md"
    report_path.write_text("\n".join(report), encoding="utf-8")

    print(f"Wrote {jsonl_path}")
    print(f"Wrote {csv_path}")
    print(f"Wrote {report_path}")


if __name__ == "__main__":
    main()
