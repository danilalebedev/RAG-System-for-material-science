from __future__ import annotations

from app.market.schemas import Commodity, MarketQuery, MarketSource


SOURCE_REGISTRY: tuple[MarketSource, ...] = (
    MarketSource(
        source_id="nornickel_reports",
        source_name="Nornickel reports / interactive database",
        source_url="https://www.nornickel.com/investors/reports-and-results/",
        source_type="company_report",
        commodities=["nickel", "copper", "palladium", "platinum"],
        entities=["норникель", "nornickel", "norilsk nickel"],
        reliability_rank=95,
    ),
    MarketSource(
        source_id="rusal_reports",
        source_name="RUSAL operating results",
        source_url="https://rusal.ru/en/investors/results-and-reports/",
        source_type="company_report",
        commodities=["aluminium", "alumina"],
        entities=["rusal", "русал"],
        reliability_rank=92,
    ),
    MarketSource(
        source_id="worldsteel_data",
        source_name="World Steel Association data",
        source_url="https://worldsteel.org/data/",
        source_type="industry_association",
        commodities=["steel"],
        entities=["worldsteel", "steel", "сталь", "world steel association"],
        reliability_rank=90,
    ),
    MarketSource(
        source_id="international_aluminium_institute",
        source_name="International Aluminium Institute statistics",
        source_url="https://international-aluminium.org/statistics/",
        source_type="industry_association",
        commodities=["aluminium", "alumina"],
        entities=["international aluminium institute", "iai", "aluminium", "алюминий"],
        reliability_rank=90,
    ),
    MarketSource(
        source_id="usgs_mcs",
        source_name="USGS Mineral Commodity Summaries",
        source_url="https://www.usgs.gov/centers/national-minerals-information-center/mineral-commodity-summaries",
        source_type="official_statistics",
        commodities=["nickel", "copper", "cobalt", "lithium", "iron ore", "palladium", "platinum"],
        entities=["usgs", "mineral commodity summaries", "страны", "country", "world"],
        reliability_rank=88,
    ),
    MarketSource(
        source_id="rosstat_fedstat_emiss",
        source_name="Rosstat / Fedstat / EMISS",
        source_url="https://fedstat.ru/",
        source_type="official_statistics",
        commodities=["steel", "aluminium", "nickel", "copper", "iron ore"],
        entities=["rosstat", "fedstat", "emiss", "росстат", "россия"],
        reliability_rank=85,
    ),
    MarketSource(
        source_id="severstal_reports",
        source_name="Severstal operating results",
        source_url="https://severstal.com/eng/ir/results_reports/",
        source_type="company_report",
        commodities=["steel", "iron ore"],
        entities=["severstal", "северсталь"],
        reliability_rank=84,
    ),
    MarketSource(
        source_id="nlmk_reports",
        source_name="NLMK operating results",
        source_url="https://nlmk.com/en/ir/results-center/",
        source_type="company_report",
        commodities=["steel"],
        entities=["nlmk", "нлмк"],
        reliability_rank=84,
    ),
    MarketSource(
        source_id="mmk_reports",
        source_name="MMK operating results",
        source_url="https://mmk.ru/en/investor/results-and-reports/",
        source_type="company_report",
        commodities=["steel"],
        entities=["mmk", "ммк"],
        reliability_rank=84,
    ),
    MarketSource(
        source_id="metalloinvest_reports",
        source_name="Metalloinvest reports",
        source_url="https://www.metalloinvest.com/investors/reports/",
        source_type="company_report",
        commodities=["iron ore", "steel"],
        entities=["metalloinvest", "металлоинвест"],
        reliability_rank=84,
    ),
)

REQUIRED_PRODUCTION_SOURCE_IDS: tuple[str, ...] = (
    "rosstat_fedstat_emiss",
    "worldsteel_data",
    "international_aluminium_institute",
    "usgs_mcs",
    "nornickel_reports",
    "rusal_reports",
    "severstal_reports",
    "nlmk_reports",
    "mmk_reports",
    "metalloinvest_reports",
)

SOURCE_FAMILY_LABELS: dict[str, str] = {
    "rosstat_fedstat_emiss": "Fedstat / Rosstat / EMISS",
    "worldsteel_data": "World Steel Association",
    "international_aluminium_institute": "International Aluminium Institute",
    "usgs_mcs": "USGS Mineral Commodity Summaries",
    "nornickel_reports": "Nornickel reports / interactive database",
    "rusal_reports": "RUSAL reports",
    "severstal_reports": "Severstal reports",
    "nlmk_reports": "NLMK reports",
    "mmk_reports": "MMK reports",
    "metalloinvest_reports": "Metalloinvest reports",
}


DEFAULT_COMMODITIES: list[Commodity] = ["nickel", "copper", "palladium", "platinum"]


def get_source(source_id: str) -> MarketSource | None:
    return next((source for source in SOURCE_REGISTRY if source.source_id == source_id), None)


def select_sources(detected: MarketQuery) -> list[MarketSource]:
    query_text = detected.original_query.lower()
    selected: dict[str, MarketSource] = {}

    for source in SOURCE_REGISTRY:
        commodity_match = bool(set(detected.commodities) & set(source.commodities))
        entity_match = any(entity.lower() in query_text for entity in source.entities)
        company_match = any(company.lower() in source.entities for company in detected.companies)
        country_match = bool(detected.countries) and source.source_id in {
            "worldsteel_data",
            "international_aluminium_institute",
            "usgs_mcs",
            "rosstat_fedstat_emiss",
        }
        if commodity_match or entity_match or company_match or country_match:
            selected[source.source_id] = source

    if not selected:
        for source in SOURCE_REGISTRY:
            if source.source_id in {"nornickel_reports", "worldsteel_data", "usgs_mcs"}:
                selected[source.source_id] = source

    return sorted(selected.values(), key=lambda source: source.reliability_rank, reverse=True)
