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
CONDITION_HINTS = (
    "temperature",
    "pressure",
    "concentration",
    "ph",
    "time",
    "rate",
    "температ",
    "давлен",
    "концентрац",
    "кислот",
    "скорост",
    "время",
    "режим",
)
EQUIPMENT_HINTS = (
    "furnace",
    "reactor",
    "autoclave",
    "cell",
    "membrane",
    "electrolyzer",
    "mixer",
    "xrd",
    "sem",
    "печ",
    "реактор",
    "автоклав",
    "ячейк",
    "мембран",
    "электролиз",
    "мешал",
    "микроскоп",
    "дифракт",
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


def extract_numeric_terms(*values: Any) -> list[str]:
    matches: list[str] = []
    for value in values:
        if isinstance(value, (dict, list)):
            text = json.dumps(value, ensure_ascii=False, default=str)
        else:
            text = str(value or "")
        matches.extend(NUMERIC_RE.findall(text))
    return unique_limited(matches, limit=12)


def extract_year_terms(*values: Any) -> list[str]:
    matches: list[str] = []
    for value in values:
        matches.extend(YEAR_RE.findall(str(value or "")))
    return unique_limited(matches, limit=12)


def query_decomposition(run: Any) -> list[dict[str, Any]]:
    plan = run.query_plan or {}
    query = getattr(run.request, "query", "")
    keywords = list(getattr(run, "keywords", []) or [])
    filters = plan.get("filters") if isinstance(plan.get("filters"), dict) else {}
    numeric_terms = extract_numeric_terms(query, filters)
    years = extract_year_terms(query, filters.get("time"), filters.get("period"), filters.get("year_from"), filters.get("year_to"))

    rows = [
        {
            "slot": "Материал",
            "values": unique_limited(list_values(plan.get("material_terms")) + keyword_matches(keywords, MATERIAL_HINTS)),
            "why": "ограничивают поиск материалами, рудами, сплавами и фазами",
        },
        {
            "slot": "Процесс",
            "values": unique_limited(list_values(plan.get("process_terms")) + keyword_matches(keywords, PROCESS_HINTS)),
            "why": "задают технологию или методику обработки",
        },
        {
            "slot": "Условия",
            "values": unique_limited(keyword_matches(keywords, CONDITION_HINTS) + list_values(filters.get("conditions"))),
            "why": "фиксируют технологические режимы до запуска поиска",
        },
        {
            "slot": "Числовые ограничения",
            "values": unique_limited(numeric_terms + list_values(filters.get("numeric_constraints"))),
            "why": "нужны для multiparameter-запросов и сравнения диапазонов",
        },
        {
            "slot": "География",
            "values": unique_limited(keyword_matches(keywords, GEOGRAPHY_HINTS) + list_values(filters.get("geography"))),
            "why": "показывает региональные ограничения и применимость практик",
        },
        {
            "slot": "Период",
            "values": unique_limited(years + list_values(filters.get("time") or filters.get("period"))),
            "why": "позволяет ограничить поиск по годам и строить временные тренды",
        },
        {
            "slot": "Свойства",
            "values": unique_limited(list_values(plan.get("property_terms")) + keyword_matches(keywords, PROPERTY_HINTS)),
            "why": "помогают ранжировать статьи по измеряемому эффекту",
        },
        {
            "slot": "Оборудование",
            "values": unique_limited(list_values(plan.get("equipment_terms")) + keyword_matches(keywords, EQUIPMENT_HINTS)),
            "why": "показывает установки, аппараты и аналитическое оборудование",
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


def comparison_rows_by_scope(run: Any, scope: str) -> list[dict[str, Any]]:
    comparison = getattr(run, "comparison", None)
    rows = getattr(comparison, "rows", []) if comparison else []
    return [row for row in rows if row.get("scope") == scope]


def top_terms(rows: list[dict[str, Any]], key: str, *, fallback_key: str | None = None, limit: int = 5) -> list[str]:
    counter: Counter[str] = Counter()
    for row in rows:
        values = list_values(row.get(key))
        if not values and fallback_key:
            values = list_values(row.get(fallback_key))
        for value in values:
            counter[compact_text(value, 80)] += 1
    return [item for item, _ in counter.most_common(limit)]


def confidence_label(score: float) -> str:
    if score >= 75:
        return "high"
    if score >= 45:
        return "medium"
    return "low"


def web_confidence(result: Any) -> tuple[int, str]:
    score = min(float(getattr(result, "score", 0) or 0) * 4, 55)
    if getattr(result, "doi", None):
        score += 10
    if getattr(result, "year", None):
        score += 8
    if getattr(result, "abstract", None):
        score += 8
    if getattr(result, "citation_count", None):
        score += min(float(result.citation_count), 300) / 15
    if getattr(result, "raw", None) and result.raw.get("journal_quartile"):
        score += {"Q1": 12, "Q2": 8, "Q3": 5, "Q4": 2}.get(str(result.raw.get("journal_quartile")), 0)
    value = int(min(round(score), 100))
    return value, confidence_label(value)


def local_confidence(row: dict[str, Any]) -> tuple[int, str]:
    score = min(float(row.get("score") or 0) * 18, 70)
    if row.get("doc_id"):
        score += 10
    if row.get("keyword_hits"):
        score += min(len(row.get("keyword_hits") or []), 4) * 4
    if row.get("preview"):
        score += 6
    value = int(min(round(score), 100))
    return value, confidence_label(value)


def year_span(values: list[int]) -> str:
    years = sorted({year for year in values if year})
    if not years:
        return "n/a"
    if len(years) == 1:
        return str(years[0])
    return f"{years[0]}-{years[-1]}"


def local_vs_world_dashboard(run: Any) -> list[dict[str, Any]]:
    local_method_rows = comparison_rows_by_scope(run, "local")
    web_method_rows = comparison_rows_by_scope(run, "web")
    web_confidences = [web_confidence(result)[0] for result in getattr(run, "results", []) or []]
    local_confidences = [local_confidence(row)[0] for row in getattr(run, "local_matches", []) or []]
    web_years = [int(result.year) for result in getattr(run, "results", []) or [] if getattr(result, "year", None)]
    local_years = [int(row["year"]) for row in getattr(run, "local_matches", []) or [] if str(row.get("year") or "").isdigit()]

    return [
        {
            "side": "Локальная база",
            "sources": len(getattr(run, "local_matches", []) or []),
            "top_methods": ", ".join(top_terms(local_method_rows, "method", fallback_key="processes")) or "n/a",
            "numeric_ranges": ", ".join(extract_numeric_terms(local_method_rows)) or "n/a",
            "geography": ", ".join(keyword_matches(getattr(run, "keywords", []) or [], GEOGRAPHY_HINTS)) or "n/a",
            "years": year_span(local_years),
            "confidence": confidence_label(sum(local_confidences) / len(local_confidences)) if local_confidences else "low",
            "evidence": "; ".join(compact_text(row.get("title") or row.get("doc_id"), 120) for row in (getattr(run, "local_matches", []) or [])[:3]) or "n/a",
        },
        {
            "side": "Мировая литература",
            "sources": len(getattr(run, "results", []) or []),
            "top_methods": ", ".join(top_terms(web_method_rows, "method", fallback_key="processes")) or ", ".join(getattr(run, "keywords", [])[:5]) or "n/a",
            "numeric_ranges": ", ".join(extract_numeric_terms(web_method_rows, [getattr(result, "abstract", "") for result in getattr(run, "results", []) or []])) or "n/a",
            "geography": ", ".join(keyword_matches(getattr(run, "keywords", []) or [], GEOGRAPHY_HINTS)) or "n/a",
            "years": year_span(web_years),
            "confidence": confidence_label(sum(web_confidences) / len(web_confidences)) if web_confidences else "low",
            "evidence": "; ".join(compact_text(getattr(result, "title", ""), 120) for result in (getattr(run, "results", []) or [])[:3]) or "n/a",
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
                "source": compact_text(row.get("doc_id") or row.get("result_id") or row.get("title"), 140),
                "confidence": compact_text(row.get("confidence") or ("medium" if row.get("scope") == "local" else "metadata/deep"), 80),
                "evidence": "; ".join(list_values(row.get("evidence"), max_chars=120)[:2]),
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


def evidence_cards(run: Any) -> list[dict[str, Any]]:
    cards: list[dict[str, Any]] = []
    for result in (getattr(run, "results", []) or [])[:20]:
        confidence_score, label = web_confidence(result)
        cards.append(
            {
                "kind": "web",
                "title": getattr(result, "title", ""),
                "source": getattr(result, "source", ""),
                "year": getattr(result, "year", None),
                "method": ", ".join(getattr(result, "keyword_hits", [])[:5]) or "metadata match",
                "numeric_ranges": ", ".join(extract_numeric_terms(getattr(result, "abstract", ""), getattr(result, "snippet", ""))) or "n/a",
                "confidence": f"{label} ({confidence_score}/100)",
                "why_relevant": ", ".join(getattr(result, "keyword_hits", [])[:8]) or compact_text(getattr(result, "abstract", ""), 180),
                "link": result_link(result),
            }
        )
    for row in (getattr(run, "local_matches", []) or [])[:20]:
        confidence_score, label = local_confidence(row)
        cards.append(
            {
                "kind": "local",
                "title": row.get("title") or row.get("doc_id") or row.get("source_path"),
                "source": row.get("kind") or "local_summary",
                "year": row.get("year") or "",
                "method": compact_text(row.get("preview") or row.get("kind"), 180),
                "numeric_ranges": ", ".join(extract_numeric_terms(row)) or "n/a",
                "confidence": f"{label} ({confidence_score}/100)",
                "why_relevant": ", ".join(list_values(row.get("keyword_hits"))) or compact_text(row.get("preview"), 180),
                "link": row.get("source_path") or row.get("doc_id") or "",
            }
        )
    return cards


def consensus_panel_rows(run: Any) -> list[dict[str, Any]]:
    comparison = getattr(run, "comparison", None)
    if not comparison:
        return []
    return [
        {
            "bucket": "Подтверждается несколькими источниками",
            "count": len(getattr(comparison, "confirmed_methods", []) or []),
            "evidence": "; ".join(compact_text(row.get("method") or row.get("material"), 120) for row in getattr(comparison, "confirmed_methods", [])[:4]),
            "action": "использовать как strongest evidence в brief",
        },
        {
            "bucket": "Только в локальной базе",
            "count": len(getattr(comparison, "local_only_methods", []) or []),
            "evidence": "; ".join(compact_text(row.get("method") or row.get("material"), 120) for row in getattr(comparison, "local_only_methods", [])[:4]),
            "action": "проверить как внутреннюю экспертизу или пробел внешнего поиска",
        },
        {
            "bucket": "Только в мировой литературе",
            "count": len(getattr(comparison, "web_only_methods", []) or []),
            "evidence": "; ".join(compact_text(row.get("method") or row.get("material"), 120) for row in getattr(comparison, "web_only_methods", [])[:4]),
            "action": "добавить как кандидатов на новые узлы графа",
        },
        {
            "bucket": "Отличаются условия или диапазоны",
            "count": len(getattr(comparison, "differing_conditions", []) or []),
            "evidence": "; ".join(compact_text(row.get("method") or row.get("material"), 120) for row in getattr(comparison, "differing_conditions", [])[:4]),
            "action": "вынести в contradiction review",
        },
    ]


def numeric_interval_rows(run: Any) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for card in evidence_cards(run):
        ranges = [item for item in (card.get("numeric_ranges") or "").split(", ") if item and item != "n/a"]
        for value in ranges[:4]:
            rows.append({"source": card["kind"], "title": compact_text(card["title"], 120), "value": value, "confidence": card["confidence"]})
    return rows[:80]


def mini_graph_edges(run: Any) -> list[dict[str, Any]]:
    edges: list[dict[str, Any]] = []
    for row in (getattr(getattr(run, "comparison", None), "rows", []) or [])[:60]:
        material = compact_text(row.get("material") or "Material", 80)
        method = compact_text(row.get("method") or ", ".join(list_values(row.get("processes"))[:2]) or "Process", 80)
        equipment = compact_text(", ".join(list_values(row.get("equipment"))[:2]) or "Equipment", 80)
        outputs = compact_text(", ".join(list_values(row.get("outputs") or row.get("observed_effects"))[:2]) or "Output", 80)
        scope = row.get("scope") or "unknown"
        edges.extend(
            [
                {"from": material, "to": method, "relation": "process", "scope": scope},
                {"from": method, "to": equipment, "relation": "uses", "scope": scope},
                {"from": equipment, "to": outputs, "relation": "produces", "scope": scope},
            ]
        )
    if not edges:
        for keyword in (getattr(run, "keywords", []) or [])[:6]:
            edges.append({"from": "Query", "to": keyword, "relation": "keyword", "scope": "query"})
    unique_edges: list[dict[str, Any]] = []
    seen: set[tuple[str, str, str, str]] = set()
    for edge in edges:
        key = (edge["from"], edge["to"], edge["relation"], edge["scope"])
        if key not in seen:
            seen.add(key)
            unique_edges.append(edge)
    return unique_edges[:80]


def graphviz_dot(run: Any) -> str:
    def quote(value: str) -> str:
        return '"' + value.replace("\\", "\\\\").replace('"', '\\"') + '"'

    lines = ["digraph G {", "rankdir=LR;", 'node [shape=box, style="rounded,filled", fillcolor="#f6f8fb", color="#b8c2d0"];']
    for edge in mini_graph_edges(run)[:40]:
        color = "#4f7cff" if edge.get("scope") == "web" else "#148a5b" if edge.get("scope") == "local" else "#777777"
        lines.append(f'{quote(edge["from"])} -> {quote(edge["to"])} [label={quote(edge["relation"])}, color="{color}"];')
    lines.append("}")
    return "\n".join(lines)


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
    dashboard = local_vs_world_dashboard(run)
    cards = evidence_cards(run)
    heatmap = method_heatmap_rows(run)
    key_findings = [
        f"Найдено {len(getattr(run, 'results', []) or [])} внешних источников и {len(getattr(run, 'local_matches', []) or [])} локальных совпадений.",
        f"Пересечения локальной базы с внешней литературой: {confirmed}; web-only методики: {web_only}; local-only методики: {local_only}.",
        f"Deep Search summaries: {len(getattr(run, 'deep_results', []) or [])}; method rows для сравнения: {len(getattr(comparison, 'rows', []) or []) if comparison else 0}.",
    ]
    if dashboard:
        key_findings.append("Local vs World: " + "; ".join(f"{row['side']} confidence={row['confidence']}, sources={row['sources']}" for row in dashboard))
    if heatmap:
        key_findings.append("Самые плотные комбинации material x process: " + "; ".join(f"{row['material']} / {row['method']} ({row['status']})" for row in heatmap[:2]))
    key_findings = unique_limited(key_findings, limit=5)
    risks = [
        row["recommendation"]
        for row in gap_radar_rows(run)
        if row["level"] not in {"OK", "возможность"} and row["value"] not in (0, "0/0")
    ][:3]
    gaps = [
        f"{row['material']} / {row['method']}: {row['status']}"
        for row in heatmap
        if row["status"] in {"только локально", "только web"}
    ][:3]
    if not gaps and web_only:
        gaps.append("Есть методики во внешней литературе, которые не совпали с локальными procedure summaries.")
    if not gaps and local_only:
        gaps.append("Есть локальные методики без подтверждения во внешнем top-N Deep Search.")
    next_steps = [
        "Запустить Deep Search для top-N источников перед финальным отчетом.",
        "Проверить строки contradiction panel с разными условиями и числовыми диапазонами.",
        "Добавить web-only методики как кандидаты на новые узлы графа знаний.",
    ]
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
        "## 5 ключевых выводов",
        "",
    ]
    rows.extend(f"- {finding}" for finding in key_findings[:5])
    rows.extend(["", "## 3 риска", ""])
    rows.extend(f"- {risk}" for risk in (risks or ["Недостаточно Deep Search summaries для уверенного сравнения методик."])[:3])
    rows.extend(["", "## 3 пробела", ""])
    rows.extend(f"- {gap}" for gap in (gaps or ["Gap radar не выявил явных local-only/web-only комбинаций; стоит расширить запрос или top-N."])[:3])
    rows.extend(["", "## Рекомендуемые следующие эксперименты/литературные направления", ""])
    rows.extend(f"- {step}" for step in next_steps)

    rows.extend(["", "## Top-5 релевантных источников", ""])
    if top_sources:
        for index, result in enumerate(top_sources[:5], start=1):
            link = result_link(result)
            label = compact_text(getattr(result, "title", ""), 240)
            rows.append(f"{index}. [{label}]({link})" if link else f"{index}. {label}")
    else:
        rows.append("Внешние источники не найдены.")

    rows.extend(["", "## Evidence highlights", ""])
    for card in cards[:5]:
        rows.append(f"- {card['kind']}: {compact_text(card['title'], 160)}; confidence={card['confidence']}; why={compact_text(card['why_relevant'], 160)}")

    rows.extend(["", "## Рекомендации", ""])
    recommendations_added = False
    for row in gap_radar_rows(run):
        if row["level"] != "OK" and row["value"] not in (0, "0/0"):
            rows.append(f"- {row['signal']}: {row['recommendation']}.")
            recommendations_added = True
    if not recommendations_added:
        rows.append("- Расширить запрос или включить Deep Search для top-N статей перед финальной демонстрацией.")
    return "\n".join(rows).strip() + "\n"
