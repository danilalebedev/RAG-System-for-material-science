from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

from dotenv import load_dotenv

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.extract.publication_metadata import (  # noqa: E402
    ExtractionConfig,
    YandexCompletionClient,
    aggregate_records,
    load_documents,
    process_documents,
)
from app.extract.publication_quality import build_and_write_quality_report  # noqa: E402


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Extract publication metadata and RECIPER-style summaries."
    )
    parser.add_argument("--documents", default="data/parsed/documents.jsonl")
    parser.add_argument("--chunks", default="data/parsed/chunks.jsonl")
    parser.add_argument("--tables", default="data/parsed/tables.jsonl")
    parser.add_argument("--output-dir", default="data/processed/publications")
    parser.add_argument("--config", default="config/extraction/publication_metadata.json")
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--source-type", default=None)
    parser.add_argument("--resume", action="store_true", default=False)
    parser.add_argument("--retry-failed", action="store_true", default=False)
    parser.add_argument("--rebuild", action="store_true", default=False)
    parser.add_argument("--no-llm", action="store_true", default=False)
    parser.add_argument("--fallback-model", action="store_true", default=False)
    parser.add_argument("--aggregate-only", action="store_true", default=False)
    parser.add_argument("--quality-report", action="store_true", default=False)
    parser.add_argument("--quality-report-path", default=None)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    root = Path(__file__).resolve().parents[1]
    load_dotenv(root / ".env")
    output_dir = root / args.output_dir
    config = ExtractionConfig.from_file(root / args.config)

    if args.aggregate_only:
        counts = aggregate_records(output_dir / "records", output_dir)
        print(counts)
        if args.quality_report:
            report_path = root / args.quality_report_path if args.quality_report_path else None
            report = build_and_write_quality_report(output_dir, report_path)
            print({"quality_gate": report["gate"], "quality_report": str(report_path or (output_dir / "publication_quality_report.json"))})
        return 0

    docs = load_documents(root / args.documents, limit=args.limit, source_type=args.source_type)
    if not docs:
        print("No documents selected.")
        return 1

    client = None
    if not args.no_llm:
        api_key = os.getenv("YANDEX_API_KEY")
        folder_id = os.getenv("YANDEX_FOLDER_ID")
        if not api_key or not folder_id:
            raise RuntimeError("YANDEX_API_KEY and YANDEX_FOLDER_ID must be set in .env")
        client = YandexCompletionClient(
            api_key=api_key,
            folder_id=folder_id,
            config=config,
            use_fallback_model=args.fallback_model,
        )
        print(f"Using Yandex model: {client.model_uri}")
    else:
        print("LLM disabled; writing rule-based baseline records.")

    manifest = process_documents(
        docs=docs,
        chunks_path=root / args.chunks,
        tables_path=root / args.tables,
        output_dir=output_dir,
        config=config,
        client=client,
        resume=args.resume and not args.rebuild,
        no_llm=args.no_llm,
        retry_failed=args.retry_failed,
    )
    print(manifest)
    if args.quality_report:
        report_path = root / args.quality_report_path if args.quality_report_path else None
        report = build_and_write_quality_report(output_dir, report_path)
        print({"quality_gate": report["gate"], "quality_report": str(report_path or (output_dir / "publication_quality_report.json"))})
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
