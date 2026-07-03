from __future__ import annotations

import hashlib
import json
import os
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from app.io_utils import write_jsonl
from app.query.reports import build_pdf_report, run_overall_summary
from app.query.rewrite import deterministic_query_rewrite, rewrite_query
from app.settings import PROJECT_ROOT
from app.web_search.clients import LiteratureSearchClient
from app.web_search.comparison import (
    compare_methods,
    load_local_publication_records,
    search_local_summaries,
)
from app.web_search.deep_search import build_yandex_client_from_env, run_deep_search
from app.web_search.journal_quality import load_quartile_map
from app.web_search.keywords import extract_keywords
from app.web_search.resource_links import build_resource_links
from app.web_search.schemas import LiteratureSearchRequest, LiteratureSearchRun


def utc_run_id(query: str) -> str:
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    digest = hashlib.sha256(query.encode("utf-8", errors="ignore")).hexdigest()[:10]
    return f"{timestamp}_{digest}"


def safe_run_id(value: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9_.-]+", "_", value).strip("._")
    return cleaned[:120] or "web_search_run"


def write_json(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2, default=str), encoding="utf-8")


def build_literature_report(run: LiteratureSearchRun) -> str:
    lines = [
        "# Literature Search Report",
        "",
        f"Query: {run.request.query}",
        f"Corrected query: {run.query_plan.get('corrected_query') if run.query_plan else run.request.query}",
        f"Materials-only search: {run.request.materials_only}",
        f"Keywords: {', '.join(run.keywords) if run.keywords else 'n/a'}",
        f"External results: {len(run.results)}",
        f"Local matches: {len(run.local_matches)}",
        f"Recommended resource links: {len(run.resource_links)}",
        f"Deep-search summaries: {len(run.deep_results)}",
        "",
        "## Overall Summary",
        "",
        run_overall_summary(run),
    ]
    if run.query_plan:
        lines.extend(
            [
                "",
                "## Query Rewrite Plan",
                "",
                "Search queries:",
                *(f"- {item}" for item in run.query_plan.get("search_queries", [])),
            ]
        )
    lines.extend(
        [
        "",
        "## Top External Sources",
        ]
    )
    for index, result in enumerate(run.results[:10], start=1):
        url = str(result.url) if result.url else ""
        doi = f" DOI: {result.doi}." if result.doi else ""
        quartile = result.raw.get("journal_quartile") if result.raw else None
        quartile_text = f" Quartile: {quartile}." if quartile else ""
        lines.append(f"{index}. {result.title} ({result.year or 'n.d.'}). {result.venue or result.source}.{doi}{quartile_text} {url}".strip())
    if run.resource_links:
        lines.extend(["", "## Recommended Resource Search Links"])
        for row in run.resource_links[:40]:
            status = "" if row.get("enabled") else " (not integrated)"
            note = f" — {row.get('note')}" if row.get("note") else ""
            lines.append(f"- {row.get('name')}{status}: {row.get('url')}{note}")
    if run.deep_results:
        lines.extend(["", "## Deep Search Summaries"])
        for item in run.deep_results:
            summary = item.document_summary or {}
            url = str(item.source_result.url) if item.source_result.url else ""
            lines.extend(
                [
                    "",
                    f"### {item.source_result.title}",
                    f"URL: {url}" if url else "URL: n/a",
                    f"Status: {item.status}; procedures: {len(item.procedure_summaries)}",
                    compact_report_text(summary.get("summary") or summary.get("main_topic") or "No summary extracted.", 1200),
                ]
            )
    if run.comparison:
        lines.extend(
            [
                "",
                "## Method Comparison",
                f"Confirmed methods: {len(run.comparison.confirmed_methods)}",
                f"Local-only methods: {len(run.comparison.local_only_methods)}",
                f"Web-only methods: {len(run.comparison.web_only_methods)}",
                f"Differing conditions: {len(run.comparison.differing_conditions)}",
                "",
                "## Gaps",
            ]
        )
        lines.extend(f"- {gap}" for gap in run.comparison.gaps)
    if run.warnings:
        lines.extend(["", "## Warnings"])
        lines.extend(f"- {warning}" for warning in run.warnings)
    return "\n".join(lines).strip() + "\n"


def compact_report_text(value: Any, max_chars: int) -> str:
    text = re.sub(r"\s+", " ", str(value or "")).strip()
    if len(text) > max_chars:
        return text[: max_chars - 3].rstrip() + "..."
    return text


def write_run_outputs(run: LiteratureSearchRun, output_dir: Path) -> LiteratureSearchRun:
    output_dir.mkdir(parents=True, exist_ok=True)
    write_json(output_dir / "request.json", run.request.model_dump(mode="json"))
    write_json(output_dir / "query_plan.json", run.query_plan)
    write_json(output_dir / "keywords.json", {"keywords": run.keywords})
    write_jsonl(output_dir / "metadata_results.jsonl", [row.model_dump(mode="json") for row in run.results])
    write_jsonl(output_dir / "local_matches.jsonl", run.local_matches)
    write_jsonl(output_dir / "resource_links.jsonl", run.resource_links)
    if run.comparison:
        write_json(output_dir / "comparison_report.json", run.comparison.model_dump(mode="json"))
    report = build_literature_report(run)
    (output_dir / "literature_report.md").write_text(report, encoding="utf-8")
    run.output_dir = output_dir
    run.report_markdown = report
    if run.request.generate_pdf_report:
        run.report_pdf_path = build_pdf_report(run, output_dir / "literature_report.pdf")
    return run


def run_literature_search(
    request: LiteratureSearchRequest,
    *,
    project_root: Path = PROJECT_ROOT,
    client: LiteratureSearchClient | None = None,
    output_root: Path | None = None,
    yandex_client: Any | None = None,
) -> LiteratureSearchRun:
    rewrite_client = None
    if request.use_llm_query_rewrite:
        rewrite_client = yandex_client if yandex_client is not None else build_yandex_client_from_env(project_root / "config" / "extraction" / "publication_metadata.json")
    query_plan = (
        rewrite_query(
            request.query,
            client=rewrite_client,
            materials_only=request.materials_only,
            use_llm=request.use_llm_query_rewrite,
        )
        if request.use_query_rewrite
        else deterministic_query_rewrite(request.query, materials_only=request.materials_only)
    )
    keywords = query_plan.all_keywords or extract_keywords(request.query)
    output_root = output_root or (project_root / "data" / "processed" / "web_search")
    run_id = safe_run_id(request.run_id or utc_run_id(request.query))
    output_dir = output_root / run_id

    publications_dir = project_root / "data" / "processed" / "publications"
    local_publications, local_document_summaries, local_procedures = load_local_publication_records(publications_dir)
    if not request.include_local_search:
        local_publications, local_document_summaries, local_procedures = [], [], []
    local_matches = []
    if request.include_local_search:
        local_matches = search_local_summaries(
            query=query_plan.corrected_query,
            keywords=keywords,
            publications=local_publications,
            document_summaries=local_document_summaries,
            procedures=local_procedures,
            top_k=request.top_k,
        )

    web_client = client or LiteratureSearchClient(
        semantic_scholar_api_key=os.getenv("SEMANTIC_SCHOLAR_API_KEY"),
        journal_quartile_map=load_quartile_map(project_root / "config" / "web_search" / "journal_quartiles.json"),
    )
    results, warnings = web_client.search(
        query_plan.corrected_query,
        keywords=keywords,
        sources=request.sources,
        top_k=request.top_k,
        query_variants=query_plan.search_queries,
        materials_only=request.materials_only,
    )
    resource_links = []
    if request.include_recommended_resource_links:
        resource_links = build_resource_links(
            corrected_query=query_plan.corrected_query,
            search_queries=query_plan.search_queries,
            selected_resource_ids=request.recommended_resource_ids or None,
        )

    deep_results = []
    if request.deep_search == "top5":
        llm_client = yandex_client if yandex_client is not None else rewrite_client
        if llm_client is None:
            llm_client = build_yandex_client_from_env(project_root / "config" / "extraction" / "publication_metadata.json")
        deep_results = run_deep_search(
            results=results,
            output_dir=output_dir,
            mode=request.deep_search,
            client=llm_client,
            fetch_excerpts=request.fetch_excerpts,
            limit=request.deep_search_limit,
        )

    comparison = compare_methods(
        query=request.query,
        local_publications=local_publications,
        local_procedures=local_procedures,
        web_deep_results=deep_results,
    )
    run = LiteratureSearchRun(
        request=request,
        query_plan=query_plan.model_dump(mode="json"),
        keywords=keywords,
        results=results,
        local_matches=local_matches,
        resource_links=resource_links,
        deep_results=deep_results,
        comparison=comparison,
        warnings=warnings,
    )
    return write_run_outputs(run, output_dir)
