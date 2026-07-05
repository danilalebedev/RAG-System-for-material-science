from __future__ import annotations

from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any

from dotenv import load_dotenv

from app.index.embeddings import apply_retrieval_profile, load_retrieval_config
from app.llm.provider_router import ProviderRouter
from app.llm.types import LLMResponse
from app.query.csv_corpus import TableHit
from app.query.literature import run_literature_search
from app.query.local_orchestrator import (
    LocalKnowledgeConfig,
    SummaryHit,
    default_config,
    first_query,
    graph_search,
    keywords_for_plan,
    safe_table_search,
    search_summaries,
)
from app.query.planner import QueryPlan, RouteName, plan_query
from app.query.rewrite import CompletionClient, QueryRewritePlan, rewrite_query
from app.query.simple_corpus import EvidenceChunk, retrieve_chunks
from app.rag.query_signals import clean_search_query
from app.rag.retrieval import RetrievalResult, hybrid_search
from app.settings import PROJECT_ROOT
from app.web_search.schemas import DEFAULT_SEARCH_SOURCES, LiteratureSearchRequest, LiteratureSearchRun, SearchSource


ORCHESTRATION_SYSTEM_PROMPT = """Ты RAG-ассистент для научно-технического корпуса по материаловедению, металлургии и горному делу.
Отвечай только по retrieved evidence. Если данных недостаточно, скажи об этом явно.
Для сравнений методик используй summary/procedure evidence, raw-фрагменты и таблицы. Не выдумывай численные значения, условия, оборудование и ссылки.
Структурируй ответ по-русски: краткий вывод, подтверждающие источники, ограничения и следующие шаги."""

METHOD_COMPARISON_SYSTEM_PROMPT = ORCHESTRATION_SYSTEM_PROMPT + """

Сценарий: сравнение методик и технических решений.
Собери ответ как пользовательский отчет, без служебной диагностики:
1. Краткий вывод: какие 2-4 решения выглядят наиболее перспективными и почему.
2. Сравнение лучших методик: принцип, применимость, условия/параметры, оборудование, плюсы, ограничения.
3. Технико-экономический контекст: реагенты, энергозатраты, CAPEX/OPEX/TCO, производительность, эксплуатационные риски, если такие данные есть в evidence.
4. Что подтверждено источниками и где есть пробелы.

Обязательно ставь ссылки на evidence в формате [raw:1], [summaries:1], [tables:1], [graph:1] или [web:1], используя только citation labels из контекста.
Если таблицы или граф дают только косвенное подтверждение, так и напиши."""

BUSINESS_ANALYSIS_SYSTEM_PROMPT = ORCHESTRATION_SYSTEM_PROMPT + """

Сценарий: бизнес-анализ и технико-экономическое сравнение.
Собери ответ как управленческий отчет, без служебной диагностики:
1. Краткий вывод: какие решения экономически предпочтительны и при каких ограничениях.
2. Таблица сравнения вариантов: технология, применимость, CAPEX/OPEX/TCO или косвенные cost-драйверы, энергопотребление, реагенты, производительность, экологические ограничения, зрелость/риски.
3. Что известно из локальной базы, таблиц и внешней литературы.
4. Какие данные нужно дозапросить для полноценного расчета.

Не выдумывай цены и экономические показатели. Если прямых CAPEX/OPEX нет, оценивай только качественные cost-драйверы, явно помечая их как косвенные.
Обязательно ставь ссылки на evidence в формате [raw:1], [summaries:1], [tables:1], [graph:1] или [web:1], используя только citation labels из контекста."""

INDEXED_SUMMARY_SOURCE_TYPES = {"document_summary", "procedure_summary"}


@dataclass(frozen=True)
class RetrievedContext:
    raw: list[dict[str, Any]] = field(default_factory=list)
    summaries: list[dict[str, Any]] = field(default_factory=list)
    tables: list[dict[str, Any]] = field(default_factory=list)
    graph: list[dict[str, Any]] = field(default_factory=list)
    web: list[dict[str, Any]] = field(default_factory=list)

    def as_dict(self) -> dict[str, list[dict[str, Any]]]:
        return {
            "raw": self.raw,
            "summaries": self.summaries,
            "tables": self.tables,
            "graph": self.graph,
            "web": self.web,
        }


@dataclass(frozen=True)
class QueryOrchestrationResult:
    plan: QueryPlan
    retrieved_context: RetrievedContext
    evidence: list[dict[str, Any]]
    answer_draft: str
    fallbacks: list[dict[str, Any]] = field(default_factory=list)
    local_diagnostics: dict[str, Any] = field(default_factory=dict)
    web_run: LiteratureSearchRun | None = None
    query_rewrite: dict[str, Any] | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "plan": self.plan.model_dump(mode="json"),
            "retrieved_context": self.retrieved_context.as_dict(),
            "evidence": self.evidence,
            "answer_draft": self.answer_draft,
            "fallbacks": self.fallbacks,
            "local_diagnostics": self.local_diagnostics,
            "query_rewrite": self.query_rewrite,
        }


def local_config_for_routes(plan: QueryPlan, *, project_root: Path) -> LocalKnowledgeConfig:
    base = default_config(project_root)
    routes = set(plan.routes)
    use_internal = "internal_rag" in routes
    return LocalKnowledgeConfig(
        project_root=base.project_root,
        chunks_path=base.chunks_path,
        publications_dir=base.publications_dir,
        graph_nodes_path=base.graph_nodes_path,
        graph_edges_path=base.graph_edges_path,
        table_roots=base.table_roots,
        documents_path=base.documents_path,
        tables_path=base.tables_path,
        top_k_raw=base.top_k_raw,
        top_k_summary=base.top_k_summary,
        top_k_tables=base.top_k_tables,
        top_k_graph=base.top_k_graph,
        table_top_rows=base.table_top_rows,
        max_scan_rows=base.max_scan_rows,
        max_table_rows=base.max_table_rows,
        max_context_chars=base.max_context_chars,
        include_raw=use_internal or "raw_rag" in routes,
        include_summaries=use_internal or "summary_rag" in routes,
        include_tables="table_search" in routes,
        include_graph="graph_search" in routes,
    )


def route_unavailable(route: str, reason: str) -> dict[str, Any]:
    return {"route": route, "status": "unavailable", "reason": reason}


def local_diagnostics(config: LocalKnowledgeConfig, plan: QueryPlan) -> dict[str, Any]:
    return {
        "chunks_jsonl_found": bool(config.chunks_path and config.chunks_path.exists()),
        "documents_jsonl_found": bool(config.documents_path and config.documents_path.exists()),
        "tables_jsonl_found": bool(config.tables_path and config.tables_path.exists()),
        "graph_nodes_found": bool(config.graph_nodes_path and config.graph_nodes_path.exists()),
        "graph_edges_found": bool(config.graph_edges_path and config.graph_edges_path.exists()),
        "actual_local_query": (getattr(plan, "internal_search_queries", []) or [plan.original_query])[0],
        "actual_web_query": (getattr(plan, "web_search_queries", []) or [plan.original_query])[0],
        "called_routes": list(plan.routes),
    }


def resolve_config_path(root: Path, value: Any, fallback: Path | None = None) -> Path | None:
    if value in (None, ""):
        return fallback
    path = Path(str(value))
    return path if path.is_absolute() else root / path


def unique_queries(values: list[str], *, limit: int = 12) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for value in values:
        text = " ".join(str(value or "").split())
        key = clean_search_query(text)
        if not text or not key or key in seen:
            continue
        seen.add(key)
        result.append(text)
        if len(result) >= limit:
            break
    return result


def local_variants_from_rewrite(rewrite_plan: QueryRewritePlan, original_query: str) -> list[str]:
    keyword_query = " ".join(rewrite_plan.all_keywords)
    entity_query = " ".join(
        [*rewrite_plan.material_terms, *rewrite_plan.process_terms, *rewrite_plan.property_terms]
    )
    unscoped_search_queries = [
        query
        for query in rewrite_plan.search_queries
        if " OR " not in query and "(" not in query and ")" not in query
    ]
    return unique_queries(
        [
            rewrite_plan.corrected_query,
            *unscoped_search_queries,
            keyword_query,
            entity_query,
            original_query,
        ],
        limit=10,
    )


def merge_queries(primary: list[str], fallback: list[str], *, limit: int = 12) -> list[str]:
    return unique_queries([*primary, *fallback], limit=limit)


def apply_query_rewrite(plan: QueryPlan, rewrite_plan: QueryRewritePlan) -> QueryPlan:
    local_variants = local_variants_from_rewrite(rewrite_plan, plan.original_query)
    web_variants = unique_queries(
        [
            rewrite_plan.corrected_query,
            *rewrite_plan.search_queries,
            *rewrite_plan.keywords_en,
            *rewrite_plan.keywords_ru,
            *plan.web_search_queries,
            *plan.rewritten_queries.web,
        ],
        limit=12,
    )
    rewritten = plan.rewritten_queries.model_copy(
        update={
            "raw_rag": merge_queries(local_variants, plan.rewritten_queries.raw_rag),
            "summary_rag": merge_queries(local_variants, plan.rewritten_queries.summary_rag),
            "graph": merge_queries(local_variants, plan.rewritten_queries.graph),
            "tables": merge_queries(local_variants, plan.rewritten_queries.tables),
            "web": merge_queries(web_variants, plan.rewritten_queries.web, limit=14),
        }
    )
    return plan.model_copy(
        update={
            "rewritten_queries": rewritten,
            "internal_search_queries": merge_queries(local_variants, plan.internal_search_queries, limit=14),
            "web_search_queries": merge_queries(web_variants, plan.web_search_queries, limit=14),
        }
    )


def raw_rows(chunks: list[EvidenceChunk]) -> list[dict[str, Any]]:
    return [
        {
            "id": f"raw:{chunk.rank}",
            "rank": chunk.rank,
            "score": round(chunk.score, 6),
            "doc_id": chunk.doc_id,
            "chunk_id": chunk.chunk_id,
            "source_path": chunk.source_path,
            "local_path": chunk.local_path,
            "preview": chunk.text[:1200],
        }
        for chunk in chunks
    ]


def indexed_raw_rows(results: list[RetrievalResult]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for result in results:
        payload = result.as_dict()
        rows.append(
            {
                "id": payload["candidate_id"],
                "rank": payload["rank"],
                "score": payload["score"],
                "source_type": payload["source_type"],
                "doc_id": payload["doc_id"],
                "chunk_id": payload["chunk_id"],
                "summary_id": payload["summary_id"],
                "source_path": payload["source_path"],
                "local_path": payload["local_path"],
                "preview": payload["text"],
                "score_components": payload["score_components"],
                "why": payload["why"],
            }
        )
    return rows


def split_indexed_summary_rows(rows: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    raw_rows_only: list[dict[str, Any]] = []
    summary_rows_only: list[dict[str, Any]] = []
    for row in rows:
        if row.get("source_type") in INDEXED_SUMMARY_SOURCE_TYPES:
            summary_row = dict(row)
            summary_row.setdefault("kind", row.get("source_type"))
            summary_rows_only.append(summary_row)
        else:
            raw_rows_only.append(row)
    return raw_rows_only, summary_rows_only


def trim_rows_keep_diagnostics(rows: list[dict[str, Any]], *, limit: int) -> list[dict[str, Any]]:
    data_rows = [row for row in rows if row.get("source_type") != "diagnostics"]
    diagnostic_rows = [row for row in rows if row.get("source_type") == "diagnostics"]
    return [*data_rows[:limit], *diagnostic_rows]


def summary_rows(hits: list[SummaryHit]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for hit in hits:
        row = hit.as_dict()
        row.setdefault("id", f"summaries:{hit.rank}")
        row.setdefault("source_type", hit.kind)
        row.setdefault("title", hit.title)
        row.setdefault("preview", hit.preview)
        rows.append(row)
    return rows


def table_rows(hits: list[TableHit]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for hit in hits:
        row = hit.as_dict()
        summary = row.get("summary") if isinstance(row.get("summary"), dict) else {}
        matched_rows = row.get("rows") or []
        preview_parts = [
            summary.get("preview"),
            "; ".join(str(item) for item in matched_rows[:3]),
        ]
        row.setdefault("id", f"tables:{hit.rank}")
        row.setdefault("title", summary.get("source_path") or summary.get("path") or summary.get("table_id") or f"Table {hit.rank}")
        row.setdefault("source_path", summary.get("source_path") or summary.get("path") or "")
        row.setdefault("path", summary.get("path") or "")
        row.setdefault("preview", " ".join(str(part) for part in preview_parts if part)[:1200])
        row.setdefault("source_type", "table")
        rows.append(row)
    return rows


def graph_rows(hits: list[dict[str, Any]], neighbors: list[dict[str, Any]], paths: list[list[dict[str, Any]]]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for hit in hits:
        node = hit.get("node") or {}
        rows.append(
            {
                "id": f"graph:{hit.get('rank')}",
                "kind": "entity",
                "rank": hit.get("rank"),
                "score": hit.get("score"),
                "node_id": node.get("node_id"),
                "type": node.get("type"),
                "label": node.get("label"),
                "matched_terms": hit.get("matched_terms") or [],
            }
        )
    for index, row in enumerate(neighbors[:30], start=1):
        edge = row.get("edge") or {}
        node = row.get("node") or {}
        rows.append(
            {
                "id": f"graph_neighbor:{index}",
                "kind": "neighbor",
                "relation": edge.get("type"),
                "node_id": node.get("node_id"),
                "type": node.get("type"),
                "label": node.get("label"),
                "doc_id": edge.get("doc_id"),
            }
        )
    for index, path in enumerate(paths[:10], start=1):
        rows.append(
            {
                "id": f"graph_path:{index}",
                "kind": "path",
                "path": " -> ".join(str(step.get("node", {}).get("label")) for step in path),
                "types": " -> ".join(str(step.get("node", {}).get("type")) for step in path),
            }
        )
    return rows


def web_rows(run: LiteratureSearchRun | None) -> list[dict[str, Any]]:
    if run is None:
        return []
    rows: list[dict[str, Any]] = []
    for result in run.results:
        rows.append(
            {
                "id": f"web:{result.result_id}",
                "source": result.source,
                "title": result.title,
                "year": result.year,
                "venue": result.venue,
                "doi": result.doi,
                "url": str(result.url) if result.url else "",
                "score": result.score,
                "keyword_hits": result.keyword_hits,
                "preview": result.abstract or result.snippet or "",
            }
        )
    for deep_result in run.deep_results:
        source = deep_result.source_result
        summary = deep_result.document_summary or {}
        if summary:
            rows.append(
                {
                    "id": f"webdocsum:{deep_result.result_id}",
                    "source": "deep_search",
                    "kind": "document_summary",
                    "source_type": "web_document_summary",
                    "title": source.title,
                    "result_id": deep_result.result_id,
                    "doc_id": summary.get("doc_id"),
                    "summary_id": summary.get("document_summary_id") or summary.get("summary_id"),
                    "url": str(source.url) if source.url else "",
                    "doi": source.doi,
                    "score": source.score,
                    "keyword_hits": source.keyword_hits,
                    "preview": summary.get("summary") or summary.get("main_topic") or source.abstract or "",
                    "summary": summary.get("summary") or "",
                    "row": summary,
                }
            )
        for index, procedure in enumerate(deep_result.procedure_summaries, start=1):
            preview = (
                procedure.get("summary")
                or procedure.get("key_points")
                or procedure.get("synthesis_or_process_method")
                or procedure.get("synthesis_method")
                or str(procedure)
            )
            rows.append(
                {
                    "id": f"webproc:{deep_result.result_id}:{index}",
                    "source": "deep_search",
                    "kind": "procedure_summary",
                    "source_type": "web_procedure_summary",
                    "title": source.title,
                    "result_id": deep_result.result_id,
                    "doc_id": procedure.get("doc_id"),
                    "summary_id": procedure.get("procedure_summary_id") or procedure.get("summary_id"),
                    "url": str(source.url) if source.url else "",
                    "doi": source.doi,
                    "score": source.score,
                    "keyword_hits": source.keyword_hits,
                    "preview": str(preview)[:1200],
                    "row": procedure,
                }
            )
    return rows


def add_evidence(evidence: list[dict[str, Any]], route: str, rows: list[dict[str, Any]], *, limit: int = 5) -> None:
    selected = [row for row in rows if row.get("source_type") != "diagnostics"][:limit]
    for row in selected:
        citation = row.get("id") or f"{route}:{len(evidence) + 1}"
        evidence.append(
            {
                "citation": citation,
                "route": route,
                "source_type": row.get("kind") or row.get("source") or route,
                "title": row.get("title") or row.get("label") or row.get("doc_id") or row.get("source_path") or row.get("id"),
                "locator": row.get("url") or row.get("doi") or row.get("source_path") or row.get("path") or row.get("node_id") or "",
                "score": row.get("score"),
                "preview": row.get("preview") or row.get("path") or row.get("relation") or "",
            }
        )


def sources_used(context: RetrievedContext) -> list[str]:
    rows = context.as_dict()
    return [name for name, values in rows.items() if values]


def build_answer_draft(plan: QueryPlan, context: RetrievedContext, evidence: list[dict[str, Any]], fallbacks: list[dict[str, Any]]) -> str:
    used = sources_used(context)
    lines = [
        f"Intent: {plan.intent}.",
        f"Routes used: {', '.join(used) if used else 'none'}.",
    ]
    if evidence:
        lines.append("Top evidence: " + "; ".join(f"[{item['citation']}] {item.get('title')}" for item in evidence[:6]))
    else:
        lines.append("No evidence was retrieved. Check route fallbacks or build the missing indexes/artifacts.")
    if fallbacks:
        lines.append("Fallbacks: " + "; ".join(f"{item['route']}: {item['reason']}" for item in fallbacks))
    return "\n".join(lines)


def has_summary_inputs(config: LocalKnowledgeConfig) -> bool:
    if not config.publications_dir or not config.publications_dir.exists():
        return False
    return any(
        (config.publications_dir / file_name).exists()
        for file_name in ("document_summaries.jsonl", "procedure_summaries.jsonl")
    )


def run_raw_route(
    plan: QueryPlan,
    config: LocalKnowledgeConfig,
    fallbacks: list[dict[str, Any]],
    *,
    retrieval_profile: str | None = None,
) -> list[dict[str, Any]]:
    if not config.chunks_path or not config.chunks_path.exists():
        fallbacks.append(route_unavailable("raw_rag", f"raw chunks file is missing: {config.chunks_path}"))
        return []
    query = first_query(plan, "raw_rag", plan.original_query)
    retrieval_config_path = config.project_root / "config" / "retrieval" / "default.json"
    index_dir = config.project_root / "data" / "indexes" / "chunks"
    lexical_dir = config.project_root / "data" / "indexes" / "lexical"
    retrieval_config: dict[str, Any] | None = None
    if retrieval_config_path.exists():
        try:
            retrieval_config = apply_retrieval_profile(load_retrieval_config(retrieval_config_path), retrieval_profile)
        except Exception as exc:  # noqa: BLE001
            fallbacks.append(route_unavailable("raw_rag_profile", f"retrieval profile unavailable, using scan fallback: {str(exc)[:300]}"))
            retrieval_config = None
    if retrieval_config is not None:
        index_dir = resolve_config_path(config.project_root, retrieval_config.get("chunk_index_dir"), config.project_root / "data" / "indexes" / "chunks") or index_dir
        lexical_dir = resolve_config_path(config.project_root, retrieval_config.get("lexical_index_dir"), config.project_root / "data" / "indexes" / "lexical") or lexical_dir
        chunks_path = resolve_config_path(config.project_root, retrieval_config.get("chunks_path"), config.chunks_path) or config.chunks_path
        publications_dir = resolve_config_path(config.project_root, retrieval_config.get("summary_publications_dir"), config.publications_dir)
        document_summary_index_dir = resolve_config_path(
            config.project_root,
            retrieval_config.get("document_summary_index_dir"),
            config.project_root / "data" / "indexes" / "document_summaries",
        )
        procedure_summary_index_dir = resolve_config_path(
            config.project_root,
            retrieval_config.get("procedure_summary_index_dir"),
            config.project_root / "data" / "indexes" / "procedure_summaries",
        )
        if not index_dir.exists() or not (index_dir / "metadata.jsonl").exists():
            fallbacks.append(
                route_unavailable(
                    "raw_rag_indexed",
                    f"indexed profile '{retrieval_profile or 'default'}' is not ready in {index_dir}; using scan fallback",
                )
            )
        elif lexical_dir.exists():
            try:
                results, diagnostics = hybrid_search(
                    query=query,
                    retrieval_config=retrieval_config,
                    index_dir=index_dir,
                    lexical_dir=lexical_dir,
                    chunks_path=chunks_path or config.chunks_path,
                    top_k=max(config.top_k_raw + config.top_k_summary + 5, 15),
                    mode="hybrid",
                    allow_network=True,
                    root=config.project_root,
                    publications_dir=publications_dir,
                    document_summary_index_dir=document_summary_index_dir,
                    procedure_summary_index_dir=procedure_summary_index_dir,
                    include_summaries=True,
                    include_tables=False,
                    include_graph=False,
                )
                if results:
                    rows = indexed_raw_rows(results)
                    rows.append(
                        {
                            "id": "raw_rag:diagnostics",
                            "rank": None,
                            "score": None,
                            "source_type": "diagnostics",
                            "doc_id": "",
                            "chunk_id": "",
                            "summary_id": "",
                            "source_path": "",
                            "local_path": "",
                            "preview": "",
                            "score_components": {},
                            "why": diagnostics.warnings,
                            "diagnostics": diagnostics.as_dict(),
                        }
                    )
                    return rows
                fallbacks.append(route_unavailable("raw_rag_indexed", "indexed RAG returned no rows; using scan fallback"))
            except Exception as exc:  # noqa: BLE001 - scan fallback keeps GUI usable.
                fallbacks.append(route_unavailable("raw_rag_indexed", f"indexed raw RAG unavailable, using scan fallback: {str(exc)[:300]}"))
    if retrieval_config_path.exists() and lexical_dir.exists() and retrieval_config is None:
        try:
            retrieval_config = load_retrieval_config(retrieval_config_path)
            results, diagnostics = hybrid_search(
                query=query,
                retrieval_config=retrieval_config,
                index_dir=index_dir,
                lexical_dir=lexical_dir,
                chunks_path=config.chunks_path,
                top_k=config.top_k_raw,
                mode="hybrid",
                allow_network=False,
                root=config.project_root,
                publications_dir=config.publications_dir,
                document_summary_index_dir=config.project_root / "data" / "indexes" / "document_summaries",
                procedure_summary_index_dir=config.project_root / "data" / "indexes" / "procedure_summaries",
                include_summaries=False,
                include_tables=False,
                include_graph=False,
            )
            if results:
                rows = indexed_raw_rows(results)
                rows.append(
                    {
                        "id": "raw_rag:diagnostics",
                        "rank": None,
                        "score": None,
                        "source_type": "diagnostics",
                        "doc_id": "",
                        "chunk_id": "",
                        "summary_id": "",
                        "source_path": "",
                        "local_path": "",
                        "preview": "",
                        "score_components": {},
                        "why": diagnostics.warnings,
                        "diagnostics": diagnostics.as_dict(),
                    }
                )
                return rows
        except Exception as exc:  # noqa: BLE001 - scan fallback keeps GUI usable.
            fallbacks.append(route_unavailable("raw_rag_indexed", f"indexed raw RAG unavailable, using scan fallback: {str(exc)[:300]}"))
    return raw_rows(retrieve_chunks(query, config.chunks_path, top_k=config.top_k_raw, max_rows=config.max_scan_rows))


def run_summary_route(plan: QueryPlan, config: LocalKnowledgeConfig, fallbacks: list[dict[str, Any]]) -> list[dict[str, Any]]:
    if not has_summary_inputs(config):
        fallbacks.append(route_unavailable("summary_rag", f"summary inputs are missing: {config.publications_dir}"))
        return []
    query = first_query(plan, "summary_rag", plan.original_query)
    return summary_rows(search_summaries(query, config.publications_dir or Path(), top_k=config.top_k_summary))


def run_table_route(plan: QueryPlan, config: LocalKnowledgeConfig, fallbacks: list[dict[str, Any]]) -> list[dict[str, Any]]:
    if not config.documents_path or not config.tables_path:
        fallbacks.append(route_unavailable("table_search", "table metadata paths are not configured"))
        return []
    query = first_query(plan, "tables", plan.original_query)
    hits, warnings = safe_table_search(query, config)
    fallbacks.extend(route_unavailable("table_search", warning) for warning in warnings)
    return table_rows(hits)


def run_graph_route(plan: QueryPlan, config: LocalKnowledgeConfig, fallbacks: list[dict[str, Any]]) -> list[dict[str, Any]]:
    query = first_query(plan, "graph", plan.original_query)
    hits, neighbors, paths, warnings = graph_search(query, config)
    fallbacks.extend(route_unavailable("graph_search", warning) for warning in warnings)
    return graph_rows(hits, neighbors, paths)


def run_web_route(
    plan: QueryPlan,
    *,
    project_root: Path,
    include_web: bool,
    web_sources: list[SearchSource] | None,
    web_top_k: int,
    web_deep_search: bool,
    web_deep_search_limit: int,
    generate_pdf_report: bool,
    fallbacks: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], LiteratureSearchRun | None]:
    if not include_web:
        fallbacks.append(route_unavailable("web_search", "web route selected by plan, but include_web=False"))
        return [], None
    web_query = (getattr(plan, "web_search_queries", []) or plan.rewritten_queries.web or [plan.original_query])[0]
    request = LiteratureSearchRequest(
        query=web_query,
        top_k=web_top_k,
        sources=web_sources or DEFAULT_SEARCH_SOURCES.copy(),
        deep_search="top5" if web_deep_search else "none",
        deep_search_limit=min(max(web_deep_search_limit, 1), 20),
        include_local_search=False,
        use_query_rewrite=True,
        use_llm_query_rewrite=False,
        generate_pdf_report=generate_pdf_report,
    )
    run = run_literature_search(request, project_root=project_root)
    run.query_plan = plan.model_dump(mode="json")
    return web_rows(run), run


def run_query_orchestration(
    query: str,
    *,
    project_root: Path = PROJECT_ROOT,
    include_web: bool = False,
    web_sources: list[SearchSource] | None = None,
    web_top_k: int = 10,
    web_deep_search: bool = False,
    web_deep_search_limit: int = 5,
    generate_pdf_report: bool = False,
    required_routes: list[RouteName] | None = None,
    retrieval_profile: str | None = None,
    local_top_k: int | None = None,
    use_query_rewrite: bool = True,
    use_llm_query_rewrite: bool = False,
    rewrite_client: CompletionClient | None = None,
) -> QueryOrchestrationResult:
    load_dotenv(project_root / ".env", override=False, encoding="utf-8-sig")
    plan = plan_query(query)
    rewrite_plan: QueryRewritePlan | None = None
    if use_query_rewrite:
        rewrite_plan = rewrite_query(
            query,
            client=rewrite_client,
            materials_only=True,
            use_llm=bool(use_llm_query_rewrite and rewrite_client),
        )
        plan = apply_query_rewrite(plan, rewrite_plan)
    if required_routes:
        routes_in_order: list[RouteName] = []
        for route in [*plan.routes, *required_routes]:
            if route not in routes_in_order:
                routes_in_order.append(route)
        plan = plan.model_copy(update={"routes": routes_in_order})
    if include_web and "web_search" not in plan.routes:
        plan = plan.model_copy(update={"routes": [*plan.routes, "web_search"]})
    config = local_config_for_routes(plan, project_root=project_root)
    if local_top_k is not None:
        bounded_top_k = min(max(int(local_top_k), 1), 100)
        config = replace(
            config,
            top_k_raw=bounded_top_k,
            top_k_summary=bounded_top_k,
            top_k_tables=min(max(4, bounded_top_k // 2), bounded_top_k),
            top_k_graph=min(max(8, bounded_top_k // 2), bounded_top_k),
        )
    routes: set[RouteName] = set(plan.routes)
    use_internal = "internal_rag" in routes
    fallbacks: list[dict[str, Any]] = []
    evidence: list[dict[str, Any]] = []
    web_run: LiteratureSearchRun | None = None

    raw = run_raw_route(plan, config, fallbacks, retrieval_profile=retrieval_profile) if use_internal or "raw_rag" in routes else []
    raw, indexed_summaries = split_indexed_summary_rows(raw)
    raw = trim_rows_keep_diagnostics(raw, limit=config.top_k_raw)
    indexed_summaries = indexed_summaries[: config.top_k_summary]
    summaries = run_summary_route(plan, config, fallbacks) if use_internal or "summary_rag" in routes else []
    if indexed_summaries:
        summaries = [*indexed_summaries, *summaries]
    tables = run_table_route(plan, config, fallbacks) if "table_search" in routes else []
    graph = run_graph_route(plan, config, fallbacks) if "graph_search" in routes else []
    web: list[dict[str, Any]] = []
    if "web_search" in routes:
        web, web_run = run_web_route(
            plan,
            project_root=project_root,
            include_web=include_web,
            web_sources=web_sources,
            web_top_k=web_top_k,
            web_deep_search=web_deep_search,
            web_deep_search_limit=web_deep_search_limit,
            generate_pdf_report=generate_pdf_report,
            fallbacks=fallbacks,
        )

    context = RetrievedContext(raw=raw, summaries=summaries, tables=tables, graph=graph, web=web)
    add_evidence(evidence, "raw", raw)
    add_evidence(evidence, "summaries", summaries)
    add_evidence(evidence, "tables", tables)
    add_evidence(evidence, "graph", graph)
    add_evidence(evidence, "web", web)
    return QueryOrchestrationResult(
        plan=plan,
        retrieved_context=context,
        evidence=evidence,
        answer_draft=build_answer_draft(plan, context, evidence, fallbacks),
        fallbacks=fallbacks,
        local_diagnostics=local_diagnostics(config, plan),
        web_run=web_run,
        query_rewrite=rewrite_plan.model_dump(mode="json") if rewrite_plan else None,
    )


def format_orchestration_context(result: QueryOrchestrationResult, *, max_chars: int = 18_000) -> str:
    payload = result.as_dict()
    context = payload["retrieved_context"]
    sections: list[tuple[str, list[dict[str, Any]]]] = [
        ("RAW", context.get("raw") or []),
        ("SUMMARIES", context.get("summaries") or []),
        ("TABLES", context.get("tables") or []),
        ("GRAPH", context.get("graph") or []),
        ("WEB", context.get("web") or []),
    ]
    parts: list[str] = []
    used = 0
    for section, rows in sections:
        if not rows:
            continue
        lines = [f"## {section}"]
        for index, row in enumerate(rows[:12], start=1):
            if row.get("source_type") == "diagnostics":
                continue
            label = row.get("id") or row.get("citation") or f"{section.lower()}:{index}"
            title = row.get("title") or row.get("label") or row.get("doc_id") or ""
            preview = row.get("preview") or row.get("summary") or row.get("path") or row.get("relation") or ""
            components = row.get("score_components") or {}
            why = row.get("why") or row.get("matched_terms") or []
            locator = row.get("url") or row.get("doi") or row.get("local_path") or row.get("source_path") or row.get("path") or row.get("node_id") or ""
            lines.append(
                f"citation=[{label}] title={title}; score={row.get('score')}; locator={locator}; components={components}; why={why}\n{str(preview)[:1400]}"
            )
        block = "\n".join(lines)
        if used + len(block) + 2 > max_chars:
            break
        parts.append(block)
        used += len(block) + 2
    return "\n\n".join(parts)


def answer_with_provider_router(
    query: str,
    result: QueryOrchestrationResult,
    *,
    project_root: Path = PROJECT_ROOT,
    max_tokens: int = 900,
    temperature: float = 0.2,
    answer_mode: str | None = None,
    extra_context: str | None = None,
) -> LLMResponse:
    router = ProviderRouter.from_env(root=project_root, primary_provider="routerai")
    context = format_orchestration_context(result)
    if extra_context:
        context = f"{context}\n\n## BUSINESS / MARKET DATA\n{extra_context.strip()}"
    if answer_mode == "business":
        system_prompt = BUSINESS_ANALYSIS_SYSTEM_PROMPT
    elif answer_mode in {"methods", "comparison"} or result.plan.answer_format == "comparison_table":
        system_prompt = METHOD_COMPARISON_SYSTEM_PROMPT
    else:
        system_prompt = ORCHESTRATION_SYSTEM_PROMPT
    return router.ask(
        query,
        system_prompt=system_prompt,
        context=context,
        max_tokens=max_tokens,
        temperature=temperature,
    )
