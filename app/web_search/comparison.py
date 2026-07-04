from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from app.web_search.clients import compact_text
from app.web_search.schemas import DeepSearchResult, MethodComparison


TOKEN_RE = re.compile(r"[A-Za-zА-Яа-яЁё0-9][A-Za-zА-Яа-яЁё0-9_+.-]*", re.UNICODE)


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    if not path.exists():
        return rows
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(row, dict):
                rows.append(row)
    return rows


def as_list(value: Any) -> list[Any]:
    if value in (None, "", [], {}):
        return []
    if isinstance(value, list):
        return [item for item in value if item not in (None, "", [], {})]
    return [value]


def normalize_text(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "").lower().replace("ё", "е")).strip()


def term_set(value: Any) -> set[str]:
    text = normalize_text(value)
    tokens = {token.strip(".,;:!?()[]{}") for token in TOKEN_RE.findall(text)}
    return {token for token in tokens if len(token) >= 3 or token.isdigit()}


def procedure_to_row(procedure: dict[str, Any], *, scope: str, title: str | None = None) -> dict[str, Any]:
    steps = []
    for step in as_list(procedure.get("steps")):
        if isinstance(step, dict):
            steps.append(compact_text(step.get("description"), 300))
        else:
            steps.append(compact_text(step, 300))
    method = procedure.get("synthesis_or_process_method") or procedure.get("synthesis_method")
    if not method and procedure.get("processes"):
        method = ", ".join(str(item) for item in as_list(procedure.get("processes"))[:3])
    material = procedure.get("material_name")
    if not material and procedure.get("materials"):
        material = as_list(procedure.get("materials"))[0]
    return {
        "scope": scope,
        "title": title or procedure.get("publication_title") or procedure.get("doc_id"),
        "doc_id": procedure.get("doc_id"),
        "result_id": procedure.get("result_id"),
        "material": compact_text(material, 300),
        "method": compact_text(method, 300),
        "processes": as_list(procedure.get("processes")),
        "conditions": as_list(procedure.get("conditions")) or as_list(procedure.get("process_parameters")),
        "equipment": as_list(procedure.get("equipment")),
        "outputs": as_list(procedure.get("outputs")),
        "observed_effects": as_list(procedure.get("observed_effects")),
        "numeric_results": as_list(procedure.get("numerical_results")),
        "steps": steps,
        "confidence": procedure.get("confidence"),
        "evidence": as_list(procedure.get("evidence")),
    }


def document_summary_to_row(summary: dict[str, Any], *, scope: str, title: str | None = None) -> dict[str, Any]:
    domain = summary.get("additional_domain_fields") if isinstance(summary.get("additional_domain_fields"), dict) else {}
    materials = as_list(summary.get("materials")) or as_list(summary.get("material_name"))
    processes = as_list(summary.get("processes")) or as_list(summary.get("methods"))
    methods = as_list(summary.get("methods")) or processes
    conditions = (
        as_list(summary.get("conditions"))
        + as_list(summary.get("process_parameters"))
        + as_list(domain.get("process_parameters"))
        + as_list(domain.get("numeric_conditions"))
    )
    numeric_results = (
        as_list(summary.get("numerical_results"))
        + as_list(summary.get("analysis_results"))
        + as_list(domain.get("analysis_results"))
        + as_list(domain.get("numerical_results"))
    )
    observed_effects = (
        as_list(summary.get("observed_effects"))
        + as_list(summary.get("key_findings"))
        + as_list(summary.get("main_conclusions"))
    )
    method = ", ".join(str(item) for item in methods[:3]) or summary.get("main_topic")
    material = ", ".join(str(item) for item in materials[:3])
    return {
        "scope": scope,
        "record_type": "document_summary",
        "title": title or summary.get("title") or summary.get("main_topic") or summary.get("doc_id"),
        "doc_id": summary.get("doc_id"),
        "result_id": summary.get("result_id"),
        "summary_id": summary.get("document_summary_id") or summary.get("summary_id"),
        "material": compact_text(material, 300),
        "method": compact_text(method, 300),
        "processes": processes,
        "conditions": conditions,
        "equipment": as_list(summary.get("equipment")),
        "outputs": as_list(summary.get("outputs")) or as_list(summary.get("properties")),
        "observed_effects": observed_effects,
        "numeric_results": numeric_results,
        "steps": [],
        "confidence": summary.get("confidence"),
        "evidence": as_list(summary.get("evidence")),
        "summary": compact_text(summary.get("summary") or summary.get("main_topic"), 1200),
        "limitations_or_gaps": as_list(summary.get("limitations_or_gaps")),
    }


def method_key(row: dict[str, Any]) -> str:
    material_tokens = sorted(term_set(row.get("material")))[:4]
    method_tokens = sorted(term_set(row.get("method")) | term_set(" ".join(str(item) for item in row.get("processes") or [])))[:6]
    if not material_tokens and not method_tokens:
        return normalize_text(row.get("title"))
    return "|".join([" ".join(material_tokens), " ".join(method_tokens)])


def row_overlap(left: dict[str, Any], right: dict[str, Any]) -> float:
    left_tokens = term_set(left.get("material")) | term_set(left.get("method")) | term_set(" ".join(map(str, left.get("processes") or [])))
    right_tokens = term_set(right.get("material")) | term_set(right.get("method")) | term_set(" ".join(map(str, right.get("processes") or [])))
    if not left_tokens or not right_tokens:
        return 0.0
    return len(left_tokens & right_tokens) / len(left_tokens | right_tokens)


def conditions_differ(left: dict[str, Any], right: dict[str, Any]) -> bool:
    left_conditions = normalize_text(json.dumps(left.get("conditions") or [], ensure_ascii=False, default=str))
    right_conditions = normalize_text(json.dumps(right.get("conditions") or [], ensure_ascii=False, default=str))
    if not left_conditions or not right_conditions:
        return False
    return left_conditions != right_conditions and row_overlap(left, right) >= 0.25


def load_local_publication_records(publications_dir: Path) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    publications_dir = Path(publications_dir)
    return (
        read_jsonl(publications_dir / "publications.jsonl"),
        read_jsonl(publications_dir / "document_summaries.jsonl"),
        read_jsonl(publications_dir / "procedure_summaries.jsonl"),
    )


def local_procedure_rows(publications: list[dict[str, Any]], procedures: list[dict[str, Any]]) -> list[dict[str, Any]]:
    title_by_doc = {str(row.get("doc_id")): row.get("title") for row in publications if row.get("doc_id")}
    rows = []
    for procedure in procedures:
        row = procedure_to_row(procedure, scope="local", title=title_by_doc.get(str(procedure.get("doc_id"))))
        row["record_type"] = "procedure_summary"
        rows.append(row)
    return rows


def local_document_rows(publications: list[dict[str, Any]], document_summaries: list[dict[str, Any]]) -> list[dict[str, Any]]:
    title_by_doc = {str(row.get("doc_id")): row.get("title") for row in publications if row.get("doc_id")}
    return [
        document_summary_to_row(summary, scope="local", title=title_by_doc.get(str(summary.get("doc_id"))))
        for summary in document_summaries
    ]


def query_ranked_rows(rows: list[dict[str, Any]], query: str, *, top_k: int = 100) -> list[dict[str, Any]]:
    terms = term_set(query)
    if not terms:
        return rows[:top_k]
    scored: list[tuple[int, dict[str, Any]]] = []
    for row in rows:
        text = normalize_text(json.dumps(row, ensure_ascii=False, default=str))
        hits = sorted(term for term in terms if term and term in text)
        ranked = dict(row)
        ranked["query_score"] = len(hits)
        ranked["keyword_hits"] = hits
        scored.append((len(hits), ranked))
    if any(score > 0 for score, _ in scored):
        scored = [item for item in scored if item[0] > 0]
    scored.sort(key=lambda item: (item[0], item[1].get("confidence") or 0), reverse=True)
    return [row for _, row in scored[:top_k]]


def local_experiment_rows(
    publications: list[dict[str, Any]],
    document_summaries: list[dict[str, Any]],
    procedures: list[dict[str, Any]],
    *,
    query: str,
    top_k: int = 100,
) -> list[dict[str, Any]]:
    rows = local_procedure_rows(publications, procedures) + local_document_rows(publications, document_summaries)
    return query_ranked_rows(rows, query, top_k=top_k)


def web_procedure_rows(deep_results: list[DeepSearchResult]) -> list[dict[str, Any]]:
    rows = []
    for deep_result in deep_results:
        for procedure in deep_result.procedure_summaries:
            enriched = dict(procedure)
            enriched["result_id"] = deep_result.result_id
            row = procedure_to_row(enriched, scope="web", title=deep_result.source_result.title)
            row["record_type"] = "procedure_summary"
            rows.append(row)
    return rows


def web_document_rows(deep_results: list[DeepSearchResult]) -> list[dict[str, Any]]:
    rows = []
    for deep_result in deep_results:
        if not deep_result.document_summary:
            continue
        summary = dict(deep_result.document_summary)
        summary["result_id"] = deep_result.result_id
        rows.append(document_summary_to_row(summary, scope="web", title=deep_result.source_result.title))
    return rows


def web_experiment_rows(deep_results: list[DeepSearchResult], *, query: str, top_k: int = 100) -> list[dict[str, Any]]:
    return query_ranked_rows(web_procedure_rows(deep_results) + web_document_rows(deep_results), query, top_k=top_k)


def compare_methods(
    *,
    query: str,
    local_publications: list[dict[str, Any]],
    local_document_summaries: list[dict[str, Any]] | None = None,
    local_procedures: list[dict[str, Any]],
    web_deep_results: list[DeepSearchResult],
) -> MethodComparison:
    local_rows = local_experiment_rows(local_publications, local_document_summaries or [], local_procedures, query=query)
    web_rows = web_experiment_rows(web_deep_results, query=query)
    rows = local_rows + web_rows

    confirmed: list[dict[str, Any]] = []
    differing: list[dict[str, Any]] = []
    matched_local: set[int] = set()
    matched_web: set[int] = set()
    for local_index, local_row in enumerate(local_rows):
        for web_index, web_row in enumerate(web_rows):
            overlap = row_overlap(local_row, web_row)
            if overlap >= 0.3 or (method_key(local_row) and method_key(local_row) == method_key(web_row)):
                matched_local.add(local_index)
                matched_web.add(web_index)
                confirmed.append(
                    {
                        "local_title": local_row.get("title"),
                        "web_title": web_row.get("title"),
                        "material": local_row.get("material") or web_row.get("material"),
                        "method": local_row.get("method") or web_row.get("method"),
                        "overlap": round(overlap, 4),
                    }
                )
                if conditions_differ(local_row, web_row):
                    differing.append(
                        {
                            "material": local_row.get("material") or web_row.get("material"),
                            "method": local_row.get("method") or web_row.get("method"),
                            "local_conditions": local_row.get("conditions"),
                            "web_conditions": web_row.get("conditions"),
                            "local_title": local_row.get("title"),
                            "web_title": web_row.get("title"),
                        }
                    )

    local_only = [row for index, row in enumerate(local_rows) if index not in matched_local]
    web_only = [row for index, row in enumerate(web_rows) if index not in matched_web]
    gaps = []
    if not web_rows:
        gaps.append("External deep_search did not return experiment summaries for comparison.")
    if web_only:
        gaps.append("External literature contains experiment summaries that did not match local summaries.")
    if local_only:
        gaps.append("Local experiment summaries are present without matching external top deep_search evidence.")
    return MethodComparison(
        query=query,
        confirmed_methods=confirmed,
        local_only_methods=local_only[:50],
        web_only_methods=web_only[:50],
        differing_conditions=differing[:50],
        gaps=gaps,
        rows=rows[:200],
    )


def search_local_summaries(
    *,
    query: str,
    keywords: list[str],
    publications: list[dict[str, Any]],
    document_summaries: list[dict[str, Any]],
    procedures: list[dict[str, Any]],
    top_k: int = 20,
) -> list[dict[str, Any]]:
    title_by_doc = {str(row.get("doc_id")): row.get("title") for row in publications if row.get("doc_id")}
    candidates: list[dict[str, Any]] = []
    terms = {normalize_text(keyword) for keyword in keywords if keyword}
    if not terms:
        terms = term_set(query)

    for row in document_summaries:
        text = " ".join(
            str(part)
            for part in [
                row.get("summary"),
                row.get("main_topic"),
                " ".join(map(str, as_list(row.get("materials")))),
                " ".join(map(str, as_list(row.get("processes")))),
                " ".join(map(str, as_list(row.get("properties")))),
                " ".join(map(str, as_list(row.get("key_findings")))),
            ]
            if part
        )
        normalized = normalize_text(text)
        hits = [term for term in terms if term and term in normalized]
        if hits:
            candidates.append(
                {
                    "kind": "document_summary",
                    "doc_id": row.get("doc_id"),
                    "title": title_by_doc.get(str(row.get("doc_id"))),
                    "score": len(hits),
                    "keyword_hits": hits,
                    "preview": compact_text(row.get("summary"), 600),
                }
            )

    for row in procedures:
        text = json.dumps(row, ensure_ascii=False, default=str)
        normalized = normalize_text(text)
        hits = [term for term in terms if term and term in normalized]
        if hits:
            candidates.append(
                {
                    "kind": "procedure_summary",
                    "doc_id": row.get("doc_id"),
                    "title": title_by_doc.get(str(row.get("doc_id"))),
                    "score": len(hits),
                    "keyword_hits": hits,
                    "preview": compact_text(row.get("key_points") or row.get("synthesis_or_process_method"), 600),
                }
            )

    candidates.sort(key=lambda row: (row.get("score") or 0), reverse=True)
    return candidates[:top_k]
