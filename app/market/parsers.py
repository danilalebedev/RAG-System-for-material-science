from __future__ import annotations

from datetime import date

from app.market.schemas import MarketDataRow, MarketSource, SourceStatus


TODAY = date.today().isoformat()


def fixture_rows() -> list[MarketDataRow]:
    return [
        MarketDataRow(source_name="Nornickel production reports", source_url="https://www.nornickel.com/investors/reports-and-results/", date_accessed=TODAY, company_or_country="Nornickel", commodity="nickel", metric="production", period="2023", value=209, unit="kt", confidence="medium", notes="Demo fixture for stable offline presentation.", raw_evidence="Nornickel annual production table style: nickel output by year, kt."),
        MarketDataRow(source_name="Nornickel production reports", source_url="https://www.nornickel.com/investors/reports-and-results/", date_accessed=TODAY, company_or_country="Nornickel", commodity="nickel", metric="production", period="2024", value=205, unit="kt", confidence="medium", notes="Demo fixture for stable offline presentation.", raw_evidence="Nickel production latest annual period, kt."),
        MarketDataRow(source_name="Nornickel production reports", source_url="https://www.nornickel.com/investors/reports-and-results/", date_accessed=TODAY, company_or_country="Nornickel", commodity="copper", metric="production", period="2023", value=425, unit="kt", confidence="medium", notes="Demo fixture for stable offline presentation.", raw_evidence="Copper production annual table, kt."),
        MarketDataRow(source_name="Nornickel production reports", source_url="https://www.nornickel.com/investors/reports-and-results/", date_accessed=TODAY, company_or_country="Nornickel", commodity="copper", metric="production", period="2024", value=433, unit="kt", confidence="medium", notes="Demo fixture for stable offline presentation.", raw_evidence="Copper production latest annual period, kt."),
        MarketDataRow(source_name="Nornickel production reports", source_url="https://www.nornickel.com/investors/reports-and-results/", date_accessed=TODAY, company_or_country="Nornickel", commodity="palladium", metric="production", period="2023", value=2692, unit="koz", confidence="medium", notes="Demo fixture for stable offline presentation.", raw_evidence="Palladium production annual table, thousand ounces."),
        MarketDataRow(source_name="Nornickel production reports", source_url="https://www.nornickel.com/investors/reports-and-results/", date_accessed=TODAY, company_or_country="Nornickel", commodity="palladium", metric="production", period="2024", value=2762, unit="koz", confidence="medium", notes="Demo fixture for stable offline presentation.", raw_evidence="Palladium production latest annual period, koz."),
        MarketDataRow(source_name="Nornickel production reports", source_url="https://www.nornickel.com/investors/reports-and-results/", date_accessed=TODAY, company_or_country="Nornickel", commodity="platinum", metric="production", period="2023", value=664, unit="koz", confidence="medium", notes="Demo fixture for stable offline presentation.", raw_evidence="Platinum production annual table, thousand ounces."),
        MarketDataRow(source_name="Nornickel production reports", source_url="https://www.nornickel.com/investors/reports-and-results/", date_accessed=TODAY, company_or_country="Nornickel", commodity="platinum", metric="production", period="2024", value=667, unit="koz", confidence="medium", notes="Demo fixture for stable offline presentation.", raw_evidence="Platinum production latest annual period, koz."),
        MarketDataRow(source_name="World Steel Association data", source_url="https://worldsteel.org/data/", date_accessed=TODAY, company_or_country="China", commodity="steel", metric="production", period="2024", value=1005, unit="Mt", confidence="medium", notes="Demo fixture for country comparison.", raw_evidence="Crude steel production by country, Mt."),
        MarketDataRow(source_name="World Steel Association data", source_url="https://worldsteel.org/data/", date_accessed=TODAY, company_or_country="India", commodity="steel", metric="production", period="2024", value=149, unit="Mt", confidence="medium", notes="Demo fixture for country comparison.", raw_evidence="Crude steel production by country, Mt."),
        MarketDataRow(source_name="World Steel Association data", source_url="https://worldsteel.org/data/", date_accessed=TODAY, company_or_country="Russia", commodity="steel", metric="production", period="2024", value=71, unit="Mt", confidence="medium", notes="Demo fixture for country comparison.", raw_evidence="Crude steel production by country, Mt."),
        MarketDataRow(source_name="World Steel Association data", source_url="https://worldsteel.org/data/", date_accessed=TODAY, company_or_country="Turkey", commodity="steel", metric="production", period="2024", value=37, unit="Mt", confidence="medium", notes="Demo fixture for country comparison.", raw_evidence="Crude steel production by country, Mt."),
        MarketDataRow(source_name="International Aluminium Institute statistics", source_url="https://international-aluminium.org/statistics/", date_accessed=TODAY, company_or_country="China", commodity="aluminium", metric="production", period="2024", value=43.4, unit="Mt", confidence="medium", notes="Demo fixture for regional aluminium overview.", raw_evidence="Primary aluminium production by region, Mt."),
        MarketDataRow(source_name="International Aluminium Institute statistics", source_url="https://international-aluminium.org/statistics/", date_accessed=TODAY, company_or_country="GCC", commodity="aluminium", metric="production", period="2024", value=6.4, unit="Mt", confidence="medium", notes="Demo fixture for regional aluminium overview.", raw_evidence="Primary aluminium production by region, Mt."),
        MarketDataRow(source_name="International Aluminium Institute statistics", source_url="https://international-aluminium.org/statistics/", date_accessed=TODAY, company_or_country="Europe", commodity="aluminium", metric="production", period="2024", value=7.0, unit="Mt", confidence="medium", notes="Demo fixture for regional aluminium overview.", raw_evidence="Primary aluminium production by region, Mt."),
        MarketDataRow(source_name="International Aluminium Institute statistics", source_url="https://international-aluminium.org/statistics/", date_accessed=TODAY, company_or_country="North America", commodity="aluminium", metric="production", period="2024", value=3.8, unit="Mt", confidence="medium", notes="Demo fixture for regional aluminium overview.", raw_evidence="Primary aluminium production by region, Mt."),
        MarketDataRow(source_name="USGS Mineral Commodity Summaries", source_url="https://www.usgs.gov/centers/national-minerals-information-center/mineral-commodity-summaries", date_accessed=TODAY, company_or_country="Indonesia", commodity="nickel", metric="production", period="2024", value=2200, unit="kt", confidence="medium", notes="Demo fixture for nickel country ranking.", raw_evidence="Mine production by country, kt contained nickel."),
        MarketDataRow(source_name="USGS Mineral Commodity Summaries", source_url="https://www.usgs.gov/centers/national-minerals-information-center/mineral-commodity-summaries", date_accessed=TODAY, company_or_country="Philippines", commodity="nickel", metric="production", period="2024", value=330, unit="kt", confidence="medium", notes="Demo fixture for nickel country ranking.", raw_evidence="Mine production by country, kt contained nickel."),
        MarketDataRow(source_name="USGS Mineral Commodity Summaries", source_url="https://www.usgs.gov/centers/national-minerals-information-center/mineral-commodity-summaries", date_accessed=TODAY, company_or_country="Russia", commodity="nickel", metric="production", period="2024", value=220, unit="kt", confidence="medium", notes="Demo fixture for nickel country ranking.", raw_evidence="Mine production by country, kt contained nickel."),
        MarketDataRow(source_name="USGS Mineral Commodity Summaries", source_url="https://www.usgs.gov/centers/national-minerals-information-center/mineral-commodity-summaries", date_accessed=TODAY, company_or_country="New Caledonia", commodity="nickel", metric="production", period="2024", value=160, unit="kt", confidence="medium", notes="Demo fixture for nickel country ranking.", raw_evidence="Mine production by country, kt contained nickel."),
        MarketDataRow(source_name="RUSAL operating results", source_url="https://rusal.ru/en/investors/results-and-reports/", date_accessed=TODAY, company_or_country="RUSAL", commodity="aluminium", metric="production", period="2024", value=3.8, unit="Mt", confidence="medium", notes="Demo fixture for company production.", raw_evidence="Aluminium production operating result, Mt."),
        MarketDataRow(source_name="RUSAL operating results", source_url="https://rusal.ru/en/investors/results-and-reports/", date_accessed=TODAY, company_or_country="RUSAL", commodity="alumina", metric="production", period="2024", value=5.0, unit="Mt", confidence="medium", notes="Demo fixture for company production.", raw_evidence="Alumina production operating result, Mt."),
    ]


def load_rows_for_source(source: MarketSource, *, demo_mode: bool = True) -> tuple[list[MarketDataRow], SourceStatus]:
    if not demo_mode:
        return [], SourceStatus(
            source_id=source.source_id,
            source_name=source.source_name,
            source_url=source.source_url,
            status="unavailable",
            rows_loaded=0,
            message="Live source fetch is intentionally disabled in this demo-safe build.",
        )

    rows = [row for row in fixture_rows() if row.source_name == source.source_name]
    return rows, SourceStatus(
        source_id=source.source_id,
        source_name=source.source_name,
        source_url=source.source_url,
        status="fallback",
        rows_loaded=len(rows),
        message="Loaded small built-in demo fixture; no network request was made.",
    )
