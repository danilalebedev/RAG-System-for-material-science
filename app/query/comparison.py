from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable

from app.query.orchestrator import QueryOrchestrationResult, run_query_orchestration
from app.query.planner import RouteName
from app.settings import PROJECT_ROOT
from app.web_search.schemas import SearchSource


NUMERIC_VALUE_RE = re.compile(
    r"(?<!\w)\d+(?:[.,]\d+)?\s*(?:°?\s*c|k|mpa|g/l|mol/l|%|wt\.?%|h|min|mm|um|µm|мпа|г/л|моль/л|мас\.?%|ч|мин|мм|мкм)?(?=$|\s|[.,;:)])",
    re.IGNORECASE,
)

METHOD_HINTS = (
    "leaching",
    "flotation",
    "smelting",
    "roasting",
    "pyrolysis",
    "hydrometallurgy",
    "pyrometallurgy",
    "bioleaching",
    "extraction",
    "precipitation",
    "сорбция",
    "выщелачивание",
    "флотация",
    "плавка",
    "обжиг",
    "пиролиз",
    "гидрометаллургия",
    "пирометаллургия",
    "биовыщелачивание",
    "экстракция",
    "осаждение",
)

MATERIAL_HINTS = (
    "nickel",
    "cobalt",
    "lithium",
    "copper",
    "manganese",
    "so2",
    "sulfur",
    "ни",
    "co",
    "ni",
    "никель",
    "кобальт",
    "литий",
    "медь",
    "марганец",
    "диоксид серы",
    "сернистый газ",
)

PROCESS_FIELDS = (
    "processes",
    "process",
    "synthesis_or_process_method",
    "synthesis_method",
    "method",
    "procedure",
    "technology",
)
MATERIAL_FIELDS = ("materials", "material_name", "input_materials", "reagents", "outputs")
CONDITION_FIELDS = ("conditions", "operating_conditions", "experimental_conditions", "process_parameters", "equipment_details")
PROPERTY_FIELDS = ("properties", "observed_effects", "analysis_results")
NUMERIC_FIELDS = ("numerical_results", "numeric_values", "analysis_results", "results", "composition")
ADVANTAGE_FIELDS = ("advantages", "key_findings", "main_conclusions")
LIMITATION_FIELDS = ("limitations", "limitations_or_gaps", "gaps")


@dataclass(frozen=True)
class ComparisonRow:
    item: str
    description: str = ""
    materials: list[str] = field(default_factory=list)
    processes: list[str] = field(default_factory=list)
    conditions: list[str] = field(default_factory=list)
    properties: list[str] = field(default_factory=list)
    numeric_values: list[str] = field(default_factory=list)
    advantages: list[str] = field(default_factory=list)
    limitations: list[str] = field(default_factory=list)
    evidence: list[dict[str, Any]] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return {
            "item": self.item,
            "description": self.description,
            "materials": self.materials,
            "processes": self.processes,
            "conditions": self.conditions,
            "properties": self.properties,
            "numeric_values": self.numeric_values,
            "advantages": self.advantages,
            "limitations": self.limitations,
            "evidence": self.evidence,
        }


@dataclass(frozen=True)
class ComparisonResult:
    query: str
    compared_items: list[str]
    comparison_dimensions: list[str]
    rows: list[ComparisonRow]
    missing_evidence: list[dict[str, Any]]
    answer_summary: str
    plan: dict[str, Any]
    retrieved_context: dict[str, list[dict[str, Any]]]
    evidence: list[dict[str, Any]]
    fallbacks: list[dict[str, Any]] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return {
            "query": self.query,
            "compared_items": self.compared_items,
            "comparison_dimensions": self.comparison_dimensions,
            "rows": [row.as_dict() for row in self.rows],
            "missing_evidence": self.missing_evidence,
            "answer_summary": self.answer_summary,
            "plan": self.plan,
            "retrieved_context": self.retrieved_context,
            "evidence": self.evidence,
            "fallbacks": self.fallbacks,
        }


def _flatten(value: Any) -> Iterable[str]:
    if value in (None, "", [], {}):
        return
    if isinstance(value, dict):
        for nested in value.values():
            yield from _flatten(nested)
        return
    if isinstance(value, (list, tuple, set)):
        for nested in value:
            yield from _flatten(nested)
        return
    yield str(value)


def _compact(value: Any, max_chars: int = 260) -> str:
    text = " ".join(str(value or "").split())
    if len(text) > max_chars:
        return text[: max_chars - 3].rstrip() + "..."
    return text


def _unique(values: Iterable[Any], *, limit: int = 8, max_chars: int = 220) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for value in values:
        text = _compact(value, max_chars=max_chars)
        key = text.casefold()
        if not text or key in seen:
            continue
        seen.add(key)
        result.append(text)
        if len(result) >= limit:
            break
    return result


def _values(row: dict[str, Any], fields: tuple[str, ...], *, limit: int = 8) -> list[str]:
    values: list[str] = []
    for field_name in fields:
        values.extend(_flatten(row.get(field_name)))
    return _unique(values, limit=limit)


def _row_payload(summary_row: dict[str, Any]) -> dict[str, Any]:
    nested = summary_row.get("row")
    return nested if isinstance(nested, dict) and nested else summary_row


def _description_from(row: dict[str, Any]) -> str:
    for field_name in ("summary", "preview", "key_findings", "main_conclusions", "title"):
        value = row.get(field_name)
        if value:
            return _compact(value, 420)
    return ""


def _item_from(row: dict[str, Any], index: int) -> str:
    candidates = []
    for field_name in PROCESS_FIELDS:
        candidates.extend(_flatten(row.get(field_name)))
    if not candidates:
        text = " ".join(_flatten(row))
        lowered = text.casefold()
        candidates = [hint for hint in METHOD_HINTS if hint in lowered]
    if not candidates:
        candidates.extend(_flatten(row.get("title")))
    return (_unique(candidates, limit=1) or [f"Method {index}"])[0]


def _numeric_values(*rows: dict[str, Any]) -> list[str]:
    values: list[str] = []
    for row in rows:
        values.extend(_values(row, NUMERIC_FIELDS, limit=12))
        values.extend(match.group(0).strip() for match in NUMERIC_VALUE_RE.finditer(" ".join(_flatten(row))))
    return _unique(values, limit=10)


def _evidence_for(prefix: str, source: dict[str, Any], global_evidence: list[dict[str, Any]], index: int) -> list[dict[str, Any]]:
    citation = source.get("id") or source.get("summary_id") or source.get("doc_id") or f"{prefix}:{index}"
    local = {
        "citation": citation,
        "route": prefix,
        "title": source.get("title") or source.get("doc_id") or source.get("source_path") or citation,
        "locator": source.get("url") or source.get("doi") or source.get("source_path") or source.get("publication_id") or "",
        "preview": source.get("preview") or source.get("summary") or "",
    }
    related = [item for item in global_evidence if item.get("citation") == citation]
    return related[:2] or [local]


def _rows_from_summaries(context: dict[str, list[dict[str, Any]]], evidence: list[dict[str, Any]], *, top_k: int) -> list[ComparisonRow]:
    rows: list[ComparisonRow] = []
    for index, summary in enumerate((context.get("summaries") or [])[:top_k], start=1):
        payload = _row_payload(summary)
        rows.append(
            ComparisonRow(
                item=_item_from(payload, index),
                description=_description_from(payload) or _description_from(summary),
                materials=_values(payload, MATERIAL_FIELDS),
                processes=_values(payload, PROCESS_FIELDS),
                conditions=_values(payload, CONDITION_FIELDS),
                properties=_values(payload, PROPERTY_FIELDS),
                numeric_values=_numeric_values(payload),
                advantages=_values(payload, ADVANTAGE_FIELDS),
                limitations=_values(payload, LIMITATION_FIELDS),
                evidence=_evidence_for("summaries", summary, evidence, index),
            )
        )
    return rows


def _rows_from_web_summaries(context: dict[str, list[dict[str, Any]]], evidence: list[dict[str, Any]], *, top_k: int) -> list[ComparisonRow]:
    rows: list[ComparisonRow] = []
    web_summaries = [
        row
        for row in context.get("web") or []
        if row.get("source") == "deep_search" and row.get("kind") in {"document_summary", "procedure_summary"}
    ]
    for index, summary in enumerate(web_summaries[:top_k], start=1):
        payload = _row_payload(summary)
        rows.append(
            ComparisonRow(
                item=_item_from(payload, index),
                description=_description_from(payload) or _description_from(summary),
                materials=_values(payload, MATERIAL_FIELDS),
                processes=_values(payload, PROCESS_FIELDS),
                conditions=_values(payload, CONDITION_FIELDS),
                properties=_values(payload, PROPERTY_FIELDS),
                numeric_values=_numeric_values(payload),
                advantages=_values(payload, ADVANTAGE_FIELDS),
                limitations=_values(payload, LIMITATION_FIELDS),
                evidence=_evidence_for("web", summary, evidence, index),
            )
        )
    return rows


def _rows_from_context_fallback(context: dict[str, list[dict[str, Any]]], evidence: list[dict[str, Any]], *, top_k: int) -> list[ComparisonRow]:
    rows: list[ComparisonRow] = []
    sources = [*(context.get("raw") or []), *(context.get("web") or [])]
    for index, source in enumerate(sources[:top_k], start=1):
        text = source.get("preview") or source.get("abstract") or source.get("snippet") or source.get("title") or ""
        lowered = text.casefold()
        processes = [hint for hint in METHOD_HINTS if hint in lowered]
        materials = [hint for hint in MATERIAL_HINTS if hint in lowered]
        rows.append(
            ComparisonRow(
                item=(_unique(processes, limit=1) or [source.get("title") or f"Candidate {index}"])[0],
                description=_compact(text, 420),
                materials=_unique(materials, limit=6),
                processes=_unique(processes, limit=6),
                numeric_values=_numeric_values(source),
                evidence=_evidence_for("raw" if source in (context.get("raw") or []) else "web", source, evidence, index),
            )
        )
    return rows


def _augment_rows_with_tables(rows: list[ComparisonRow], tables: list[dict[str, Any]]) -> list[ComparisonRow]:
    if not rows or not tables:
        return rows
    augmented: list[ComparisonRow] = []
    for index, row in enumerate(rows):
        related_tables = tables[index:: max(len(rows), 1)][:2]
        table_numbers: list[str] = []
        for table in related_tables:
            table_numbers.extend(_numeric_values(table))
        numeric_values = _unique([*row.numeric_values, *table_numbers], limit=10)
        table_evidence = [
            {
                "citation": table.get("id") or f"tables:{index + 1}",
                "route": "tables",
                "title": table.get("table_name") or table.get("title") or table.get("path") or "Table evidence",
                "locator": table.get("path") or table.get("source_path") or "",
                "preview": table.get("preview") or table.get("matched_rows") or "",
            }
            for table in related_tables
        ]
        augmented.append(
            ComparisonRow(
                item=row.item,
                description=row.description,
                materials=row.materials,
                processes=row.processes,
                conditions=row.conditions,
                properties=row.properties,
                numeric_values=numeric_values,
                advantages=row.advantages,
                limitations=row.limitations,
                evidence=[*row.evidence, *table_evidence],
            )
        )
    return augmented


def _augment_rows_with_graph(rows: list[ComparisonRow], graph: list[dict[str, Any]]) -> list[ComparisonRow]:
    if not rows or not graph:
        return rows
    materials = _unique(row.get("label") for row in graph if str(row.get("type") or "").casefold() in {"material", "materials"})
    processes = _unique(row.get("label") for row in graph if str(row.get("type") or "").casefold() in {"process", "processes"})
    properties = _unique(row.get("label") for row in graph if str(row.get("type") or "").casefold() in {"property", "properties"})
    if not (materials or processes or properties):
        return rows
    return [
        ComparisonRow(
            item=row.item,
            description=row.description,
            materials=_unique([*row.materials, *materials], limit=8),
            processes=_unique([*row.processes, *processes], limit=8),
            conditions=row.conditions,
            properties=_unique([*row.properties, *properties], limit=8),
            numeric_values=row.numeric_values,
            advantages=row.advantages,
            limitations=row.limitations,
            evidence=row.evidence,
        )
        for row in rows
    ]


def _missing_evidence(orchestration: QueryOrchestrationResult, rows: list[ComparisonRow]) -> list[dict[str, Any]]:
    payload = orchestration.as_dict()
    missing = list(payload.get("fallbacks") or [])
    for row in rows:
        if not row.numeric_values:
            missing.append({"route": "table_search", "status": "partial", "reason": f"No numeric values found for {row.item}"})
        if not row.evidence:
            missing.append({"route": "raw_rag", "status": "partial", "reason": f"No direct evidence collected for {row.item}"})
    return missing


def _answer_summary(query: str, rows: list[ComparisonRow], missing: list[dict[str, Any]]) -> str:
    if not rows:
        return "Comparison mode did not retrieve enough context to build a method table."
    item_list = ", ".join(row.item for row in rows[:4])
    evidence_note = "with explicit evidence" if not missing else "with partial evidence and visible fallbacks"
    return f"Compared {len(rows)} candidate methods for: {query}. Main candidates: {item_list}. Built deterministically from retrieved context {evidence_note}."


def compare_methods(
    query: str,
    *,
    project_root: Path = PROJECT_ROOT,
    include_web: bool = False,
    web_sources: list[SearchSource] | None = None,
    top_k: int = 5,
) -> ComparisonResult:
    required_routes: list[RouteName] = ["summary_rag", "raw_rag", "table_search", "graph_search"]
    if include_web:
        required_routes.append("web_search")
    orchestration = run_query_orchestration(
        query,
        project_root=project_root,
        include_web=include_web,
        web_sources=web_sources,
        web_top_k=top_k,
        web_deep_search=include_web,
        generate_pdf_report=False,
        required_routes=required_routes,
    )
    payload = orchestration.as_dict()
    context: dict[str, list[dict[str, Any]]] = payload["retrieved_context"]
    evidence: list[dict[str, Any]] = payload["evidence"]

    rows = _rows_from_summaries(context, evidence, top_k=top_k)
    rows.extend(_rows_from_web_summaries(context, evidence, top_k=top_k))
    if not rows:
        rows = _rows_from_context_fallback(context, evidence, top_k=top_k)
    rows = _augment_rows_with_tables(rows, context.get("tables") or [])
    rows = _augment_rows_with_graph(rows, context.get("graph") or [])

    missing = _missing_evidence(orchestration, rows)
    return ComparisonResult(
        query=query,
        compared_items=[row.item for row in rows],
        comparison_dimensions=[
            "description",
            "materials",
            "processes",
            "conditions",
            "properties",
            "numeric_values",
            "advantages",
            "limitations",
            "evidence",
        ],
        rows=rows,
        missing_evidence=missing,
        answer_summary=_answer_summary(query, rows, missing),
        plan=payload["plan"],
        retrieved_context=context,
        evidence=evidence,
        fallbacks=payload.get("fallbacks") or [],
    )
