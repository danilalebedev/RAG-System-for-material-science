from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

import pandas as pd
import streamlit as st
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.query.literature import run_literature_search  # noqa: E402
from app.query.reports import run_overall_summary  # noqa: E402
from app.web_search.schemas import ALL_SEARCH_SOURCES, DEFAULT_SEARCH_SOURCES, SEARCH_SOURCE_LABELS, LiteratureSearchRequest  # noqa: E402


load_dotenv(ROOT / ".env")


def display_value(value: Any, *, max_chars: int = 900) -> Any:
    if value in (None, "", [], {}):
        return ""
    if isinstance(value, (list, dict)):
        text = json.dumps(value, ensure_ascii=False, default=str)
    else:
        text = str(value)
    if len(text) > max_chars:
        return text[: max_chars - 3].rstrip() + "..."
    return text


def table_df(rows: list[dict[str, Any]]) -> pd.DataFrame:
    if not rows:
        return pd.DataFrame()
    normalized = [{key: display_value(value) for key, value in row.items()} for row in rows]
    return pd.DataFrame(normalized)


def render_table(rows: list[dict[str, Any]], *, empty_text: str = "Нет данных.") -> None:
    if not rows:
        st.info(empty_text)
        return
    st.dataframe(table_df(rows), use_container_width=True, hide_index=True)


def result_rows(run: Any) -> list[dict[str, Any]]:
    rows = []
    for item in run.results:
        rows.append(
            {
                "source": SEARCH_SOURCE_LABELS.get(item.source, item.source),
                "title": item.title,
                "year": item.year,
                "venue": item.venue,
                "quartile": item.raw.get("journal_quartile", "") if item.raw else "",
                "doi": item.doi,
                "score": item.score,
                "url": str(item.url) if item.url else None,
                "keywords": ", ".join(item.keyword_hits),
            }
        )
    return rows


def deep_rows(run: Any) -> list[dict[str, Any]]:
    rows = []
    for item in run.deep_results:
        summary = item.document_summary or {}
        rows.append(
            {
                "title": item.source_result.title,
                "status": item.status,
                "llm": item.llm_used,
                "procedures": len(item.procedure_summaries),
                "summary": summary.get("summary") or summary.get("main_topic"),
                "fetch_error": item.fetch_error,
            }
        )
    return rows


def comparison_rows(run: Any, key: str) -> list[dict[str, Any]]:
    if not run.comparison:
        return []
    return getattr(run.comparison, key, []) or []


def local_rows(run: Any) -> list[dict[str, Any]]:
    return run.local_matches or []


def render_chart(rows: list[dict[str, Any]]) -> None:
    if not rows:
        st.info("Нет данных для графика.")
        return
    df = pd.DataFrame(rows)
    col1, col2 = st.columns(2)
    with col1:
        if "year" in df and df["year"].notna().any():
            st.bar_chart(df.dropna(subset=["year"]).groupby("year").size().rename("count"))
    with col2:
        if "source" in df:
            st.bar_chart(df.groupby("source").size().rename("count"))


def render_warnings(warnings: list[str]) -> None:
    if not warnings:
        return
    with st.expander(f"Предупреждения источников ({len(warnings)})", expanded=False):
        for warning in warnings:
            st.warning(warning)


def render_run(run: Any) -> None:
    st.session_state["last_run"] = run
    tabs = st.tabs(["Ответ", "Публикации", "Deep Search", "Сравнение", "Evidence", "Графики", "Отчет"])
    corrected_query = run.query_plan.get("corrected_query") if run.query_plan else run.request.query
    search_queries = (run.query_plan or {}).get("search_queries") or []

    with tabs[0]:
        st.subheader("Поиск выполнен")
        col1, col2, col3 = st.columns(3)
        col1.metric("Внешние статьи", len(run.results))
        col2.metric("Локальные совпадения", len(run.local_matches))
        col3.metric("Deep Search summaries", len(run.deep_results))
        st.markdown(f"**Переформулированный запрос:** {corrected_query}")
        st.markdown(f"**Ключевые слова:** {', '.join(run.keywords) if run.keywords else 'n/a'}")
        if search_queries:
            with st.expander("Варианты запроса для поиска"):
                for item in search_queries:
                    st.write(f"- {item}")
        if run.query_plan:
            with st.expander("Технический JSON rewrite plan"):
                st.json(run.query_plan)
        with st.expander("Как ранжируются статьи"):
            st.markdown(
                "- результаты выбранных API-баз объединяются и дедуплицируются по DOI или нормализованному title;\n"
                "- score растет за совпадения ключевых слов в title/abstract/venue;\n"
                "- добавляется бонус за abstract, DOI, citations и свежий год;\n"
                "- score также растет за квартиль журнала, если он известен: Q1 +5, Q2 +3, Q3 +1.5, Q4 +0.5;\n"
                "- при `Materials science only` остаются только статьи с domain-сигналами: materials, metallurgy, alloy, ore, nickel, copper, flotation, leaching и т.п."
            )
        render_warnings(run.warnings)
        if run.comparison and run.comparison.gaps:
            st.write("Gaps")
            for gap in run.comparison.gaps:
                st.write(f"- {gap}")

    with tabs[1]:
        rows = result_rows(run)
        st.write("Найденные статьи")
        render_table(rows, empty_text="Внешние статьи не найдены.")
        if rows:
            st.download_button(
                "Download literature JSON",
                data=table_df(rows).to_json(orient="records", force_ascii=False, indent=2),
                file_name="literature_results.json",
                mime="application/json",
            )
        if run.report_pdf_path and Path(run.report_pdf_path).exists():
            st.download_button(
                "Download relevant articles PDF",
                data=Path(run.report_pdf_path).read_bytes(),
                file_name="relevant_articles_report.pdf",
                mime="application/pdf",
            )

    with tabs[2]:
        if run.request.deep_search != "top5":
            st.info("Deep Search не запускался. Включите `Deep search` в sidebar и повторите запрос.")
        else:
            st.subheader("Общий вывод по найденным статьям")
            st.write(run_overall_summary(run))
            st.write("Summary по отдельным статьям")
            render_table(deep_rows(run), empty_text="Deep Search запущен, но summaries не извлечены.")
            for item in run.deep_results:
                summary = item.document_summary or {}
                with st.expander(item.source_result.title):
                    if item.source_result.url:
                        st.markdown(f"[Открыть источник]({item.source_result.url})")
                    st.write(summary.get("summary") or summary.get("main_topic") or "Summary не извлечен.")
                    if item.procedure_summaries:
                        st.write("Procedure summaries")
                        render_table(item.procedure_summaries[:10])
                    elif item.status == "no_llm_credentials":
                        st.warning("LLM credentials не найдены, поэтому сохранен metadata-only fallback summary.")

    with tabs[3]:
        col1, col2 = st.columns(2)
        with col1:
            st.write("Confirmed")
            render_table(comparison_rows(run, "confirmed_methods"))
            st.write("Local only")
            render_table(comparison_rows(run, "local_only_methods"))
        with col2:
            st.write("Web only")
            render_table(comparison_rows(run, "web_only_methods"))
            st.write("Different conditions")
            render_table(comparison_rows(run, "differing_conditions"))

    with tabs[4]:
        st.write("Local evidence")
        render_table(local_rows(run))
        if run.comparison:
            st.write("Method rows")
            render_table(run.comparison.rows)

    with tabs[5]:
        render_chart(result_rows(run))
        if run.comparison:
            coverage = pd.DataFrame(
                [
                    {"bucket": "confirmed", "count": len(run.comparison.confirmed_methods)},
                    {"bucket": "local_only", "count": len(run.comparison.local_only_methods)},
                    {"bucket": "web_only", "count": len(run.comparison.web_only_methods)},
                    {"bucket": "different_conditions", "count": len(run.comparison.differing_conditions)},
                ]
            ).set_index("bucket")
            st.bar_chart(coverage)

    with tabs[6]:
        st.download_button(
            "Download report",
            data=run.report_markdown or "",
            file_name="literature_report.md",
            mime="text/markdown",
        )
        if run.report_pdf_path and Path(run.report_pdf_path).exists():
            st.download_button(
                "Download PDF report",
                data=Path(run.report_pdf_path).read_bytes(),
                file_name="literature_report.pdf",
                mime="application/pdf",
            )
        st.markdown(run.report_markdown or "")


def render_history() -> None:
    for message in st.session_state["history"][-8:]:
        with st.chat_message(message["role"]):
            st.write(message["content"])


def main() -> None:
    st.set_page_config(page_title="Поиск научных публикаций", layout="wide")
    st.title("Поиск научных публикаций")

    with st.sidebar:
        local_search = st.checkbox("Локальный поиск", value=True)
        web_search = st.checkbox("Внешний поиск публикаций", value=True)
        source_options = st.multiselect(
            "Search resources",
            options=ALL_SEARCH_SOURCES,
            default=DEFAULT_SEARCH_SOURCES,
            format_func=lambda item: SEARCH_SOURCE_LABELS.get(item, item),
            disabled=not web_search,
            help="Это реальные API-базы, по которым выполняется автоматический поиск и ранжирование.",
        )
        if "arxiv" in source_options:
            st.caption("arXiv может отвечать медленнее остальных источников.")
        top_k = st.slider("Top K", min_value=5, max_value=50, value=20, step=5)
        deep_search = st.checkbox("Deep search", value=False)
        max_deep = max(1, min(top_k, 15))
        deep_search_limit = st.slider(
            "Статей для Deep Search",
            min_value=1,
            max_value=max_deep,
            value=min(5, max_deep),
            step=1,
            disabled=not deep_search,
        )
        fetch_excerpts = st.checkbox("Fetch safe excerpts", value=True, disabled=not deep_search)
        pdf_report = st.checkbox("Generate PDF report", value=True)
        materials_only = st.checkbox("Materials science only", value=True)
        query_rewrite = st.checkbox("Rewrite/multiply query", value=True)
        llm_query_rewrite = st.checkbox("Use LLM rewrite if available", value=True, disabled=not query_rewrite)
        language = st.selectbox("Language", options=["auto", "ru", "en"], index=0)

    if "history" not in st.session_state:
        st.session_state["history"] = []

    render_history()

    query = st.chat_input("Спросите про материал, процесс, режим или свойство")
    if query:
        st.session_state["history"].append({"role": "user", "content": query})
        with st.chat_message("user"):
            st.write(query)

        request = LiteratureSearchRequest(
            query=query,
            top_k=top_k,
            sources=source_options if web_search else [],
            deep_search="top5" if deep_search else "none",
            deep_search_limit=deep_search_limit,
            language=language,
            include_local_search=local_search,
            materials_only=materials_only,
            use_query_rewrite=query_rewrite,
            use_llm_query_rewrite=llm_query_rewrite,
            include_recommended_resource_links=False,
            recommended_resource_ids=[],
            fetch_excerpts=fetch_excerpts,
            generate_pdf_report=pdf_report,
        )
        with st.chat_message("assistant"):
            with st.spinner("Выполняю поиск..."):
                run = run_literature_search(request)
            answer = f"Найдено внешних источников: {len(run.results)}; локальных совпадений: {len(run.local_matches)}."
            st.write(answer)
        st.session_state["history"].append({"role": "assistant", "content": answer})
        render_run(run)
    elif st.session_state.get("last_run"):
        render_run(st.session_state["last_run"])
    else:
        st.info("Введите запрос в чат ниже.")


if __name__ == "__main__":
    main()
