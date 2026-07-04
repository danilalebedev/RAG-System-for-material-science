from __future__ import annotations

import re
from typing import Any, Protocol

from pydantic import BaseModel, Field

from app.extract.publication_metadata import extract_json_object
from app.web_search.keywords import extract_keywords


class CompletionClient(Protocol):
    model_uri: str

    def complete(self, prompt: str) -> tuple[str, dict[str, Any]]:
        ...


MATERIALS_SCOPE_TERMS = [
    "materials science",
    "metallurgy",
    "mineral processing",
    "hydrometallurgy",
    "non-ferrous metallurgy",
    "mine water",
    "acid mine drainage",
    "mining wastewater",
    "heavy metal removal",
    "alloy",
    "ore",
    "nickel",
    "copper",
    "cobalt",
]

DOMAIN_REWRITE_HINTS: list[tuple[re.Pattern[str], dict[str, list[str]]]] = [
    (
        re.compile(r"(шахтн\w*\s+вод|кисл\w*\s+шахтн\w*\s+вод|mine water|acid mine drainage|mining wastewater)", re.I),
        {
            "keywords_ru": ["очистка шахтных вод", "кислые шахтные воды", "горнорудные предприятия"],
            "keywords_en": ["mine water treatment", "acid mine drainage treatment", "mining wastewater"],
            "material_terms": ["mine water", "acid mine drainage", "mining wastewater", "heavy metal wastewater"],
            "process_terms": ["treatment", "purification", "remediation", "neutralization", "precipitation", "sorption", "membrane treatment"],
            "search_queries": [
                "acid mine drainage treatment non-ferrous metallurgy review",
                "mine water treatment heavy metal removal mining wastewater",
                "mine water purification mining enterprises non-ferrous metallurgy",
                "acid mine drainage remediation sulfide ores heavy metals",
                "очистка шахтных вод цветная металлургия обзор",
                "очистка кислых шахтных вод горнорудные предприятия",
            ],
        },
    ),
    (
        re.compile(r"(цветн\w*\s+металлург|non[- ]ferrous metallurgy)", re.I),
        {
            "keywords_ru": ["цветная металлургия"],
            "keywords_en": ["non-ferrous metallurgy"],
            "material_terms": ["non-ferrous metallurgy"],
            "process_terms": [],
            "search_queries": ["non-ferrous metallurgy wastewater treatment review"],
        },
    ),
    (
        re.compile(r"(горн\w*[- ]?рудн\w*|mining enterprise|ore mining)", re.I),
        {
            "keywords_ru": ["горно-рудные предприятия"],
            "keywords_en": ["mining enterprises", "ore mining"],
            "material_terms": ["ore mining"],
            "process_terms": [],
            "search_queries": ["mining enterprise wastewater treatment heavy metals"],
        },
    ),
]


class QueryRewritePlan(BaseModel):
    original_query: str
    corrected_query: str
    search_queries: list[str] = Field(default_factory=list)
    keywords_ru: list[str] = Field(default_factory=list)
    keywords_en: list[str] = Field(default_factory=list)
    material_terms: list[str] = Field(default_factory=list)
    process_terms: list[str] = Field(default_factory=list)
    property_terms: list[str] = Field(default_factory=list)
    filters: dict[str, Any] = Field(default_factory=dict)
    rewrite_used_llm: bool = False
    notes: list[str] = Field(default_factory=list)

    @property
    def all_keywords(self) -> list[str]:
        return list(dict.fromkeys(self.keywords_ru + self.keywords_en + extract_keywords(self.corrected_query)))


def compact_text(value: Any, max_chars: int | None = None) -> str:
    text = re.sub(r"\s+", " ", str(value or "")).strip()
    if max_chars is not None and len(text) > max_chars:
        return text[: max_chars - 3].rstrip() + "..."
    return text


def scoped_query(query: str) -> str:
    base = compact_text(query, 500)
    scope = " OR ".join(f'"{term}"' for term in MATERIALS_SCOPE_TERMS[:5])
    return f"{base} ({scope})"


def unique_values(*groups: list[str], limit: int = 20) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for group in groups:
        for value in group:
            text = compact_text(value, 500)
            key = text.casefold()
            if not text or key in seen:
                continue
            result.append(text)
            seen.add(key)
            if len(result) >= limit:
                return result
    return result


def domain_rewrite_hints(query: str) -> dict[str, list[str]]:
    hints: dict[str, list[str]] = {
        "keywords_ru": [],
        "keywords_en": [],
        "material_terms": [],
        "process_terms": [],
        "property_terms": [],
        "search_queries": [],
    }
    for pattern, payload in DOMAIN_REWRITE_HINTS:
        if not pattern.search(query or ""):
            continue
        for key, values in payload.items():
            hints[key] = unique_values(hints.get(key, []), values, limit=24)
    return hints


def deterministic_query_rewrite(query: str, *, materials_only: bool = True) -> QueryRewritePlan:
    keywords = extract_keywords(query, max_keywords=10)
    hints = domain_rewrite_hints(query)
    keyword_query = " ".join(keywords)
    corrected = compact_text(
        " ".join(
            unique_values(
                hints["keywords_en"][:4],
                hints["material_terms"][:3],
                hints["process_terms"][:3],
                limit=10,
            )
        )
        or query,
        500,
    )
    search_queries = [corrected, *hints["search_queries"]]
    if keyword_query and keyword_query != corrected.lower():
        search_queries.append(keyword_query)
    if materials_only:
        search_queries.append(scoped_query(corrected))
        if keyword_query:
            search_queries.append(scoped_query(keyword_query))
    search_queries = [item for item in dict.fromkeys(compact_text(item, 700) for item in search_queries) if item]
    return QueryRewritePlan(
        original_query=query,
        corrected_query=corrected,
        search_queries=search_queries[:6],
        keywords_ru=unique_values(hints["keywords_ru"], keywords, limit=16),
        keywords_en=unique_values(hints["keywords_en"], limit=16),
        material_terms=unique_values(hints["material_terms"], limit=16),
        process_terms=unique_values(hints["process_terms"], limit=16),
        property_terms=unique_values(hints["property_terms"], limit=16),
        filters={"materials_only": materials_only, "domain_hints_applied": bool(hints["search_queries"])},
        rewrite_used_llm=False,
        notes=["deterministic rewrite fallback"],
    )


def build_rewrite_prompt(query: str, *, materials_only: bool) -> str:
    scope = "materials science, metallurgy, mineral processing, alloys, ores, hydrometallurgy"
    return f"""
Ты query rewrite engine для R&D-поиска по публикациям и RAG.
Нужно исправить запрос пользователя, выделить материалы/процессы/свойства и
сгенерировать несколько поисковых формулировок для scholarly search.

Правила:
- Не отвечай на вопрос, только перепиши запрос.
- Область поиска: {scope if materials_only else "general scholarly search"}.
- Сделай русский и английский варианты, если исходный запрос русский.
- Search queries должны быть короткими и пригодными для Crossref/Semantic Scholar/OpenAlex.
- Не добавляй фактов, которых нет в запросе.

Верни только JSON:
{{
  "corrected_query": "string",
  "search_queries": ["string"],
  "keywords_ru": ["string"],
  "keywords_en": ["string"],
  "material_terms": ["string"],
  "process_terms": ["string"],
  "property_terms": ["string"],
  "filters": {{"materials_only": true}}
}}

USER_QUERY:
{query}
""".strip()


def normalize_rewrite_response(
    query: str,
    parsed: dict[str, Any],
    *,
    materials_only: bool,
    used_llm: bool,
) -> QueryRewritePlan:
    fallback = deterministic_query_rewrite(query, materials_only=materials_only)
    corrected = compact_text(parsed.get("corrected_query") or fallback.corrected_query, 500)
    search_queries = []
    for item in parsed.get("search_queries") or []:
        text = compact_text(item, 700)
        if text:
            search_queries.append(text)
    if corrected:
        search_queries.insert(0, corrected)
    if materials_only:
        search_queries.extend(scoped_query(item) for item in search_queries[:3])
    search_queries = unique_values(search_queries, fallback.search_queries, limit=8)
    return QueryRewritePlan(
        original_query=query,
        corrected_query=corrected,
        search_queries=search_queries or fallback.search_queries,
        keywords_ru=unique_values([compact_text(item, 120) for item in (parsed.get("keywords_ru") or []) if item], fallback.keywords_ru, limit=16),
        keywords_en=unique_values([compact_text(item, 120) for item in (parsed.get("keywords_en") or []) if item], fallback.keywords_en, limit=16),
        material_terms=unique_values([compact_text(item, 120) for item in (parsed.get("material_terms") or []) if item], fallback.material_terms, limit=16),
        process_terms=unique_values([compact_text(item, 120) for item in (parsed.get("process_terms") or []) if item], fallback.process_terms, limit=16),
        property_terms=unique_values([compact_text(item, 120) for item in (parsed.get("property_terms") or []) if item], fallback.property_terms, limit=16),
        filters={**(parsed.get("filters") if isinstance(parsed.get("filters"), dict) else {}), "materials_only": materials_only},
        rewrite_used_llm=used_llm,
        notes=[],
    )


def rewrite_query(
    query: str,
    *,
    client: CompletionClient | None = None,
    materials_only: bool = True,
    use_llm: bool = True,
) -> QueryRewritePlan:
    if client is None or not use_llm:
        return deterministic_query_rewrite(query, materials_only=materials_only)
    try:
        raw_response, _usage = client.complete(build_rewrite_prompt(query, materials_only=materials_only))
        parsed = extract_json_object(raw_response)
        return normalize_rewrite_response(query, parsed, materials_only=materials_only, used_llm=True)
    except Exception as exc:  # noqa: BLE001 - rewrite must never block search.
        plan = deterministic_query_rewrite(query, materials_only=materials_only)
        plan.notes.append(f"llm rewrite failed: {compact_text(exc, 300)}")
        return plan
