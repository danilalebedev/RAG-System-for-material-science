from __future__ import annotations

from types import SimpleNamespace

from app.ui.demo_app import (
    answer_metrics,
    citation_ref_map,
    comparison_answer_sections,
    display_source_title,
    local_rows_from_literature,
    market_radar_rows,
    method_comparison_rows,
    run_query_orchestration_compat,
    search_context_rows,
    should_run_market_radar,
    source_rows,
    workflow_summary_rows,
)


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
            "request_type": "Анализ методик и свойств",
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


def test_method_comparison_rows_are_user_facing_for_business_mode() -> None:
    comparison = SimpleNamespace(
        as_dict=lambda: {
            "rows": [
                {
                    "item": "reverse osmosis",
                    "score": 8.7,
                    "materials": ["mine water"],
                    "conditions": ["TDS 1000 mg/L"],
                    "numeric_values": ["200-300 mg/L sulfate"],
                    "business_context": ["energy", "opex"],
                    "limitations": ["membrane fouling"],
                    "evidence": [{"citation": "tables:1", "title": "water treatment economics"}],
                }
            ]
        }
    )

    rows = method_comparison_rows({"request_type": "Бизнес-аналитика", "method_comparison": comparison})

    assert list(rows[0]) == [
        "#",
        "Релевантность /10",
        "Решение / технология",
        "Где применимо",
        "Условия / KPI",
        "Экономика",
        "Риски / ограничения",
        "Источники",
    ]
    assert rows[0]["Экономика"] == "energy; opex"
    assert "[tables:1]" in rows[0]["Источники"]


def test_market_radar_rows_are_compact_user_facing() -> None:
    market_row = SimpleNamespace(
        commodity="nickel",
        company_or_country="Nornickel",
        period="2024",
        value=205,
        unit="kt",
        source_name="Nornickel production reports",
        confidence="high",
    )
    radar = SimpleNamespace(production_rows=[market_row])

    rows = market_radar_rows({"market_radar": radar})

    assert rows[0]["Показатель"] == "nickel"
    assert rows[0]["Значение"] == 205
    assert rows[0]["Источник"] == "Nornickel production reports"


def test_market_radar_runs_only_for_market_like_queries() -> None:
    assert should_run_market_radar("Сравни производство стали в России и Китае за 2024 год")
    assert should_run_market_radar("Доли компаний на рынке никеля")
    assert not should_run_market_radar(
        "Технико-экономическое сравнение вариантов подготовки воды для обогатительной фабрики"
    )


def test_run_query_orchestration_compat_handles_stale_signature(monkeypatch) -> None:
    captured: dict[str, object] = {}

    def old_run_query_orchestration(
        query: str,
        *,
        project_root: object,
        include_web: bool,
        web_sources: list[object],
        web_top_k: int,
        web_deep_search: bool,
        web_deep_search_limit: int,
        generate_pdf_report: bool,
        required_routes: list[str],
        retrieval_profile: str,
        use_query_rewrite: bool,
        use_llm_query_rewrite: bool,
        rewrite_client: object,
    ) -> str:
        captured.update(locals())
        return "ok"

    monkeypatch.setattr("app.ui.demo_app.run_query_orchestration", old_run_query_orchestration)

    result = run_query_orchestration_compat(
        "query",
        project_root=object(),
        include_web=False,
        web_sources=[],
        web_top_k=5,
        web_deep_search=False,
        web_deep_search_limit=5,
        generate_pdf_report=False,
        required_routes=["summary_rag"],
        retrieval_profile="routerai_bge_m3",
        use_query_rewrite=True,
        use_llm_query_rewrite=False,
        rewrite_client=None,
        local_top_k=20,
    )

    assert result == "ok"
    assert "local_top_k" not in captured


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


def test_display_source_title_prefers_file_name_over_hash() -> None:
    row = {
        "doc_id": "162cb4ec8dc1d8c1",
        "source_path": r"C:\repo\data\raw\Обзор распределения металлов.docx",
    }

    assert display_source_title(row) == "Обзор распределения металлов"


def test_citation_ref_map_links_summary_rows_through_same_doc_id(tmp_path, monkeypatch) -> None:
    source = tmp_path / "Распределение Au Ag МПГ.docx"
    source.write_text("demo", encoding="utf-8")
    monkeypatch.setattr("app.ui.demo_app.local_file_for_row", lambda row: source if row.get("local_path") else None)
    orchestration = SimpleNamespace(
        retrieved_context=SimpleNamespace(
            as_dict=lambda: {
                "raw": [
                    {
                        "id": "raw_chunk:abc123456789",
                        "chunk_id": "abc123456789",
                        "doc_id": "doc-hash",
                        "local_path": str(source),
                        "preview": "text",
                    }
                ],
                "summaries": [
                    {
                        "id": "document_summary:docsum_doc_hash",
                        "doc_id": "doc-hash",
                        "preview": "summary",
                    }
                ],
                "tables": [],
                "graph": [],
                "web": [],
            }
        )
    )

    refs = citation_ref_map(None, orchestration)

    assert "raw:abc123456789" in refs
    assert "document_summary:docsum_doc_hash" in refs
    assert refs["document_summary:docsum_doc_hash"]["href"].startswith("file:///")
    assert refs["document_summary:docsum_doc_hash"]["label"] == "Распределение Au Ag МПГ"


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
