from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from dotenv import load_dotenv

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.query.literature import run_literature_search  # noqa: E402
from app.web_search.schemas import ALL_SEARCH_SOURCES, DEFAULT_SEARCH_SOURCES, LiteratureSearchRequest  # noqa: E402


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Search external scholarly literature and optionally run deep_search.")
    parser.add_argument("query", help="User literature search query.")
    parser.add_argument("--top-k", type=int, default=20)
    parser.add_argument("--deep-search", choices=["none", "top5"], default="none")
    parser.add_argument("--deep-search-limit", type=int, default=5)
    parser.add_argument("--sources", nargs="+", choices=ALL_SEARCH_SOURCES, default=DEFAULT_SEARCH_SOURCES)
    parser.add_argument("--language", default="auto")
    parser.add_argument("--run-id", default=None)
    parser.add_argument("--output-root", default=None)
    parser.add_argument("--no-local-search", action="store_true", default=False)
    parser.add_argument("--no-materials-only", action="store_true", default=False)
    parser.add_argument("--no-query-rewrite", action="store_true", default=False)
    parser.add_argument("--no-llm-query-rewrite", action="store_true", default=False)
    parser.add_argument("--no-comparison-insights", action="store_true", default=False)
    parser.add_argument("--no-recommended-resource-links", action="store_true", default=False)
    parser.add_argument("--recommended-resources", nargs="*", default=None)
    parser.add_argument("--no-fetch-excerpts", action="store_true", default=False)
    parser.add_argument("--no-pdf-report", action="store_true", default=False)
    parser.add_argument("--json", action="store_true", default=False, help="Print machine-readable run summary.")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    root = Path(__file__).resolve().parents[1]
    load_dotenv(root / ".env")
    request = LiteratureSearchRequest(
        query=args.query,
        top_k=args.top_k,
        sources=args.sources,
        deep_search=args.deep_search,
        deep_search_limit=args.deep_search_limit,
        language=args.language,
        include_local_search=not args.no_local_search,
        materials_only=not args.no_materials_only,
        use_query_rewrite=not args.no_query_rewrite,
        use_llm_query_rewrite=not args.no_llm_query_rewrite,
        generate_comparison_insights=not args.no_comparison_insights,
        include_recommended_resource_links=not args.no_recommended_resource_links,
        recommended_resource_ids=args.recommended_resources or [],
        fetch_excerpts=not args.no_fetch_excerpts,
        generate_pdf_report=not args.no_pdf_report,
        run_id=args.run_id,
    )
    output_root = Path(args.output_root) if args.output_root else None
    run = run_literature_search(request, project_root=root, output_root=output_root)
    summary = {
        "output_dir": str(run.output_dir),
        "keywords": run.keywords,
        "external_results": len(run.results),
        "local_matches": len(run.local_matches),
        "resource_links": len(run.resource_links),
        "deep_results": len(run.deep_results),
        "deep_search_limit": run.request.deep_search_limit,
        "pdf_report": str(run.report_pdf_path) if run.report_pdf_path else None,
        "docx_report": str(run.report_docx_path) if run.report_docx_path else None,
        "links_report": str(run.links_report_docx_path) if run.links_report_docx_path else None,
        "deep_report": str(run.deep_report_docx_path) if run.deep_report_docx_path else None,
        "full_run_json": str(run.full_run_json_path) if run.full_run_json_path else None,
        "warnings": run.warnings,
    }
    if args.json:
        print(json.dumps(summary, ensure_ascii=False, indent=2, default=str))
    else:
        print(f"Output: {run.output_dir}")
        print(f"Keywords: {', '.join(run.keywords) if run.keywords else 'n/a'}")
        print(f"External results: {len(run.results)}")
        print(f"Local matches: {len(run.local_matches)}")
        print(f"Resource links: {len(run.resource_links)}")
        print(f"Deep-search results: {len(run.deep_results)}")
        print(f"Deep-search limit: {run.request.deep_search_limit}")
        if run.report_pdf_path:
            print(f"PDF report: {run.report_pdf_path}")
        if run.report_docx_path:
            print(f"DOCX report: {run.report_docx_path}")
        for warning in run.warnings:
            print(f"Warning: {warning}")
        for index, result in enumerate(run.results[: min(args.top_k, 10)], start=1):
            print(f"{index}. [{result.source}] {result.title} ({result.year or 'n.d.'}) score={result.score}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
