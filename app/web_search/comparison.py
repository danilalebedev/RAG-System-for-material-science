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
        rows.append(procedure_to_row(procedure, scope="local", title=title_by_doc.get(str(procedure.get("doc_id")))))
    return rows


def web_procedure_rows(deep_results: list[DeepSearchResult]) -> list[dict[str, Any]]:
    rows = []
    for deep_result in deep_results:
        for procedure in deep_result.procedure_summaries:
            enriched = dict(procedure)
            enriched["result_id"] = deep_result.result_id
            rows.append(procedure_to_row(enriched, scope="web", title=deep_result.source_result.title))
    return rows


def compare_methods(
    *,
    query: str,
    local_publications: list[dict[str, Any]],
    local_procedures: list[dict[str, Any]],
    web_deep_results: list[DeepSearchResult],
) -> MethodComparison:
    local_rows = local_procedure_rows(local_publications, local_procedures)
    web_rows = web_procedure_rows(web_deep_results)
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
        gaps.append("Внешний deep_search не вернул procedure summaries для сравнения методик.")
    if web_only:
        gaps.append("Есть методики во внешней литературе, которые не совпали с локальными procedure summaries.")
    if local_only:
        gaps.append("Есть локальные методики без подтверждения во внешнем top-5 deep_search.")
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
