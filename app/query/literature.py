from __future__ import annotations

import hashlib
import json
import os
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from app.io_utils import write_jsonl
from app.query import reports as report_builders
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

    report = report_builders.build_literature_report(run)
    links_report = report_builders.build_links_report(run)
    deep_report = report_builders.build_deep_report(run)
    report_builders.write_text_report(output_dir / "literature_report.md", report)
    report_builders.write_text_report(output_dir / "literature_links_report.md", links_report)
    report_builders.write_text_report(output_dir / "deep_search_report.md", deep_report)
    report_builders.write_json_report(output_dir / "full_run.json", report_builders.build_full_run_payload(run))

    run.output_dir = output_dir
    run.report_markdown = report
    run.links_report_markdown = links_report
    run.deep_report_markdown = deep_report
    run.full_run_json_path = output_dir / "full_run.json"
    if run.request.generate_pdf_report:
        run.report_pdf_path = report_builders.build_pdf_report(run, output_dir / "literature_report.pdf", mode="full")
        run.links_report_pdf_path = report_builders.build_pdf_report(run, output_dir / "literature_links_report.pdf", mode="links")
        run.deep_report_pdf_path = report_builders.build_pdf_report(run, output_dir / "deep_search_report.pdf", mode="deep")
    run.report_docx_path = report_builders.build_docx_report(run, output_dir / "literature_report.docx", mode="full")
    run.links_report_docx_path = report_builders.build_docx_report(run, output_dir / "literature_links_report.docx", mode="links")
    run.deep_report_docx_path = report_builders.build_docx_report(run, output_dir / "deep_search_report.docx", mode="deep")
    return run


def publication_records(project_root: Path, include_local_search: bool) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    publications_dir = project_root / "data" / "processed" / "publications"
    local_publications, local_document_summaries, local_procedures = load_local_publication_records(publications_dir)
    if not include_local_search:
        return [], [], []
    return local_publications, local_document_summaries, local_procedures


def yandex_client(project_root: Path, yandex_client_arg: Any | None = None) -> Any | None:
    if yandex_client_arg is not None:
        return yandex_client_arg
    return build_yandex_client_from_env(project_root / "config" / "extraction" / "publication_metadata.json")


def run_literature_search(
    request: LiteratureSearchRequest,
    *,
    project_root: Path = PROJECT_ROOT,
    client: LiteratureSearchClient | None = None,
    output_root: Path | None = None,
    yandex_client: Any | None = None,
) -> LiteratureSearchRun:
    rewrite_client = yandex_client if request.use_llm_query_rewrite else None
    if request.use_llm_query_rewrite and rewrite_client is None:
        rewrite_client = build_yandex_client_from_env(project_root / "config" / "extraction" / "publication_metadata.json")
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

    local_publications, local_document_summaries, local_procedures = publication_records(project_root, request.include_local_search)
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
        llm_client = yandex_client or rewrite_client or build_yandex_client_from_env(project_root / "config" / "extraction" / "publication_metadata.json")
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


def run_deep_search_for_existing_run(
    run: LiteratureSearchRun,
    *,
    project_root: Path = PROJECT_ROOT,
    deep_search_limit: int | None = None,
    fetch_excerpts: bool | None = None,
    yandex_client: Any | None = None,
) -> LiteratureSearchRun:
    request = run.request.model_copy(
        update={
            "deep_search": "top5",
            "deep_search_limit": deep_search_limit or run.request.deep_search_limit,
            "fetch_excerpts": run.request.fetch_excerpts if fetch_excerpts is None else fetch_excerpts,
        }
    )
    output_dir = run.output_dir or (project_root / "data" / "processed" / "web_search" / safe_run_id(request.run_id or utc_run_id(request.query)))
    local_publications, _, local_procedures = publication_records(project_root, request.include_local_search)
    deep_results = run_deep_search(
        results=run.results,
        output_dir=output_dir,
        mode="top5",
        client=yandex_client if yandex_client is not None else build_yandex_client_from_env(project_root / "config" / "extraction" / "publication_metadata.json"),
        fetch_excerpts=request.fetch_excerpts,
        limit=request.deep_search_limit,
    )
    comparison = compare_methods(
        query=request.query,
        local_publications=local_publications,
        local_procedures=local_procedures,
        web_deep_results=deep_results,
    )
    updated = run.model_copy(
        update={
            "request": request,
            "deep_results": deep_results,
            "comparison": comparison,
        },
        deep=True,
    )
    return write_run_outputs(updated, output_dir)
