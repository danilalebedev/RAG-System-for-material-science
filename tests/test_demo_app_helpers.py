from __future__ import annotations

from types import SimpleNamespace

from app.ui.demo_app import search_context_rows, workflow_summary_rows


def test_search_context_rows_are_user_facing() -> None:
    run = SimpleNamespace(
        request=SimpleNamespace(query="Найди никелевые сплавы для судостроения"),
        keywords=["никелевые сплавы", "судостроение", "твердость"],
        query_plan={
            "original_query": "Найди никелевые сплавы для судостроения",
            "llm_rewrite": {
                "corrected_query": "nickel alloys shipbuilding hardness",
                "search_queries": ["nickel alloys shipbuilding", "marine nickel alloys"],
                "rewrite_used_llm": True,
            },
            "internal_search_queries": ["никелевые сплавы судостроение"],
            "rewritten_queries": {
                "raw_rag": ["nickel alloys marine applications"],
                "summary_rag": ["никелевые сплавы твердость"],
            },
        },
    )

    rows = search_context_rows(run, None)
    labels = [row["Что используется"] for row in rows]
    values = " ".join(row["Значение"] for row in rows)

    assert labels[:2] == ["Исходный запрос", "Поисковая формулировка"]
    assert "Ключевые слова" in labels
    assert "Web-поиск" in labels
    assert "Локальный RAG" in labels
    assert "nickel alloys shipbuilding hardness" in values
    assert "никелевые сплавы, судостроение, твердость" in values
    assert not any({"stage", "query", "llm"} & set(row) for row in rows)


def test_search_context_rows_falls_back_to_orchestration_plan() -> None:
    orchestration = SimpleNamespace(
        query_rewrite={"corrected_query": "nickel ore flotation", "rewrite_used_llm": False},
        plan=SimpleNamespace(
            model_dump=lambda mode="json": {
                "original_query": "никелевая руда флотация",
                "web_search_queries": ["nickel ore flotation"],
                "internal_search_queries": ["никелевая руда"],
            }
        ),
    )

    rows = search_context_rows(None, orchestration)

    assert rows[0] == {"Что используется": "Исходный запрос", "Значение": "никелевая руда флотация"}
    assert rows[1] == {"Что используется": "Поисковая формулировка", "Значение": "nickel ore flotation"}


def test_workflow_summary_rows_explain_orchestration_without_json() -> None:
    run = SimpleNamespace(
        local_matches=[{"title": "Local nickel report"}],
        results=[
            SimpleNamespace(source="crossref"),
            SimpleNamespace(source="openalex"),
        ],
        deep_results=[{"summary": "Deep summary"}],
    )
    orchestration = SimpleNamespace(
        plan=SimpleNamespace(routes=["summary_rag", "raw_rag", "table_search", "graph_search"]),
        retrieved_context=SimpleNamespace(
            as_dict=lambda: {
                "raw": [{"id": 1}, {"id": 2}],
                "summaries": [{"id": 3}],
                "tables": [{"id": 4}],
                "graph": [{"id": 5}, {"id": 6}, {"id": 7}],
                "web": [],
            }
        ),
        fallbacks=[],
    )
    answer = SimpleNamespace(metadata=lambda: {"provider": "routerai", "model": "deepseek/deepseek-chat-v3.1"})

    rows = workflow_summary_rows(
        {
            "request_type": "Поиск методик",
            "literature_run": run,
            "orchestration": orchestration,
            "answer": answer,
        }
    )
    labels = [row["Шаг"] for row in rows]
    text = " ".join(f"{row['Что сделано']} {row['Объем']}" for row in rows)

    assert labels[:2] == ["Сценарий", "Маршрут"]
    assert "Summary RAG -> Raw RAG -> Tables -> Knowledge graph" in text
    assert "raw: 2; summary: 1; tables: 1; graph: 3" in text
    assert "2 источников" in text
    assert "summary extraction выполнен" in text
    assert "deepseek/deepseek-chat-v3.1" in text
    assert not any({"retrieved_context", "plan", "query_rewrite"} & set(row) for row in rows)
