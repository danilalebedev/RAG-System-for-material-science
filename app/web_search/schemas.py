from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, HttpUrl, field_validator


SearchSource = Literal["crossref", "semantic_scholar", "openalex", "europepmc", "arxiv", "datacite"]
DeepSearchMode = Literal["none", "top5"]
ALL_SEARCH_SOURCES: list[SearchSource] = ["crossref", "semantic_scholar", "openalex", "europepmc", "arxiv", "datacite"]
DEFAULT_SEARCH_SOURCES: list[SearchSource] = ["crossref", "semantic_scholar", "openalex", "europepmc", "datacite"]
SEARCH_SOURCE_LABELS: dict[SearchSource, str] = {
    "crossref": "Crossref",
    "semantic_scholar": "Semantic Scholar",
    "openalex": "OpenAlex",
    "europepmc": "Europe PMC",
    "arxiv": "arXiv",
    "datacite": "DataCite",
}


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class LiteratureSearchRequest(BaseModel):
    query: str = Field(min_length=2, max_length=800)
    top_k: int = Field(default=20, ge=1, le=100)
    sources: list[SearchSource] = Field(default_factory=lambda: DEFAULT_SEARCH_SOURCES.copy())
    deep_search: DeepSearchMode = "none"
    deep_search_limit: int = Field(default=5, ge=1, le=20)
    language: str = Field(default="auto", max_length=32)
    include_local_search: bool = True
    materials_only: bool = True
    use_query_rewrite: bool = True
    use_llm_query_rewrite: bool = True
    generate_comparison_insights: bool = True
    include_recommended_resource_links: bool = True
    recommended_resource_ids: list[str] = Field(default_factory=list)
    fetch_excerpts: bool = True
    generate_pdf_report: bool = True
    run_id: str | None = Field(default=None, max_length=120)

    @field_validator("sources")
    @classmethod
    def unique_sources(cls, value: list[SearchSource]) -> list[SearchSource]:
        return list(dict.fromkeys(value))


class LiteratureSearchResult(BaseModel):
    model_config = ConfigDict(extra="allow")

    result_id: str
    source: SearchSource
    title: str
    authors: list[str] = Field(default_factory=list)
    year: int | None = None
    venue: str | None = None
    doi: str | None = None
    url: HttpUrl | None = None
    abstract: str | None = None
    snippet: str | None = None
    open_access_pdf_url: HttpUrl | None = None
    citation_count: int | None = None
    reference_count: int | None = None
    score: float = 0.0
    keyword_hits: list[str] = Field(default_factory=list)
    external_ids: dict[str, str] = Field(default_factory=dict)
    fetched_at: str = Field(default_factory=utc_now)
    raw: dict[str, Any] = Field(default_factory=dict)

    def evidence_text(self) -> str:
        parts = [self.title, self.abstract, self.snippet, self.venue, str(self.year or "")]
        return " ".join(str(part) for part in parts if part)


class DeepSearchResult(BaseModel):
    result_id: str
    source_result: LiteratureSearchResult
    status: Literal["ok", "metadata_only", "no_llm_credentials", "failed"] = "metadata_only"
    llm_used: bool = False
    excerpt_chars: int = 0
    fetched_url: str | None = None
    fetch_error: str | None = None
    document_summary: dict[str, Any] = Field(default_factory=dict)
    procedure_summaries: list[dict[str, Any]] = Field(default_factory=list)
    error: str | None = None


class MethodComparison(BaseModel):
    query: str
    generated_at: str = Field(default_factory=utc_now)
    confirmed_methods: list[dict[str, Any]] = Field(default_factory=list)
    local_only_methods: list[dict[str, Any]] = Field(default_factory=list)
    web_only_methods: list[dict[str, Any]] = Field(default_factory=list)
    differing_conditions: list[dict[str, Any]] = Field(default_factory=list)
    gaps: list[str] = Field(default_factory=list)
    rows: list[dict[str, Any]] = Field(default_factory=list)


class LiteratureSearchRun(BaseModel):
    request: LiteratureSearchRequest
    query_plan: dict[str, Any] = Field(default_factory=dict)
    keywords: list[str]
    results: list[LiteratureSearchResult]
    local_matches: list[dict[str, Any]] = Field(default_factory=list)
    resource_links: list[dict[str, Any]] = Field(default_factory=list)
    deep_results: list[DeepSearchResult] = Field(default_factory=list)
    comparison: MethodComparison | None = None
    output_dir: Path | None = None
    report_markdown: str | None = None
    report_pdf_path: Path | None = None
    report_docx_path: Path | None = None
    links_report_markdown: str | None = None
    links_report_pdf_path: Path | None = None
    links_report_docx_path: Path | None = None
    deep_report_markdown: str | None = None
    deep_report_pdf_path: Path | None = None
    deep_report_docx_path: Path | None = None
    executive_brief_markdown: str | None = None
    executive_brief_pdf_path: Path | None = None
    executive_brief_docx_path: Path | None = None
    full_run_json_path: Path | None = None
    warnings: list[str] = Field(default_factory=list)
