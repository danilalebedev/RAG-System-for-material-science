from __future__ import annotations

from types import SimpleNamespace

from app.ui.demo_app import answer_metrics, comparison_answer_sections, local_rows_from_literature, search_context_rows, source_rows, workflow_summary_rows


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


def test_publication_tables_are_compact_user_facing() -> None:
    run = SimpleNamespace(
        results=[
            SimpleNamespace(
                title="Nickel mine water treatment review",
                year=2024,
                source="openalex",
                score=9.5,
                journal_quartile="Q1",
                raw={},
            )
        ],
        local_matches=[
            {
                "title": "Локальный обзор очистки шахтных вод",
                "score": 0.72,
                "preview": "Фрагмент по сорбции и нейтрализации.",
            }
        ],
    )

    web_rows = source_rows(run)
    local_rows = local_rows_from_literature(run)

    assert list(web_rows[0]) == ["#", "Релевантность /10", "Год", "База", "Q", "Заголовок"]
    assert list(local_rows[0]) == ["#", "Релевантность /10", "Заголовок", "Фрагмент"]
    assert web_rows[0]["Релевантность /10"] == 10.0
    assert local_rows[0]["Релевантность /10"] == 10.0


def test_comparison_answer_sections_parse_three_user_blocks() -> None:
    answer = SimpleNamespace(
        text="""## Резюме по локальным источникам
Локально найдены отчеты по нейтрализации.

## Резюме по web-источникам
Во внешних источниках чаще встречается мембранная очистка.

## Сравнение источников: отличия и пробелы
Web шире покрывает зарубежные технологии, local лучше покрывает российскую практику."""
    )

    sections = comparison_answer_sections(answer)

    assert "нейтрализации" in sections["local"]
    assert "мембранная очистка" in sections["web"]
    assert "зарубежные технологии" in sections["diff"]


def test_answer_metrics_cost_label_has_no_approximation_prefix() -> None:
    answer = SimpleNamespace(
        metadata=lambda: {
            "usage": {
                "elapsed_seconds": 1.25,
                "total_tokens": 1000,
                "cost_rub": 0.5,
            }
        }
    )

    metrics = answer_metrics({"answer": answer, "comparison_answer": None})

    assert metrics["cost"] == "0.5 ₽"
    assert "~" not in metrics["cost"]


def test_answer_metrics_estimates_cost_from_tokens_without_approximation_prefix() -> None:
    answer = SimpleNamespace(
        metadata=lambda: {
            "usage": {
                "elapsed_seconds": 1.25,
                "total_tokens": 1000,
            }
        }
    )

    metrics = answer_metrics({"answer": answer, "comparison_answer": None})

    assert "~" not in metrics["cost"]
    assert metrics["cost"].endswith("₽")
