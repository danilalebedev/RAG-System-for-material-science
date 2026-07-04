from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

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
from app.query.simple_corpus import EvidenceChunk, retrieve_chunks
from app.settings import PROJECT_ROOT
from app.web_search.schemas import DEFAULT_SEARCH_SOURCES, LiteratureSearchRequest, LiteratureSearchRun, SearchSource


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
    web_run: LiteratureSearchRun | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "plan": self.plan.model_dump(mode="json"),
            "retrieved_context": self.retrieved_context.as_dict(),
            "evidence": self.evidence,
            "answer_draft": self.answer_draft,
            "fallbacks": self.fallbacks,
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


def summary_rows(hits: list[SummaryHit]) -> list[dict[str, Any]]:
    return [hit.as_dict() for hit in hits]


def table_rows(hits: list[TableHit]) -> list[dict[str, Any]]:
    return [hit.as_dict() for hit in hits]


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
    return rows


def add_evidence(evidence: list[dict[str, Any]], route: str, rows: list[dict[str, Any]], *, limit: int = 5) -> None:
    for row in rows[:limit]:
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


def run_raw_route(plan: QueryPlan, config: LocalKnowledgeConfig, fallbacks: list[dict[str, Any]]) -> list[dict[str, Any]]:
    if not config.chunks_path or not config.chunks_path.exists():
        fallbacks.append(route_unavailable("raw_rag", f"raw chunks file is missing: {config.chunks_path}"))
        return []
    query = first_query(plan, "raw_rag", plan.original_query)
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
    generate_pdf_report: bool,
    fallbacks: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], LiteratureSearchRun | None]:
    if not include_web:
        fallbacks.append(route_unavailable("web_search", "web route selected by plan, but include_web=False"))
        return [], None
    web_query = (plan.rewritten_queries.web or [plan.original_query])[0]
    request = LiteratureSearchRequest(
        query=web_query,
        top_k=web_top_k,
        sources=web_sources or DEFAULT_SEARCH_SOURCES.copy(),
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
    generate_pdf_report: bool = False,
    required_routes: list[RouteName] | None = None,
) -> QueryOrchestrationResult:
    plan = plan_query(query)
    if required_routes:
        routes_in_order: list[RouteName] = []
        for route in [*plan.routes, *required_routes]:
            if route not in routes_in_order:
                routes_in_order.append(route)
        plan = plan.model_copy(update={"routes": routes_in_order})
    config = local_config_for_routes(plan, project_root=project_root)
    routes: set[RouteName] = set(plan.routes)
    use_internal = "internal_rag" in routes
    fallbacks: list[dict[str, Any]] = []
    evidence: list[dict[str, Any]] = []
    web_run: LiteratureSearchRun | None = None

    raw = run_raw_route(plan, config, fallbacks) if use_internal or "raw_rag" in routes else []
    summaries = run_summary_route(plan, config, fallbacks) if use_internal or "summary_rag" in routes else []
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
        web_run=web_run,
    )
