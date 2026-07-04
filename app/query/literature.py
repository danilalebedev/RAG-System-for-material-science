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
from app.query.planner import QueryPlan, plan_query
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
from app.web_search.open_access import OpenAccessResolver
from app.web_search.resource_links import build_resource_links
from app.web_search.schemas import LiteratureSearchRequest, LiteratureSearchRun


def plan_keywords(plan: QueryPlan, fallback_query: str) -> list[str]:
    aliases = [alias for values in getattr(plan, "entity_aliases", {}).values() for alias in values]
    entity_terms = (
        plan.entities.materials
        + plan.entities.processes
        + plan.entities.equipment
        + plan.entities.properties
        + plan.entities.experts
        + plan.entities.facilities
    )
    return list(dict.fromkeys(entity_terms + aliases + extract_keywords(fallback_query)))


def first_variant(values: list[str], fallback: str) -> str:
    return values[0] if values else fallback


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
    executive_brief = report_builders.build_executive_brief_report(run)
    report_builders.write_text_report(output_dir / "literature_report.md", report)
    report_builders.write_text_report(output_dir / "literature_links_report.md", links_report)
    report_builders.write_text_report(output_dir / "deep_search_report.md", deep_report)
    report_builders.write_text_report(output_dir / "executive_brief.md", executive_brief)
    report_builders.write_json_report(output_dir / "full_run.json", report_builders.build_full_run_payload(run))

    run.output_dir = output_dir
    run.report_markdown = report
    run.links_report_markdown = links_report
    run.deep_report_markdown = deep_report
    run.executive_brief_markdown = executive_brief
    run.full_run_json_path = output_dir / "full_run.json"
    if run.request.generate_pdf_report:
        run.report_pdf_path = report_builders.build_pdf_report(run, output_dir / "literature_report.pdf", mode="full")
        run.links_report_pdf_path = report_builders.build_pdf_report(run, output_dir / "literature_links_report.pdf", mode="links")
        run.deep_report_pdf_path = report_builders.build_pdf_report(run, output_dir / "deep_search_report.pdf", mode="deep")
        run.executive_brief_pdf_path = report_builders.build_pdf_report(run, output_dir / "executive_brief.pdf", mode="brief")
    run.report_docx_path = report_builders.build_docx_report(run, output_dir / "literature_report.docx", mode="full")
    run.links_report_docx_path = report_builders.build_docx_report(run, output_dir / "literature_links_report.docx", mode="links")
    run.deep_report_docx_path = report_builders.build_docx_report(run, output_dir / "deep_search_report.docx", mode="deep")
    run.executive_brief_docx_path = report_builders.build_docx_report(run, output_dir / "executive_brief.docx", mode="brief")
    return run


def publication_records(project_root: Path, include_local_search: bool) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    publications_dir = project_root / "data" / "processed" / "publications"
    local_publications, local_document_summaries, local_procedures = load_local_publication_records(publications_dir)
    if not include_local_search:
        return [], [], []
    return local_publications, local_document_summaries, local_procedures


def enrich_open_access(results: list[Any], warnings: list[str], *, limit: int = 10) -> None:
    resolver = OpenAccessResolver()
    for result in results[:limit]:
        try:
            oa = resolver.resolve(doi=result.doi, title=result.title, year=result.year).as_dict()
        except Exception as exc:
            warnings.append(f"Open access resolver skipped for '{result.title[:80]}': {exc}")
            oa = {
                "title": result.title,
                "doi": result.doi or "",
                "year": str(result.year or ""),
                "open_access": bool(result.open_access_pdf_url),
                "access_status": "open" if result.open_access_pdf_url else "unknown",
                "best_pdf_url": str(result.open_access_pdf_url or ""),
                "landing_page_url": str(result.url or ""),
                "source": result.source,
                "license": "",
                "evidence": ["Resolver failed; using search-result metadata."],
            }
        if not oa.get("best_pdf_url") and result.open_access_pdf_url:
            oa["best_pdf_url"] = str(result.open_access_pdf_url)
            oa["open_access"] = True
            oa["access_status"] = "open"
        if not oa.get("landing_page_url") and result.url:
            oa["landing_page_url"] = str(result.url)
        result.open_access = oa


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
    query_plan = plan_query(request.query)
    keywords = plan_keywords(query_plan, request.query)
    local_query = first_variant(query_plan.internal_search_queries, query_plan.original_query)
    web_query = first_variant(query_plan.web_search_queries, query_plan.original_query)
    web_variants = query_plan.web_search_queries or query_plan.rewritten_queries.web or [web_query]
    output_root = output_root or (project_root / "data" / "processed" / "web_search")
    run_id = safe_run_id(request.run_id or utc_run_id(request.query))
    output_dir = output_root / run_id

    local_publications, local_document_summaries, local_procedures = publication_records(project_root, request.include_local_search)
    local_matches = []
    if request.include_local_search:
        local_matches = search_local_summaries(
            query=local_query,
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
        web_query,
        keywords=keywords,
        sources=request.sources,
        top_k=request.top_k,
        query_variants=web_variants,
        materials_only=request.materials_only,
        relevance_terms=[alias for values in query_plan.entity_aliases.values() for alias in values],
    )
    enrich_open_access(results, warnings, limit=min(request.top_k, 10))
    resource_links = []
    if request.include_recommended_resource_links:
        resource_links = build_resource_links(
            corrected_query=web_query,
            search_queries=web_variants,
            selected_resource_ids=request.recommended_resource_ids or None,
        )

    deep_results = []
    if request.deep_search == "top5":
        llm_client = yandex_client if yandex_client is not None else build_yandex_client_from_env(project_root / "config" / "extraction" / "publication_metadata.json")
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
