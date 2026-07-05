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
    "reverse osmosis",
    "ion exchange",
    "electrodialysis",
    "nanofiltration",
    "ultrafiltration",
    "evaporation",
    "chemical precipitation",
    "neutralization",
    "coagulation",
    "flocculation",
    "sorption",
    "adsorption",
    "membrane treatment",
    "desalination",
    "demineralization",
    "water preparation",
    "water treatment",
    "electrolyte circulation",
    "electrolyte feed",
    "electrolysis",
    "electrowinning",
    "electrorefining",
    "diaphragm cell",
    "diaphragm cells",
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
    "обратный осмос",
    "ионный обмен",
    "электродиализ",
    "нанофильтрация",
    "ультрафильтрация",
    "выпаривание",
    "нейтрализация",
    "коагуляция",
    "флокуляция",
    "сорбция",
    "адсорбция",
    "мембранная очистка",
    "обессоливание",
    "деминерализация",
    "водоподготовка",
    "очистка воды",
    "циркуляция электролита",
    "подача электролита",
    "электролиз",
    "электролитическое производство",
    "электрорафинирование",
    "электроэкстракция",
    "диафрагменная ячейка",
    "диафрагменные ячейки",
)

MATERIAL_HINTS = (
    "mine water",
    "groundwater",
    "process water",
    "wastewater",
    "sulfate",
    "chloride",
    "calcium",
    "magnesium",
    "sodium",
    "electrolyte",
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
    "шахтная вода",
    "шахтные воды",
    "скважина",
    "оборотная вода",
    "сточные воды",
    "сульфаты",
    "хлориды",
    "кальций",
    "магний",
    "натрий",
    "электролит",
)
FOCUS_TERMS_BY_DOMAIN: dict[str, tuple[str, ...]] = {
    "water_treatment": (
        "mine water",
        "groundwater",
        "process water",
        "wastewater",
        "water treatment",
        "water preparation",
        "reverse osmosis",
        "ion exchange",
        "electrodialysis",
        "nanofiltration",
        "ultrafiltration",
        "membrane",
        "desalination",
        "demineralization",
        "tds",
        "sulfate",
        "chloride",
        "calcium",
        "magnesium",
        "sodium",
        "мг/л",
        "мг/дм3",
        "сухой остаток",
        "обессол",
        "водоподготов",
        "очистк",
        "шахтн",
        "скважин",
        "оборотн",
        "сточн",
        "сульфат",
        "хлорид",
        "кальци",
        "магни",
        "натри",
        "обратный осмос",
        "ионный обмен",
        "электродиализ",
        "нанофильтрац",
        "ультрафильтрац",
        "мембран",
        "деминерализ",
    ),
    "electrolysis": (
        "electrolyte",
        "electrolysis",
        "electrowinning",
        "electrorefining",
        "cell",
        "bath",
        "anode",
        "cathode",
        "diaphragm",
        "flow",
        "circulation",
        "feed",
        "outlet",
        "электрол",
        "ванн",
        "анод",
        "катод",
        "диафраг",
        "ячейк",
        "циркуляц",
        "подач",
        "вывод",
        "поток",
        "рафинирован",
        "осажден",
    ),
}
WATER_QUERY_TERMS = (
    "water",
    "mine water",
    "groundwater",
    "wastewater",
    "desalination",
    "demineralization",
    "tds",
    "sulfate",
    "chloride",
    "вод",
    "обессол",
    "водоподготов",
    "сухой остаток",
    "сульфат",
    "хлорид",
    "скважин",
    "шахтн",
    "сточн",
)
WATER_ALLOWED_METHOD_TERMS = (
    "reverse osmosis",
    "ion exchange",
    "electrodialysis",
    "nanofiltration",
    "ultrafiltration",
    "membrane",
    "desalination",
    "demineralization",
    "precipitation",
    "neutralization",
    "coagulation",
    "flocculation",
    "sorption",
    "adsorption",
    "carbonate",
    "lime",
    "reagent",
    "обратный осмос",
    "ионный обмен",
    "электродиализ",
    "нанофильтрац",
    "ультрафильтрац",
    "мембран",
    "обессол",
    "деминерализ",
    "осаждение",
    "нейтрализац",
    "коагуляц",
    "флокуляц",
    "сорбц",
    "адсорбц",
    "карбонат",
    "извест",
    "реагент",
)
WATER_MATERIAL_TERMS = (
    "mine water",
    "groundwater",
    "wastewater",
    "process water",
    "sulfate",
    "chloride",
    "calcium",
    "magnesium",
    "sodium",
    "tds",
    "мг/л",
    "мг/дм3",
    "шахтн",
    "скважин",
    "сточн",
    "оборотн",
    "сульфат",
    "хлорид",
    "кальци",
    "магни",
    "натри",
    "сухой остаток",
)
WATER_BLOCKED_METHOD_TERMS = (
    "flotation",
    "флотац",
    "leaching",
    "выщелач",
    "smelting",
    "плавк",
    "roasting",
    "обжиг",
    "liquid extraction",
    "жидкостная экстрак",
    "electrolysis",
    "электролиз",
)
ELECTROLYSIS_QUERY_TERMS = (
    "electrolyte",
    "electrolysis",
    "electrowinning",
    "electrorefining",
    "diaphragm",
    "anode",
    "cathode",
    "cell",
    "bath",
    "электрол",
    "электрорафин",
    "электроэкстрак",
    "диафраг",
    "анод",
    "катод",
    "ванн",
    "ячейк",
)
ELECTROLYSIS_ALLOWED_TERMS = (
    "electrolyte",
    "electrolysis",
    "electrowinning",
    "electrorefining",
    "diaphragm",
    "anode",
    "cathode",
    "cell",
    "bath",
    "circulation",
    "feed",
    "flow",
    "outlet",
    "current density",
    "электрол",
    "электрорафин",
    "электроэкстрак",
    "диафраг",
    "анод",
    "катод",
    "ванн",
    "ячейк",
    "циркуляц",
    "подач",
    "поток",
    "вывод",
    "плотность тока",
)
ELECTROLYSIS_BLOCKED_METHOD_TERMS = (
    "flotation",
    "флотац",
    "smelting",
    "плавк",
    "roasting",
    "обжиг",
    "don process",
    "процесс don",
)

PROCESS_FIELDS = (
    "methods",
    "processes",
    "process",
    "synthesis_or_process_method",
    "synthesis_method",
    "method",
    "procedure",
    "technology",
    "technologies",
)
MATERIAL_FIELDS = ("materials", "material_name", "input_materials", "reagents", "outputs")
CONDITION_FIELDS = ("conditions", "operating_conditions", "experimental_conditions", "process_parameters", "equipment_details")
PROPERTY_FIELDS = ("properties", "observed_effects", "analysis_results")
NUMERIC_FIELDS = ("numerical_results", "numeric_values", "analysis_results", "results", "composition")
ADVANTAGE_FIELDS = ("advantages", "key_findings", "main_conclusions")
LIMITATION_FIELDS = ("limitations", "limitations_or_gaps", "gaps")
BUSINESS_FIELDS = (
    "economics",
    "economic_results",
    "techno_economic",
    "costs",
    "capex",
    "opex",
    "tco",
    "energy_consumption",
    "reagent_consumption",
    "productivity",
    "throughput",
    "industrial_applicability",
    "scale",
)
BUSINESS_HINTS = (
    "capex",
    "opex",
    "cost",
    "costs",
    "tco",
    "npv",
    "roi",
    "energy",
    "reagent",
    "throughput",
    "productivity",
    "scale-up",
    "industrial",
    "operating cost",
    "capital cost",
    "капекс",
    "опекс",
    "стоимость",
    "затраты",
    "себестоимость",
    "энергозатраты",
    "энергопотребление",
    "реагент",
    "производительность",
    "промышлен",
    "масштабирован",
)


@dataclass(frozen=True)
class ComparisonRow:
    item: str
    description: str = ""
    score: float = 0.0
    materials: list[str] = field(default_factory=list)
    processes: list[str] = field(default_factory=list)
    conditions: list[str] = field(default_factory=list)
    properties: list[str] = field(default_factory=list)
    numeric_values: list[str] = field(default_factory=list)
    business_context: list[str] = field(default_factory=list)
    advantages: list[str] = field(default_factory=list)
    limitations: list[str] = field(default_factory=list)
    evidence: list[dict[str, Any]] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return {
            "item": self.item,
            "description": self.description,
            "score": round(self.score, 2),
            "materials": self.materials,
            "processes": self.processes,
            "conditions": self.conditions,
            "properties": self.properties,
            "numeric_values": self.numeric_values,
            "business_context": self.business_context,
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


def _contains_any(text: str, terms: Iterable[str]) -> bool:
    folded = text.casefold()
    return any(term.casefold() in folded for term in terms)


def _query_focus_terms(query: str) -> list[str]:
    folded = query.casefold()
    terms: list[str] = []
    for domain_terms in FOCUS_TERMS_BY_DOMAIN.values():
        if any(term in folded for term in domain_terms):
            terms.extend(domain_terms)
    return _unique(terms, limit=80, max_chars=80)


def _row_text(row: ComparisonRow) -> str:
    evidence_text = " ".join(
        " ".join(_flatten({key: item.get(key) for key in ("title", "locator", "preview", "route", "citation")}))
        for item in row.evidence
        if isinstance(item, dict)
    )
    return " ".join(
        [
            row.item,
            row.description,
            " ".join(row.materials),
            " ".join(row.processes),
            " ".join(row.conditions),
            " ".join(row.properties),
            " ".join(row.numeric_values),
            " ".join(row.business_context),
            " ".join(row.advantages),
            " ".join(row.limitations),
            evidence_text,
        ]
    ).casefold()


def _focus_hit_count(row: ComparisonRow, focus_terms: list[str]) -> int:
    text = _row_text(row)
    return sum(1 for term in focus_terms if term.casefold() in text)


def _preferred_focus_item(row: ComparisonRow, terms: Iterable[str]) -> str | None:
    for value in [*row.processes, row.item, row.description, *row.conditions, *row.properties]:
        text = str(value or "").strip()
        if text and _contains_any(text, terms):
            return _compact(text, 120)
    return None


def _with_item(row: ComparisonRow, item: str) -> ComparisonRow:
    if item == row.item:
        return row
    return ComparisonRow(
        item=item,
        description=row.description,
        score=row.score,
        materials=row.materials,
        processes=row.processes,
        conditions=row.conditions,
        properties=row.properties,
        numeric_values=row.numeric_values,
        business_context=row.business_context,
        advantages=row.advantages,
        limitations=row.limitations,
        evidence=row.evidence,
    )


def _filter_and_boost_for_query(query: str, rows: list[ComparisonRow]) -> list[ComparisonRow]:
    focus_terms = _query_focus_terms(query)
    if not focus_terms:
        return rows
    water_query = _contains_any(query, WATER_QUERY_TERMS)
    electrolysis_query = _contains_any(query, ELECTROLYSIS_QUERY_TERMS)
    scored: list[tuple[int, ComparisonRow]] = []
    for row in rows:
        row_text = _row_text(row)
        if water_query:
            allowed = _contains_any(row_text, WATER_ALLOWED_METHOD_TERMS) or (
                _contains_any(row_text, WATER_MATERIAL_TERMS) and bool(row.numeric_values or row.business_context)
            )
            blocked_item = _contains_any(row.item, WATER_BLOCKED_METHOD_TERMS)
            if not allowed or (blocked_item and not _contains_any(row.item, WATER_ALLOWED_METHOD_TERMS)):
                continue
            preferred = _preferred_focus_item(row, WATER_ALLOWED_METHOD_TERMS)
            if preferred:
                row = _with_item(row, preferred)
        if electrolysis_query:
            allowed = _contains_any(row_text, ELECTROLYSIS_ALLOWED_TERMS)
            blocked_item = _contains_any(row.item, ELECTROLYSIS_BLOCKED_METHOD_TERMS)
            preferred = _preferred_focus_item(row, ELECTROLYSIS_ALLOWED_TERMS)
            if not allowed or (blocked_item and preferred is None):
                continue
            if preferred:
                row = _with_item(row, preferred)
        hits = _focus_hit_count(row, focus_terms)
        if hits <= 0:
            continue
        scored.append(
            (
                hits,
                ComparisonRow(
                    item=row.item,
                    description=row.description,
                    score=min(10.0, row.score + min(2.5, hits * 0.45)),
                    materials=row.materials,
                    processes=row.processes,
                    conditions=row.conditions,
                    properties=row.properties,
                    numeric_values=row.numeric_values,
                    business_context=row.business_context,
                    advantages=row.advantages,
                    limitations=row.limitations,
                    evidence=row.evidence,
                ),
            )
        )
    if not scored:
        return []
    scored.sort(key=lambda item: (item[0], item[1].score), reverse=True)
    return [row for _, row in scored]


def _filter_or_fallback_rows(
    query: str,
    rows: list[ComparisonRow],
    context: dict[str, list[dict[str, Any]]],
    evidence: list[dict[str, Any]],
    *,
    top_k: int,
) -> list[ComparisonRow]:
    filtered = _filter_and_boost_for_query(query, rows)
    fallback_rows = _rows_from_context_fallback(context, evidence, top_k=top_k * 2)
    fallback_filtered = _filter_and_boost_for_query(query, fallback_rows)
    if filtered:
        min_rows = min(3, top_k)
        if len(filtered) >= min_rows:
            return filtered
        existing = {re.sub(r"\W+", " ", row.item.casefold()).strip() for row in filtered}
        supplemented = list(filtered)
        for row in fallback_filtered:
            key = re.sub(r"\W+", " ", row.item.casefold()).strip()
            if key in existing:
                continue
            supplemented.append(row)
            existing.add(key)
            if len(supplemented) >= min_rows:
                break
        return supplemented
    return fallback_filtered or fallback_rows


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


def _is_placeholder_item(item: str) -> bool:
    folded = item.casefold()
    return item.startswith("Method ") or folded.endswith((".pdf", ".docx", ".xlsx", ".xls")) or "\\" in item


def _numeric_values(*rows: dict[str, Any]) -> list[str]:
    values: list[str] = []
    for row in rows:
        values.extend(_values(row, NUMERIC_FIELDS, limit=12))
        values.extend(match.group(0).strip() for match in NUMERIC_VALUE_RE.finditer(" ".join(_flatten(row))))
    return _unique(values, limit=10)


def _business_context(*rows: dict[str, Any]) -> list[str]:
    values: list[str] = []
    for row in rows:
        values.extend(_values(row, BUSINESS_FIELDS, limit=12))
        text = " ".join(_flatten(row))
        lowered = text.casefold()
        values.extend(hint for hint in BUSINESS_HINTS if hint in lowered)
        values.extend(
            match.group(0).strip()
            for match in re.finditer(
                r"(?<!\w)\d+(?:[.,]\d+)?\s*(?:руб|₽|usd|eur|kwh|квт\s*ч|м3/ч|м³/ч|т/ч|kg/t|кг/т|г/л)(?=$|\s|[.,;:)])",
                text,
                flags=re.IGNORECASE,
            )
        )
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
        flattened = " ".join(_flatten(payload)).casefold()
        item = _item_from(payload, index)
        processes = _unique([*_values(payload, PROCESS_FIELDS), *[hint for hint in METHOD_HINTS if hint in flattened]], limit=8)
        business_context = _business_context(payload)
        if _is_placeholder_item(item):
            continue
        rows.append(
            ComparisonRow(
                item=item,
                description=_description_from(payload) or _description_from(summary),
                score=float(summary.get("score") or 0.0),
                materials=_values(payload, MATERIAL_FIELDS),
                processes=processes,
                conditions=_values(payload, CONDITION_FIELDS),
                properties=_values(payload, PROPERTY_FIELDS),
                numeric_values=_numeric_values(payload),
                business_context=business_context,
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
        flattened = " ".join(_flatten(payload)).casefold()
        item = _item_from(payload, index)
        processes = _unique([*_values(payload, PROCESS_FIELDS), *[hint for hint in METHOD_HINTS if hint in flattened]], limit=8)
        business_context = _business_context(payload)
        if _is_placeholder_item(item):
            continue
        rows.append(
            ComparisonRow(
                item=item,
                description=_description_from(payload) or _description_from(summary),
                score=float(summary.get("score") or 0.0),
                materials=_values(payload, MATERIAL_FIELDS),
                processes=processes,
                conditions=_values(payload, CONDITION_FIELDS),
                properties=_values(payload, PROPERTY_FIELDS),
                numeric_values=_numeric_values(payload),
                business_context=business_context,
                advantages=_values(payload, ADVANTAGE_FIELDS),
                limitations=_values(payload, LIMITATION_FIELDS),
                evidence=_evidence_for("web", summary, evidence, index),
            )
        )
    return rows


def _rows_from_tables(context: dict[str, list[dict[str, Any]]], evidence: list[dict[str, Any]], *, top_k: int) -> list[ComparisonRow]:
    rows: list[ComparisonRow] = []
    for index, table in enumerate((context.get("tables") or [])[:top_k], start=1):
        summary = table.get("summary") if isinstance(table.get("summary"), dict) else {}
        matched_rows = table.get("rows") if isinstance(table.get("rows"), list) else []
        payload: dict[str, Any] = {
            **summary,
            "title": table.get("title") or summary.get("source_path") or summary.get("path"),
            "preview": table.get("preview") or summary.get("preview"),
            "matched_rows": matched_rows,
            "matched_terms": table.get("matched_terms") or [],
        }
        flattened = " ".join(_flatten(payload)).casefold()
        item = _item_from(payload, index)
        processes = _unique([*_values(payload, PROCESS_FIELDS), *[hint for hint in METHOD_HINTS if hint in flattened]], limit=8)
        business_context = _business_context(payload)
        if _is_placeholder_item(item):
            continue
        rows.append(
            ComparisonRow(
                item=item,
                description=_description_from(payload),
                score=float(table.get("score") or 0.0),
                materials=_values(payload, MATERIAL_FIELDS),
                processes=processes,
                conditions=_values(payload, CONDITION_FIELDS),
                properties=_values(payload, PROPERTY_FIELDS),
                numeric_values=_numeric_values(payload),
                business_context=business_context,
                evidence=_evidence_for("tables", table, evidence, index),
            )
        )
    return rows


def _rows_from_graph(context: dict[str, list[dict[str, Any]]], evidence: list[dict[str, Any]], *, top_k: int) -> list[ComparisonRow]:
    rows: list[ComparisonRow] = []
    for index, graph_row in enumerate((context.get("graph") or [])[:top_k], start=1):
        text = " ".join(_flatten(graph_row))
        lowered_type = str(graph_row.get("type") or "").casefold()
        lowered_text = text.casefold()
        if "process" not in lowered_type and not any(hint in lowered_text for hint in METHOD_HINTS):
            continue
        item = _item_from(graph_row, index)
        if _is_placeholder_item(item):
            continue
        rows.append(
            ComparisonRow(
                item=item,
                description=_compact(graph_row.get("relation") or graph_row.get("path") or graph_row.get("label"), 420),
                score=float(graph_row.get("score") or 0.0),
                materials=_unique([hint for hint in MATERIAL_HINTS if hint in lowered_text], limit=8),
                processes=_unique([graph_row.get("label"), *[hint for hint in METHOD_HINTS if hint in lowered_text]], limit=8),
                evidence=_evidence_for("graph", graph_row, evidence, index),
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
                score=float(source.get("score") or 0.0),
                materials=_unique(materials, limit=6),
                processes=_unique(processes, limit=6),
                numeric_values=_numeric_values(source),
                business_context=_business_context(source),
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
                score=row.score,
                materials=row.materials,
                processes=row.processes,
                conditions=row.conditions,
                properties=row.properties,
                numeric_values=numeric_values,
                business_context=_unique([*row.business_context, *_business_context(*related_tables)], limit=10),
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
            score=row.score,
            materials=_unique([*row.materials, *materials], limit=8),
            processes=_unique([*row.processes, *processes], limit=8),
            conditions=row.conditions,
            properties=_unique([*row.properties, *properties], limit=8),
            numeric_values=row.numeric_values,
            business_context=row.business_context,
            advantages=row.advantages,
            limitations=row.limitations,
            evidence=row.evidence,
        )
        for row in rows
    ]


def _row_score(row: ComparisonRow) -> float:
    score = min(max(row.score, 0.0), 10.0)
    score += min(len(row.evidence), 4) * 0.8
    score += min(len(row.numeric_values), 4) * 0.5
    score += min(len(row.business_context), 4) * 0.6
    score += 0.5 if row.conditions else 0.0
    score += 0.5 if row.advantages else 0.0
    score -= 0.4 if not row.description else 0.0
    return round(min(score, 10.0), 2)


def _merge_rows(rows: list[ComparisonRow]) -> list[ComparisonRow]:
    grouped: dict[str, ComparisonRow] = {}
    for row in rows:
        key = re.sub(r"\W+", " ", row.item.casefold()).strip() or row.item.casefold()
        existing = grouped.get(key)
        if existing is None:
            grouped[key] = row
            continue
        grouped[key] = ComparisonRow(
            item=existing.item,
            description=existing.description or row.description,
            score=max(existing.score, row.score),
            materials=_unique([*existing.materials, *row.materials], limit=10),
            processes=_unique([*existing.processes, *row.processes], limit=10),
            conditions=_unique([*existing.conditions, *row.conditions], limit=10),
            properties=_unique([*existing.properties, *row.properties], limit=10),
            numeric_values=_unique([*existing.numeric_values, *row.numeric_values], limit=12),
            business_context=_unique([*existing.business_context, *row.business_context], limit=12),
            advantages=_unique([*existing.advantages, *row.advantages], limit=10),
            limitations=_unique([*existing.limitations, *row.limitations], limit=10),
            evidence=[*existing.evidence, *row.evidence][:8],
        )
    return list(grouped.values())


def _rank_rows(rows: list[ComparisonRow], *, top_k: int) -> list[ComparisonRow]:
    ranked = [
        ComparisonRow(
            item=row.item,
            description=row.description,
            score=_row_score(row),
            materials=row.materials,
            processes=row.processes,
            conditions=row.conditions,
            properties=row.properties,
            numeric_values=row.numeric_values,
            business_context=row.business_context,
            advantages=row.advantages,
            limitations=row.limitations,
            evidence=row.evidence,
        )
        for row in _merge_rows(rows)
    ]
    ranked.sort(key=lambda row: row.score, reverse=True)
    return ranked[:top_k]


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
        return "Недостаточно evidence, чтобы построить таблицу сравнения методик."
    item_list = ", ".join(row.item for row in rows[:4])
    evidence_note = "с прямыми ссылками на evidence" if not missing else "с частичными данными и отмеченными пробелами"
    return f"Сравнено {len(rows)} методик/технических решений по запросу: {query}. Основные кандидаты: {item_list}. Таблица собрана из summary, raw RAG, графа и табличного поиска {evidence_note}."


def build_method_comparison_from_orchestration(
    query: str,
    orchestration: QueryOrchestrationResult,
    *,
    top_k: int = 8,
) -> ComparisonResult:
    payload = orchestration.as_dict()
    context: dict[str, list[dict[str, Any]]] = payload["retrieved_context"]
    evidence: list[dict[str, Any]] = payload["evidence"]

    rows = _rows_from_summaries(context, evidence, top_k=top_k * 2)
    rows.extend(_rows_from_web_summaries(context, evidence, top_k=top_k))
    rows.extend(_rows_from_tables(context, evidence, top_k=top_k * 2))
    rows.extend(_rows_from_graph(context, evidence, top_k=top_k * 2))
    if not rows:
        rows = _rows_from_context_fallback(context, evidence, top_k=top_k)
    rows = _filter_or_fallback_rows(query, rows, context, evidence, top_k=top_k)
    rows = _augment_rows_with_tables(rows, context.get("tables") or [])
    rows = _augment_rows_with_graph(rows, context.get("graph") or [])
    rows = _rank_rows(rows, top_k=top_k)

    missing = _missing_evidence(orchestration, rows)
    return ComparisonResult(
        query=query,
        compared_items=[row.item for row in rows],
        comparison_dimensions=[
            "score",
            "description",
            "materials",
            "processes",
            "conditions",
            "properties",
            "numeric_values",
            "business_context",
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
    rows.extend(_rows_from_tables(context, evidence, top_k=top_k))
    rows.extend(_rows_from_graph(context, evidence, top_k=top_k))
    if not rows:
        rows = _rows_from_context_fallback(context, evidence, top_k=top_k)
    rows = _filter_or_fallback_rows(query, rows, context, evidence, top_k=top_k)
    rows = _augment_rows_with_tables(rows, context.get("tables") or [])
    rows = _augment_rows_with_graph(rows, context.get("graph") or [])
    rows = _rank_rows(rows, top_k=top_k)

    missing = _missing_evidence(orchestration, rows)
    return ComparisonResult(
        query=query,
        compared_items=[row.item for row in rows],
        comparison_dimensions=[
            "score",
            "description",
            "materials",
            "processes",
            "conditions",
            "properties",
            "numeric_values",
            "business_context",
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
