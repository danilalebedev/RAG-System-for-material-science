from __future__ import annotations

import json
import re
import unicodedata
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable, Iterator

from app.graph.search import load_graph, neighbors, paths_to_types, search_entities
from app.query.csv_corpus import TableHit, format_table_context, search_tables
from app.query.planner import QueryPlan, plan_query
from app.query.simple_corpus import EvidenceChunk, format_evidence_context, retrieve_chunks
from app.settings import PROJECT_ROOT
from app.web_search.keywords import extract_keywords


TOKEN_RE = re.compile(r"[\w.+#%-]+", re.UNICODE)
SUMMARY_TEXT_FIELDS = (
    "title",
    "summary",
    "main_topic",
    "key_findings",
    "main_conclusions",
    "materials",
    "material_name",
    "input_materials",
    "reagents",
    "outputs",
    "processes",
    "synthesis_or_process_method",
    "synthesis_method",
    "equipment",
    "equipment_details",
    "properties",
    "observed_effects",
    "numerical_results",
    "analysis_results",
    "limitations_or_gaps",
    "additional_domain_fields",
)


@dataclass(frozen=True)
class SummaryHit:
    rank: int
    score: float
    kind: str
    doc_id: str
    publication_id: str
    summary_id: str
    title: str
    preview: str
    matched_terms: tuple[str, ...] = ()
    row: dict[str, Any] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        return {
            "rank": self.rank,
            "score": round(self.score, 6),
            "kind": self.kind,
            "doc_id": self.doc_id,
            "publication_id": self.publication_id,
            "summary_id": self.summary_id,
            "title": self.title,
            "preview": self.preview,
            "matched_terms": list(self.matched_terms),
            "row": self.row,
        }


@dataclass(frozen=True)
class LocalKnowledgeConfig:
    project_root: Path = PROJECT_ROOT
    chunks_path: Path | None = None
    publications_dir: Path | None = None
    graph_nodes_path: Path | None = None
    graph_edges_path: Path | None = None
    table_roots: tuple[Path, ...] = ()
    documents_path: Path | None = None
    tables_path: Path | None = None
    top_k_raw: int = 5
    top_k_summary: int = 5
    top_k_tables: int = 4
    top_k_graph: int = 8
    table_top_rows: int = 3
    max_scan_rows: int = 20_000
    max_table_rows: int = 500
    max_context_chars: int = 16_000
    include_raw: bool = True
    include_summaries: bool = True
    include_tables: bool = True
    include_graph: bool = True


@dataclass(frozen=True)
class LocalKnowledgeBundle:
    query: str
    query_plan: dict[str, Any]
    keywords: list[str]
    raw_chunks: list[EvidenceChunk]
    summary_hits: list[SummaryHit]
    table_hits: list[TableHit]
    graph_hits: list[dict[str, Any]]
    graph_neighbors: list[dict[str, Any]]
    graph_paths: list[list[dict[str, Any]]]
    context: str
    brief: str
    warnings: list[str] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return {
            "query": self.query,
            "query_plan": self.query_plan,
            "keywords": self.keywords,
            "raw_chunks": [
                {
                    "rank": item.rank,
                    "score": item.score,
                    "chunk_id": item.chunk_id,
                    "doc_id": item.doc_id,
                    "source_path": item.source_path,
                    "local_path": item.local_path,
                    "text": item.text,
                }
                for item in self.raw_chunks
            ],
            "summary_hits": [item.as_dict() for item in self.summary_hits],
            "table_hits": [item.as_dict() for item in self.table_hits],
            "graph_hits": self.graph_hits,
            "graph_neighbors": self.graph_neighbors,
            "graph_paths": self.graph_paths,
            "context": self.context,
            "brief": self.brief,
            "warnings": self.warnings,
        }


def default_config(project_root: Path = PROJECT_ROOT) -> LocalKnowledgeConfig:
    return LocalKnowledgeConfig(
        project_root=project_root,
        chunks_path=project_root / "data" / "parsed" / "chunks.jsonl",
        publications_dir=project_root / "data" / "processed" / "publications",
        graph_nodes_path=project_root / "data" / "index" / "knowledge_graph_nodes.jsonl",
        graph_edges_path=project_root / "data" / "index" / "knowledge_graph_edges.jsonl",
        table_roots=(project_root / "data" / "parsed" / "spreadsheets_csv",),
        documents_path=project_root / "data" / "parsed" / "documents.jsonl",
        tables_path=project_root / "data" / "parsed" / "tables.jsonl",
    )


def iter_jsonl(path: Path) -> Iterator[dict[str, Any]]:
    if not path.exists():
        return
    with path.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                yield json.loads(line)


def normalize_text(value: Any) -> str:
    text = unicodedata.normalize("NFKC", str(value or "")).casefold()
    return re.sub(r"\s+", " ", text).strip()


def compact_text(value: Any, max_chars: int | None = None) -> str:
    if isinstance(value, (dict, list)):
        text = json.dumps(value, ensure_ascii=False, default=str)
    else:
        text = str(value or "")
    text = re.sub(r"\s+", " ", text).strip()
    if max_chars is not None and len(text) > max_chars:
        return text[: max_chars - 3].rstrip() + "..."
    return text


def query_terms(query: str, *, max_terms: int = 48) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for token in TOKEN_RE.findall(normalize_text(query)):
        token = token.strip(".+#%-_")
        if len(token) < 2 or token in seen:
            continue
        seen.add(token)
        result.append(token)
        if len(result) >= max_terms:
            break
    return result


def flatten_text(value: Any) -> Iterator[str]:
    if value in (None, "", [], {}):
        return
    if isinstance(value, dict):
        for item in value.values():
            yield from flatten_text(item)
        return
    if isinstance(value, list):
        for item in value:
            yield from flatten_text(item)
        return
    yield str(value)


def row_search_text(row: dict[str, Any]) -> str:
    values: list[str] = []
    for field_name in SUMMARY_TEXT_FIELDS:
        values.extend(flatten_text(row.get(field_name)))
    if not values:
        values.extend(flatten_text(row))
    return " ".join(values)


def score_text(text: str, terms: Iterable[str]) -> tuple[float, tuple[str, ...]]:
    terms_tuple = tuple(terms)
    normalized = normalize_text(text)
    matched = tuple(term for term in terms_tuple if term in normalized)
    if not matched:
        return 0.0, ()
    coverage = len(matched) / max(len(terms_tuple), 1)
    density = sum(normalized.count(term) for term in matched) / max(len(TOKEN_RE.findall(normalized)), 1)
    return coverage * 10.0 + min(density, 1.0), matched


def summary_id(row: dict[str, Any], kind: str) -> str:
    return str(
        row.get("document_summary_id")
        or row.get("procedure_summary_id")
        or row.get("summary_id")
        or row.get("id")
        or f"{kind}:{row.get('doc_id') or ''}"
    )


def summary_preview(row: dict[str, Any]) -> str:
    return compact_text(
        row.get("summary")
        or row.get("main_topic")
        or row.get("synthesis_or_process_method")
        or row.get("synthesis_method")
        or row.get("key_findings")
        or row.get("observed_effects")
        or row_search_text(row),
        900,
    )


def search_summaries(
    query: str,
    publications_dir: Path,
    *,
    top_k: int = 5,
) -> list[SummaryHit]:
    terms = query_terms(query)
    candidates: list[SummaryHit] = []
    inputs = (
        ("document_summary", publications_dir / "document_summaries.jsonl"),
        ("procedure_summary", publications_dir / "procedure_summaries.jsonl"),
    )
    for kind, path in inputs:
        for row in iter_jsonl(path):
            score, matched = score_text(row_search_text(row), terms)
            if score <= 0:
                continue
            candidates.append(
                SummaryHit(
                    rank=0,
                    score=score,
                    kind=kind,
                    doc_id=str(row.get("doc_id") or ""),
                    publication_id=str(row.get("publication_id") or ""),
                    summary_id=summary_id(row, kind),
                    title=compact_text(row.get("title") or row.get("source_path") or row.get("doc_id"), 220),
                    preview=summary_preview(row),
                    matched_terms=matched,
                    row=row,
                )
            )
    candidates.sort(key=lambda item: item.score, reverse=True)
    return [
        SummaryHit(
            rank=rank,
            score=item.score,
            kind=item.kind,
            doc_id=item.doc_id,
            publication_id=item.publication_id,
            summary_id=item.summary_id,
            title=item.title,
            preview=item.preview,
            matched_terms=item.matched_terms,
            row=item.row,
        )
        for rank, item in enumerate(candidates[:top_k], start=1)
    ]


def graph_search(query: str, config: LocalKnowledgeConfig) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[list[dict[str, Any]]], list[str]]:
    warnings: list[str] = []
    if not config.graph_nodes_path or not config.graph_edges_path:
        return [], [], [], warnings
    if not config.graph_nodes_path.exists() or not config.graph_edges_path.exists():
        warnings.append("Knowledge graph artifacts are missing. Build them with scripts/build_knowledge_graph.py.")
        return [], [], [], warnings
    nodes, edges = load_graph(config.graph_nodes_path, config.graph_edges_path)
    hits = search_entities(nodes, query, top_k=config.top_k_graph)
    selected_id = hits[0].node.get("node_id") if hits else None
    neighbor_rows = neighbors(nodes, edges, str(selected_id), limit=60) if selected_id else []
    path_rows = paths_to_types(nodes, edges, str(selected_id), limit=20) if selected_id else []
    return [hit.as_dict() for hit in hits], neighbor_rows, path_rows, warnings


def safe_table_search(query: str, config: LocalKnowledgeConfig) -> tuple[list[TableHit], list[str]]:
    warnings: list[str] = []
    if not config.documents_path or not config.tables_path:
        return [], warnings
    try:
        hits = search_tables(
            query,
            roots=config.table_roots,
            documents_path=config.documents_path,
            tables_path=config.tables_path,
            project_root=config.project_root,
            top_k=config.top_k_tables,
            top_rows=config.table_top_rows,
            max_rows_per_table=config.max_table_rows,
        )
    except Exception as exc:  # noqa: BLE001 - local orchestrator must degrade gracefully in GUI.
        warnings.append(f"Table search failed: {compact_text(exc, 300)}")
        return [], warnings
    return hits, warnings


def format_summary_context(hits: list[SummaryHit], *, max_chars: int = 8_000) -> str:
    parts: list[str] = []
    used = 0
    for hit in hits:
        block = (
            f"[S{hit.rank}] kind={hit.kind}; doc_id={hit.doc_id}; "
            f"summary_id={hit.summary_id}; score={hit.score:.3f}\n"
            f"{hit.preview}"
        )
        if used + len(block) + 2 > max_chars:
            break
        parts.append(block)
        used += len(block) + 2
    return "\n\n".join(parts)


def format_graph_context(
    hits: list[dict[str, Any]],
    neighbor_rows: list[dict[str, Any]],
    path_rows: list[list[dict[str, Any]]],
    *,
    max_chars: int = 5_000,
) -> str:
    parts: list[str] = []
    for hit in hits[:8]:
        node = hit.get("node") or {}
        parts.append(
            f"[G{hit.get('rank')}] type={node.get('type')}; node_id={node.get('node_id')}; "
            f"score={hit.get('score')}\n{node.get('label')}"
        )
    for index, row in enumerate(neighbor_rows[:12], start=1):
        edge = row.get("edge") or {}
        node = row.get("node") or {}
        parts.append(f"[GN{index}] {edge.get('type')} -> {node.get('type')} {node.get('label')}")
    for index, path in enumerate(path_rows[:8], start=1):
        label_path = " -> ".join(str(step.get("node", {}).get("label")) for step in path)
        type_path = " -> ".join(str(step.get("node", {}).get("type")) for step in path)
        parts.append(f"[GP{index}] {type_path}: {label_path}")
    text = "\n".join(parts)
    return text[:max_chars]


def build_local_context(
    raw_chunks: list[EvidenceChunk],
    summary_hits: list[SummaryHit],
    table_hits: list[TableHit],
    graph_hits: list[dict[str, Any]],
    graph_neighbor_rows: list[dict[str, Any]],
    graph_path_rows: list[list[dict[str, Any]]],
    *,
    max_chars: int,
) -> str:
    blocks = [
        ("RAW RAG", format_evidence_context(raw_chunks, max_chars=max_chars // 3)),
        ("SUMMARY RAG", format_summary_context(summary_hits, max_chars=max_chars // 3)),
        ("TABLES", format_table_context(table_hits, max_chars=max_chars // 4)),
        ("KNOWLEDGE GRAPH", format_graph_context(graph_hits, graph_neighbor_rows, graph_path_rows, max_chars=max_chars // 4)),
    ]
    context_parts: list[str] = []
    used = 0
    for title, text in blocks:
        if not text:
            continue
        block = f"## {title}\n{text}"
        if used + len(block) + 2 > max_chars:
            break
        context_parts.append(block)
        used += len(block) + 2
    return "\n\n".join(context_parts)


def build_brief(
    query: str,
    plan: QueryPlan,
    raw_chunks: list[EvidenceChunk],
    summary_hits: list[SummaryHit],
    table_hits: list[TableHit],
    graph_hits: list[dict[str, Any]],
    warnings: list[str],
) -> str:
    lines = [
        "# Local Knowledge Brief",
        "",
        f"Query: {query}",
        f"Intent: {plan.intent}",
        f"Routes: {', '.join(plan.routes) if plan.routes else 'n/a'}",
        f"Retrieval streams: raw={len(raw_chunks)}, summary={len(summary_hits)}, tables={len(table_hits)}, graph={len(graph_hits)}",
        "",
        "## Best evidence",
    ]
    if summary_hits:
        lines.append(f"- Summary: [S{summary_hits[0].rank}] {summary_hits[0].preview}")
    if raw_chunks:
        lines.append(f"- Raw chunk: [{raw_chunks[0].rank}] doc_id={raw_chunks[0].doc_id}; source={raw_chunks[0].source_path}")
    if table_hits:
        summary = table_hits[0].summary
        lines.append(f"- Table: [T{table_hits[0].rank}] {summary.source}; doc_id={summary.doc_id}; path={summary.path}")
    if graph_hits:
        node = graph_hits[0].get("node") or {}
        lines.append(f"- Graph: [G{graph_hits[0].get('rank')}] {node.get('type')} {node.get('label')}")
    lines.extend(
        [
            "",
            "## Suggested answer strategy",
            "- Use summary evidence for high-level procedure matching.",
            "- Use raw chunks for exact citations and source grounding.",
            "- Use tables for numeric values, compositions, regimes, and row-level facts.",
            "- Use graph hits to explain entity relations and gaps.",
        ]
    )
    if warnings:
        lines.extend(["", "## Warnings"])
        lines.extend(f"- {warning}" for warning in warnings)
    return "\n".join(lines).strip() + "\n"


def first_query(plan: QueryPlan, route: str, fallback: str) -> str:
    queries = getattr(plan.rewritten_queries, route, []) or []
    return queries[0] if queries else fallback


def keywords_for_plan(plan: QueryPlan) -> list[str]:
    entity_terms = (
        plan.entities.materials
        + plan.entities.processes
        + plan.entities.equipment
        + plan.entities.properties
        + plan.entities.experts
        + plan.entities.facilities
    )
    return list(dict.fromkeys(entity_terms + extract_keywords(plan.original_query)))


def run_local_knowledge(
    query: str,
    *,
    config: LocalKnowledgeConfig | None = None,
    use_query_rewrite: bool = True,
) -> LocalKnowledgeBundle:
    config = config or default_config()
    plan = plan_query(query)
    warnings: list[str] = []

    raw_chunks: list[EvidenceChunk] = []
    if config.include_raw and config.chunks_path:
        if config.chunks_path.exists():
            raw_query = first_query(plan, "raw_rag", plan.original_query)
            raw_chunks = retrieve_chunks(raw_query, config.chunks_path, top_k=config.top_k_raw, max_rows=config.max_scan_rows)
        else:
            warnings.append(f"Raw chunks file is missing: {config.chunks_path}")

    summary_hits: list[SummaryHit] = []
    if config.include_summaries and config.publications_dir:
        if config.publications_dir.exists():
            summary_query = first_query(plan, "summary_rag", plan.original_query)
            summary_hits = search_summaries(summary_query, config.publications_dir, top_k=config.top_k_summary)
        else:
            warnings.append(f"Publication summaries directory is missing: {config.publications_dir}")

    table_hits: list[TableHit] = []
    if config.include_tables:
        table_query = first_query(plan, "tables", plan.original_query)
        table_hits, table_warnings = safe_table_search(table_query, config)
        warnings.extend(table_warnings)

    graph_hits: list[dict[str, Any]] = []
    graph_neighbor_rows: list[dict[str, Any]] = []
    graph_path_rows: list[list[dict[str, Any]]] = []
    if config.include_graph:
        graph_query = first_query(plan, "graph", plan.original_query)
        graph_hits, graph_neighbor_rows, graph_path_rows, graph_warnings = graph_search(graph_query, config)
        warnings.extend(graph_warnings)

    context = build_local_context(
        raw_chunks,
        summary_hits,
        table_hits,
        graph_hits,
        graph_neighbor_rows,
        graph_path_rows,
        max_chars=config.max_context_chars,
    )
    brief = build_brief(query, plan, raw_chunks, summary_hits, table_hits, graph_hits, warnings)
    return LocalKnowledgeBundle(
        query=query,
        query_plan=plan.model_dump(mode="json"),
        keywords=keywords_for_plan(plan),
        raw_chunks=raw_chunks,
        summary_hits=summary_hits,
        table_hits=table_hits,
        graph_hits=graph_hits,
        graph_neighbors=graph_neighbor_rows,
        graph_paths=graph_path_rows,
        context=context,
        brief=brief,
        warnings=warnings,
    )
