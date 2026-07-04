from __future__ import annotations

import re
import unicodedata
from typing import Any, Literal

from pydantic import BaseModel, Field

from app.web_search.keywords import extract_keywords


Intent = Literal[
    "find_documents",
    "summarize_topic",
    "compare_methods",
    "extract_numbers",
    "find_contradictions",
    "find_experts",
    "graph_exploration",
    "web_literature_search",
    "internal_vs_external_comparison",
]
AnswerFormat = Literal["short_answer", "comparison_table", "evidence_matrix", "graph_explanation", "report"]
RouteName = Literal["raw_rag", "summary_rag", "graph_search", "table_search", "web_search", "internal_rag"]


SUPPORTED_INTENTS: tuple[str, ...] = (
    "find_documents",
    "summarize_topic",
    "compare_methods",
    "extract_numbers",
    "find_contradictions",
    "find_experts",
    "graph_exploration",
    "web_literature_search",
    "internal_vs_external_comparison",
)

MATERIAL_TERMS = (
    "nickel",
    "ni",
    "copper",
    "cu",
    "cobalt",
    "co",
    "platinum",
    "palladium",
    "gold",
    "silver",
    "alloy",
    "ore",
    "slag",
    "matte",
    "tailings",
    "никель",
    "никеля",
    "медь",
    "меди",
    "кобальт",
    "кобальта",
    "платина",
    "палладий",
    "золото",
    "серебро",
    "сплав",
    "руда",
    "руды",
    "шлак",
    "штейн",
    "хвосты",
)
NICKEL_ORE_ALIASES = (
    "никелевая руда",
    "никелевые руды",
    "nickel ore",
    "nickel ores",
    "латеритная никелевая руда",
    "сульфидная никелевая руда",
    "laterite nickel ore",
    "sulfide nickel ore",
    "Ni ore",
    "сульфидные никелевые концентраты",
    "limonite saprolite nickel ore",
)
MATERIAL_PHRASE_ALIASES: dict[str, tuple[str, ...]] = {
    "никелевая руда": NICKEL_ORE_ALIASES,
    "никелевые руды": NICKEL_ORE_ALIASES,
    "nickel ore": NICKEL_ORE_ALIASES,
    "nickel ores": NICKEL_ORE_ALIASES,
    "ni ore": NICKEL_ORE_ALIASES,
    "латеритная никелевая руда": NICKEL_ORE_ALIASES,
    "сульфидная никелевая руда": NICKEL_ORE_ALIASES,
    "laterite nickel ore": NICKEL_ORE_ALIASES,
    "sulfide nickel ore": NICKEL_ORE_ALIASES,
}
PROCESS_TERMS = (
    "leaching",
    "flotation",
    "smelting",
    "roasting",
    "annealing",
    "electrolysis",
    "extraction",
    "recovery",
    "выщелачивание",
    "флотация",
    "плавка",
    "обжиг",
    "отжиг",
    "электролиз",
    "экстракция",
    "извлечение",
)
EQUIPMENT_TERMS = (
    "furnace",
    "reactor",
    "autoclave",
    "cell",
    "membrane",
    "electrolyzer",
    "xrd",
    "sem",
    "печь",
    "реактор",
    "автоклав",
    "ячейка",
    "мембрана",
    "электролизер",
    "микроскоп",
)
PROPERTY_TERMS = (
    "hardness",
    "strength",
    "corrosion",
    "selectivity",
    "purity",
    "composition",
    "temperature",
    "pressure",
    "ph",
    "твёрдость",
    "твердость",
    "прочность",
    "коррозия",
    "селективность",
    "чистота",
    "состав",
    "температура",
    "давление",
)
FACILITY_TERMS = (
    "norilsk",
    "canada",
    "australia",
    "finland",
    "china",
    "норильск",
    "красноярск",
    "кольский",
    "мончегорск",
    "таймыр",
    "россия",
)

NUMERIC_RE = re.compile(
    r"(?<!\w)\d+(?:[.,]\d+)?\s*(?:°?\s*c|k|mpa|мпа|g/l|г/л|mol/l|моль/л|%|wt\.?%|мас\.?%|h|ч|мин|mm|мм|um|µm|мкм)?(?=$|\s|[.,;:)])",
    re.IGNORECASE,
)
TOKEN_RE = re.compile(r"[\w.+#%-]+", re.UNICODE)


class QueryEntities(BaseModel):
    materials: list[str] = Field(default_factory=list)
    processes: list[str] = Field(default_factory=list)
    equipment: list[str] = Field(default_factory=list)
    properties: list[str] = Field(default_factory=list)
    experts: list[str] = Field(default_factory=list)
    facilities: list[str] = Field(default_factory=list)


class RewrittenQueries(BaseModel):
    raw_rag: list[str] = Field(default_factory=list)
    summary_rag: list[str] = Field(default_factory=list)
    graph: list[str] = Field(default_factory=list)
    tables: list[str] = Field(default_factory=list)
    web: list[str] = Field(default_factory=list)


class QueryPlan(BaseModel):
    original_query: str
    intent: Intent
    domain: str
    entities: QueryEntities = Field(default_factory=QueryEntities)
    rewritten_queries: RewrittenQueries = Field(default_factory=RewrittenQueries)
    internal_search_queries: list[str] = Field(default_factory=list)
    web_search_queries: list[str] = Field(default_factory=list)
    entity_aliases: dict[str, list[str]] = Field(default_factory=dict)
    slots: dict[str, list[str]] = Field(default_factory=dict)
    decomposed_questions: list[str] = Field(default_factory=list)
    routes: list[RouteName] = Field(default_factory=list)
    answer_format: AnswerFormat = "short_answer"
    needs_clarification: bool = False
    clarifying_question: str | None = None


def normalize_text(value: Any) -> str:
    text = unicodedata.normalize("NFKC", str(value or "")).casefold()
    return re.sub(r"\s+", " ", text).strip()


def compact_text(value: Any, max_chars: int = 700) -> str:
    text = re.sub(r"\s+", " ", str(value or "")).strip()
    if len(text) > max_chars:
        return text[: max_chars - 3].rstrip() + "..."
    return text


def unique(values: list[str], *, limit: int = 12) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for value in values:
        text = compact_text(value, 120)
        key = normalize_text(text)
        if not text or key in seen:
            continue
        seen.add(key)
        result.append(text)
        if len(result) >= limit:
            break
    return result


def term_in_text(term: str, text: str) -> bool:
    if len(term) <= 2 and term.isascii():
        return bool(re.search(rf"(?<!\w){re.escape(term)}(?!\w)", text, flags=re.IGNORECASE))
    return term in text


def contains_any(text: str, terms: tuple[str, ...]) -> bool:
    return any(term_in_text(term, text) for term in terms)


def matched_terms(query: str, terms: tuple[str, ...]) -> list[str]:
    normalized = normalize_text(query)
    matches: list[str] = []
    for term in terms:
        if term_in_text(term, normalized):
            matches.append(term)
    return unique(matches)


def material_phrase_aliases(query: str) -> dict[str, list[str]]:
    normalized = normalize_text(query)
    aliases: dict[str, list[str]] = {}
    for phrase, values in MATERIAL_PHRASE_ALIASES.items():
        if term_in_text(phrase, normalized):
            aliases[values[0]] = unique(list(values), limit=16)
    nickel_present = contains_any(normalized, ("nickel", "ni", "никель", "никелевая", "никелевые", "никелевой"))
    ore_present = contains_any(normalized, ("ore", "ores", "руда", "руды", "руд"))
    if nickel_present and ore_present:
        aliases[NICKEL_ORE_ALIASES[0]] = unique(list(NICKEL_ORE_ALIASES), limit=16)
    return aliases


def numeric_terms(query: str) -> list[str]:
    return unique([match.group(0).strip() for match in NUMERIC_RE.finditer(query)], limit=12)


def likely_experts(query: str) -> list[str]:
    names = re.findall(r"\b[A-Z][a-z]+(?:\s+[A-Z][a-z]+){1,2}\b", query)
    return unique(names, limit=8)


def infer_domain(query: str) -> str:
    normalized = normalize_text(query)
    if contains_any(normalized, MATERIAL_TERMS + PROCESS_TERMS + PROPERTY_TERMS):
        return "materials_science"
    return "general_research"


def infer_entities(query: str) -> QueryEntities:
    aliases = material_phrase_aliases(query)
    phrase_materials = list(aliases)
    return QueryEntities(
        materials=unique(phrase_materials + matched_terms(query, MATERIAL_TERMS), limit=16),
        processes=matched_terms(query, PROCESS_TERMS),
        equipment=matched_terms(query, EQUIPMENT_TERMS),
        properties=unique(matched_terms(query, PROPERTY_TERMS) + numeric_terms(query)),
        experts=likely_experts(query),
        facilities=matched_terms(query, FACILITY_TERMS),
    )


def infer_intent(query: str, entities: QueryEntities) -> Intent:
    normalized = normalize_text(query)
    if contains_any(normalized, ("internal vs external", "local vs world", "сравни локальную", "внутрен", "миров", "внешн")):
        return "internal_vs_external_comparison"
    if contains_any(normalized, ("contradict", "conflict", "disagree", "противореч", "расхожд", "конфликт")):
        return "find_contradictions"
    if contains_any(normalized, ("compare", "difference", "different", "better", "worse", "отлич", "сравн", "лучше", "хуже")):
        return "compare_methods"
    if numeric_terms(query) or contains_any(normalized, ("composition", "состав", "процент", "температур", "давлен", "числ")):
        return "extract_numbers"
    if contains_any(normalized, ("expert", "author", "researcher", "кто заним", "эксперт", "автор", "исследователь")):
        return "find_experts"
    if contains_any(normalized, ("relation", "related", "path", "entity", "graph", "связано", "связь", "путь", "граф", "сущност")):
        return "graph_exploration"
    if contains_any(normalized, ("paper", "papers", "article", "articles", "publication", "publications", "литератур", "стать", "публикац", "свеж")):
        return "web_literature_search"
    if contains_any(normalized, ("overview", "summarize", "summary", "обзор", "суммар", "расскажи", "что известно")):
        return "summarize_topic"
    if entities.materials or entities.processes or entities.properties:
        return "summarize_topic"
    return "find_documents"


def is_short_material_topic(query: str, entities: QueryEntities) -> bool:
    token_count = len(TOKEN_RE.findall(query))
    return token_count <= 5 and bool(entities.materials) and intent_like_topic(query)


def intent_like_topic(query: str) -> bool:
    normalized = normalize_text(query)
    return not contains_any(
        normalized,
        (
            "compare",
            "difference",
            "better",
            "worse",
            "сравн",
            "отлич",
            "лучше",
            "хуже",
            "source",
            "evidence",
            "где написано",
        ),
    )


def routes_for_query(query: str, intent: Intent, entities: QueryEntities | None = None) -> list[RouteName]:
    normalized = normalize_text(query)
    routes: list[RouteName] = []
    if entities and is_short_material_topic(query, entities):
        routes.extend(["raw_rag", "summary_rag", "table_search", "graph_search"])
    if numeric_terms(query) or contains_any(normalized, ("%", "composition", "состав", "температур", "давлен", "концентрац")):
        routes.extend(["table_search", "raw_rag"])
    if contains_any(normalized, ("compare", "difference", "different", "better", "worse", "отлич", "сравн", "лучше", "хуже")):
        routes.extend(["summary_rag", "raw_rag", "table_search"])
    if contains_any(normalized, ("relation", "related", "path", "entity", "graph", "связано", "связь", "путь", "граф", "сущност")):
        routes.extend(["graph_search", "summary_rag"])
    if contains_any(normalized, ("paper", "papers", "article", "articles", "publication", "publications", "литератур", "стать", "публикац", "свеж")):
        routes.extend(["web_search", "internal_rag"])
    if contains_any(normalized, ("source", "evidence", "where written", "где написано", "источник", "доказательств", "подтвержд")):
        routes.append("raw_rag")
    if intent == "find_experts":
        routes.extend(["graph_search", "summary_rag"])
    if intent == "find_contradictions":
        routes.extend(["summary_rag", "raw_rag", "table_search", "web_search"])
    if intent == "internal_vs_external_comparison":
        routes.extend(["internal_rag", "web_search", "summary_rag", "raw_rag"])
    if not routes and intent in {"summarize_topic", "find_documents"}:
        routes.extend(["summary_rag", "graph_search"])
    return [route for route in dict.fromkeys(routes)]


def infer_answer_format(intent: Intent, routes: list[RouteName]) -> AnswerFormat:
    if intent in {"compare_methods", "internal_vs_external_comparison"}:
        return "comparison_table"
    if intent in {"extract_numbers", "find_contradictions"}:
        return "evidence_matrix"
    if intent in {"graph_exploration", "find_experts"} or "graph_search" in routes:
        return "graph_explanation"
    if intent == "web_literature_search":
        return "report"
    return "short_answer"


def build_entity_aliases(query: str, entities: QueryEntities) -> dict[str, list[str]]:
    aliases = material_phrase_aliases(query)
    for material in entities.materials:
        aliases.setdefault(material, [material])
    return {key: unique(values, limit=16) for key, values in aliases.items()}


def build_slots(entities: QueryEntities) -> dict[str, list[str]]:
    return {
        "materials": entities.materials,
        "processes": entities.processes,
        "equipment": entities.equipment,
        "properties": entities.properties,
        "experts": entities.experts,
        "facilities": entities.facilities,
    }


def clean_search_queries(query: str, entities: QueryEntities, *, web: bool = False) -> list[str]:
    aliases = build_entity_aliases(query, entities)
    alias_values = [alias for values in aliases.values() for alias in values]
    keywords = extract_keywords(query, max_keywords=8)
    base = compact_text(query)
    variants = [base]
    variants.extend(alias_values)
    if keywords:
        variants.append(" ".join(keywords))
    if web:
        for alias in alias_values[:6]:
            variants.append(f"{alias} metallurgy")
            variants.append(f"{alias} materials science")
    return unique(variants, limit=12)


def route_query_variants(query: str, entities: QueryEntities, routes: list[RouteName]) -> RewrittenQueries:
    keywords = extract_keywords(query, max_keywords=10)
    keyword_query = " ".join(keywords)
    entity_terms = unique(
        entities.materials + entities.processes + entities.equipment + entities.properties + entities.facilities,
        limit=16,
    )
    entity_query = " ".join(entity_terms)
    numbers = " ".join(numeric_terms(query))
    base = compact_text(query)
    internal_queries = clean_search_queries(query, entities)
    web_queries = clean_search_queries(query, entities, web=True)

    def variants(*extra: str) -> list[str]:
        return unique([base, *internal_queries, keyword_query, entity_query, *extra], limit=8)

    rewritten = RewrittenQueries()
    if "raw_rag" in routes or "internal_rag" in routes:
        rewritten.raw_rag = variants(numbers)
    if "summary_rag" in routes or "internal_rag" in routes:
        rewritten.summary_rag = variants("procedure summary " + entity_query if entity_query else "")
    if "graph_search" in routes:
        rewritten.graph = variants(entity_query)
    if "table_search" in routes:
        rewritten.tables = variants(numbers, " ".join(entities.properties))
    if "web_search" in routes:
        rewritten.web = unique(web_queries + [base + " materials science", base + " metallurgy publication"], limit=10)
    return rewritten


def decompose_questions(query: str, intent: Intent, entities: QueryEntities, routes: list[RouteName]) -> list[str]:
    subject = " ".join(unique(entities.materials + entities.processes + entities.properties, limit=8)) or compact_text(query, 160)
    questions: list[str] = []
    if "summary_rag" in routes:
        questions.append(f"What is known about {subject} in internal summaries?")
    if "raw_rag" in routes:
        questions.append(f"Which source passages support facts about {subject}?")
    if "table_search" in routes:
        questions.append(f"Which tables contain numeric parameters for {subject}?")
    if "graph_search" in routes:
        questions.append(f"How are entities related for {subject}?")
    if "web_search" in routes:
        questions.append(f"Which external publications discuss {subject}?")
    if intent == "find_contradictions":
        questions.append(f"Do sources disagree on methods or conditions for {subject}?")
    return unique(questions, limit=8)


def clarification_state(query: str, entities: QueryEntities) -> tuple[bool, str | None]:
    token_count = len(TOKEN_RE.findall(query))
    has_entities = any((entities.materials, entities.processes, entities.properties, entities.equipment, entities.facilities))
    if token_count < 2 and not has_entities:
        return True, "Please specify a material, process, property, source, or comparison target."
    if not has_entities:
        return False, None
    return False, None


def plan_query(query: str) -> QueryPlan:
    original = compact_text(query, 1000)
    entities = infer_entities(original)
    intent = infer_intent(original, entities)
    routes = routes_for_query(original, intent, entities)
    needs_clarification, clarifying_question = clarification_state(original, entities)
    internal_queries = clean_search_queries(original, entities)
    web_queries = clean_search_queries(original, entities, web=True)
    aliases = build_entity_aliases(original, entities)
    return QueryPlan(
        original_query=original,
        intent=intent,
        domain=infer_domain(original),
        entities=entities,
        rewritten_queries=route_query_variants(original, entities, routes),
        internal_search_queries=internal_queries,
        web_search_queries=web_queries,
        entity_aliases=aliases,
        slots=build_slots(entities),
        decomposed_questions=decompose_questions(original, intent, entities, routes),
        routes=routes,
        answer_format=infer_answer_format(intent, routes),
        needs_clarification=needs_clarification,
        clarifying_question=clarifying_question,
    )
