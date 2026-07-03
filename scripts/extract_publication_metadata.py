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
from app.extract.summary_quality import build_and_write_summary_quality_report  # noqa: E402


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
    parser.add_argument("--summary-audit", action="store_true", default=False)
    parser.add_argument("--summary-audit-llm", action="store_true", default=False)
    parser.add_argument("--summary-audit-sample-size", type=int, default=15)
    parser.add_argument("--summary-audit-seed", type=int, default=1729)
    parser.add_argument("--summary-audit-no-procedures", action="store_true", default=False)
    parser.add_argument("--summary-audit-path", default=None)
    return parser.parse_args()


def build_client(args: argparse.Namespace, config: ExtractionConfig) -> YandexCompletionClient:
    api_key = os.getenv("YANDEX_API_KEY")
    folder_id = os.getenv("YANDEX_FOLDER_ID")
    if not api_key or not folder_id:
        raise RuntimeError("YANDEX_API_KEY and YANDEX_FOLDER_ID must be set in .env")
    return YandexCompletionClient(
        api_key=api_key,
        folder_id=folder_id,
        config=config,
        use_fallback_model=args.fallback_model,
    )


def maybe_write_quality_report(args: argparse.Namespace, root: Path, output_dir: Path) -> None:
    if not args.quality_report:
        return
    report_path = root / args.quality_report_path if args.quality_report_path else None
    report = build_and_write_quality_report(output_dir, report_path)
    print(
        {
            "quality_gate": report["gate"],
            "quality_report": str(report_path or (output_dir / "publication_quality_report.json")),
        }
    )


def maybe_write_summary_audit(
    args: argparse.Namespace,
    root: Path,
    output_dir: Path,
    client: YandexCompletionClient | None,
) -> None:
    if not args.summary_audit:
        return
    audit_client = client if args.summary_audit_llm else None
    report_path = root / args.summary_audit_path if args.summary_audit_path else None
    report = build_and_write_summary_quality_report(
        output_dir,
        client=audit_client,
        sample_size=args.summary_audit_sample_size,
        seed=args.summary_audit_seed,
        include_procedures=not args.summary_audit_no_procedures,
        report_path=report_path,
    )
    print(
        {
            "summary_audit_gate": report["gate"],
            "summary_audit_report": str(report_path or (output_dir / "summary_quality_report.json")),
        }
    )


def main() -> int:
    args = parse_args()
    root = Path(__file__).resolve().parents[1]
    load_dotenv(root / ".env")
    output_dir = root / args.output_dir
    config = ExtractionConfig.from_file(root / args.config)

    if args.aggregate_only:
        counts = aggregate_records(output_dir / "records", output_dir)
        print(counts)
        maybe_write_quality_report(args, root, output_dir)
        audit_client = build_client(args, config) if args.summary_audit and args.summary_audit_llm else None
        maybe_write_summary_audit(args, root, output_dir, audit_client)
        return 0

    docs = load_documents(root / args.documents, limit=args.limit, source_type=args.source_type)
    if not docs:
        print("No documents selected.")
        return 1

    client = None
    if not args.no_llm:
        client = build_client(args, config)
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
    maybe_write_quality_report(args, root, output_dir)
    audit_client = client
    if args.summary_audit_llm and audit_client is None:
        audit_client = build_client(args, config)
    maybe_write_summary_audit(args, root, output_dir, audit_client)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
