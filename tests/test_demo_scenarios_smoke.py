from __future__ import annotations

from app.web_search.schemas import LiteratureSearchResult
from scripts import smoke_demo_scenarios


def test_context_counts_returns_stable_sections() -> None:
    payload = {
        "retrieved_context": {
            "raw": [{"id": "raw:1"}],
            "summaries": [],
            "tables": [{"id": "table:1"}, {"id": "table:2"}],
            "graph": [{"id": "graph:1"}],
            "web": [],
        }
    }

    assert smoke_demo_scenarios.context_counts(payload) == {
        "raw": 1,
        "summaries": 0,
        "tables": 2,
        "graph": 1,
        "web": 0,
    }


def test_offline_literature_client_returns_materials_science_result() -> None:
    client = smoke_demo_scenarios.OfflineLiteratureClient()

    results, warnings = client.search(
        "nickel ore flotation",
        keywords=["nickel", "flotation"],
        sources=["crossref"],
        top_k=3,
        query_variants=["nickel ore flotation"],
        materials_only=True,
        relevance_terms=["Ni"],
    )

    assert warnings == []
    assert len(results) == 1
    assert isinstance(results[0], LiteratureSearchResult)
    assert results[0].source == "crossref"
    assert "nickel" in results[0].evidence_text().casefold()


def test_run_smoke_orchestrates_three_current_modes(monkeypatch, tmp_path) -> None:
    calls: list[tuple[str, str]] = []

    def fake_literature(query: str, *, output_root):
        calls.append(("literature", query))
        assert output_root == tmp_path
        return {"mode": "Литературный поиск", "web_results": 1}

    def fake_orchestration(mode: str, query: str):
        calls.append((mode, query))
        return {"mode": mode, "routes": smoke_demo_scenarios.REQUEST_TYPES[mode]}

    monkeypatch.setattr(smoke_demo_scenarios, "run_literature_smoke", fake_literature)
    monkeypatch.setattr(smoke_demo_scenarios, "run_orchestration_smoke", fake_orchestration)

    payload = smoke_demo_scenarios.run_smoke(output_root=tmp_path)

    assert payload["status"] == "ok"
    assert [row["mode"] for row in payload["scenarios"]] == ["Литературный поиск", "Поиск методик", "Поиск свойств"]
    assert calls[0][0] == "literature"
    assert calls[1][0] == "Поиск методик"
    assert calls[2][0] == "Поиск свойств"

