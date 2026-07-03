from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.ingest.yandex_disk import download_files, list_public_files, select_seed_files
from app.io_utils import read_jsonl, write_csv, write_jsonl
from app.settings import load_config, paths


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--max-files", type=int, default=None)
    parser.add_argument("--all", action="store_true", help="Download every supported file from the public dataset.")
    parser.add_argument("--overwrite", action="store_true")
    args = parser.parse_args()

    cfg = load_config()
    p = paths()
    inventory_path = p.interim_dir / "yandex_inventory.jsonl"
    files = read_jsonl(inventory_path)
    if not files:
        files = list_public_files(cfg["public_dataset_url"])
        write_jsonl(inventory_path, files)

    seed_cfg = cfg["seed_download"]
    if args.all:
        selected = [row for row in files if row.get("download_url")]
    else:
        max_files = args.max_files or int(seed_cfg["max_files"])
        selected = select_seed_files(
            files,
            max_files=max_files,
            preferred_extensions=seed_cfg["preferred_extensions"],
            max_file_size_mb=float(seed_cfg["max_file_size_mb"]),
        )
    manifest = download_files(selected, p.raw_dir, overwrite=args.overwrite, public_key=cfg["public_dataset_url"])
    write_jsonl(p.interim_dir / "download_manifest.jsonl", manifest)
    write_csv(p.interim_dir / "download_manifest.csv", manifest)
    print(f"Selected: {len(selected)}")
    print(f"Downloaded/skipped manifest: {p.interim_dir / 'download_manifest.csv'}")


if __name__ == "__main__":
    main()
