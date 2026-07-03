from __future__ import annotations

import json
from pathlib import Path

import requests

from app.web_search.clients import (
    LiteratureSearchClient,
    dedupe_and_rank_results,
    parse_crossref_item,
    parse_semantic_scholar_item,
    score_result,
)
from app.web_search.comparison import compare_methods
from app.web_search.deep_search import run_deep_search
from app.web_search.fetch import is_safe_external_url
from app.web_search.keywords import extract_keywords
from app.query.reports import build_deep_report, build_docx_report, build_links_report, build_pdf_report, comparison_insights, run_overall_summary
from app.query.rewrite import deterministic_query_rewrite
from app.ui.demo_app import table_df
from app.web_search.resource_links import build_resource_links
from app.web_search.schemas import DeepSearchResult, LiteratureSearchRequest, LiteratureSearchResult, LiteratureSearchRun


def test_extract_keywords_ru_en_domain_terms() -> None:
    keywords = extract_keywords('Сравни "nickel alloy" отжиг 900 C и твердость после annealing')
    assert "nickel alloy" in keywords
    assert "отжиг" in keywords
    assert "твердость" in keywords
    assert "annealing" in keywords


def test_parse_crossref_and_semantic_scholar_items() -> None:
    crossref = parse_crossref_item(
        {
            "DOI": "10.1000/example",
            "title": ["Nickel alloy annealing hardness"],
            "container-title": ["Materials Journal"],
            "published-print": {"date-parts": [[2024, 1, 1]]},
            "abstract": "<jats:p>Annealing changes hardness.</jats:p>",
            "author": [{"given": "A.", "family": "Smith"}],
            "URL": "https://doi.org/10.1000/example",
            "is-referenced-by-count": 12,
        },
        keywords=["nickel", "hardness"],
    )
    assert crossref is not None
    assert crossref.doi == "10.1000/example"
    assert crossref.year == 2024
    assert "hardness" in crossref.keyword_hits

    semantic = parse_semantic_scholar_item(
        {
            "paperId": "paper-1",
            "title": "Copper flotation process",
            "abstract": "Flotation improves copper recovery.",
            "year": 2023,
            "venue": "Hydrometallurgy",
            "url": "https://www.semanticscholar.org/paper/paper-1",
            "externalIds": {"DOI": "10.1000/copper"},
            "authors": [{"name": "B. Jones"}],
            "citationCount": 7,
        },
        keywords=["copper", "flotation"],
    )
    assert semantic is not None
    assert semantic.source == "semantic_scholar"
    assert semantic.doi == "10.1000/copper"


def test_dedupe_prefers_higher_scored_doi_result() -> None:
    low = LiteratureSearchResult(
        result_id="crossref_a",
        source="crossref",
        title="Nickel alloy",
        doi="10.1/a",
        abstract=None,
    )
    high = LiteratureSearchResult(
        result_id="semantic_scholar_a",
        source="semantic_scholar",
        title="Nickel alloy annealing hardness",
        doi="10.1/a",
        abstract="nickel annealing hardness",
        citation_count=100,
    )
    ranked = dedupe_and_rank_results([low, high], ["nickel", "hardness"], top_k=10)
    assert len(ranked) == 1
    assert ranked[0].result_id == "semantic_scholar_a"


def test_client_search_uses_mocked_api_responses() -> None:
    class Response:
        status_code = 200

        def __init__(self, payload: dict) -> None:
            self._payload = payload

        def json(self) -> dict:
            return self._payload

    class Session:
        def get(self, url: str, **kwargs):
            if "crossref" in url:
                return Response(
                    {
                        "message": {
                            "items": [
                                {
                                    "DOI": "10.1/nickel",
                                    "title": ["Nickel flotation"],
                                    "URL": "https://doi.org/10.1/nickel",
                                }
                            ]
                        }
                    }
                )
            return Response(
                {
                    "data": [
                        {
                            "paperId": "p1",
                            "title": "Nickel flotation",
                            "url": "https://www.semanticscholar.org/paper/p1",
                            "externalIds": {"DOI": "10.1/nickel"},
                        }
                    ]
                }
            )

    client = LiteratureSearchClient(session=Session())  # type: ignore[arg-type]
    results, warnings = client.search("nickel flotation", keywords=["nickel", "flotation"], sources=["crossref", "semantic_scholar"], top_k=5)
    assert warnings == []
    assert len(results) == 1
    assert results[0].doi == "10.1/nickel"


def test_client_search_uses_mocked_extended_api_responses() -> None:
    class Response:
        status_code = 200

        def __init__(self, payload: dict | None = None, text: str = "") -> None:
            self._payload = payload or {}
            self.text = text

        def json(self) -> dict:
            return self._payload

    class Session:
        def get(self, url: str, **kwargs):
            if "openalex" in url:
                return Response(
                    {
                        "results": [
                            {
                                "id": "https://openalex.org/W1",
                                "doi": "https://doi.org/10.1/openalex",
                                "display_name": "Nickel alloy openalex hardness",
                                "publication_year": 2024,
                                "primary_location": {"source": {"display_name": "Hydrometallurgy"}, "landing_page_url": "https://example.org/openalex"},
                                "abstract_inverted_index": {"Nickel": [0], "alloy": [1], "hardness": [2]},
                                "cited_by_count": 5,
                            }
                        ]
                    }
                )
            if "europepmc" in url:
                return Response(
                    {
                        "resultList": {
                            "result": [
                                {
                                    "id": "123",
                                    "source": "MED",
                                    "title": "Nickel alloy europepmc corrosion",
                                    "abstractText": "Nickel alloy corrosion in materials science.",
                                    "journalTitle": "Materials",
                                    "pubYear": "2023",
                                    "doi": "10.1/europepmc",
                                    "citedByCount": "2",
                                }
                            ]
                        }
                    }
                )
            if "export.arxiv.org" in url:
                return Response(
                    text="""<?xml version="1.0" encoding="UTF-8"?>
<feed xmlns="http://www.w3.org/2005/Atom" xmlns:arxiv="http://arxiv.org/schemas/atom">
  <entry>
    <id>https://arxiv.org/abs/2601.00001</id>
    <updated>2026-01-01T00:00:00Z</updated>
    <published>2026-01-01T00:00:00Z</published>
    <title>Nickel alloy arxiv annealing</title>
    <summary>Nickel alloy annealing for materials science.</summary>
    <author><name>A. Author</name></author>
    <link title="pdf" href="https://arxiv.org/pdf/2601.00001" type="application/pdf"/>
  </entry>
</feed>"""
                )
            if "datacite" in url:
                return Response(
                    {
                        "data": [
                            {
                                "id": "10.1/datacite",
                                "attributes": {
                                    "doi": "10.1/datacite",
                                    "titles": [{"title": "Nickel alloy datacite dataset"}],
                                    "publisher": "Data Repository",
                                    "publicationYear": 2022,
                                    "descriptions": [{"description": "Nickel alloy materials data."}],
                                    "url": "https://example.org/datacite",
                                },
                            }
                        ]
                    }
                )
            return Response({})

    client = LiteratureSearchClient(session=Session())  # type: ignore[arg-type]
    results, warnings = client.search(
        "nickel alloy",
        keywords=["nickel", "alloy"],
        sources=["openalex", "europepmc", "arxiv", "datacite"],
        top_k=10,
    )
    assert warnings == []
    assert {item.source for item in results} == {"openalex", "europepmc", "arxiv", "datacite"}
    assert {item.doi for item in results if item.doi} >= {"10.1/openalex", "10.1/europepmc", "10.1/datacite"}


def test_client_search_continues_when_one_source_times_out() -> None:
    class Response:
        status_code = 200

        def __init__(self, payload: dict) -> None:
            self._payload = payload

        def json(self) -> dict:
            return self._payload

    class Session:
        def get(self, url: str, **kwargs):
            if "openalex" in url:
                return Response(
                    {
                        "results": [
                            {
                                "id": "https://openalex.org/W1",
                                "display_name": "Nickel alloy hardness",
                                "primary_location": {"source": {"display_name": "Hydrometallurgy"}},
                            }
                        ]
                    }
                )
            raise requests.Timeout("simulated timeout")

    client = LiteratureSearchClient(session=Session())  # type: ignore[arg-type]
    results, warnings = client.search("nickel alloy", keywords=["nickel"], sources=["openalex", "arxiv"], top_k=5)
    assert [item.source for item in results] == ["openalex"]
    assert warnings
    assert "arXiv search skipped" in warnings[0]


def test_deterministic_query_rewrite_scopes_materials_search() -> None:
    plan = deterministic_query_rewrite("как отжиг влияет на твердость никелевых сплавов", materials_only=True)
    assert plan.search_queries
    assert plan.filters["materials_only"] is True
    assert any("materials science" in query for query in plan.search_queries)
    assert "твердость" in plan.all_keywords


def test_materials_only_filter_removes_non_domain_results() -> None:
    domain = LiteratureSearchResult(
        result_id="a",
        source="crossref",
        title="Nickel alloy annealing hardness",
        abstract="Materials science study of nickel alloy annealing.",
    )
    unrelated = LiteratureSearchResult(
        result_id="b",
        source="crossref",
        title="Financial market volatility",
        abstract="A study of stocks and macroeconomics.",
    )
    ranked = dedupe_and_rank_results([domain, unrelated], ["nickel"], top_k=10, materials_only=True)
    assert [item.result_id for item in ranked] == ["a"]


def test_journal_quartile_boost_increases_score() -> None:
    result = LiteratureSearchResult(
        result_id="q1",
        source="crossref",
        title="Nickel alloy annealing hardness",
        venue="Hydrometallurgy",
        abstract="Nickel alloy annealing hardness in materials science.",
    )
    score = score_result(result, ["nickel", "hardness"], journal_quartile_map={"hydrometallurgy": "Q1"})
    assert result.raw["journal_quartile"] == "Q1"
    assert result.raw["journal_quartile_boost"] == 5.0
    assert score >= 17.0


def test_dedupe_ranking_prefers_known_higher_quartile_when_relevance_is_close() -> None:
    q1 = LiteratureSearchResult(
        result_id="q1",
        source="crossref",
        title="Nickel alloy hardness",
        venue="Hydrometallurgy",
        abstract="Nickel alloy hardness in materials science.",
    )
    no_quartile = LiteratureSearchResult(
        result_id="none",
        source="crossref",
        title="Nickel alloy hardness",
        venue="Unknown Journal",
        abstract="Nickel alloy hardness in materials science.",
    )
    ranked = dedupe_and_rank_results(
        [no_quartile, q1],
        ["nickel", "hardness"],
        top_k=10,
        journal_quartile_map={"hydrometallurgy": "Q1"},
    )
    assert ranked[0].result_id == "q1"


def test_recommended_resource_links_include_organizer_sources_and_block_scihub() -> None:
    rows = build_resource_links(
        corrected_query="nickel alloy annealing",
        search_queries=["nickel alloy annealing materials science"],
        selected_resource_ids=["springer", "google_patents"],
    )
    enabled = [row for row in rows if row["enabled"]]
    assert {row["resource_id"] for row in enabled} == {"springer", "google_patents"}
    assert all("nickel+alloy+annealing" in row["url"] for row in enabled)
    scihub = [row for row in rows if row["resource_id"] == "scihub"]
    assert scihub
    assert scihub[0]["enabled"] is False


def test_url_safety_blocks_private_and_allows_public_with_fake_resolver() -> None:
    assert is_safe_external_url("http://example.org")[0] is False
    assert is_safe_external_url("https://localhost/paper")[0] is False
    assert is_safe_external_url("https://127.0.0.1/paper")[0] is False

    def resolver(host: str, port: int | None):
        return [(None, None, None, None, ("93.184.216.34", port or 443))]

    ok, reason = is_safe_external_url("https://example.org/paper", resolver=resolver)
    assert ok is True
    assert reason is None


def test_deep_search_without_llm_writes_schema(tmp_path: Path) -> None:
    result = LiteratureSearchResult(
        result_id="crossref_1",
        source="crossref",
        title="Nickel alloy annealing",
        abstract="Annealing of nickel alloys changes hardness.",
        url="https://example.org/paper",
    )
    deep = run_deep_search(results=[result], output_dir=tmp_path, mode="top5", client=None, fetch_excerpts=False)
    assert len(deep) == 1
    assert deep[0].status == "no_llm_credentials"
    assert (tmp_path / "web_document_summaries.jsonl").exists()
    row = json.loads((tmp_path / "web_document_summaries.jsonl").read_text(encoding="utf-8").splitlines()[0])
    assert row["result_id"] == "crossref_1"


def test_deep_search_respects_configured_limit(tmp_path: Path) -> None:
    results = [
        LiteratureSearchResult(
            result_id=f"crossref_{index}",
            source="crossref",
            title=f"Nickel alloy annealing {index}",
            abstract="Annealing of nickel alloys changes hardness.",
            url=f"https://example.org/paper-{index}",
        )
        for index in range(4)
    ]
    deep = run_deep_search(results=results, output_dir=tmp_path, mode="top5", client=None, fetch_excerpts=False, limit=2)
    assert [item.result_id for item in deep] == ["crossref_0", "crossref_1"]


def test_overall_summary_uses_deep_search_article_summaries() -> None:
    source = LiteratureSearchResult(result_id="s2_1", source="semantic_scholar", title="Nickel annealing")
    deep = DeepSearchResult(
        result_id="s2_1",
        source_result=source,
        document_summary={
            "summary": "Annealing improves ductility and changes hardness in nickel alloys.",
            "materials": ["nickel alloys"],
            "processes": ["annealing"],
            "key_findings": ["temperature controls hardness range"],
        },
        procedure_summaries=[{"synthesis_or_process_method": "annealing"}],
    )
    run = LiteratureSearchRun(
        request=LiteratureSearchRequest(query="nickel annealing", deep_search="top5"),
        keywords=["nickel", "annealing"],
        results=[source],
        deep_results=[deep],
        comparison=None,
    )
    summary = run_overall_summary(run)
    assert "Общий вывод по статьям" in summary
    assert "Annealing improves ductility" in summary
    assert "nickel alloys" in summary


def test_compare_methods_finds_shared_and_unique_methods() -> None:
    local_publications = [{"doc_id": "doc1", "title": "Local nickel work"}]
    local_procedures = [
        {
            "doc_id": "doc1",
            "material_name": "nickel alloy",
            "synthesis_or_process_method": "annealing",
            "conditions": [{"temperature": "900 C"}],
        },
        {
            "doc_id": "doc1",
            "material_name": "copper ore",
            "synthesis_or_process_method": "flotation",
        },
    ]
    source = LiteratureSearchResult(result_id="s2_1", source="semantic_scholar", title="Web nickel annealing")
    deep = DeepSearchResult(
        result_id="s2_1",
        source_result=source,
        procedure_summaries=[
            {
                "result_id": "s2_1",
                "material_name": "nickel alloy",
                "synthesis_or_process_method": "annealing",
                "conditions": [{"temperature": "950 C"}],
            },
            {
                "result_id": "s2_1",
                "material_name": "cobalt alloy",
                "synthesis_or_process_method": "aging",
            },
        ],
    )
    comparison = compare_methods(
        query="nickel annealing",
        local_publications=local_publications,
        local_procedures=local_procedures,
        web_deep_results=[deep],
    )
    assert comparison.confirmed_methods
    assert comparison.local_only_methods
    assert comparison.web_only_methods
    assert comparison.differing_conditions


def test_pdf_report_is_generated(tmp_path: Path) -> None:
    result = LiteratureSearchResult(
        result_id="crossref_pdf",
        source="crossref",
        title="Nickel alloy annealing hardness",
        year=2024,
        url="https://example.org/paper",
    )
    run = LiteratureSearchRun(
        request=LiteratureSearchRequest(query="nickel alloy annealing", generate_pdf_report=True),
        query_plan={"corrected_query": "nickel alloy annealing", "search_queries": ["nickel alloy annealing materials science"]},
        keywords=["nickel", "alloy", "annealing"],
        results=[result],
        local_matches=[],
        deep_results=[],
        comparison=None,
    )
    output = build_pdf_report(run, tmp_path / "report.pdf")
    assert output.exists()
    assert output.stat().st_size > 1000


def test_docx_and_split_reports_are_generated(tmp_path: Path) -> None:
    result = LiteratureSearchResult(
        result_id="crossref_docx",
        source="crossref",
        title="Nickel alloy annealing hardness",
        year=2024,
        url="https://example.org/paper",
    )
    run = LiteratureSearchRun(
        request=LiteratureSearchRequest(query="nickel alloy annealing", generate_pdf_report=True),
        query_plan={"corrected_query": "nickel alloy annealing", "search_queries": ["nickel alloy annealing materials science"]},
        keywords=["nickel", "alloy", "annealing"],
        results=[result],
        local_matches=[{"title": "Local nickel report"}],
        deep_results=[
            DeepSearchResult(
                result_id="crossref_docx",
                source_result=result,
                document_summary={"summary": "Annealing changes hardness in nickel alloys."},
            )
        ],
        comparison=None,
    )
    links = build_links_report(run)
    deep = build_deep_report(run)
    assert "Отчет по релевантным ссылкам" in links
    assert "https://example.org/paper" in links
    assert "Deep Search отчет" in deep
    assert "Annealing changes hardness" in deep

    output = build_docx_report(run, tmp_path / "report.docx", mode="full")
    assert output.exists()
    assert output.stat().st_size > 1000


def test_comparison_insights_can_be_disabled() -> None:
    result = LiteratureSearchResult(result_id="crossref_insights", source="crossref", title="Nickel alloy", year=2024)
    run = LiteratureSearchRun(
        request=LiteratureSearchRequest(query="nickel alloy", generate_comparison_insights=False),
        keywords=["nickel"],
        results=[result],
        comparison=None,
    )
    assert comparison_insights(run) == ""


def test_streamlit_table_df_serializes_mixed_nested_values() -> None:
    df = table_df(
        [
            {"conditions": [{"temperature": "900 C"}], "title": "A"},
            {"conditions": "not specified", "title": "B"},
            {"conditions": None, "title": "C"},
        ]
    )
    assert list(df["conditions"]) == ['[{"temperature": "900 C"}]', "not specified", ""]
