from __future__ import annotations

from app.market.normalization import normalize_unit_value
from app.market.radar import detect_market_query, run_market_radar


def test_nornickel_latest_production_query_returns_core_metals() -> None:
    result = run_market_radar(
        "Сколько никеля, меди, палладия и платины произвёл Норникель в последнем доступном периоде?"
    )

    assert result.detected.companies == ["Nornickel"]
    assert set(result.detected.commodities) == {"nickel", "copper", "palladium", "platinum"}
    assert {row.commodity for row in result.production_rows} == {"nickel", "copper", "palladium", "platinum"}
    assert all(row.period == "2024" for row in result.production_rows)
    assert result.market_summary
    assert any(status.status == "fallback" for status in result.source_status)


def test_steel_country_comparison_detects_countries() -> None:
    result = run_market_radar("Сравни производство стали в России, Китае, Индии и Турции.")

    assert result.detected.intent == "market_comparison"
    assert result.detected.commodities == ["steel"]
    assert set(result.detected.countries) == {"Russia", "China", "India", "Turkey"}
    assert {row.company_or_country for row in result.production_rows} == {"Russia", "China", "India", "Turkey"}


def test_aluminium_region_query_uses_iai_fixture() -> None:
    result = run_market_radar("Покажи мировое производство алюминия по регионам.")

    assert "aluminium" in result.detected.commodities
    assert any(row.source_name == "International Aluminium Institute statistics" for row in result.production_rows)
    assert result.charts["latest_comparison"]


def test_normalize_mln_t_to_mt() -> None:
    value, unit, warning = normalize_unit_value("3.8", "mln t")

    assert value == 3.8
    assert unit == "Mt"
    assert warning


def test_short_chemical_alias_does_not_match_inside_words() -> None:
    detected = detect_market_query("Compare copper production by country")

    assert "copper" in detected.commodities
    assert "cobalt" not in detected.commodities


def test_water_treatment_teo_query_returns_engineering_economics() -> None:
    result = run_market_radar(
        "Технико-экономическое сравнение вариантов подготовки воды и обессоливания для обогатительной фабрики: "
        "сульфаты, хлориды, кальций, магний, натрий, сухой остаток"
    )

    assert result.detected.intent == "techno_economic_water_treatment"
    assert result.detected.commodities == ["water treatment"]
    technologies = {row.company_or_country for row in result.production_rows}
    assert "Обратный осмос (RO)" in technologies
    assert "Электродиализ / EDR" in technologies
    assert any(row.metric == "energy" for row in result.production_rows)
    assert "Techno-economic radar" in result.market_summary
    assert result.missing_data


def test_water_treatment_teo_query_matches_full_demo_wording() -> None:
    result = run_market_radar(
        "Технико-экономическое сравнение вариантов подготовки воды (обессоливания) для предприятий "
        "горно-металлургической промышленности (обогатительная фабрика). Уточнения для сужения области поиска: "
        "Требования к воде - содержание сульфатов, хлоридов, кальция, магния, натрия - 200-300 мг/л каждого; "
        "сухой остаток - 1000 мг/дм3. Исходная вода из скважины 120 и содержит на порядок больше солей."
    )

    assert result.detected.intent == "techno_economic_water_treatment"
    assert result.production_rows


def test_business_financial_query_returns_revenue_and_sales_facts() -> None:
    result = run_market_radar("Сравни выручку и продажи металлургических компаний за 2024 год")

    assert result.detected.intent == "company_financials"
    assert "company financials" in result.detected.commodities
    metrics = {row.metric for row in result.production_rows}
    assert {"revenue", "sales"} <= metrics
    assert any(row.company_or_country == "Nornickel" and row.value == 12.5 for row in result.production_rows)
    assert all(row.source_url.startswith(("http://", "https://")) for row in result.production_rows)
    assert "финансовые показатели" in result.market_summary
