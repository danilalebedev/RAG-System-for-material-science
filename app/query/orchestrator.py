from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from app.query.literature import run_literature_search
from app.query.local_orchestrator import LocalKnowledgeBundle, LocalKnowledgeConfig, default_config, run_local_knowledge
from app.query.planner import QueryPlan, plan_query
from app.settings import PROJECT_ROOT
from app.web_search.schemas import DEFAULT_SEARCH_SOURCES, LiteratureSearchRequest, LiteratureSearchRun, SearchSource


@dataclass(frozen=True)
class QueryOrchestrationResult:
    query_plan: QueryPlan
    local_knowledge: LocalKnowledgeBundle | None = None
    web_run: LiteratureSearchRun | None = None
    warnings: tuple[str, ...] = ()

    def as_dict(self) -> dict[str, Any]:
        return {
            "query_plan": self.query_plan.model_dump(mode="json"),
            "local_knowledge": self.local_knowledge.as_dict() if self.local_knowledge else None,
            "web_run": self.web_run.model_dump(mode="json") if self.web_run else None,
            "warnings": list(self.warnings),
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


def run_query_orchestration(
    query: str,
    *,
    project_root: Path = PROJECT_ROOT,
    include_local: bool = True,
    include_web: bool = False,
    web_sources: list[SearchSource] | None = None,
    web_top_k: int = 10,
    generate_pdf_report: bool = False,
) -> QueryOrchestrationResult:
    plan = plan_query(query)
    warnings: list[str] = []
    local_bundle: LocalKnowledgeBundle | None = None
    web_run: LiteratureSearchRun | None = None

    if include_local:
        local_bundle = run_local_knowledge(query, config=local_config_for_routes(plan, project_root=project_root))
        warnings.extend(local_bundle.warnings)

    if include_web and "web_search" in plan.routes:
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
        web_run = run_literature_search(request, project_root=project_root)
        web_run.query_plan = plan.model_dump(mode="json")

    return QueryOrchestrationResult(
        query_plan=plan,
        local_knowledge=local_bundle,
        web_run=web_run,
        warnings=tuple(dict.fromkeys(warnings)),
    )
