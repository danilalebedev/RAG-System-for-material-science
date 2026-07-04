from __future__ import annotations

import json
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

import pandas as pd
import streamlit as st
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.query.literature import run_deep_search_for_existing_run, run_literature_search  # noqa: E402
from app.query.orchestrator import answer_with_provider_router, run_query_orchestration  # noqa: E402
from app.query.reports import (  # noqa: E402
    build_run_archive,
    comparison_insights,
    compact_text,
    repair_mojibake,
    result_link,
    run_overall_summary,
    source_counts,
    year_counts,
)
from app.web_search.deep_search import build_router_completion_client_from_env  # noqa: E402
from app.web_search.schemas import ALL_SEARCH_SOURCES, DEFAULT_SEARCH_SOURCES, SEARCH_SOURCE_LABELS, LiteratureSearchRequest  # noqa: E402


load_dotenv(ROOT / ".env", encoding="utf-8-sig")

REQUEST_TYPES = {
    "Литературный поиск": ["summary_rag", "raw_rag"],
    "Поиск методик": ["summary_rag", "raw_rag", "table_search", "graph_search"],
    "Поиск свойств": ["raw_rag", "summary_rag", "table_search", "graph_search"],
}


def display_value(value: Any, *, max_chars: int = 900) -> Any:
    if value in (None, "", [], {}):
        return ""
    if isinstance(value, (list, dict)):
        text = json.dumps(value, ensure_ascii=False, default=str)
    else:
        text = repair_mojibake(value)
    if len(text) > max_chars:
        return text[: max_chars - 3].rstrip() + "..."
    return text


def table_df(rows: list[dict[str, Any]]) -> pd.DataFrame:
    if not rows:
        return pd.DataFrame()
    return pd.DataFrame([{key: display_value(value) for key, value in row.items()} for row in rows])


def render_table(rows: list[dict[str, Any]], *, empty_text: str = "Нет данных.") -> None:
    if not rows:
        st.info(empty_text)
        return
    st.dataframe(table_df(rows), use_container_width=True, hide_index=True)


def source_rows(run: Any) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for index, result in enumerate(getattr(run, "results", []) or [], start=1):
        raw = getattr(result, "raw", None) or {}
        rows.append(
            {
                "#": index,
                "title": result.title,
                "year": result.year,
                "source": SEARCH_SOURCE_LABELS.get(result.source, result.source),
                "score": round(float(result.score or 0.0), 3),
                "quartile": getattr(result, "journal_quartile", None) or raw.get("journal_quartile") or "",
                "link": result_link(result),
            }
        )
    return rows


def local_rows_from_literature(run: Any) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for index, row in enumerate(getattr(run, "local_matches", []) or [], start=1):
        rows.append(
            {
                "#": index,
                "title": row.get("title") or row.get("doc_id") or row.get("source_path"),
                "score": row.get("score"),
                "method": row.get("method") or row.get("synthesis_or_process_method"),
                "material": row.get("material") or row.get("material_name"),
                "evidence": row.get("preview") or row.get("summary") or row.get("source_path"),
            }
        )
    return rows


def orchestration_rows(orchestration: Any | None, section: str) -> list[dict[str, Any]]:
    if orchestration is None:
        return []
    return list((orchestration.retrieved_context.as_dict().get(section) or []))


def comparison_rows(run: Any | None, name: str) -> list[dict[str, Any]]:
    if run is None or not getattr(run, "comparison", None):
        return []
    return list(getattr(run.comparison, name, []) or [])


def confidence_label(run: Any | None, orchestration: Any | None) -> tuple[str, float]:
    web = len(getattr(run, "results", []) or []) if run else 0
    local = len(getattr(run, "local_matches", []) or []) if run else 0
    deep = len(getattr(run, "deep_results", []) or []) if run else 0
    evidence = len(getattr(orchestration, "evidence", []) or []) if orchestration else 0
    score = min(1.0, 0.02 * web + 0.04 * local + 0.08 * deep + 0.04 * evidence)
    if score >= 0.72:
        return "Высокая", score
    if score >= 0.38:
        return "Средняя", score
    return "Низкая", score


def rewritten_query_rows(run: Any | None, orchestration: Any | None) -> list[dict[str, Any]]:
    plan = getattr(run, "query_plan", None) if run else None
    if not plan and orchestration is not None:
        plan = orchestration.plan.model_dump(mode="json")
    plan = plan or {}
    rewrite = plan.get("llm_rewrite") if isinstance(plan.get("llm_rewrite"), dict) else {}
    rows: list[dict[str, Any]] = []
    if rewrite:
        rows.append({"stage": "corrected", "query": rewrite.get("corrected_query"), "llm": rewrite.get("rewrite_used_llm")})
        for query in rewrite.get("search_queries") or []:
            rows.append({"stage": "search_variant", "query": query, "llm": rewrite.get("rewrite_used_llm")})
    rewritten = plan.get("rewritten_queries") if isinstance(plan.get("rewritten_queries"), dict) else {}
    for route, queries in rewritten.items():
        for query in queries or []:
            rows.append({"stage": route, "query": query, "llm": False})
    return rows


def graph_dot_from_orchestration(orchestration: Any | None) -> str:
    rows = orchestration_rows(orchestration, "graph")
    if not rows:
        return "digraph G { rankdir=LR; empty [label=\"Нет графовых связей\"]; }"
    lines = [
        "digraph G {",
        "rankdir=LR;",
        "node [shape=box, style=\"rounded,filled\", fillcolor=\"#eef7f4\", color=\"#9fb8ad\", fontname=\"Arial\"];",
    ]
    for row in rows[:30]:
        if row.get("kind") == "neighbor":
            left = compact_text(row.get("relation") or "relation", 50)
            right = compact_text(row.get("label") or row.get("node_id"), 80)
            lines.append(f'"{left}" -> "{right}";')
        elif row.get("kind") == "entity":
            label = compact_text(row.get("label") or row.get("node_id"), 80)
            node_type = compact_text(row.get("type") or "entity", 40)
            lines.append(f'"{node_type}" -> "{label}";')
    lines.append("}")
    return "\n".join(lines)


def method_graph_dot(run: Any | None) -> str:
    rows = []
    if run is not None and getattr(run, "comparison", None):
        rows = list(run.comparison.rows or [])
    if not rows:
        return "digraph G { rankdir=LR; empty [label=\"Нет comparison rows\"]; }"
    lines = [
        "digraph G {",
        "rankdir=LR;",
        "node [shape=box, style=\"rounded,filled\", fontname=\"Arial\", color=\"#c8cdd6\"];",
    ]
    for row in rows[:40]:
        material = compact_text(row.get("material") or "material", 60)
        method = compact_text(row.get("method") or row.get("synthesis_or_process_method") or "method", 70)
        scope = compact_text(row.get("scope") or "source", 40)
        title = compact_text(row.get("title") or row.get("doc_id") or scope, 80)
        lines.append(f'"Material: {material}" -> "Method: {method}" [label="{scope}"];')
        lines.append(f'"Method: {method}" -> "Source: {title}";')
    lines.append("}")
    return "\n".join(lines)


def property_rows(run: Any | None, orchestration: Any | None) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    if run is not None and getattr(run, "comparison", None):
        for row in run.comparison.rows or []:
            rows.append(
                {
                    "scope": row.get("scope"),
                    "material": row.get("material") or row.get("material_name"),
                    "method": row.get("method") or row.get("synthesis_or_process_method"),
                    "outputs": row.get("outputs"),
                    "numeric_results": row.get("numeric_results") or row.get("analysis_results"),
                    "conditions": row.get("conditions"),
                    "evidence": row.get("title") or row.get("doc_id"),
                }
            )
    for row in orchestration_rows(orchestration, "tables")[:25]:
        rows.append(
            {
                "scope": "local_table",
                "material": row.get("matched_terms"),
                "method": "",
                "outputs": row.get("summary"),
                "numeric_results": row.get("preview") or row.get("rows"),
                "conditions": row.get("path"),
                "evidence": row.get("source") or row.get("doc_id"),
            }
        )
    return rows


def render_download(path: Path | None, label: str, mime: str) -> None:
    if not path or not Path(path).exists():
        return
    data = Path(path).read_bytes()
    st.download_button(label, data=data, file_name=Path(path).name, mime=mime, use_container_width=True)


def render_reports(run: Any | None) -> None:
    if run is None:
        st.info("Отчет появится после web-search.")
        return
    cols = st.columns(3)
    with cols[0]:
        render_download(getattr(run, "links_report_pdf_path", None), "PDF: только ссылки", "application/pdf")
        render_download(getattr(run, "links_report_docx_path", None), "DOCX: только ссылки", "application/vnd.openxmlformats-officedocument.wordprocessingml.document")
    with cols[1]:
        render_download(getattr(run, "deep_report_pdf_path", None), "PDF: Deep Search", "application/pdf")
        render_download(getattr(run, "deep_report_docx_path", None), "DOCX: Deep Search", "application/vnd.openxmlformats-officedocument.wordprocessingml.document")
    with cols[2]:
        render_download(getattr(run, "report_pdf_path", None), "PDF: полный отчет", "application/pdf")
        render_download(getattr(run, "report_docx_path", None), "DOCX: полный отчет", "application/vnd.openxmlformats-officedocument.wordprocessingml.document")
        if getattr(run, "full_run_json_path", None):
            render_download(run.full_run_json_path, "JSON: все данные", "application/json")
    if getattr(run, "output_dir", None):
        archive = build_run_archive(run, Path(run.output_dir) / "run_artifacts.zip")
        render_download(archive, "ZIP: все артефакты поиска", "application/zip")


def render_result(record: dict[str, Any]) -> None:
    run = record.get("literature_run")
    orchestration = record.get("orchestration")
    answer = record.get("answer")
    confidence_text, confidence_score = confidence_label(run, orchestration)

    cols = st.columns(4)
    cols[0].metric("Web sources", len(getattr(run, "results", []) or []))
    cols[1].metric("Local evidence", len(getattr(run, "local_matches", []) or []) + len(getattr(orchestration, "evidence", []) or []))
    cols[2].metric("Deep Search summaries", len(getattr(run, "deep_results", []) or []))
    cols[3].metric("Confidence", f"{confidence_text} ({confidence_score:.0%})")

    tabs = st.tabs(["Ответ", "Источники", "Сравнение", "Evidence", "Графы", "Графики", "Отчеты"])
    with tabs[0]:
        if answer is not None:
            st.markdown(compact_text(getattr(answer, "text", ""), 6000))
            metadata = answer.metadata() if hasattr(answer, "metadata") else {}
            render_table([metadata], empty_text="Нет metadata по LLM.")
        elif run is not None:
            st.write(run_overall_summary(run))
            insights = comparison_insights(run)
            if insights:
                st.write(insights)
        elif orchestration is not None:
            st.text(orchestration.answer_draft)
        st.markdown("**Ключевые слова и переформулировки**")
        if run is not None:
            st.write(", ".join(getattr(run, "keywords", []) or []) or "n/a")
        render_table(rewritten_query_rows(run, orchestration), empty_text="Переформулировки не найдены.")

    with tabs[1]:
        st.markdown("**Web-search**")
        render_table(source_rows(run), empty_text="Web-источники не найдены.")
        st.markdown("**Локальный поиск**")
        render_table(local_rows_from_literature(run), empty_text="Локальные совпадения не найдены в literature layer.")
        if run is not None and getattr(run, "resource_links", None):
            st.markdown("**Дополнительные ссылки**")
            render_table(run.resource_links)

    with tabs[2]:
        st.markdown("**Подтверждается локально и во внешней литературе**")
        render_table(comparison_rows(run, "confirmed_methods"))
        st.markdown("**Только локально**")
        render_table(comparison_rows(run, "local_only_methods"))
        st.markdown("**Только во внешней литературе**")
        render_table(comparison_rows(run, "web_only_methods"))
        st.markdown("**Свойства и численные результаты**")
        render_table(property_rows(run, orchestration))

    with tabs[3]:
        if orchestration is None:
            st.info("Local RAG evidence появится для режимов методик/свойств или при генерации ответа.")
        else:
            st.markdown("**Raw RAG**")
            render_table(orchestration_rows(orchestration, "raw"))
            st.markdown("**Summary RAG**")
            render_table(orchestration_rows(orchestration, "summaries"))
            st.markdown("**Tables**")
            render_table(orchestration_rows(orchestration, "tables"))
            if orchestration.fallbacks:
                st.markdown("**Fallbacks**")
                render_table(orchestration.fallbacks)

    with tabs[4]:
        col_a, col_b = st.columns(2)
        with col_a:
            st.markdown("**Knowledge graph**")
            st.graphviz_chart(graph_dot_from_orchestration(orchestration), use_container_width=True)
        with col_b:
            st.markdown("**Методики: local vs web**")
            st.graphviz_chart(method_graph_dot(run), use_container_width=True)

    with tabs[5]:
        years = table_df(year_counts(run)) if run is not None else pd.DataFrame()
        sources = table_df(source_counts(run)) if run is not None else pd.DataFrame()
        if not years.empty:
            st.bar_chart(years.set_index("year"))
        else:
            st.info("Нет данных по годам публикаций.")
        if not sources.empty:
            st.bar_chart(sources.set_index("source"))
        else:
            st.info("Нет данных по базам данных.")

    with tabs[6]:
        render_reports(run)


def execute_query(query: str, options: dict[str, Any]) -> dict[str, Any]:
    request_type = options["request_type"]
    literature_run = None
    orchestration = None
    answer = None
    llm_client = build_router_completion_client_from_env(ROOT) if options["use_llm_rewrite"] or options["deep_search"] else None

    if request_type == "Литературный поиск":
        request = LiteratureSearchRequest(
            query=query,
            top_k=options["top_k"],
            sources=options["sources"] if options["web_search"] else [],
            deep_search="top5" if options["deep_search"] else "none",
            deep_search_limit=options["deep_limit"],
            include_local_search=options["local_search"],
            materials_only=True,
            use_query_rewrite=True,
            use_llm_query_rewrite=options["use_llm_rewrite"],
            generate_comparison_insights=options["comparison_insights"],
            include_recommended_resource_links=False,
            fetch_excerpts=options["fetch_excerpts"],
            generate_pdf_report=options["generate_pdf"],
        )
        literature_run = run_literature_search(request, project_root=ROOT, yandex_client=llm_client)
    else:
        orchestration = run_query_orchestration(
            query,
            project_root=ROOT,
            include_web=options["web_search"],
            web_sources=options["sources"],
            web_top_k=options["top_k"],
            web_deep_search=options["deep_search"],
            web_deep_search_limit=options["deep_limit"],
            generate_pdf_report=options["generate_pdf"],
            required_routes=REQUEST_TYPES[request_type],
        )
        literature_run = orchestration.web_run
        if options["generate_answer"]:
            answer = answer_with_provider_router(query, orchestration, project_root=ROOT, max_tokens=options["answer_tokens"])

    return {
        "query": query,
        "request_type": request_type,
        "created_at": datetime.now().strftime("%H:%M:%S"),
        "literature_run": literature_run,
        "orchestration": orchestration,
        "answer": answer,
    }


def render_sidebar() -> dict[str, Any]:
    with st.sidebar:
        st.header("Настройки")
        request_type = st.radio("Тип запроса", list(REQUEST_TYPES), horizontal=False)
        local_search = st.checkbox("Local search", value=True)
        web_search = st.checkbox("Web literature search", value=True)
        use_llm_rewrite = st.checkbox("LLM rewrite запроса", value=True)
        deep_search = st.checkbox("Deep Search", value=False)
        deep_limit = st.slider("Статей для Deep Search", min_value=1, max_value=20, value=5)
        top_k = st.slider("Top K", min_value=3, max_value=60, value=20)
        sources = st.multiselect(
            "Search resources",
            options=ALL_SEARCH_SOURCES,
            default=DEFAULT_SEARCH_SOURCES,
            format_func=lambda item: SEARCH_SOURCE_LABELS.get(item, item),
        )
        generate_answer = st.checkbox("Ответ через RouterAI", value=request_type != "Литературный поиск")
        answer_tokens = st.slider("Длина ответа", min_value=300, max_value=1800, value=900, step=100)
        generate_pdf = st.checkbox("Генерировать PDF", value=True)
        comparison_insights = st.checkbox("Выводы по сравнению", value=True)
        fetch_excerpts = st.checkbox("Загружать безопасные excerpts", value=True)
    return {
        "request_type": request_type,
        "local_search": local_search,
        "web_search": web_search,
        "use_llm_rewrite": use_llm_rewrite,
        "deep_search": deep_search,
        "deep_limit": deep_limit,
        "top_k": top_k,
        "sources": sources or DEFAULT_SEARCH_SOURCES.copy(),
        "generate_answer": generate_answer,
        "answer_tokens": answer_tokens,
        "generate_pdf": generate_pdf,
        "comparison_insights": comparison_insights,
        "fetch_excerpts": fetch_excerpts,
    }


def main() -> None:
    st.set_page_config(page_title="Oreacle", layout="wide")
    st.title("Oreacle")
    st.caption("RAG + web literature search для материаловедения, металлургии и горного дела")
    options = render_sidebar()

    st.session_state.setdefault("messages", [])
    st.session_state.setdefault("records", [])

    for message in st.session_state["messages"][-8:]:
        with st.chat_message(message["role"]):
            st.write(message["content"])

    query = st.chat_input("Введите запрос по материалам, методикам или свойствам")
    if query:
        st.session_state["messages"].append({"role": "user", "content": query})
        with st.chat_message("user"):
            st.write(query)
        with st.status("Выполняю поиск и сбор evidence...", expanded=True) as status:
            record = execute_query(query, options)
            st.session_state["records"].append(record)
            status.update(label="Готово", state="complete")
        st.session_state["messages"].append({"role": "assistant", "content": "Готово: результаты ниже, отчеты доступны во вкладке «Отчеты»."})
        st.rerun()

    if st.session_state["records"]:
        record = st.session_state["records"][-1]
        run = record.get("literature_run")
        if run is not None:
            col1, col2 = st.columns([1, 3])
            with col1:
                if st.button("Запустить Deep Search по текущей выдаче", use_container_width=True):
                    with st.status("Запускаю Deep Search...", expanded=True) as status:
                        llm_client = build_router_completion_client_from_env(ROOT)
                        updated = run_deep_search_for_existing_run(
                            run,
                            project_root=ROOT,
                            deep_search_limit=options["deep_limit"],
                            fetch_excerpts=options["fetch_excerpts"],
                            yandex_client=llm_client,
                        )
                        record["literature_run"] = updated
                        status.update(label="Deep Search готов", state="complete")
                    st.rerun()
            with col2:
                st.write(f"Последний запрос: {record['query']}")
        render_result(record)
    else:
        st.info("Введите запрос в чат. Текущий экран сохраняет историю сообщений и не очищает запрос после поиска.")


if __name__ == "__main__":
    main()
