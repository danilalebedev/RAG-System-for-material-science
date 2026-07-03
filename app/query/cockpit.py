from __future__ import annotations

import json
import re
from collections import Counter
from typing import Any


NUMERIC_RE = re.compile(
    r"\b\d+(?:[.,]\d+)?\s*(?:°?\s*c|k|к|mpa|мпа|g/l|г/л|mol/l|моль/л|%|h|ч|мин|час(?:а|ов)?|mm|мм|um|µm|мкм)\b",
    re.IGNORECASE,
)
YEAR_RE = re.compile(r"\b(?:19|20)\d{2}\b")

MATERIAL_HINTS = (
    "nickel",
    "copper",
    "cobalt",
    "platinum",
    "palladium",
    "alloy",
    "ore",
    "slag",
    "matte",
    "н никел",
    "никел",
    "мед",
    "кобальт",
    "платин",
    "паллад",
    "сплав",
    "руда",
    "шлак",
    "штейн",
)
PROCESS_HINTS = (
    "leaching",
    "flotation",
    "smelting",
    "roasting",
    "annealing",
    "electrolysis",
    "extraction",
    "выщелач",
    "флотац",
    "плавк",
    "обжиг",
    "отжиг",
    "электрол",
    "экстракц",
    "рафинир",
)
PROPERTY_HINTS = (
    "hardness",
    "strength",
    "corrosion",
    "recovery",
    "selectivity",
    "purity",
    "твёрд",
    "тверд",
    "прочн",
    "корроз",
    "извлеч",
    "селектив",
    "чистот",
)
GEOGRAPHY_HINTS = (
    "норильск",
    "краснояр",
    "кольск",
    "мончегор",
    "таймыр",
    "росси",
    "canada",
    "australia",
    "finland",
    "china",
)

DEMO_SCENARIOS: list[dict[str, str]] = [
    {
        "id": "mine_water",
        "label": "Шахтные воды",
        "focus": "Очистка и извлечение металлов из шахтных вод",
        "query": "обессоливание шахтных вод мембранные методы эффективность никель медь",
    },
    {
        "id": "catholyte",
        "label": "Католит Ni",
        "focus": "Электроэкстракция и циркуляция католита",
        "query": "циркуляция католита электроэкстракция никеля анодные процессы",
    },
    {
        "id": "matte_slag",
        "label": "Штейн-шлак",
        "focus": "Распределение ценных металлов между фазами",
        "query": "распределение золота серебра металлов платиновой группы между штейном и шлаком",
    },
    {
        "id": "sulfur_gas",
        "label": "SO2 из газов",
        "focus": "Очистка металлургических газов",
        "query": "удаление диоксида серы металлургические газы никель медь",
    },
    {
        "id": "cold_leaching",
        "label": "Выщелачивание холод",
        "focus": "Температурные ограничения для кучного выщелачивания",
        "query": "кучное выщелачивание никелевых руд холодный климат температура",
    },
]


def compact_text(value: Any, max_chars: int | None = None) -> str:
    text = re.sub(r"\s+", " ", str(value or "")).strip()
    if max_chars is not None and len(text) > max_chars:
        return text[: max_chars - 3].rstrip() + "..."
    return text


def list_values(value: Any, *, max_chars: int = 180) -> list[str]:
    if value in (None, "", [], {}):
        return []
    if isinstance(value, list):
        values = value
    else:
        values = [value]
    result: list[str] = []
    for item in values:
        if isinstance(item, (dict, list)):
            text = json.dumps(item, ensure_ascii=False, default=str)
        else:
            text = str(item)
        text = compact_text(text, max_chars)
        if text:
            result.append(text)
    return result


def unique_limited(values: list[str], *, limit: int = 12) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for value in values:
        text = compact_text(value, 180)
        key = text.lower()
        if not text or key in seen:
            continue
        seen.add(key)
        result.append(text)
        if len(result) >= limit:
            break
    return result


def result_link(result: Any) -> str:
    if getattr(result, "url", None):
        return str(result.url)
    if getattr(result, "doi", None):
        return f"https://doi.org/{result.doi}"
    return ""


def keyword_matches(keywords: list[str], hints: tuple[str, ...]) -> list[str]:
    matches: list[str] = []
    for keyword in keywords:
        lowered = keyword.lower()
        if any(hint in lowered for hint in hints):
            matches.append(keyword)
    return matches


def query_decomposition(run: Any) -> list[dict[str, Any]]:
    plan = run.query_plan or {}
    query = getattr(run.request, "query", "")
    keywords = list(getattr(run, "keywords", []) or [])
    filters = plan.get("filters") if isinstance(plan.get("filters"), dict) else {}
    numeric_terms = NUMERIC_RE.findall(query)
    years = YEAR_RE.findall(query)

    rows = [
        {
            "slot": "Материалы",
            "values": unique_limited(list_values(plan.get("material_terms")) + keyword_matches(keywords, MATERIAL_HINTS)),
            "why": "ограничивают поиск материалами, рудами, сплавами и фазами",
        },
        {
            "slot": "Процессы",
            "values": unique_limited(list_values(plan.get("process_terms")) + keyword_matches(keywords, PROCESS_HINTS)),
            "why": "задают технологию или методику обработки",
        },
        {
            "slot": "Свойства и outputs",
            "values": unique_limited(list_values(plan.get("property_terms")) + keyword_matches(keywords, PROPERTY_HINTS)),
            "why": "помогают ранжировать статьи по измеряемому эффекту",
        },
        {
            "slot": "Условия и числа",
            "values": unique_limited(numeric_terms + list_values(filters.get("conditions") or filters.get("numeric_constraints"))),
            "why": "нужны для будущих multiparameter-запросов и сравнения режимов",
        },
        {
            "slot": "География и период",
            "values": unique_limited(keyword_matches(keywords, GEOGRAPHY_HINTS) + years + list_values(filters.get("geography") or filters.get("time"))),
            "why": "показывают географические и временные ограничения, если они есть",
        },
        {
            "slot": "Варианты поискового запроса",
            "values": unique_limited(list_values(plan.get("search_queries")), limit=8),
            "why": "именно эти RU/EN формулировки отправляются во внешние базы",
        },
    ]
    return rows


def local_vs_web_metrics(run: Any) -> list[dict[str, Any]]:
    comparison = getattr(run, "comparison", None)
    rows = getattr(comparison, "rows", []) if comparison else []
    local_method_count = sum(1 for row in rows if row.get("scope") == "local")
    web_method_count = sum(1 for row in rows if row.get("scope") == "web")
    confirmed = len(getattr(comparison, "confirmed_methods", []) or []) if comparison else 0
    local_only = len(getattr(comparison, "local_only_methods", []) or []) if comparison else 0
    web_only = len(getattr(comparison, "web_only_methods", []) or []) if comparison else 0
    differing = len(getattr(comparison, "differing_conditions", []) or []) if comparison else 0
    return [
        {
            "metric": "Источники",
            "local": len(getattr(run, "local_matches", []) or []),
            "web": len(getattr(run, "results", []) or []),
            "interpretation": "масштаб покрытия локальной базы и внешней литературы",
        },
        {
            "metric": "Методики после Deep Search",
            "local": local_method_count,
            "web": web_method_count,
            "interpretation": "сколько procedure summaries доступно для сравнения",
        },
        {
            "metric": "Подтверждено обеими сторонами",
            "local": confirmed,
            "web": confirmed,
            "interpretation": "локальные методики, найденные во внешней литературе",
        },
        {
            "metric": "Уникально",
            "local": local_only,
            "web": web_only,
            "interpretation": "кандидаты на gap-analysis и расширение графа знаний",
        },
        {
            "metric": "Разные условия",
            "local": differing,
            "web": differing,
            "interpretation": "одна методика, но отличаются режимы, диапазоны или контекст",
        },
    ]


def method_matrix_rows(run: Any) -> list[dict[str, Any]]:
    comparison = getattr(run, "comparison", None)
    if not comparison:
        return []
    rows = []
    for index, row in enumerate(getattr(comparison, "rows", []) or [], start=1):
        rows.append(
            {
                "#": index,
                "scope": "Локальная БД" if row.get("scope") == "local" else "Web",
                "title": compact_text(row.get("title"), 220),
                "material": compact_text(row.get("material"), 140),
                "method": compact_text(row.get("method"), 160),
                "conditions": "; ".join(list_values(row.get("conditions"), max_chars=120)[:4]),
                "equipment": "; ".join(list_values(row.get("equipment"), max_chars=100)[:3]),
                "outputs": "; ".join(list_values(row.get("outputs"), max_chars=100)[:3]),
                "effects": "; ".join(list_values(row.get("observed_effects"), max_chars=120)[:3]),
                "numeric": "; ".join(list_values(row.get("numeric_results"), max_chars=120)[:3]),
            }
        )
    return rows


def method_heatmap_rows(run: Any) -> list[dict[str, Any]]:
    comparison = getattr(run, "comparison", None)
    if not comparison:
        return []
    grouped: dict[tuple[str, str], Counter[str]] = {}
    for row in getattr(comparison, "rows", []) or []:
        material = compact_text(row.get("material") or "n/a", 80)
        method = compact_text(row.get("method") or ", ".join(list_values(row.get("processes"))[:2]) or "n/a", 100)
        key = (material, method)
        grouped.setdefault(key, Counter())[row.get("scope") or "unknown"] += 1
    result = []
    for (material, method), counts in grouped.items():
        local_count = counts.get("local", 0)
        web_count = counts.get("web", 0)
        if local_count and web_count:
            status = "есть локально и во внешней литературе"
        elif local_count:
            status = "только локально"
        else:
            status = "только web"
        result.append({"material": material, "method": method, "local": local_count, "web": web_count, "status": status})
    return sorted(result, key=lambda row: (row["local"] + row["web"], row["material"]), reverse=True)[:100]


def gap_radar_rows(run: Any) -> list[dict[str, Any]]:
    comparison = getattr(run, "comparison", None)
    results = getattr(run, "results", []) or []
    deep_results = getattr(run, "deep_results", []) or []
    confirmed = len(getattr(comparison, "confirmed_methods", []) or []) if comparison else 0
    local_only = len(getattr(comparison, "local_only_methods", []) or []) if comparison else 0
    web_only = len(getattr(comparison, "web_only_methods", []) or []) if comparison else 0
    differing = len(getattr(comparison, "differing_conditions", []) or []) if comparison else 0
    without_year = sum(1 for result in results if not getattr(result, "year", None))
    without_doi = sum(1 for result in results if not getattr(result, "doi", None))

    return [
        {
            "signal": "Подтвержденные методики",
            "value": confirmed,
            "level": "OK" if confirmed else "средний риск",
            "recommendation": "использовать как strongest evidence для демонстрации" if confirmed else "запустить Deep Search или расширить запрос",
        },
        {
            "signal": "Только локально",
            "value": local_only,
            "level": "средний риск" if local_only else "OK",
            "recommendation": "проверить, являются ли это внутренними ноу-хау или пробелом внешнего поиска",
        },
        {
            "signal": "Только во внешней литературе",
            "value": web_only,
            "level": "возможность" if web_only else "OK",
            "recommendation": "добавить в граф как кандидаты на новые технологии/методики",
        },
        {
            "signal": "Разные условия/диапазоны",
            "value": differing,
            "level": "высокий риск" if differing else "OK",
            "recommendation": "показать как contradiction panel и проверить численные режимы",
        },
        {
            "signal": "Web-источники без года",
            "value": without_year,
            "level": "низкий риск" if without_year else "OK",
            "recommendation": "понижать доверие при построении временных трендов",
        },
        {
            "signal": "Web-источники без DOI",
            "value": without_doi,
            "level": "низкий риск" if without_doi else "OK",
            "recommendation": "использовать ссылку и source id, но помечать как менее проверяемые",
        },
        {
            "signal": "Deep Search покрытие",
            "value": f"{len(deep_results)}/{min(len(results), getattr(run.request, 'deep_search_limit', 0) or 0)}",
            "level": "OK" if deep_results else "средний риск",
            "recommendation": "запускать для top-N статей перед финальным отчетом",
        },
    ]


def executive_brief_markdown(run: Any) -> str:
    comparison = getattr(run, "comparison", None)
    confirmed = len(getattr(comparison, "confirmed_methods", []) or []) if comparison else 0
    local_only = len(getattr(comparison, "local_only_methods", []) or []) if comparison else 0
    web_only = len(getattr(comparison, "web_only_methods", []) or []) if comparison else 0
    differing = len(getattr(comparison, "differing_conditions", []) or []) if comparison else 0
    corrected_query = (run.query_plan or {}).get("corrected_query") or run.request.query
    top_sources = list(getattr(run, "results", []) or [])[:8]
    rows = [
        "# Краткий управленческий вывод",
        "",
        f"Запрос: {run.request.query}",
        f"Поисковая формулировка: {corrected_query}",
        "",
        "## Что найдено",
        "",
        f"- Внешних источников: {len(getattr(run, 'results', []) or [])}.",
        f"- Локальных совпадений: {len(getattr(run, 'local_matches', []) or [])}.",
        f"- Deep Search summaries: {len(getattr(run, 'deep_results', []) or [])}.",
        f"- Методики: подтверждено {confirmed}, только локально {local_only}, только web {web_only}, разные условия {differing}.",
        "",
        "## Вывод для демонстрации",
        "",
    ]
    if confirmed:
        rows.append("- Есть пересечение локальной базы с мировой литературой: это можно показывать как проверяемость и доверие к графу.")
    if web_only:
        rows.append("- Внешняя литература расширяет локальную базу: найденные web-only методики можно превращать в кандидатов на новые узлы графа.")
    if local_only:
        rows.append("- Локальная база содержит уникальные методики: их стоит подсветить как внутреннюю экспертизу или область для внешней валидации.")
    if differing:
        rows.append("- Есть различия в условиях: это хороший сценарий для панели противоречий и проверки численных диапазонов.")
    if not any([confirmed, web_only, local_only, differing]):
        rows.append("- Пока доступен metadata-only слой: он уже дает список литературы и основу для последующего Deep Search.")

    rows.extend(["", "## Релевантные ссылки", ""])
    if top_sources:
        for index, result in enumerate(top_sources, start=1):
            link = result_link(result)
            label = compact_text(getattr(result, "title", ""), 240)
            rows.append(f"{index}. [{label}]({link})" if link else f"{index}. {label}")
    else:
        rows.append("Внешние источники не найдены.")

    rows.extend(["", "## Рекомендации", ""])
    recommendations_added = False
    for row in gap_radar_rows(run):
        if row["level"] != "OK" and row["value"] not in (0, "0/0"):
            rows.append(f"- {row['signal']}: {row['recommendation']}.")
            recommendations_added = True
    if not recommendations_added:
        rows.append("- Расширить запрос или включить Deep Search для top-N статей перед финальной демонстрацией.")
    return "\n".join(rows).strip() + "\n"
