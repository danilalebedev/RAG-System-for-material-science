from __future__ import annotations

import json
import subprocess
import sys

import pandas as pd

from app.market.charts import prepare_market_chart_df
from app.market.normalization import normalize_unit_value
from app.market.parsers import LIVE_PARSER_PLACEHOLDERS
from app.market.radar import detect_market_query, production_dashboard_rows, run_market_radar
from app.market.sources import REQUIRED_PRODUCTION_SOURCE_IDS, SOURCE_REGISTRY


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


def test_market_chart_single_row_has_flat_string_columns() -> None:
    chart_df = prepare_market_chart_df(
        [{"period": "2024", "entity": "Russia", "commodity": "nickel", "value": 220, "unit": "kt"}],
        index="period",
        columns=["entity", "commodity"],
    )

    assert not chart_df.empty
    assert not isinstance(chart_df.columns, pd.MultiIndex)
    assert list(chart_df.columns) == ["Russia · nickel"]
    assert list(chart_df.index) == ["2024"]


def test_market_chart_multiple_commodities_flattens_columns() -> None:
    chart_df = prepare_market_chart_df(
        [
            {"period": "2024", "entity": "Nornickel", "commodity": "nickel", "value": 205},
            {"period": "2024", "entity": "Nornickel", "commodity": "copper", "value": 433},
            {"period": "2024", "entity": "Russia", "commodity": "nickel", "value": 220},
        ],
        index="period",
        columns=["entity", "commodity"],
    )

    assert not chart_df.empty
    assert not isinstance(chart_df.columns, pd.MultiIndex)
    assert set(chart_df.columns) == {"Nornickel · copper", "Nornickel · nickel", "Russia · nickel"}
    assert all(isinstance(column, str) for column in chart_df.columns)


def test_market_chart_empty_data_is_empty_dataframe() -> None:
    chart_df = prepare_market_chart_df([], index="period", columns=["entity", "commodity"])

    assert chart_df.empty


def test_production_dashboard_schema_rows_are_dashboard_ready() -> None:
    result = run_market_radar("How much nickel did Nornickel produce in the latest period?")
    rows = production_dashboard_rows(result.production_rows)

    assert rows
    for row in rows:
        assert set(row) == {
            "commodity",
            "producer_or_country",
            "period",
            "value",
            "unit",
            "source_url",
            "confidence",
        }
        assert row["commodity"]
        assert row["producer_or_country"]
        assert row["period"]
        assert row["unit"]
        assert row["source_url"]
        assert row["confidence"] in {"high", "medium", "low"}


def test_source_registry_contains_required_production_source_families() -> None:
    source_ids = {source.source_id for source in SOURCE_REGISTRY}

    assert set(REQUIRED_PRODUCTION_SOURCE_IDS).issubset(source_ids)
    assert set(REQUIRED_PRODUCTION_SOURCE_IDS).issubset(LIVE_PARSER_PLACEHOLDERS)


def test_run_production_radar_wrapper_outputs_dashboard_rows() -> None:
    completed = subprocess.run(
        [
            sys.executable,
            "scripts/run_production_radar.py",
            "How much nickel did Nornickel produce?",
        ],
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    payload = json.loads(completed.stdout)

    assert payload["agent"] == "Agent F - Business / Production Radar"
    assert payload["dashboard_rows"]
    assert payload["dashboard_rows"][0]["commodity"] == "nickel"
    assert "producer_or_country" in payload["dashboard_rows"][0]


def test_source_credibility_panel_data_exists() -> None:
    result = run_market_radar("How much nickel did Nornickel produce?")

    assert result.source_credibility
    first = result.source_credibility[0]
    assert first.source_name
    assert first.source_url
    assert first.source_type in {
        "official_statistics",
        "company_report",
        "industry_association",
        "demo_fixture",
        "planned_connector",
    }
    assert first.mode in {"live", "fallback", "stub"}
    assert first.date_accessed
    assert first.confidence in {"high", "medium", "low"}
    assert first.caveat


def test_business_implications_for_nickel_russia_and_nornickel() -> None:
    russia = run_market_radar("Show Russia nickel production")
    nornickel = run_market_radar("How much nickel did Nornickel produce?")
    text = " ".join(russia.business_implications + nornickel.business_implications).lower()

    assert "nickel ore" in text
    assert "sulfide concentrates" in text
    assert "smelting" in text
    assert "leaching" in text
    assert "npi" in text
    assert "pgm by-products" in text


def test_related_internal_terms_for_core_commodities() -> None:
    expectations = {
        "nickel": ["никелевая руда", "никелевые сульфидные концентраты", "NPI"],
        "copper": ["медная руда", "медно-никелевые концентраты", "штейн", "шлак"],
        "palladium platinum": ["МПГ", "платиновые металлы", "потери МПГ"],
        "aluminium": ["глинозём", "первичный алюминий", "электролиз алюминия"],
        "steel": ["сталь", "чугун", "DRI", "доменное производство"],
    }

    for query, expected_terms in expectations.items():
        result = run_market_radar(query)
        for term in expected_terms:
            assert term in result.internal_knowledge_terms


def test_market_radar_handles_empty_production_rows() -> None:
    result = run_market_radar("zirconium 1999")

    assert result.production_rows == []
    assert result.source_credibility
    assert result.business_implications
    assert result.charts["time_series"] == []
    assert result.charts["latest_comparison"] == []


def test_market_radar_handles_stub_sources_without_live_fetch() -> None:
    result = run_market_radar("How much nickel did Nornickel produce?", demo_mode=False)

    assert result.production_rows == []
    assert result.source_credibility
    assert all(item.mode == "stub" for item in result.source_credibility)
    assert result.business_implications
