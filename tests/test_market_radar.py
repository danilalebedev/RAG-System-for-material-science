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
