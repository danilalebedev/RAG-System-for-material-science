from __future__ import annotations

import json
import zipfile
from pathlib import Path

import requests

from app.llm.types import LLMResponse
from app.query.literature import answer_literature_with_provider_router, format_literature_context
from app.web_search.clients import (
    LiteratureSearchClient,
    dedupe_and_rank_results,
    parse_crossref_item,
    parse_semantic_scholar_item,
    score_result,
)
from app.web_search.comparison import compare_methods
from app.web_search.deep_search import run_deep_search
from app.web_search.fetch import is_safe_external_url, safe_fetch_excerpt
from app.web_search.keywords import extract_keywords
from app.query.cockpit import (
    build_search_query_from_slots,
    consensus_panel_rows,
    executive_brief_markdown,
    evidence_cards,
    gap_radar_rows,
    local_vs_world_dashboard,
    local_vs_web_metrics,
    method_heatmap_rows,
    method_matrix_rows,
    mini_graph_edges,
    numeric_interval_rows,
    query_decomposition,
)
from app.query.reports import (
    build_answer_exports,
    build_deep_report,
    build_docx_report,
    build_executive_brief_report,
    build_links_report,
    build_local_publications_archive,
    build_pdf_report,
    build_run_archive,
    build_section_exports,
    build_web_publications_archive,
    compact_text,
    comparison_insights,
    literature_graph_markdown,
    markdown_to_docx,
    property_report_markdown,
    property_report_rows_from_run,
    relevance_confidence,
    routerai_budget_summary,
    run_overall_summary,
)
from app.query.rewrite import deterministic_query_rewrite
from app.ui.demo_app import comparison_graph_dot, comparison_graph_title, knowledge_graph_dot, table_df
from app.web_search.open_access import OpenAccessResolver
from app.web_search.resource_links import build_resource_links
from app.web_search.schemas import DeepSearchResult, LiteratureSearchRequest, LiteratureSearchResult, LiteratureSearchRun, MethodComparison


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


def test_open_access_resolver_short_circuits_arxiv_doi() -> None:
    result = OpenAccessResolver().resolve(doi="10.48550/arXiv.2604.11229", title="Nickel paper", year=2026)
    assert result.source == "arxiv"
    assert result.open_access is True
    assert result.best_pdf_url == "https://arxiv.org/pdf/2604.11229"
    assert result.landing_page_url == "https://arxiv.org/abs/2604.11229"


def test_open_access_resolver_skips_unpaywall_without_email_and_uses_openalex() -> None:
    class Response:
        status_code = 200

        def json(self) -> dict:
            return {
                "results": [
                    {
                        "title": "Open nickel paper",
                        "publication_year": 2025,
                        "open_access": {"is_oa": True, "oa_url": "https://example.org/open"},
                        "primary_location": {"pdf_url": "https://example.org/open.pdf", "landing_page_url": "https://example.org/open"},
                    }
                ]
            }

    class Session:
        def __init__(self) -> None:
            self.urls: list[str] = []

        def get(self, url: str, **kwargs):
            self.urls.append(url)
            return Response()

    session = Session()
    result = OpenAccessResolver(session=session, unpaywall_email="").resolve(doi="10.1/open", title="Open nickel paper")
    assert result.source == "openalex"
    assert result.open_access is True
    assert result.best_pdf_url == "https://example.org/open.pdf"
    assert all("unpaywall" not in url for url in session.urls)


def test_open_access_resolver_keeps_looking_after_unpaywall_paywalled() -> None:
    class Response:
        status_code = 200

        def __init__(self, payload: dict) -> None:
            self._payload = payload

        def json(self) -> dict:
            return self._payload

    class Session:
        def __init__(self) -> None:
            self.urls: list[str] = []

        def get(self, url: str, **kwargs):
            self.urls.append(url)
            if "unpaywall" in url:
                return Response({"title": "Nickel paper", "is_oa": False, "doi_url": "https://doi.org/10.1/paywalled"})
            if "openalex" in url:
                return Response(
                    {
                        "results": [
                            {
                                "title": "Nickel paper",
                                "publication_year": 2024,
                                "open_access": {"is_oa": True, "oa_url": "https://example.org/open"},
                                "primary_location": {"landing_page_url": "https://example.org/open"},
                            }
                        ]
                    }
                )
            return Response({})

    session = Session()
    result = OpenAccessResolver(session=session, unpaywall_email="team@example.org").resolve(doi="10.1/paywalled", title="Nickel paper")
    assert result.source == "openalex"
    assert result.open_access is True
    assert result.access_status == "open"
    assert any("unpaywall" in url for url in session.urls)
    assert any("openalex" in url for url in session.urls)


def test_open_access_resolver_returns_best_non_open_fallback() -> None:
    class Response:
        status_code = 200

        def __init__(self, payload: dict) -> None:
            self._payload = payload

        def json(self) -> dict:
            return self._payload

    class Session:
        def get(self, url: str, **kwargs):
            if "unpaywall" in url:
                return Response({"title": "Nickel paper", "is_oa": False, "doi_url": "https://doi.org/10.1/no-open"})
            if "openalex" in url:
                return Response(
                    {
                        "results": [
                            {
                                "title": "Nickel paper",
                                "open_access": {"is_oa": False},
                                "primary_location": {"landing_page_url": "https://example.org/metadata"},
                            }
                        ]
                    }
                )
            return Response({})

    result = OpenAccessResolver(session=Session(), unpaywall_email="team@example.org").resolve(doi="10.1/no-open", title="Nickel paper")
    assert result.source == "openalex"
    assert result.open_access is False
    assert result.access_status == "metadata_only"


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
    confidence = relevance_confidence(result)
    assert confidence["label"] == "Высокая"
    assert confidence["confidence"] >= 72
    assert any("квартиль журнала: Q1" in reason for reason in confidence["reasons"])


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


def test_safe_fetch_excerpt_returns_error_on_request_exception() -> None:
    class BrokenSession:
        def get(self, *_args: object, **_kwargs: object) -> object:
            raise requests.exceptions.SSLError("certificate verify failed")

    fetched = safe_fetch_excerpt(
        "https://example.org/paper",
        session=BrokenSession(),  # type: ignore[arg-type]
        resolver=lambda _host, port: [(None, None, None, None, ("93.184.216.34", port or 443))],
    )

    assert fetched.text == ""
    assert "certificate verify failed" in (fetched.error or "")


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


def test_literature_context_includes_web_local_deep_and_comparison() -> None:
    source = LiteratureSearchResult(
        result_id="web_1",
        source="openalex",
        title="Nickel alloy annealing hardness",
        year=2024,
        url="https://example.org/paper",
        abstract="Annealing changes hardness in nickel alloys.",
        score=3.2,
        keyword_hits=["nickel", "annealing"],
    )
    comparison = MethodComparison(
        query="nickel annealing",
        confirmed_methods=[{"material": "nickel alloy", "method": "annealing"}],
        web_only_methods=[{"material": "nickel alloy", "method": "aging"}],
        gaps=["Need numeric hardness ranges."],
    )
    run = LiteratureSearchRun(
        request=LiteratureSearchRequest(query="nickel annealing", deep_search="top5"),
        query_plan={"llm_rewrite": {"corrected_query": "nickel alloy annealing hardness"}},
        keywords=["nickel", "annealing"],
        results=[source],
        local_matches=[{"title": "Local nickel procedure", "method": "annealing", "preview": "Local annealing evidence."}],
        deep_results=[
            DeepSearchResult(
                result_id="web_1",
                source_result=source,
                status="ok",
                llm_used=True,
                document_summary={"summary": "Annealing modifies hardness.", "materials": ["nickel alloy"]},
                procedure_summaries=[{"synthesis_or_process_method": "annealing", "conditions": [{"temperature": "900 C"}]}],
            )
        ],
        comparison=comparison,
    )

    context = format_literature_context(run)

    assert "nickel alloy annealing hardness" in context
    assert "https://example.org/paper" in context
    assert "Local annealing evidence" in context
    assert "Annealing modifies hardness" in context
    assert "Need numeric hardness ranges" in context


def test_answer_literature_with_provider_router_passes_literature_context(monkeypatch, tmp_path: Path) -> None:
    captured: dict[str, object] = {}

    class FakeRouter:
        def ask(self, question: str, **kwargs: object) -> LLMResponse:
            captured["question"] = question
            captured.update(kwargs)
            return LLMResponse(
                text="literature answer",
                provider="routerai",
                model="deepseek/deepseek-chat-v3.1",
                status="primary",
                used_evidence=bool(kwargs.get("context")),
            )

    monkeypatch.setattr("app.query.literature.ProviderRouter.from_env", lambda **_: FakeRouter())
    source = LiteratureSearchResult(
        result_id="crossref_1",
        source="crossref",
        title="Nickel ore flotation",
        url="https://example.org/flotation",
        abstract="Xanthate flotation improves nickel recovery.",
    )
    run = LiteratureSearchRun(
        request=LiteratureSearchRequest(query="nickel ore flotation"),
        keywords=["nickel", "flotation"],
        results=[source],
    )

    response = answer_literature_with_provider_router("nickel ore flotation", run, project_root=tmp_path)

    assert response.provider == "routerai"
    assert captured["question"] == "nickel ore flotation"
    assert "Xanthate flotation improves nickel recovery" in str(captured["context"])
    assert "научно-технический аналитик" in str(captured["system_prompt"])


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


def test_compare_methods_uses_local_and_web_document_summaries() -> None:
    local_publications = [{"doc_id": "doc1", "title": "Local nickel ore flotation"}]
    local_document_summaries = [
        {
            "doc_id": "doc1",
            "document_summary_id": "docsum1",
            "summary": "Nickel ore flotation improves Ni recovery.",
            "materials": ["nickel ore"],
            "processes": ["flotation"],
            "key_findings": ["collector dosage changes recovery"],
            "additional_domain_fields": {"numeric_conditions": ["pH 9"], "analysis_results": ["88% Ni recovery"]},
            "confidence": 0.82,
        }
    ]
    source = LiteratureSearchResult(result_id="s2_2", source="semantic_scholar", title="Web nickel ore flotation")
    deep = DeepSearchResult(
        result_id="s2_2",
        source_result=source,
        document_summary={
            "document_summary_id": "webdocsum1",
            "summary": "Nickel ore flotation with xanthate improves recovery.",
            "materials": ["nickel ore"],
            "processes": ["flotation"],
            "analysis_results": ["91% Ni recovery"],
            "confidence": 0.75,
        },
    )

    comparison = compare_methods(
        query="nickel ore flotation recovery",
        local_publications=local_publications,
        local_document_summaries=local_document_summaries,
        local_procedures=[],
        web_deep_results=[deep],
    )

    scopes = {row["scope"] for row in comparison.rows}
    assert scopes == {"local", "web"}
    assert {row["record_type"] for row in comparison.rows} == {"document_summary"}
    assert any("88% Ni recovery" in json.dumps(row.get("numeric_results"), ensure_ascii=False) for row in comparison.rows)
    assert any("91% Ni recovery" in json.dumps(row.get("numeric_results"), ensure_ascii=False) for row in comparison.rows)
    assert comparison.confirmed_methods


def test_cockpit_builds_query_slots_metrics_and_brief() -> None:
    source = LiteratureSearchResult(
        result_id="web_1",
        source="openalex",
        title="Nickel alloy annealing hardness",
        year=2024,
        doi="10.1000/nickel",
        url="https://example.org/paper",
        abstract="Annealing at 950 C changes hardness in nickel alloys.",
        authors=["A. Expert"],
        venue="Materials Journal",
    )
    comparison = MethodComparison(
        query="nickel alloy annealing 900 C",
        confirmed_methods=[{"material": "nickel alloy", "method": "annealing"}],
        local_only_methods=[{"scope": "local", "material": "copper ore", "method": "flotation"}],
        web_only_methods=[{"scope": "web", "material": "cobalt alloy", "method": "aging"}],
        differing_conditions=[{"material": "nickel alloy", "method": "annealing"}],
        rows=[
            {
                "scope": "local",
                "title": "Local nickel work",
                "material": "nickel alloy",
                "method": "annealing",
                "conditions": [{"temperature": "900 C"}],
                "equipment": ["tube furnace"],
                "outputs": ["hardness"],
                "numeric_results": ["220 HV"],
            },
            {
                "scope": "web",
                "title": "Nickel alloy annealing hardness",
                "material": "nickel alloy",
                "method": "annealing",
                "conditions": [{"temperature": "950 C"}],
                "equipment": ["furnace"],
                "outputs": ["ductility"],
                "numeric_results": ["18% elongation"],
            },
        ],
    )
    run = LiteratureSearchRun(
        request=LiteratureSearchRequest(query="nickel alloy annealing 900 C Norilsk autoclave 2020", deep_search="top5", deep_search_limit=3),
        query_plan={
            "corrected_query": "nickel alloy annealing hardness",
            "material_terms": ["nickel alloy"],
            "process_terms": ["annealing"],
            "property_terms": ["hardness"],
            "equipment_terms": ["autoclave"],
            "search_queries": ["nickel alloy annealing materials science"],
        },
        keywords=["nickel", "alloy", "annealing", "hardness", "Norilsk", "autoclave"],
        results=[source],
        local_matches=[{"title": "Local nickel work"}],
        deep_results=[DeepSearchResult(result_id="web_1", source_result=source, document_summary={"summary": "Annealing changes hardness."})],
        comparison=comparison,
    )

    slots = query_decomposition(run)
    assert any(row["slot"] == "Материал" and "nickel alloy" in row["values"] for row in slots)
    assert any("900 C" in row["values"] for row in slots)
    assert any(row["slot"] == "Оборудование" and "autoclave" in row["values"] for row in slots)
    assert any(row["slot"] == "Период" and "2020" in row["values"] for row in slots)
    metrics = local_vs_web_metrics(run)
    assert metrics[0]["local"] == 1
    assert metrics[0]["web"] == 1
    dashboard = local_vs_world_dashboard(run)
    assert {row["side"] for row in dashboard} == {"Локальная база", "Мировая литература"}
    assert method_matrix_rows(run)[0]["scope"] == "Локальная БД"
    assert method_matrix_rows(run)[0]["equipment"] == "tube furnace"
    assert method_heatmap_rows(run)[0]["status"] == "есть локально и во внешней литературе"
    assert consensus_panel_rows(run)[0]["count"] == 1
    assert evidence_cards(run)[0]["kind"] == "web"
    assert numeric_interval_rows(run)
    graph_edges = mini_graph_edges(run)
    assert {"from": "Expert: A. Expert", "to": "Publication: Nickel alloy annealing hardness", "relation": "authored", "scope": "web"} in graph_edges
    assert {"from": "Publication: Local nickel work", "to": "Experiment: annealing", "relation": "describes", "scope": "local"} in graph_edges
    assert {"from": "Material: nickel alloy", "to": "Process: annealing", "relation": "processed by", "scope": "local"} in graph_edges
    graph_markdown = literature_graph_markdown(run)
    assert "Publication: Nickel alloy annealing hardness" in graph_markdown
    graph_dot = knowledge_graph_dot(run, None)
    assert "Publication: Nickel alloy annealing hardness" in graph_dot
    property_graph = comparison_graph_dot(run, None, "Поиск свойств")
    assert comparison_graph_title("Поиск свойств") == "**Свойства: local vs web**"
    assert "Property:" in property_graph
    assert "hardness" in property_graph
    assert "ductility" in property_graph
    assert "Value/range:" in property_graph
    method_graph = comparison_graph_dot(run, None, "Поиск методик")
    assert "Method: annealing" in method_graph
    property_rows_for_report = property_report_rows_from_run(run)
    assert property_rows_for_report
    property_markdown = property_report_markdown("Свойства", run.request.query, property_rows_for_report)
    assert "hardness" in property_markdown
    assert "ductility" in property_markdown
    assert any(row["signal"] == "Разные условия/диапазоны" and row["value"] == 1 for row in gap_radar_rows(run))
    brief = executive_brief_markdown(run)
    assert "Краткий управленческий вывод" in brief
    assert "5 ключевых выводов" in brief
    assert "3 риска" in brief
    assert "3 пробела" in brief
    assert "Nickel alloy annealing hardness" in brief
    assert "https://example.org/paper" in brief


def test_build_search_query_from_edited_slots() -> None:
    query = build_search_query_from_slots(
        "кучное выщелачивание никелевой руды",
        {
            "Материал": "никелевая руда",
            "Процесс": "кучное выщелачивание",
            "Условия": "холодный климат",
            "Числовые ограничения": "5 C",
            "География": "Норильск",
            "Период": "2020-2026",
            "Свойства": "извлечение Ni",
            "Оборудование": "реактор",
        },
    )
    assert "Материал: никелевая руда" in query
    assert "Числовые ограничения: 5 C" in query
    assert "Период: 2020-2026" in query
    assert "Оборудование: реактор" in query


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
        title="Nickel alloy\x00 annealing\x08 hardness",
        year=2024,
        url="https://example.org/paper\x0b",
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
                document_summary={"summary": "Annealing\x00 changes hardness in nickel alloys."},
            )
        ],
        comparison=None,
    )
    assert "\x00" not in compact_text(result.title)
    links = build_links_report(run)
    deep = build_deep_report(run)
    assert "Отчет по релевантным ссылкам" in links
    assert "https://example.org/paper" in links
    assert "Confidence:" in links
    assert "Deep Search отчет" in deep
    assert "Annealing changes hardness" in deep
    brief = build_executive_brief_report(run)
    assert "Краткий управленческий вывод" in brief
    assert "https://example.org/paper" in brief

    output = build_docx_report(run, tmp_path / "report.docx", mode="full")
    assert output.exists()
    assert output.stat().st_size > 1000
    brief_docx = build_docx_report(run, tmp_path / "executive_brief.docx", mode="brief")
    assert brief_docx.exists()
    assert brief_docx.stat().st_size > 1000
    brief_pdf = build_pdf_report(run, tmp_path / "executive_brief.pdf", mode="brief")
    assert brief_pdf.exists()
    assert brief_pdf.stat().st_size > 1000


def test_markdown_to_docx_sanitizes_xml_control_chars(tmp_path: Path) -> None:
    output = markdown_to_docx(
        "# Heading\x00 with control chars\n\n## Subheading\x08\n\n- Bullet\x0b item\n\nParagraph\x1f text",
        tmp_path / "control_chars.docx",
    )
    assert output.exists()
    assert output.stat().st_size > 1000


def test_section_exports_and_archive_include_local_files(tmp_path: Path) -> None:
    local_root = tmp_path / "data" / "raw"
    local_root.mkdir(parents=True)
    local_file = local_root / "local_nickel_report.pdf"
    local_file.write_bytes(b"%PDF-1.4\nlocal fixture\n")
    run_dir = tmp_path / "run"
    result = LiteratureSearchResult(
        result_id="crossref_archive",
        source="crossref",
        title="Nickel alloy annealing hardness",
        year=2024,
        url="https://example.org/paper",
        score=2.5,
        keyword_hits=["nickel"],
    )
    comparison = MethodComparison(
        query="nickel alloy annealing",
        rows=[
            {
                "scope": "web",
                "material": "nickel alloy",
                "method": "annealing",
                "outputs": ["hardness"],
                "numeric_results": ["220 HV"],
                "conditions": [{"temperature": "900 C"}],
                "title": "Nickel alloy annealing hardness",
            }
        ],
    )
    run = LiteratureSearchRun(
        request=LiteratureSearchRequest(query="nickel alloy annealing", generate_pdf_report=True),
        query_plan={"corrected_query": "nickel alloy annealing", "search_queries": ["nickel alloy annealing materials science"]},
        keywords=["nickel", "alloy", "annealing"],
        results=[result],
        local_matches=[{"doc_id": "doc1", "title": "Local nickel report", "local_path": str(local_file)}],
        deep_results=[],
        comparison=comparison,
        output_dir=run_dir,
    )

    exports = build_section_exports(run, "sources", run_dir / "section_reports")
    assert exports["pdf"].exists()
    assert exports["docx"].exists()
    assert exports["markdown"].read_text(encoding="utf-8")
    property_exports = build_section_exports(run, "properties", run_dir / "section_reports")
    assert "220 HV" in property_exports["markdown"].read_text(encoding="utf-8")

    answer = LLMResponse(
        text="RouterAI synthesized literature answer.",
        provider="routerai",
        model="test",
        status="primary",
        used_evidence=True,
        usage={"prompt_tokens": 120, "completion_tokens": 30, "total_tokens": 150},
    )
    answer_exports = build_answer_exports(run_dir / "answer_report", query="nickel alloy annealing", answer=answer, run=run)
    assert answer_exports["pdf"].exists()
    assert answer_exports["docx"].exists()
    assert answer_exports["json"].exists()
    answer_markdown = answer_exports["markdown"].read_text(encoding="utf-8")
    assert "RouterAI synthesized literature answer" in answer_markdown
    assert "https://example.org/paper" in answer_markdown
    assert "Метрики запроса" in answer_markdown
    answer_json = json.loads(answer_exports["json"].read_text(encoding="utf-8"))
    assert answer_json["routerai_budget"]["budget_rub"] == 1500
    assert answer_json["routerai_budget"]["total_tokens"] == 150
    assert routerai_budget_summary(answer)["budget_status"] == "tokens_recorded"

    archive = build_run_archive(run, run_dir / "run_artifacts.zip", project_root=tmp_path, answer=answer, query="nickel alloy annealing")
    assert archive.exists()
    web_manifest = json.loads((run_dir / "web_links_manifest.json").read_text(encoding="utf-8"))
    assert web_manifest["web_links"][0]["relevance_confidence"]["label"] in {"Средняя", "Высокая", "Низкая"}
    links_csv = (run_dir / "links.csv").read_text(encoding="utf-8-sig")
    assert "confidence_percent" in links_csv
    with zipfile.ZipFile(archive) as zf:
        names = set(zf.namelist())
    assert "web_links_manifest.json" in names
    assert "local_publication_files_manifest.json" in names
    assert "section_reports/sources_report.pdf" in names
    assert "section_reports/sources_report.docx" in names
    assert "section_reports/properties_report.pdf" in names
    assert "section_reports/properties_report.docx" in names
    assert "answer_report/routerai_answer.pdf" in names
    assert "answer_report/routerai_answer.docx" in names
    assert "answer_report/routerai_answer.json" in names
    assert "local_publications/01_local_nickel_report.pdf" in names

    local_archive = build_local_publications_archive(run, run_dir / "local_publications.zip", project_root=tmp_path)
    web_archive = build_web_publications_archive(run, run_dir / "web_publications.zip")
    with zipfile.ZipFile(local_archive) as zf:
        local_names = set(zf.namelist())
    with zipfile.ZipFile(web_archive) as zf:
        web_names = set(zf.namelist())
        web_shortcut = zf.read("01_Nickel alloy annealing hardness.url").decode("utf-8")
    assert "01_Local nickel report.pdf" in local_names
    assert "sources.csv" in local_names
    assert "01_Nickel alloy annealing hardness.url" in web_names
    assert "URL=https://example.org/paper" in web_shortcut


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
