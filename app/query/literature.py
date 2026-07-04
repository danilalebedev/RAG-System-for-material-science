from __future__ import annotations

import hashlib
import json
import os
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from app.io_utils import write_jsonl
from app.llm.provider_router import ProviderRouter
from app.llm.types import LLMResponse
from app.query import reports as report_builders
from app.query.planner import QueryPlan, plan_query
from app.query.rewrite import deterministic_query_rewrite, rewrite_query
from app.settings import PROJECT_ROOT
from app.web_search.clients import LiteratureSearchClient
from app.web_search.comparison import (
    compare_methods,
    load_local_publication_records,
    search_local_summaries,
)
from app.web_search.deep_search import build_router_completion_client_from_env, run_deep_search
from app.web_search.journal_quality import load_quartile_map
from app.web_search.keywords import extract_keywords
from app.web_search.open_access import OpenAccessResolver
from app.web_search.resource_links import build_resource_links
from app.web_search.schemas import LiteratureSearchRequest, LiteratureSearchRun


LITERATURE_SYSTEM_PROMPT = """Ты научно-технический аналитик по материаловедению, металлургии и горному делу.
Отвечай по-русски и только по переданному evidence: найденным публикациям, локальным совпадениям, Deep Search summary и comparison report.
Не выдумывай DOI, ссылки, численные значения, условия и выводы. Если данных недостаточно, явно отдели это от подтвержденных фактов.
Сделай развернутый, но читаемый отчет для бизнес-пользователя.
Структура: 1) Краткий вывод; 2) Основные тренды и методы; 3) Резюме по локальным источникам; 4) Резюме по web-источникам; 5) Что отличается в local vs web; 6) Риски, пробелы и следующие шаги.
В каждом содержательном разделе указывай evidence-ссылки вида [web:1], [web:2], [local:1] рядом с тезисами, если такие источники есть в контексте.
Не используй markdown-таблицы и жирный текст."""

LITERATURE_COMPARISON_PROMPT = """Сравни локальные и внешние данные по литературному поиску.
Ответ нужен для бизнес-пользователя, без сырых JSON и служебной диагностики.
Структура строго из трех разделов: 1) Резюме по локальным источникам; 2) Резюме по web-источникам; 3) Сравнение источников: отличия и пробелы.
Сделай текст подробнее обычного summary: выдели основные тренды, группы методик, типовые установки/оборудование, условия применения, какие материалы подтверждают тезисы, где данные расходятся.
В каждом разделе добавляй evidence-ссылки вида [web:1], [web:2], [local:1], если такие источники есть в контексте.
Внутри разделов пиши короткими абзацами или списком, без markdown-таблиц и без жирного текста.
Не выдумывай факты, диапазоны, DOI и ссылки."""


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


LOW_SIGNAL_RELEVANCE_TERMS = {
    "литературный",
    "обзор",
    "отечественная",
    "мировая",
    "практика",
    "review",
    "literature",
    "domestic",
    "world",
    "practice",
    "цветной",
    "цветная",
    "цветных",
    "метод",
    "методы",
    "методов",
}


def subject_relevance_terms(query_plan: QueryPlan, rewrite_plan: Any) -> list[str]:
    candidates: list[str] = []
    candidates.extend(alias for values in query_plan.entity_aliases.values() for alias in values)
    candidates.extend(getattr(rewrite_plan, "keywords_ru", []) or [])
    candidates.extend(getattr(rewrite_plan, "keywords_en", []) or [])
    candidates.extend(getattr(rewrite_plan, "material_terms", []) or [])
    candidates.extend(getattr(rewrite_plan, "process_terms", []) or [])
    candidates.extend(getattr(rewrite_plan, "property_terms", []) or [])
    result: list[str] = []
    seen: set[str] = set()
    for value in candidates:
        text = compact_context_value(value, 120)
        key = text.casefold().replace("ё", "е")
        if not text or key in seen:
            continue
        key_tokens = [token for token in re.split(r"\W+", key) if token]
        low_signal_phrase = bool(key_tokens) and all(token in LOW_SIGNAL_RELEVANCE_TERMS for token in key_tokens)
        if key in LOW_SIGNAL_RELEVANCE_TERMS or low_signal_phrase:
            continue
        if len(key) < 4:
            continue
        result.append(text)
        seen.add(key)
    return result[:40]


def subject_keywords(values: list[str]) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for value in values:
        text = compact_context_value(value, 120)
        key = text.casefold().replace("ё", "е")
        key_tokens = [token for token in re.split(r"\W+", key) if token]
        low_signal_phrase = bool(key_tokens) and all(token in LOW_SIGNAL_RELEVANCE_TERMS for token in key_tokens)
        if not text or key in seen or key in LOW_SIGNAL_RELEVANCE_TERMS or low_signal_phrase:
            continue
        result.append(text)
        seen.add(key)
    return result


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


def compact_context_value(value: Any, max_chars: int = 900) -> str:
    text = report_builders.compact_text(value, max_chars=max_chars)
    return text.replace("\n", " ").strip()


def result_url(result: Any) -> str:
    if getattr(result, "url", None):
        return str(result.url)
    if getattr(result, "doi", None):
        doi = str(result.doi).removeprefix("https://doi.org/")
        return f"https://doi.org/{doi}"
    return ""


def format_literature_context(run: LiteratureSearchRun, *, max_chars: int = 18_000) -> str:
    plan = run.query_plan or {}
    rewrite = plan.get("llm_rewrite") if isinstance(plan.get("llm_rewrite"), dict) else {}
    parts: list[str] = [
        "# REQUEST",
        f"original_query: {compact_context_value(run.request.query, 500)}",
        f"corrected_query: {compact_context_value(rewrite.get('corrected_query') or plan.get('corrected_query') or '', 500)}",
        f"keywords: {', '.join(run.keywords[:40])}",
        "",
        "# WEB RESULTS",
    ]
    for index, result in enumerate(run.results[:12], start=1):
        parts.append(
            "\n".join(
                [
                    f"[web:{index}] source={result.source}; score={round(float(result.score or 0.0), 4)}; year={result.year}; quartile={getattr(result, 'journal_quartile', '') or result.raw.get('journal_quartile', '')}",
                    f"title: {compact_context_value(result.title, 350)}",
                    f"link: {result_url(result)}",
                    f"doi: {result.doi or ''}",
                    f"keyword_hits: {', '.join(result.keyword_hits[:20])}",
                    f"abstract_or_snippet: {compact_context_value(result.abstract or result.snippet or '', 900)}",
                ]
            )
        )

    if run.local_matches:
        parts.extend(["", "# LOCAL MATCHES"])
        for index, row in enumerate(run.local_matches[:10], start=1):
            parts.append(
                "\n".join(
                    [
                        f"[local:{index}] score={row.get('score')}; doc_id={compact_context_value(row.get('doc_id'), 120)}",
                        f"title: {compact_context_value(row.get('title') or row.get('source_path') or row.get('local_path'), 350)}",
                        f"method: {compact_context_value(row.get('method') or row.get('synthesis_or_process_method'), 250)}",
                        f"material: {compact_context_value(row.get('material') or row.get('material_name'), 250)}",
                        f"evidence: {compact_context_value(row.get('preview') or row.get('summary') or row, 900)}",
                    ]
                )
            )

    if run.deep_results:
        parts.extend(["", "# DEEP SEARCH SUMMARIES"])
        for index, deep_result in enumerate(run.deep_results[:8], start=1):
            source = deep_result.source_result
            summary = deep_result.document_summary or {}
            parts.append(
                "\n".join(
                    [
                        f"[deep:{index}] status={deep_result.status}; llm_used={deep_result.llm_used}; source={source.source}",
                        f"title: {compact_context_value(source.title, 350)}",
                        f"link: {result_url(source)}",
                        f"summary: {compact_context_value(summary.get('summary') or summary.get('main_topic') or '', 1200)}",
                        f"materials: {compact_context_value(summary.get('materials'), 400)}",
                        f"processes: {compact_context_value(summary.get('processes') or summary.get('methods'), 400)}",
                        f"key_findings: {compact_context_value(summary.get('key_findings') or summary.get('analysis_results'), 700)}",
                    ]
                )
            )
            for proc_index, procedure in enumerate(deep_result.procedure_summaries[:3], start=1):
                parts.append(
                    "\n".join(
                        [
                            f"[deep:{index}:procedure:{proc_index}]",
                            f"method: {compact_context_value(procedure.get('synthesis_or_process_method') or procedure.get('method'), 250)}",
                            f"material: {compact_context_value(procedure.get('material_name') or procedure.get('materials'), 250)}",
                            f"conditions: {compact_context_value(procedure.get('conditions'), 700)}",
                            f"equipment: {compact_context_value(procedure.get('equipment'), 350)}",
                            f"outputs: {compact_context_value(procedure.get('outputs') or procedure.get('analysis_results'), 700)}",
                            f"numeric_results: {compact_context_value(procedure.get('numeric_results') or procedure.get('analysis_results'), 700)}",
                        ]
                    )
                )

    if run.comparison is not None:
        comparison = run.comparison
        parts.extend(
            [
                "",
                "# LOCAL VS WEB COMPARISON",
                f"confirmed_methods_count: {len(comparison.confirmed_methods)}",
                f"local_only_methods_count: {len(comparison.local_only_methods)}",
                f"web_only_methods_count: {len(comparison.web_only_methods)}",
                f"differing_conditions_count: {len(comparison.differing_conditions)}",
                f"gaps: {compact_context_value(comparison.gaps, 1000)}",
            ]
        )
        for section_name, rows in (
            ("confirmed", comparison.confirmed_methods),
            ("local_only", comparison.local_only_methods),
            ("web_only", comparison.web_only_methods),
            ("differing_conditions", comparison.differing_conditions),
        ):
            if rows:
                parts.append(f"## {section_name}")
            for row in rows[:5]:
                parts.append(compact_context_value(row, 900))

    text = "\n".join(parts)
    if len(text) <= max_chars:
        return text
    return text[: max_chars - 80].rstrip() + "\n\n[context truncated by max_chars]"


def answer_literature_with_provider_router(
    query: str,
    run: LiteratureSearchRun,
    *,
    project_root: Path = PROJECT_ROOT,
    max_tokens: int = 900,
    temperature: float = 0.2,
) -> LLMResponse:
    router = ProviderRouter.from_env(root=project_root, primary_provider="routerai")
    return router.ask(
        query,
        system_prompt=LITERATURE_SYSTEM_PROMPT,
        context=format_literature_context(run),
        max_tokens=max(max_tokens, 1300),
        temperature=temperature,
    )


def compare_literature_with_provider_router(
    query: str,
    run: LiteratureSearchRun,
    *,
    project_root: Path = PROJECT_ROOT,
    max_tokens: int = 700,
    temperature: float = 0.1,
) -> LLMResponse:
    router = ProviderRouter.from_env(root=project_root, primary_provider="routerai")
    return router.ask(
        f"Сравни локальный и внешний поиск по запросу: {query}",
        system_prompt=LITERATURE_COMPARISON_PROMPT,
        context=format_literature_context(run, max_chars=16_000),
        max_tokens=max(max_tokens, 1400),
        temperature=temperature,
    )


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
    run.report_docx_path = report_builders.build_docx_report(run, output_dir / "literature_report.docx", mode="full")
    run.links_report_docx_path = report_builders.build_docx_report(run, output_dir / "literature_links_report.docx", mode="links")
    run.deep_report_docx_path = report_builders.build_docx_report(run, output_dir / "deep_search_report.docx", mode="deep")
    run.executive_brief_docx_path = report_builders.build_docx_report(run, output_dir / "executive_brief.docx", mode="brief")
    if run.request.generate_pdf_report:
        run.report_pdf_path = report_builders.convert_docx_to_pdf(run.report_docx_path, output_dir / "literature_report.pdf") or report_builders.build_pdf_report(
            run,
            output_dir / "literature_report.pdf",
            mode="full",
        )
        run.links_report_pdf_path = report_builders.convert_docx_to_pdf(
            run.links_report_docx_path,
            output_dir / "literature_links_report.pdf",
        ) or report_builders.build_pdf_report(run, output_dir / "literature_links_report.pdf", mode="links")
        run.deep_report_pdf_path = report_builders.convert_docx_to_pdf(
            run.deep_report_docx_path,
            output_dir / "deep_search_report.pdf",
        ) or report_builders.build_pdf_report(run, output_dir / "deep_search_report.pdf", mode="deep")
        run.executive_brief_pdf_path = report_builders.convert_docx_to_pdf(
            run.executive_brief_docx_path,
            output_dir / "executive_brief.pdf",
        ) or report_builders.build_pdf_report(run, output_dir / "executive_brief.pdf", mode="brief")
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


def llm_completion_client(project_root: Path, yandex_client_arg: Any | None = None) -> Any | None:
    if yandex_client_arg is not None:
        return yandex_client_arg
    return build_router_completion_client_from_env(project_root)


def optional_rewrite_client(project_root: Path, yandex_client_arg: Any | None = None) -> tuple[Any | None, list[str]]:
    if yandex_client_arg is not None:
        return yandex_client_arg, []
    try:
        return build_router_completion_client_from_env(project_root), []
    except Exception as exc:  # noqa: BLE001 - query rewrite must not block metadata search.
        return None, [f"LLM query rewrite unavailable, deterministic domain fallback used: {compact_context_value(exc, 220)}"]


def run_literature_search(
    request: LiteratureSearchRequest,
    *,
    project_root: Path = PROJECT_ROOT,
    client: LiteratureSearchClient | None = None,
    output_root: Path | None = None,
    yandex_client: Any | None = None,
) -> LiteratureSearchRun:
    query_plan = plan_query(request.query)
    rewrite_client = None
    rewrite_warnings: list[str] = []
    if request.use_llm_query_rewrite:
        rewrite_client, rewrite_warnings = optional_rewrite_client(project_root, yandex_client)
    rewrite_plan = (
        rewrite_query(
            request.query,
            client=rewrite_client,
            materials_only=request.materials_only,
            use_llm=bool(rewrite_client and request.use_llm_query_rewrite),
        )
        if request.use_query_rewrite
        else deterministic_query_rewrite(request.query, materials_only=request.materials_only)
    )
    keywords = subject_keywords(
        plan_keywords(query_plan, request.query)
        + rewrite_plan.keywords_ru
        + rewrite_plan.keywords_en
        + rewrite_plan.material_terms
        + rewrite_plan.process_terms
        + rewrite_plan.property_terms
    )
    local_query = first_variant(query_plan.internal_search_queries, query_plan.original_query)
    web_query = rewrite_plan.corrected_query or first_variant(query_plan.web_search_queries, query_plan.original_query)
    web_variants = list(
        dict.fromkeys(
            rewrite_plan.search_queries
            + query_plan.web_search_queries
            + query_plan.rewritten_queries.web
            + [web_query]
        )
    )
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
            top_k=request.local_top_k or request.top_k,
        )

    web_client = client or LiteratureSearchClient(
        semantic_scholar_api_key=os.getenv("SEMANTIC_SCHOLAR_API_KEY"),
        journal_quartile_map=load_quartile_map(project_root / "config" / "web_search" / "journal_quartiles.json"),
    )
    relevance_terms = subject_relevance_terms(query_plan, rewrite_plan)
    results, warnings = web_client.search(
        web_query,
        keywords=keywords,
        sources=request.sources,
        top_k=request.web_top_k or request.top_k,
        query_variants=web_variants,
        materials_only=request.materials_only,
        relevance_terms=relevance_terms,
    )
    warnings = [*rewrite_warnings, *rewrite_plan.notes, *warnings]
    enrich_open_access(results, warnings, limit=min(request.web_top_k or request.top_k, 10))
    resource_links = []
    if request.include_recommended_resource_links:
        resource_links = build_resource_links(
            corrected_query=web_query,
            search_queries=web_variants,
            selected_resource_ids=request.recommended_resource_ids or None,
        )

    deep_results = []
    if request.deep_search == "top5":
        llm_client = llm_completion_client(project_root, yandex_client)
        deep_results = run_deep_search(
            results=results,
            output_dir=output_dir,
            mode=request.deep_search,
            client=llm_client,
            fetch_excerpts=request.fetch_excerpts,
            limit=request.deep_search_limit,
            max_total_seconds=request.deep_search_max_seconds,
        )

    comparison = compare_methods(
        query=request.query,
        local_publications=local_publications,
        local_document_summaries=local_document_summaries,
        local_procedures=local_procedures,
        web_deep_results=deep_results,
    )
    run = LiteratureSearchRun(
        request=request,
        query_plan={
            **query_plan.model_dump(mode="json"),
            "original_user_query": request.query,
            "llm_rewrite": rewrite_plan.model_dump(mode="json"),
            "subject_relevance_terms": relevance_terms,
        },
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
    deep_search_max_seconds: int | None = None,
    fetch_excerpts: bool | None = None,
    yandex_client: Any | None = None,
) -> LiteratureSearchRun:
    request = run.request.model_copy(
        update={
            "deep_search": "top5",
            "deep_search_limit": deep_search_limit or run.request.deep_search_limit,
            "deep_search_max_seconds": deep_search_max_seconds or run.request.deep_search_max_seconds,
            "fetch_excerpts": run.request.fetch_excerpts if fetch_excerpts is None else fetch_excerpts,
        }
    )
    output_dir = run.output_dir or (project_root / "data" / "processed" / "web_search" / safe_run_id(request.run_id or utc_run_id(request.query)))
    local_publications, local_document_summaries, local_procedures = publication_records(project_root, request.include_local_search)
    deep_results = run_deep_search(
        results=run.results,
        output_dir=output_dir,
        mode="top5",
        client=yandex_client if yandex_client is not None else build_router_completion_client_from_env(project_root),
        fetch_excerpts=request.fetch_excerpts,
        limit=request.deep_search_limit,
        max_total_seconds=request.deep_search_max_seconds,
    )
    comparison = compare_methods(
        query=request.query,
        local_publications=local_publications,
        local_document_summaries=local_document_summaries,
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
