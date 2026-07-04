from __future__ import annotations

from typing import Any

from app.query.comparison import compare_methods


class FakeOrchestration:
    def as_dict(self) -> dict[str, Any]:
        return {
            "plan": {
                "original_query": "compare leaching and flotation",
                "intent": "compare_methods",
                "domain": "materials_science",
                "entities": {
                    "materials": ["nickel"],
                    "processes": ["leaching", "flotation"],
                    "equipment": [],
                    "properties": [],
                    "experts": [],
                    "facilities": [],
                },
                "rewritten_queries": {"raw_rag": [], "summary_rag": [], "graph": [], "tables": [], "web": []},
                "decomposed_questions": [],
                "routes": ["summary_rag", "raw_rag", "table_search", "graph_search"],
                "answer_format": "comparison_table",
                "needs_clarification": False,
                "clarifying_question": None,
            },
            "retrieved_context": {
                "raw": [
                    {
                        "id": "raw:1",
                        "doc_id": "doc-1",
                        "source_path": "paper.pdf",
                        "preview": "Leaching recovered nickel at 80 C with 20% acid.",
                    }
                ],
                "summaries": [
                    {
                        "id": "summaries:1",
                        "summary_id": "sum-1",
                        "title": "Nickel leaching",
                        "preview": "Acid leaching extracts nickel from tailings.",
                        "row": {
                            "synthesis_or_process_method": "acid leaching",
                            "materials": ["nickel tailings"],
                            "operating_conditions": ["80 C", "20% acid"],
                            "properties": ["recovery"],
                            "numerical_results": ["92% Ni recovery"],
                            "key_findings": ["high recovery"],
                            "limitations_or_gaps": ["acid consumption"],
                        },
                    }
                ],
                "tables": [
                    {
                        "id": "tables:1",
                        "table_name": "Leaching parameters",
                        "preview": "80 C, 20% acid, 92% recovery",
                    }
                ],
                "graph": [
                    {"id": "graph:1", "type": "Material", "label": "nickel"},
                    {"id": "graph:2", "type": "Process", "label": "leaching"},
                ],
                "web": [],
            },
            "evidence": [{"citation": "summaries:1", "route": "summaries", "title": "Nickel leaching"}],
            "answer_draft": "draft",
            "fallbacks": [],
        }


def test_compare_methods_returns_required_shape(monkeypatch) -> None:
    def fake_run_query_orchestration(*args: Any, **kwargs: Any) -> FakeOrchestration:
        assert kwargs["required_routes"] == ["summary_rag", "raw_rag", "table_search", "graph_search"]
        return FakeOrchestration()

    monkeypatch.setattr("app.query.comparison.run_query_orchestration", fake_run_query_orchestration)
    payload = compare_methods("compare leaching and flotation", top_k=5).as_dict()

    assert set(payload) >= {
        "query",
        "compared_items",
        "comparison_dimensions",
        "rows",
        "missing_evidence",
        "answer_summary",
    }
    assert payload["plan"]["intent"] == "compare_methods"
    assert payload["compared_items"] == ["acid leaching"]
    row = payload["rows"][0]
    assert row["item"] == "acid leaching"
    assert "nickel tailings" in row["materials"]
    assert row["numeric_values"]
    assert row["evidence"]


def test_compare_methods_adds_web_route_when_enabled(monkeypatch) -> None:
    captured: dict[str, Any] = {}

    def fake_run_query_orchestration(*args: Any, **kwargs: Any) -> FakeOrchestration:
        captured.update(kwargs)
        return FakeOrchestration()

    monkeypatch.setattr("app.query.comparison.run_query_orchestration", fake_run_query_orchestration)
    compare_methods("compare local and world leaching", include_web=True, top_k=3)

    assert captured["include_web"] is True
    assert captured["web_top_k"] == 3
    assert captured["web_deep_search"] is True
    assert captured["required_routes"] == ["summary_rag", "raw_rag", "table_search", "graph_search", "web_search"]


def test_compare_methods_builds_rows_from_web_deep_summaries(monkeypatch) -> None:
    class WebSummaryOrchestration(FakeOrchestration):
        def as_dict(self) -> dict[str, Any]:
            payload = super().as_dict()
            payload["retrieved_context"]["summaries"] = []
            payload["retrieved_context"]["web"] = [
                {
                    "id": "webdocsum:1",
                    "source": "deep_search",
                    "kind": "document_summary",
                    "title": "Web nickel flotation",
                    "preview": "Nickel ore flotation improves recovery.",
                    "row": {
                        "methods": ["flotation"],
                        "materials": ["nickel ore"],
                        "process_parameters": ["pH 9"],
                        "analysis_results": ["91% Ni recovery"],
                        "key_findings": ["xanthate dosage matters"],
                    },
                }
            ]
            payload["evidence"] = [{"citation": "webdocsum:1", "route": "web", "title": "Web nickel flotation"}]
            return payload

    monkeypatch.setattr("app.query.comparison.run_query_orchestration", lambda *args, **kwargs: WebSummaryOrchestration())

    result = compare_methods("compare nickel ore flotation", include_web=True, top_k=3)

    assert result.rows
    row = result.rows[0]
    assert row.item == "flotation"
    assert "nickel ore" in row.materials
    assert "91% Ni recovery" in row.numeric_values
