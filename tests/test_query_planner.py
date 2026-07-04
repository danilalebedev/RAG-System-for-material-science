from __future__ import annotations

from app.query.orchestrator import run_query_orchestration
from app.query.planner import plan_query


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
    plan = plan_query("Показать связи: никель -> процессы -> свойства -> публикации")
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
    payload = plan_query("где написано про извлечение никеля из хвостов").model_dump(mode="json")
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


def test_orchestrator_returns_structured_result_with_fallbacks(tmp_path) -> None:
    result = run_query_orchestration("compare nickel leaching at 80 C", project_root=tmp_path, include_web=False)
    payload = result.as_dict()
    assert set(payload) == {"plan", "retrieved_context", "evidence", "answer_draft", "fallbacks", "local_diagnostics"}
    assert set(payload["retrieved_context"]) == {"raw", "summaries", "tables", "graph", "web"}
    assert payload["plan"]["intent"] == "compare_methods"
    assert isinstance(payload["evidence"], list)
    assert payload["answer_draft"]
    assert any(item["route"] in {"raw_rag", "summary_rag"} for item in payload["fallbacks"])


def test_nickel_ore_query_uses_phrase_aliases_and_forced_routes() -> None:
    plan = plan_query("никелевая руда")
    assert "никелевая руда" in plan.entities.materials
    assert {"raw_rag", "summary_rag", "table_search", "graph_search"}.issubset(set(plan.routes))
    assert "Материал:" not in " ".join(plan.internal_search_queries)
    assert "nickel ore" in " ".join(plan.web_search_queries)
    assert "никелевая руда" in plan.entity_aliases
