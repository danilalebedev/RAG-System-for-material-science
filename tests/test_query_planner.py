from __future__ import annotations

import zipfile
from pathlib import Path

from app.llm.types import LLMResponse
from app.query.local_orchestrator import first_query
from app.query.orchestrator import (
    QueryOrchestrationResult,
    RetrievedContext,
    answer_with_provider_router,
    run_query_orchestration,
    split_indexed_summary_rows,
    trim_rows_keep_diagnostics,
)
from app.query.planner import plan_query
from app.query.reports import build_orchestration_archive, build_orchestration_exports


def test_numeric_query_routes_to_tables_and_raw_rag() -> None:
    plan = plan_query("nickel leaching at 80 C and 20% acid composition")
    assert plan.intent == "extract_numbers"
    assert "table_search" in plan.routes
    assert "raw_rag" in plan.routes
    assert plan.answer_format == "evidence_matrix"
    assert plan.rewritten_queries.tables


def test_comparison_query_routes_to_summary_raw_and_tables() -> None:
    plan = plan_query("compare nickel leaching and flotation, which is better?")
    assert plan.intent == "compare_methods"
    assert "summary_rag" in plan.routes
    assert "raw_rag" in plan.routes
    assert "table_search" in plan.routes
    assert plan.answer_format == "comparison_table"


def test_graph_query_routes_to_graph_and_summary() -> None:
    plan = plan_query("how is nickel related to autoclave leaching path in graph")
    assert plan.intent == "graph_exploration"
    assert "graph_search" in plan.routes
    assert "summary_rag" in plan.routes
    assert plan.rewritten_queries.graph


def test_demo_graph_prompt_keeps_graph_route_with_publications_tail() -> None:
    plan = plan_query("РџРѕРєР°Р·Р°С‚СЊ СЃРІСЏР·Рё: РЅРёРєРµР»СЊ -> РїСЂРѕС†РµСЃСЃС‹ -> СЃРІРѕР№СЃС‚РІР° -> РїСѓР±Р»РёРєР°С†РёРё")
    assert plan.intent == "graph_exploration"
    assert "graph_search" in plan.routes
    assert plan.answer_format == "graph_explanation"


def test_literature_query_routes_to_web_and_internal_rag() -> None:
    plan = plan_query("fresh articles about nickel tailings recovery")
    assert plan.intent == "web_literature_search"
    assert "web_search" in plan.routes
    assert "internal_rag" in plan.routes
    assert plan.rewritten_queries.web


def test_query_plan_json_has_required_stable_keys() -> None:
    payload = plan_query("РіРґРµ РЅР°РїРёСЃР°РЅРѕ РїСЂРѕ РёР·РІР»РµС‡РµРЅРёРµ РЅРёРєРµР»СЏ РёР· С…РІРѕСЃС‚РѕРІ").model_dump(mode="json")
    assert set(payload) == {
        "original_query",
        "intent",
        "domain",
        "entities",
        "rewritten_queries",
        "internal_search_queries",
        "web_search_queries",
        "entity_aliases",
        "slots",
        "decomposed_questions",
        "routes",
        "answer_format",
        "needs_clarification",
        "clarifying_question",
    }
    assert set(payload["entities"]) == {"materials", "processes", "equipment", "properties", "experts", "facilities"}
    assert set(payload["rewritten_queries"]) == {"raw_rag", "summary_rag", "graph", "tables", "web"}
    assert set(payload["slots"]) == {"materials", "processes", "equipment", "properties", "experts", "facilities"}
    assert payload["needs_clarification"] is False
    assert payload["clarifying_question"] is None


def test_query_plan_search_strings_do_not_include_slot_noise() -> None:
    plan = plan_query("compare nickel leaching and flotation")
    joined = " ".join(plan.rewritten_queries.summary_rag)
    assert "procedure summary" not in joined.casefold()
    noisy = plan.model_copy(
        update={
            "rewritten_queries": plan.rewritten_queries.model_copy(
                update={"summary_rag": ["procedure summary nickel ore raw_rag"]}
            )
        }
    )
    assert first_query(noisy, "summary_rag", noisy.original_query) == "nickel ore"


def test_indexed_summary_rows_are_split_from_raw_stream() -> None:
    raw, summaries = split_indexed_summary_rows(
        [
            {"id": "raw:1", "source_type": "raw_chunk", "title": "Raw"},
            {"id": "document_summary:1", "source_type": "document_summary", "title": "Summary"},
            {"id": "procedure_summary:1", "source_type": "procedure_summary", "title": "Procedure"},
            {"id": "raw_rag:diagnostics", "source_type": "diagnostics"},
        ]
    )
    assert [row["id"] for row in raw] == ["raw:1", "raw_rag:diagnostics"]
    assert [row["id"] for row in summaries] == ["document_summary:1", "procedure_summary:1"]
    assert summaries[0]["kind"] == "document_summary"


def test_trim_rows_keep_diagnostics_preserves_stream_metadata() -> None:
    rows = [
        {"id": "raw:1", "source_type": "raw_chunk"},
        {"id": "raw:2", "source_type": "raw_chunk"},
        {"id": "raw_rag:diagnostics", "source_type": "diagnostics"},
    ]
    assert [row["id"] for row in trim_rows_keep_diagnostics(rows, limit=1)] == ["raw:1", "raw_rag:diagnostics"]


def test_orchestrator_returns_structured_result_with_fallbacks(tmp_path) -> None:
    result = run_query_orchestration("compare nickel leaching at 80 C", project_root=tmp_path, include_web=False)
    payload = result.as_dict()
    assert set(payload) == {"plan", "retrieved_context", "evidence", "answer_draft", "fallbacks", "local_diagnostics", "query_rewrite"}
    assert set(payload["retrieved_context"]) == {"raw", "summaries", "tables", "graph", "web"}
    assert payload["plan"]["intent"] == "compare_methods"
    assert isinstance(payload["evidence"], list)
    assert payload["answer_draft"]
    assert any(item["route"] in {"raw_rag", "summary_rag"} for item in payload["fallbacks"])
    assert payload["query_rewrite"]["corrected_query"] == "compare nickel leaching at 80 C"


def test_orchestrator_applies_llm_rewrite_to_local_rag_routes(tmp_path) -> None:
    class FakeRewriteClient:
        model_uri = "fake-routerai"

        def complete(self, prompt: str) -> tuple[str, dict[str, object]]:
            return (
                """
                {
                  "corrected_query": "nickel alloys annealing hardness",
                  "search_queries": ["nickel alloys heat treatment hardness"],
                  "keywords_ru": ["никелевые сплавы", "твердость"],
                  "keywords_en": ["nickel alloys", "hardness"],
                  "material_terms": ["nickel alloys"],
                  "process_terms": ["annealing", "heat treatment"],
                  "property_terms": ["hardness"],
                  "filters": {"materials_only": true}
                }
                """,
                {},
            )

    result = run_query_orchestration(
        "найди режимы термообработки для никелевых сплавов",
        project_root=tmp_path,
        include_web=False,
        required_routes=["raw_rag", "summary_rag"],
        use_llm_query_rewrite=True,
        rewrite_client=FakeRewriteClient(),
    )

    assert result.query_rewrite is not None
    assert result.query_rewrite["rewrite_used_llm"] is True
    assert result.plan.rewritten_queries.raw_rag[0] == "nickel alloys annealing hardness"
    assert result.plan.rewritten_queries.summary_rag[0] == "nickel alloys annealing hardness"
    assert result.local_diagnostics["actual_local_query"] == "nickel alloys annealing hardness"


def test_nickel_ore_query_uses_phrase_aliases_and_forced_routes() -> None:
    query = "\u043d\u0438\u043a\u0435\u043b\u0435\u0432\u0430\u044f \u0440\u0443\u0434\u0430"
    plan = plan_query(query)
    assert query in plan.entities.materials
    assert {"raw_rag", "summary_rag", "table_search", "graph_search"}.issubset(set(plan.routes))
    assert "\u041c\u0430\u0442\u0435\u0440\u0438\u0430\u043b:" not in " ".join(plan.internal_search_queries)
    assert "nickel ore" in " ".join(plan.web_search_queries)
    assert query in plan.entity_aliases

def test_answer_with_provider_router_passes_retrieved_context(monkeypatch, tmp_path) -> None:
    captured: dict[str, object] = {}

    class FakeRouter:
        def ask(self, question: str, **kwargs: object) -> LLMResponse:
            captured["question"] = question
            captured.update(kwargs)
            return LLMResponse(
                text="router answer",
                provider="routerai",
                model="deepseek/deepseek-chat-v3.1",
                status="fallback",
                used_evidence=bool(kwargs.get("context")),
            )

    monkeypatch.setattr("app.query.orchestrator.ProviderRouter.from_env", lambda **_: FakeRouter())
    result = QueryOrchestrationResult(
        plan=plan_query("nickel ore"),
        retrieved_context=RetrievedContext(
            raw=[
                {
                    "id": "raw:1",
                    "score": 1.0,
                    "doc_id": "doc1",
                    "preview": "Nickel ore flotation evidence.",
                    "score_components": {"lexical": 1.0},
                    "why": ["nickel ore"],
                }
            ]
        ),
        evidence=[],
        answer_draft="draft",
    )

    response = answer_with_provider_router("nickel ore", result, project_root=tmp_path)

    assert response.provider == "routerai"
    assert captured["question"] == "nickel ore"
    assert "Nickel ore flotation evidence" in str(captured["context"])


def test_orchestration_exports_and_archive_include_local_sources(tmp_path: Path) -> None:
    local_root = tmp_path / "data" / "raw"
    local_root.mkdir(parents=True)
    local_file = local_root / "local_method.txt"
    local_file.write_text("local nickel alloy method", encoding="utf-8")
    orchestration = QueryOrchestrationResult(
        plan=plan_query("nickel alloy annealing hardness"),
        retrieved_context=RetrievedContext(
            raw=[
                {
                    "id": "raw:1",
                    "source_type": "raw_chunk",
                    "title": "Local method",
                    "local_path": str(local_file),
                    "preview": "Annealing evidence from local file.",
                    "score": 0.91,
                }
            ],
            summaries=[
                {
                    "id": "procedure_summary:1",
                    "source_type": "procedure_summary",
                    "title": "Procedure summary",
                    "preview": "Heat treatment affects hardness.",
                    "score": 0.8,
                }
            ],
            web=[
                {
                    "id": "web:1",
                    "source": "openalex",
                    "title": "External paper",
                    "url": "https://example.org/paper",
                    "score": 0.7,
                }
            ],
        ),
        evidence=[],
        answer_draft="draft answer",
    )
    answer = LLMResponse(text="RouterAI answer", provider="routerai", model="test", status="primary", used_evidence=True)
    output_dir = tmp_path / "rag_run"

    exports = build_orchestration_exports(orchestration, "full", output_dir / "section_reports", answer=answer)
    assert exports["pdf"].exists()
    assert exports["docx"].exists()
    assert "RouterAI answer" in exports["markdown"].read_text(encoding="utf-8")

    archive = build_orchestration_archive(orchestration, output_dir / "orchestration_artifacts.zip", answer=answer, project_root=tmp_path)
    assert archive.exists()
    with zipfile.ZipFile(archive) as zf:
        names = set(zf.namelist())
    assert "orchestration_payload.json" in names
    assert "orchestration_web_links_manifest.json" in names
    assert "orchestration_local_files_manifest.json" in names
    assert "section_reports/full_report.pdf" in names
    assert "section_reports/full_report.docx" in names
    assert "local_publications/01_local_method.txt" in names
