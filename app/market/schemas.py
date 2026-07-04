from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field


Commodity = Literal[
    "nickel",
    "copper",
    "palladium",
    "platinum",
    "steel",
    "aluminium",
    "alumina",
    "iron ore",
    "cobalt",
    "lithium",
]
Metric = Literal["production", "sales", "guidance", "capacity", "reserves", "resources"]
Confidence = Literal["high", "medium", "low"]
SourceStatusValue = Literal["loaded", "unavailable", "fallback"]
MarketSourceType = Literal[
    "official_statistics",
    "company_report",
    "industry_association",
    "demo_fixture",
    "planned_connector",
]
SourceMode = Literal["live", "fallback", "stub"]


class MarketDataRow(BaseModel):
    source_name: str
    source_url: str
    date_accessed: str
    company_or_country: str
    commodity: Commodity
    metric: Metric = "production"
    period: str
    value: float | str
    unit: str
    confidence: Confidence = "medium"
    notes: str = ""
    raw_evidence: str = ""


class MarketSource(BaseModel):
    source_id: str
    source_name: str
    source_url: str
    source_type: MarketSourceType
    commodities: list[Commodity] = Field(default_factory=list)
    entities: list[str] = Field(default_factory=list)
    reliability_rank: int = 50


class SourceStatus(BaseModel):
    source_id: str
    source_name: str
    source_url: str
    status: SourceStatusValue
    rows_loaded: int = 0
    message: str = ""


class SourceCredibility(BaseModel):
    source_name: str
    source_url: str
    source_type: MarketSourceType
    mode: SourceMode
    date_accessed: str
    confidence: Confidence
    caveat: str = ""


class MarketQuery(BaseModel):
    original_query: str
    intent: str
    commodities: list[Commodity] = Field(default_factory=list)
    companies: list[str] = Field(default_factory=list)
    countries: list[str] = Field(default_factory=list)
    periods: list[str] = Field(default_factory=list)
    latest_requested: bool = False
    link_internal_terms: bool = False


class MarketRadarResult(BaseModel):
    query: str
    detected: MarketQuery
    selected_sources: list[MarketSource] = Field(default_factory=list)
    production_rows: list[MarketDataRow] = Field(default_factory=list)
    market_summary: str = ""
    source_status: list[SourceStatus] = Field(default_factory=list)
    source_credibility: list[SourceCredibility] = Field(default_factory=list)
    business_implications: list[str] = Field(default_factory=list)
    missing_data: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    suggested_sources: list[str] = Field(default_factory=list)
    internal_knowledge_terms: list[str] = Field(default_factory=list)
    charts: dict[str, list[dict[str, Any]]] = Field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        return self.model_dump(mode="json")
