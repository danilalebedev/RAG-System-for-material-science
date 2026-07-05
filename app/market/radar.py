from __future__ import annotations

import re
from collections import defaultdict
from typing import Iterable

from app.market.normalization import latest_rows, normalize_rows, period_sort_key
from app.market.parsers import load_rows_for_source
from app.market.schemas import Commodity, MarketDataRow, MarketQuery, MarketRadarResult, MarketSource, SourceStatus
from app.market.sources import DEFAULT_COMMODITIES, select_sources


COMMODITY_ALIASES: dict[Commodity, tuple[str, ...]] = {
    "nickel": ("nickel", "ni", "никель", "никеля", "никеле", "никелевая", "никелевой"),
    "copper": ("copper", "cu", "медь", "меди", "медный", "медная"),
    "palladium": ("palladium", "pd", "палладий", "палладия"),
    "platinum": ("platinum", "pt", "платина", "платины"),
    "steel": ("steel", "сталь", "стали", "crude steel"),
    "aluminium": ("aluminium", "aluminum", "al", "алюминий", "алюминия"),
    "alumina": ("alumina", "глинозем", "глинозёма", "al2o3"),
    "iron ore": ("iron ore", "железная руда", "железной руды", "руда железа"),
    "cobalt": ("cobalt", "co", "кобальт", "кобальта"),
    "lithium": ("lithium", "li", "литий", "лития"),
    "company financials": ("выручка", "продажи", "revenue", "sales", "финансы", "financials"),
}

COMPANY_ALIASES: dict[str, tuple[str, ...]] = {
    "Nornickel": ("норникель", "норильский никель", "nornickel", "norilsk nickel"),
    "RUSAL": ("rusal", "русал"),
    "Severstal": ("severstal", "северсталь"),
    "NLMK": ("nlmk", "нлмк"),
    "MMK": ("mmk", "ммк"),
    "Metalloinvest": ("metalloinvest", "металлоинвест"),
}

COUNTRY_ALIASES: dict[str, tuple[str, ...]] = {
    "Russia": ("россия", "россии", "russia", "russian"),
    "China": ("китай", "китае", "china", "chinese"),
    "India": ("индия", "индии", "india"),
    "Turkey": ("турция", "турции", "turkey"),
    "Indonesia": ("индонезия", "индонезии", "indonesia"),
    "Philippines": ("филиппины", "philippines"),
    "New Caledonia": ("новая каледония", "new caledonia"),
}

INTERNAL_TERMS_BY_COMMODITY: dict[Commodity, tuple[str, ...]] = {
    "nickel": ("никелевая руда", "никелевые руды", "сульфидные никелевые концентраты", "латеритные никелевые руды"),
    "copper": ("медные концентраты", "медная руда", "Cu recovery"),
    "palladium": ("PGM", "платиноиды", "палладиевые концентраты"),
    "platinum": ("PGM", "платиноиды", "платиновые концентраты"),
}

WATER_TREATMENT_TERMS = (
    "подготовка воды",
    "подготовк",
    "водоподготовка",
    "обессоливание",
    "очистка воды",
    "шахтные воды",
    "скважин",
    "сухой остаток",
    "сульфат",
    "хлорид",
    "кальци",
    "магни",
    "натри",
    "water treatment",
    "water preparation",
    "desalination",
    "mine water",
    "groundwater",
    "tds",
    "sulfate",
    "chloride",
)
TECHNO_ECONOMIC_TERMS = (
    "технико-эконом",
    "капекс",
    "capex",
    "опекс",
    "opex",
    "tco",
    "стоимость",
    "затраты",
    "энергопотреб",
    "энергозатрат",
    "реагент",
    "производительность",
    "вариант",
    "сравнение",
    "cost",
    "energy",
    "reagent",
    "throughput",
)
FINANCIAL_TERMS = (
    "выруч",
    "продаж",
    "реализац",
    "оборот",
    "revenue",
    "sales",
    "financial",
    "market size",
)

YEAR_RE = re.compile(r"\b(?:19|20)\d{2}\b")


def _contains_alias(text: str, aliases: Iterable[str]) -> bool:
    folded = text.lower()
    for alias in aliases:
        alias_folded = alias.lower()
        if len(alias_folded) <= 2 and alias_folded.isascii():
            pattern = rf"(?<![a-zа-я0-9]){re.escape(alias_folded)}(?![a-zа-я0-9])"
            if re.search(pattern, folded):
                return True
            continue
        if alias_folded in folded:
            return True
    return False


def detect_market_query(query: str) -> MarketQuery:
    folded = query.lower()
    commodities = [commodity for commodity, aliases in COMMODITY_ALIASES.items() if _contains_alias(folded, aliases)]
    if any(term in folded for term in WATER_TREATMENT_TERMS) and "water treatment" not in commodities:
        commodities.append("water treatment")
    if any(term in folded for term in FINANCIAL_TERMS) and "company financials" not in commodities:
        commodities.append("company financials")
    companies = [company for company, aliases in COMPANY_ALIASES.items() if _contains_alias(folded, aliases)]
    countries = [country for country, aliases in COUNTRY_ALIASES.items() if _contains_alias(folded, aliases)]
    periods = sorted(set(YEAR_RE.findall(query)))
    latest_requested = any(token in folded for token in ("последн", "latest", "current", "свеж"))
    link_internal_terms = any(token in folded for token in ("свяжи", "связать", "internal", "внутренн", "документ"))

    if not commodities and any(company == "Nornickel" for company in companies):
        commodities = list(DEFAULT_COMMODITIES)
    if not commodities and any(token in folded for token in ("pgm", "платиноид")):
        commodities = ["palladium", "platinum"]

    if "water treatment" in commodities and any(token in folded for token in TECHNO_ECONOMIC_TERMS):
        intent = "techno_economic_water_treatment"
    elif "company financials" in commodities and (companies or any(token in folded for token in FINANCIAL_TERMS)):
        intent = "company_financials"
    elif any(token in folded for token in ("динамик", "time series", "по годам", "trend")):
        intent = "time_series"
    elif any(token in folded for token in ("сравн", "compare", "топ", "ranking", "роль")):
        intent = "market_comparison"
    elif companies:
        intent = "company_production"
    elif countries:
        intent = "country_production"
    else:
        intent = "commodity_overview"

    return MarketQuery(
        original_query=query,
        intent=intent,
        commodities=commodities,
        companies=companies,
        countries=countries,
        periods=periods,
        latest_requested=latest_requested,
        link_internal_terms=link_internal_terms,
    )


def _row_matches(row: MarketDataRow, detected: MarketQuery) -> bool:
    if detected.commodities and row.commodity not in detected.commodities:
        requested_business_only = detected.commodities == ["company financials"]
        if not (requested_business_only and row.metric in {"revenue", "sales"}):
            return False
    if detected.periods and row.period not in detected.periods:
        return False
    if detected.companies and row.company_or_country not in detected.companies:
        return False
    if detected.countries and row.company_or_country not in detected.countries:
        if not detected.companies:
            return False
    return True


def _load_source_rows(sources: Iterable[MarketSource], *, demo_mode: bool) -> tuple[list[MarketDataRow], list[SourceStatus]]:
    rows: list[MarketDataRow] = []
    statuses: list[SourceStatus] = []
    for source in sources:
        source_rows, status = load_rows_for_source(source, demo_mode=demo_mode)
        rows.extend(source_rows)
        statuses.append(status)
    return rows, statuses


def _rank_rows(rows: Iterable[MarketDataRow]) -> list[MarketDataRow]:
    confidence_weight = {"high": 0, "medium": 1, "low": 2}
    return sorted(
        rows,
        key=lambda row: (
            row.company_or_country,
            row.commodity,
            confidence_weight.get(row.confidence, 3),
            period_sort_key(row.period),
        ),
        reverse=False,
    )


def _row_label(row: MarketDataRow) -> str:
    labels = {
        "production": "производство",
        "sales": "продажи",
        "revenue": "выручка",
        "capacity": "мощность",
        "capex": "CAPEX",
        "opex": "OPEX",
        "energy": "энергия",
        "reagents": "реагенты",
    }
    metric = labels.get(row.metric, row.metric)
    if row.commodity == "company financials":
        return metric
    return f"{metric}: {row.commodity}"


def _build_charts(rows: list[MarketDataRow]) -> dict[str, list[dict[str, object]]]:
    time_series = [
        {
            "period": row.period,
            "entity": row.company_or_country,
            "commodity": row.commodity,
            "metric": row.metric,
            "label": _row_label(row),
            "value": row.value,
            "unit": row.unit,
        }
        for row in sorted(rows, key=lambda item: (period_sort_key(item.period), item.company_or_country, item.commodity))
    ]
    latest = latest_rows(rows)
    comparison = [
        {
            "entity": row.company_or_country,
            "commodity": row.commodity,
            "metric": row.metric,
            "label": _row_label(row),
            "period": row.period,
            "value": row.value,
            "unit": row.unit,
        }
        for row in latest
    ]
    return {"time_series": time_series, "latest_comparison": comparison}


def _summary(rows: list[MarketDataRow], detected: MarketQuery) -> str:
    if not rows:
        return "Данных по запросу в доступных источниках Market Radar не найдено. Проверьте выбранные компании, страны или период."

    if detected.intent == "techno_economic_water_treatment":
        technologies = sorted({row.company_or_country for row in rows})
        metrics = sorted({row.metric for row in rows})
        return (
            "Techno-economic radar собрал demo-диапазоны и cost-драйверы по водоподготовке: "
            + ", ".join(technologies[:8])
            + ". Покрытые показатели: "
            + ", ".join(metrics[:8])
            + ". Это не смета CAPEX/OPEX, а shortlist для сравнения и постановки расчета."
        )

    latest = latest_rows(rows) if detected.latest_requested or detected.intent != "time_series" else rows
    grouped: dict[str, list[str]] = defaultdict(list)
    for row in latest:
        grouped[row.company_or_country].append(f"{_row_label(row)}: {row.value} {row.unit} ({row.period})")

    parts = [f"{entity}: " + "; ".join(values) for entity, values in grouped.items()]
    prefix = "Market Radar собрал проверяемые производственные, рыночные и финансовые показатели без LLM-синтеза чисел."
    return prefix + " " + " | ".join(parts[:8])


def _missing_data(rows: list[MarketDataRow], detected: MarketQuery, statuses: list[SourceStatus]) -> list[str]:
    missing: list[str] = []
    if detected.intent == "techno_economic_water_treatment":
        if rows:
            missing.extend(
                [
                    "Нет проектной производительности обогатительной фабрики, м3/ч.",
                    "Нет лабораторной ионной матрицы исходной воды по сезонам.",
                    "Нет требований по концентрату/рассолу: сброс, возврат, ZLD или утилизация.",
                    "Нет локальных цен на электроэнергию, реагенты, мембраны и утилизацию осадка/рассола.",
                ]
            )
            return missing
        missing.append("Нет demo-строк по технико-экономике водоподготовки.")
    if not rows:
        missing.append("Нет строк, совпавших с выбранными commodity/company/country/period фильтрами.")
    available_keys = {(row.company_or_country, row.commodity) for row in rows}
    for company in detected.companies:
        for commodity in detected.commodities:
            if (company, commodity) not in available_keys:
                missing.append(f"Нет production row для {company} / {commodity}.")
    unavailable = [status.source_name for status in statuses if status.status == "unavailable"]
    if unavailable:
        missing.append("Live загрузка отключена или недоступна: " + ", ".join(unavailable))
    return missing


def _suggested_sources(detected: MarketQuery, rows: list[MarketDataRow]) -> list[str]:
    suggestions: list[str] = []
    if detected.intent == "techno_economic_water_treatment":
        return [
            "Добавить коммерческие предложения/опросные листы по RO/NF/EDR/IX для конкретной производительности.",
            "Добавить результаты jar-test/пилотных испытаний по scaling/fouling для воды скважины 120.",
            "Добавить локальные тарифы и регламент обращения с концентратом/осадком.",
        ]
    if detected.companies and not rows:
        suggestions.append("Добавить последний quarterly/annual production report компании.")
    if detected.countries:
        suggestions.append("Проверить свежий выпуск World Steel / IAI / USGS по выбранной commodity.")
    if not detected.periods and detected.latest_requested:
        suggestions.append("Для публичного демо актуализировать fixture/cache после проверки официального отчета.")
    return suggestions


def _internal_terms(detected: MarketQuery) -> list[str]:
    if not detected.link_internal_terms and not any(item in detected.commodities for item in ("nickel", "copper", "palladium", "platinum")):
        return []
    terms: list[str] = []
    for commodity in detected.commodities:
        for term in INTERNAL_TERMS_BY_COMMODITY.get(commodity, ()):
            if term not in terms:
                terms.append(term)
    return terms


def run_market_radar(query: str, *, demo_mode: bool = True) -> MarketRadarResult:
    detected = detect_market_query(query)
    selected_sources = select_sources(detected)
    loaded_rows, source_status = _load_source_rows(selected_sources, demo_mode=demo_mode)
    normalized_rows, warnings = normalize_rows(loaded_rows)
    matched_rows = _rank_rows(row for row in normalized_rows if _row_matches(row, detected))

    if detected.latest_requested and matched_rows:
        matched_rows = latest_rows(matched_rows)

    return MarketRadarResult(
        query=query,
        detected=detected,
        selected_sources=selected_sources,
        production_rows=matched_rows,
        market_summary=_summary(matched_rows, detected),
        source_status=source_status,
        missing_data=_missing_data(matched_rows, detected, source_status),
        warnings=warnings,
        suggested_sources=_suggested_sources(detected, matched_rows),
        internal_knowledge_terms=_internal_terms(detected),
        charts=_build_charts(matched_rows),
    )
