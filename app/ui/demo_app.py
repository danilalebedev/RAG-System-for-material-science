from __future__ import annotations

import json
import sys
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pandas as pd
import streamlit as st
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.query.cockpit import (  # noqa: E402
    DEMO_SCENARIOS,
    SEARCH_QUERY_SLOT_ORDER,
    build_search_query_from_slots,
    consensus_panel_rows,
    executive_brief_markdown,
    evidence_cards,
    gap_radar_rows,
    graphviz_dot,
    local_vs_web_metrics,
    local_vs_world_dashboard,
    method_heatmap_rows,
    method_matrix_rows,
    mini_graph_edges,
    numeric_interval_rows,
    query_decomposition,
)
from app.query.literature import run_deep_search_for_existing_run, run_literature_search  # noqa: E402
from app.query.local_orchestrator import run_local_knowledge  # noqa: E402
from app.query.comparison import compare_methods  # noqa: E402
from app.query.orchestrator import run_query_orchestration  # noqa: E402
from app.query.planner import plan_query  # noqa: E402
from app.query.reports import comparison_insights, run_overall_summary, source_counts, year_counts  # noqa: E402
from app.query.rewrite import deterministic_query_rewrite  # noqa: E402
from app.graph.search import load_graph, neighbors as graph_neighbors, paths_to_types, search_entities  # noqa: E402
from app.market.radar import run_market_radar  # noqa: E402
from app.web_search.schemas import ALL_SEARCH_SOURCES, DEFAULT_SEARCH_SOURCES, SEARCH_SOURCE_LABELS, LiteratureSearchRequest  # noqa: E402


load_dotenv(ROOT / ".env")
GRAPH_NODES_PATH = ROOT / "data" / "index" / "knowledge_graph_nodes.jsonl"
GRAPH_EDGES_PATH = ROOT / "data" / "index" / "knowledge_graph_edges.jsonl"
CHUNKS_PATH = ROOT / "data" / "parsed" / "chunks.jsonl"
DOCUMENTS_PATH = ROOT / "data" / "parsed" / "documents.jsonl"
TABLES_PATH = ROOT / "data" / "parsed" / "tables.jsonl"
MARKET_MODE = "Рыночная разведка"


DEMO_PROMPTS = {
    "quick": [
        "Сравни методы переработки литий-ионных батарей для извлечения никеля и кобальта",
        "Найди технологии удаления SO2 в металлургии",
        "Покажи связи никель → процессы → свойства",
        "Найди таблицы с Ni/Cu/Co",
    ],
    "compare": [
        "Сравни методы переработки литий-ионных батарей для извлечения никеля и кобальта",
        "Сравни методы удаления SO2 в металлургии",
        "Сравни гидрометаллургию и пирометаллургию для извлечения Co",
    ],
    "tables": [
        "Найди численные параметры извлечения Ni/Cu/Co",
        "Покажи температуры и проценты кислот для выщелачивания никеля",
    ],
    "graph": [
        "Покажи связи никель → процессы → свойства",
        "Какие процессы связаны с извлечением кобальта",
    ],
    "web_local": [
        "Сравни внутреннюю базу и свежие публикации по recycling LIB",
        "Найди свежие публикации про извлечение никеля из хвостов",
    ],
}
MARKET_DEMO_PROMPTS = [
    "Сколько никеля, меди, палладия и платины произвёл Норникель в последнем доступном периоде?",
    "Покажи динамику производства Ni/Cu/Pd/Pt Норникеля по годам.",
    "Сравни производство стали в России, Китае, Индии и Турции.",
    "Покажи мировое производство алюминия по регионам.",
    "Покажи топ стран по добыче никеля и роль России.",
    "Свяжи рыночные данные по никелю с внутренними документами по никелевой руде и сульфидным концентратам.",
]

DEMO_SCENARIO_GALLERY = [
    {
        "label": "Сравнить методы переработки LIB для извлечения Ni и Co",
        "query": "Сравнить методы переработки литий-ионных батарей для извлечения Ni и Co",
        "mode": "Сравнение методик",
    },
    {
        "label": "Технологии удаления SO₂ и ограничения",
        "query": "Найти технологии удаления SO2 в металлургии и сравнить ограничения",
        "mode": "Сравнение методик",
    },
    {
        "label": "Связи: никель → процессы → свойства → публикации",
        "query": "Показать связи: никель → процессы → свойства → публикации",
        "mode": "Граф знаний",
    },
    {
        "label": "Таблицы Ni, Cu, Co",
        "query": "Найти таблицы с содержанием Ni, Cu, Co и сравнить значения",
        "mode": "Табличные данные",
    },
    {
        "label": "Внутреннее vs внешнее: кучное выщелачивание",
        "query": "Сравнить внутренние данные с внешними публикациями по кучному выщелачиванию в холодном климате",
        "mode": "Внутреннее vs внешнее",
    },
]


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


def render_cockpit_styles() -> None:
    st.markdown(
        """
        <style>
        .block-container {padding-top: 1.6rem; padding-bottom: 2.4rem;}
        .rd-hero {
            border: 1px solid rgba(25, 35, 55, 0.12);
            border-radius: 8px;
            padding: 26px 28px;
            margin-bottom: 18px;
            background: linear-gradient(135deg, #f8fafc 0%, #eef7f4 52%, #f7f3ea 100%);
        }
        .rd-hero h1 {
            margin: 0 0 8px 0;
            font-size: 2.35rem;
            line-height: 1.05;
            letter-spacing: 0;
            color: #14213d;
        }
        .rd-hero p {
            margin: 0;
            max-width: 980px;
            color: #405066;
            font-size: 1.02rem;
            line-height: 1.55;
        }
        .rd-card {
            border: 1px solid rgba(30, 42, 62, 0.12);
            border-radius: 8px;
            background: #ffffff;
            padding: 16px 16px 14px 16px;
            min-height: 106px;
            box-shadow: 0 1px 2px rgba(20, 33, 61, 0.04);
        }
        .rd-card strong {color: #172033; font-size: 1.02rem;}
        .rd-card span {display: block; color: #5a687b; margin-top: 7px; line-height: 1.38;}
        .chip-row {display: flex; flex-wrap: wrap; gap: 7px; margin: 8px 0 12px 0;}
        .chip {
            display: inline-flex;
            align-items: center;
            border-radius: 999px;
            border: 1px solid rgba(20, 33, 61, 0.14);
            background: #f8fafc;
            color: #1f2a3d;
            padding: 4px 10px;
            font-size: 0.82rem;
            line-height: 1.2;
            white-space: nowrap;
        }
        .chip.route {background: #eef7f4;}
        .chip.intent {background: #fff7e6;}
        .section-label {
            color: #536276;
            text-transform: uppercase;
            letter-spacing: .08em;
            font-size: .72rem;
            font-weight: 700;
            margin: 20px 0 6px 0;
        }
        </style>
        """,
        unsafe_allow_html=True,
    )


def render_hero() -> None:
    st.markdown(
        """
        <div class="rd-hero">
          <h1>Oreacle</h1>
          <p><strong>R&amp;D Knowledge Cockpit for Metals &amp; Mining</strong></p>
          <p>От разрозненных отчётов, таблиц и публикаций — к проверяемым инженерным решениям.</p>
        </div>
        """,
        unsafe_allow_html=True,
    )


def apply_demo_scenario(query: str, mode: str) -> None:
    st.session_state["rd_question"] = query
    st.session_state["active_demo_mode"] = mode
    if mode == MARKET_MODE:
        st.session_state["market_query"] = query
    if mode == "Сравнение методик":
        st.session_state["comparison_query"] = query


def render_demo_scenario_gallery() -> None:
    st.markdown('<div class="section-label">Demo scenarios</div>', unsafe_allow_html=True)
    columns = st.columns(5)
    market_scenarios = [
        {"label": "Market Radar: Норникель Ni/Cu/PGM", "query": MARKET_DEMO_PROMPTS[0], "mode": MARKET_MODE},
        {"label": "Market Radar: сталь по странам", "query": MARKET_DEMO_PROMPTS[2], "mode": MARKET_MODE},
        {"label": "Market Radar: алюминий по регионам", "query": MARKET_DEMO_PROMPTS[3], "mode": MARKET_MODE},
    ]
    for index, scenario in enumerate(DEMO_SCENARIO_GALLERY + market_scenarios):
        with columns[index % 5]:
            st.button(
                scenario["label"],
                key=f"scenario_gallery_{index}",
                on_click=apply_demo_scenario,
                args=(scenario["query"], scenario["mode"]),
                use_container_width=True,
            )


def _chip(label: str, value: Any, css_class: str = "") -> str:
    text = display_value(value, max_chars=120)
    if not text:
        return ""
    return f'<span class="chip {css_class}">{label}: {text}</span>'


def render_chip_row(chips: list[str]) -> None:
    html = "".join(chip for chip in chips if chip)
    if html:
        st.markdown(f'<div class="chip-row">{html}</div>', unsafe_allow_html=True)


def render_mode_cards() -> None:
    cards = [
        ("Быстрый поиск", "Найти документы, факты и источники по внутренней базе и web."),
        ("Сравнение методик", "Собрать таблицу методов, условий, чисел, плюсов и ограничений."),
        ("Табличные данные", "Вытащить параметры, проценты, температуры и составы из CSV/Excel."),
        ("Граф знаний", "Показать связи Materials / Processes / Properties / Publications."),
        ("Внутреннее vs внешнее", "Сопоставить локальные данные с открытыми публикациями."),
    ]
    cards.append((MARKET_MODE, "Публичные production-данные, источники, KPI, динамика и рыночные caveats."))
    columns = st.columns(len(cards))
    for column, (title, text) in zip(columns, cards):
        column.markdown(f'<div class="rd-card"><strong>{title}</strong><span>{text}</span></div>', unsafe_allow_html=True)


def set_prompt(target_key: str, prompt: str) -> None:
    st.session_state[target_key] = prompt


def render_prompt_buttons(prompts: list[str], *, target_key: str, prefix: str) -> None:
    st.caption("Demo prompts")
    columns = st.columns(min(4, len(prompts)))
    for index, prompt in enumerate(prompts):
        columns[index % len(columns)].button(
            prompt,
            key=f"{prefix}_prompt_{index}",
            on_click=set_prompt,
            args=(target_key, prompt),
            use_container_width=True,
        )


def render_empty_state() -> None:
    st.info(
        "Выберите demo prompt или задайте вопрос: cockpit построит QueryPlan, запустит нужные retrievers, покажет источники, evidence и fallbacks."
    )
    render_prompt_buttons(DEMO_PROMPTS["quick"], target_key="rd_question", prefix="empty")


def query_plan_search_queries(plan: dict[str, Any]) -> list[str]:
    rewritten = plan.get("rewritten_queries") if isinstance(plan.get("rewritten_queries"), dict) else {}
    values: list[str] = []
    for key in ("raw_rag", "summary_rag", "graph", "tables", "web"):
        for item in rewritten.get(key) or []:
            if item and item not in values:
                values.append(str(item))
    for item in plan.get("search_queries") or []:
        if item and item not in values:
            values.append(str(item))
    for key in ("internal_search_queries", "web_search_queries"):
        for item in plan.get(key) or []:
            if item and item not in values:
                values.append(str(item))
    return values


def query_plan_display_query(plan: dict[str, Any], fallback: str) -> str:
    return str(plan.get("original_query") or plan.get("corrected_query") or fallback)


def render_query_intelligence_plan(plan: dict[str, Any]) -> None:
    if not plan:
        st.info("No query plan available.")
        return
    st.markdown('<div class="section-label">Query Intelligence</div>', unsafe_allow_html=True)
    entities = plan.get("entities") if isinstance(plan.get("entities"), dict) else {}
    entity_values: list[str] = []
    for values in entities.values():
        entity_values.extend(values or [])
    render_chip_row(
        [
            _chip("intent", plan.get("intent") or "n/a", "intent"),
            _chip("domain", plan.get("domain") or "n/a"),
            _chip("формат ответа", plan.get("answer_format") or "n/a"),
            _chip("выделенные сущности", ", ".join(entity_values[:8]) or "none"),
            *[_chip("источник поиска", route, "route") for route in plan.get("routes") or []],
        ]
    )
    if plan.get("entity_aliases"):
        st.caption("Синонимы / aliases")
        st.json(plan.get("entity_aliases"), expanded=False)
    col_local, col_web = st.columns(2)
    with col_local:
        st.caption("Запросы к локальной базе")
        for item in plan.get("internal_search_queries") or []:
            st.write(f"- {item}")
    with col_web:
        st.caption("Запросы к внешнему поиску")
        for item in plan.get("web_search_queries") or []:
            st.write(f"- {item}")
    if plan.get("needs_clarification"):
        st.warning(plan.get("clarifying_question") or "Clarification is needed.")
    with st.expander("Query Intelligence JSON", expanded=False):
        st.json(plan)


def render_route_orchestration_result(result: Any) -> None:
    payload = result.as_dict() if hasattr(result, "as_dict") else dict(result or {})
    plan = payload.get("plan") or payload.get("query_plan") or {}
    context = payload.get("retrieved_context") or {}
    evidence = payload.get("evidence") or []
    fallbacks = payload.get("fallbacks") or []
    diagnostics = payload.get("local_diagnostics") or {}

    st.subheader("Использованные источники поиска")
    render_query_intelligence_plan(plan)

    source_rows = [
        {"source": source, "items": len(rows or []), "used": bool(rows)}
        for source, rows in context.items()
    ]
    st.write("Найденные источники")
    render_table(source_rows, empty_text="Источники не вернули результатов.")
    if diagnostics:
        with st.expander("Диагностика локального поиска", expanded=not any(row["used"] for row in source_rows)):
            render_table([diagnostics])

    if payload.get("answer_draft"):
        st.text_area("Executive summary", value=payload["answer_draft"], height=150)

    tabs = st.tabs(["Evidence", "Фрагменты внутренних документов", "Summaries", "Tables", "Graph context", "Web", "Недоступные источники"])
    with tabs[0]:
        render_table(evidence, empty_text="No evidence collected.")
    with tabs[1]:
        render_table(context.get("raw") or [], empty_text="Фрагменты внутренних документов не найдены.")
    with tabs[2]:
        render_table(context.get("summaries") or [], empty_text="No summary evidence.")
    with tabs[3]:
        render_table(context.get("tables") or [], empty_text="No table evidence.")
    with tabs[4]:
        render_table(context.get("graph") or [], empty_text="No graph evidence.")
    with tabs[5]:
        render_table(context.get("web") or [], empty_text="No web evidence.")
    with tabs[6]:
        if fallbacks:
            render_table(fallbacks)
        else:
            st.success("Все выбранные источники поиска отработали без резервного режима.")


def render_market_radar_result(result: Any) -> None:
    payload = result.as_dict() if hasattr(result, "as_dict") else dict(result or {})
    rows = payload.get("production_rows") or []
    statuses = payload.get("source_status") or []
    charts = payload.get("charts") or {}

    st.markdown('<div class="section-label">Executive summary</div>', unsafe_allow_html=True)
    st.write(payload.get("market_summary") or "Market summary is not available.")

    latest_rows = charts.get("latest_comparison") or []
    if latest_rows:
        st.markdown('<div class="section-label">KPI cards</div>', unsafe_allow_html=True)
        columns = st.columns(min(4, len(latest_rows)))
        for index, row in enumerate(latest_rows[:8]):
            with columns[index % len(columns)]:
                st.metric(
                    label=f"{row.get('entity')} · {row.get('commodity')}",
                    value=f"{row.get('value')} {row.get('unit')}",
                    delta=str(row.get("period") or ""),
                )

    tabs = st.tabs(["Production table", "Time series", "Comparison", "Source status", "Caveats", "Internal links", "JSON"])
    with tabs[0]:
        render_table(rows, empty_text="Production rows не найдены для выбранных фильтров.")
    with tabs[1]:
        time_series = charts.get("time_series") or []
        if time_series:
            df = pd.DataFrame(time_series)
            df["value"] = pd.to_numeric(df["value"], errors="coerce")
            chart_df = df.pivot_table(index="period", columns=["entity", "commodity"], values="value", aggfunc="first")
            st.line_chart(chart_df)
            render_table(time_series)
        else:
            st.info("Нет временного ряда для графика.")
    with tabs[2]:
        if latest_rows:
            df = pd.DataFrame(latest_rows)
            df["value"] = pd.to_numeric(df["value"], errors="coerce")
            chart_df = df.pivot_table(index="entity", columns="commodity", values="value", aggfunc="first")
            st.bar_chart(chart_df)
            render_table(latest_rows)
        else:
            st.info("Нет сопоставимых KPI для comparison chart.")
    with tabs[3]:
        render_table(statuses, empty_text="Статусы источников не сформированы.")
    with tabs[4]:
        caveats = [{"type": "missing_data", "message": item} for item in payload.get("missing_data") or []]
        caveats += [{"type": "warning", "message": item} for item in payload.get("warnings") or []]
        caveats += [{"type": "suggested_source", "message": item} for item in payload.get("suggested_sources") or []]
        render_table(caveats, empty_text="Критичных caveats нет. Для продакшена всё равно проверьте свежие официальные отчёты.")
    with tabs[5]:
        terms = payload.get("internal_knowledge_terms") or []
        if terms:
            render_chip_row([_chip("internal term", term, "route") for term in terms])
            st.caption("Эти термины можно отправить в Local Knowledge / Graph для связки рынка с внутренними документами.")
        else:
            st.info("Связанные внутренние термины появятся для Ni/Cu/PGM или запросов со словом «свяжи».")
    with tabs[6]:
        st.json(payload)


def render_market_radar_panel(*, safe_demo_mode: bool) -> None:
    st.subheader("Market Radar / Рыночная разведка")
    st.caption("Официальные и demo-safe production данные: компании, страны, commodities, периоды, источники и caveats.")
    render_prompt_buttons(MARKET_DEMO_PROMPTS, target_key="market_query", prefix="market")
    query = st.text_area(
        "Market intelligence query",
        key="market_query",
        height=82,
        placeholder="Например: Сколько никеля, меди, палладия и платины произвёл Норникель?",
    )
    col_run, col_note = st.columns([1, 3])
    with col_run:
        run_market = st.button("Run Market Radar", type="primary", key="run_market_radar", use_container_width=True)
    with col_note:
        st.caption("Числа берутся из структурированных строк источников/fixtures; LLM не используется для numeric facts.")

    if run_market:
        if not query:
            st.warning("Введите market query или выберите demo prompt.")
        else:
            with st.spinner("Collecting public production indicators..."):
                st.session_state["last_market_radar_result"] = run_market_radar(query, demo_mode=safe_demo_mode)
            render_market_radar_result(st.session_state["last_market_radar_result"])
    elif st.session_state.get("last_market_radar_result"):
        render_market_radar_result(st.session_state["last_market_radar_result"])


def render_comparison_mode_result(result: Any) -> None:
    payload = result.as_dict() if hasattr(result, "as_dict") else dict(result or {})
    rows = payload.get("rows") or []
    plan = payload.get("plan") or {}
    context = payload.get("retrieved_context") or {}
    missing = payload.get("missing_evidence") or []

    st.markdown('<div class="section-label">Executive summary</div>', unsafe_allow_html=True)
    st.write(payload.get("answer_summary") or "No summary was produced.")

    render_query_intelligence_plan(plan)

    st.markdown('<div class="section-label">Sources</div>', unsafe_allow_html=True)
    render_table(
        [{"source": source, "items": len(items or []), "used": bool(items)} for source, items in context.items()],
        empty_text="Найденные источники отсутствуют.",
    )

    st.markdown('<div class="section-label">Comparison table</div>', unsafe_allow_html=True)
    table_rows = [
        {
            "Method": row.get("item"),
            "Description": row.get("description"),
            "Materials": row.get("materials"),
            "Processes": row.get("processes"),
            "Conditions": row.get("conditions"),
            "Properties": row.get("properties"),
            "Numeric values": row.get("numeric_values"),
            "Advantages": row.get("advantages"),
            "Limitations": row.get("limitations"),
        }
        for row in rows
    ]
    render_table(table_rows, empty_text="No comparison rows were generated.")

    st.markdown('<div class="section-label">Evidence & sources</div>', unsafe_allow_html=True)
    for index, row in enumerate(rows, start=1):
        with st.expander(f"{index}. {row.get('item') or 'Method'} evidence", expanded=index == 1):
            render_table(row.get("evidence") or [], empty_text="No direct evidence for this row.")

    st.markdown('<div class="section-label">Missing evidence / unavailable sources</div>', unsafe_allow_html=True)
    if missing:
        render_table(missing)
    else:
        st.success("No missing evidence detected.")

    graph_context = context.get("graph") or []
    if graph_context:
        st.markdown('<div class="section-label">Graph context</div>', unsafe_allow_html=True)
        render_table(graph_context[:20])

    with st.expander("Full structured comparison JSON", expanded=False):
        st.json(payload)


def render_comparison_mode_panel(*, include_web: bool, source_options: list[str], top_k: int) -> None:
    render_prompt_buttons(DEMO_PROMPTS["compare"], target_key="comparison_query", prefix="compare")
    query = st.text_area(
        "Что сравнить?",
        key="comparison_query",
        height=90,
        placeholder="Сравни методы переработки литий-ионных батарей для извлечения никеля и кобальта",
    )
    col_run, col_web = st.columns([1, 3])
    with col_web:
        comparison_include_web = st.checkbox("Include web search", value=include_web, key="comparison_include_web")
    with col_run:
        run_comparison = st.button("Run comparison", type="primary", key="run_comparison_mode", use_container_width=True)
    if run_comparison:
        if not query:
            st.warning("Введите запрос для сравнения методик.")
            return
        with st.spinner("Building deterministic comparison table..."):
            st.session_state["last_comparison_result"] = compare_methods(
                query,
                include_web=comparison_include_web,
                web_sources=source_options,
                top_k=min(top_k, 10),
            )
    if st.session_state.get("last_comparison_result"):
        render_comparison_mode_result(st.session_state["last_comparison_result"])
    else:
        st.info("Comparison Mode соберет методы, условия, численные параметры, ограничения и evidence из доступных retrievers.")


def render_local_knowledge_bundle(bundle: Any) -> None:
    st.subheader("Local Knowledge")
    col1, col2, col3, col4 = st.columns(4)
    col1.metric("Raw chunks", len(bundle.raw_chunks))
    col2.metric("Summaries", len(bundle.summary_hits))
    col3.metric("Tables", len(bundle.table_hits))
    col4.metric("Graph entities", len(bundle.graph_hits))
    st.markdown(bundle.brief)
    if bundle.warnings:
        render_warnings(bundle.warnings)

    tabs = st.tabs(["Raw", "Summaries", "Tables", "Graph", "Context", "Query Plan"])
    with tabs[0]:
        render_table(
            [
                {
                    "rank": item.rank,
                    "score": item.score,
                    "doc_id": item.doc_id,
                    "chunk_id": item.chunk_id,
                    "source_path": item.source_path,
                    "text": item.text[:900],
                }
                for item in bundle.raw_chunks
            ],
            empty_text="No raw chunks found.",
        )
    with tabs[1]:
        render_table([item.as_dict() for item in bundle.summary_hits], empty_text="No summary hits found.")
    with tabs[2]:
        render_table([item.as_dict() for item in bundle.table_hits], empty_text="No table hits found.")
    with tabs[3]:
        render_table(bundle.graph_hits, empty_text="No graph hits found.")
        st.write("Neighbors")
        render_table(bundle.graph_neighbors, empty_text="No graph neighbors found.")
    with tabs[4]:
        st.text_area("Combined evidence context", value=bundle.context, height=420)
        st.download_button("Download local context", data=bundle.context, file_name="local_knowledge_context.md", mime="text/markdown")
    with tabs[5]:
        render_query_intelligence_plan(bundle.query_plan)


def render_local_world_cards(rows: list[dict[str, Any]]) -> None:
    if not rows:
        st.info("Нет данных для Local vs World Dashboard.")
        return
    cols = st.columns(2)
    for index, row in enumerate(rows[:2]):
        with cols[index]:
            st.markdown(f"### {row.get('side', 'Source')}")
            metric_cols = st.columns(2)
            metric_cols[0].metric("Sources", row.get("sources", 0))
            metric_cols[1].metric("Confidence", row.get("confidence", "n/a"))
            st.write(f"**Top methods:** {row.get('top_methods') or 'n/a'}")
            st.write(f"**Parameter ranges:** {row.get('numeric_ranges') or 'n/a'}")
            st.write(f"**Geography:** {row.get('geography') or 'n/a'}")
            st.write(f"**Years:** {row.get('years') or 'n/a'}")
            st.write(f"**Evidence:** {row.get('evidence') or 'n/a'}")


def render_evidence_cards(cards: list[dict[str, Any]], *, limit: int = 8) -> None:
    if not cards:
        st.info("Нет evidence cards.")
        return
    for card in cards[:limit]:
        title = display_value(card.get("title"), max_chars=140) or "Untitled"
        label = f"{card.get('kind', 'source').upper()} | {title}"
        with st.expander(label, expanded=False):
            col1, col2, col3 = st.columns(3)
            col1.metric("Confidence", card.get("confidence") or "n/a")
            col2.metric("Year", card.get("year") or "n/a")
            col3.metric("Source", card.get("source") or "n/a")
            st.write(f"**Method / signal:** {card.get('method') or 'n/a'}")
            st.write(f"**Numeric ranges:** {card.get('numeric_ranges') or 'n/a'}")
            st.write(f"**Why relevant:** {card.get('why_relevant') or 'n/a'}")
            if card.get("link"):
                st.markdown(f"[Open evidence]({card['link']})")


def render_heatmap(rows: list[dict[str, Any]]) -> None:
    if not rows:
        st.info("Heatmap появится после Deep Search или procedure summaries.")
        return
    df = pd.DataFrame(rows)
    pivot = df.pivot_table(index="material", columns="method", values=["local", "web"], aggfunc="sum", fill_value=0)
    st.dataframe(pivot, use_container_width=True)
    display_df = table_df(rows)
    color_map = {
        "есть локально и во внешней литературе": "background-color: #d8f3dc",
        "только локально": "background-color: #dbeafe",
        "только web": "background-color: #ffedd5",
    }

    def style_status(row: pd.Series) -> list[str]:
        color = color_map.get(str(row.get("status", "")), "")
        return [color if column == "status" else "" for column in row.index]

    st.dataframe(display_df.style.apply(style_status, axis=1), use_container_width=True, hide_index=True)


def result_rows(run: Any) -> list[dict[str, Any]]:
    rows = []
    for item in run.results:
        oa = item.open_access or {}
        access_status = oa.get("access_status") or ("open" if item.open_access_pdf_url else "unknown")
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
                "access": access_status,
                "full_text_source": oa.get("source") or "",
                "legal_pdf": oa.get("best_pdf_url") or "",
            }
        )
    return rows


def access_badge(open_access: dict[str, Any]) -> str:
    status = open_access.get("access_status") or "unknown"
    if status == "open":
        return "Open full text"
    if status == "paywalled":
        return "Paywalled"
    if status == "metadata_only":
        return "Metadata only"
    return "Access unknown"


def render_open_access_cards(run: Any) -> None:
    for item in run.results[:10]:
        oa = item.open_access or {}
        with st.expander(f"{access_badge(oa)} | {item.title}", expanded=False):
            st.write(f"Source of full text: {oa.get('source') or item.source}")
            if oa.get("best_pdf_url"):
                st.markdown(f"[Open legal full text]({oa['best_pdf_url']})")
                st.button("Add legal full text to corpus", key=f"add_oa_{item.result_id}", disabled=True)
            else:
                landing = oa.get("landing_page_url") or str(item.url or "")
                if landing:
                    st.markdown(f"[Open publisher / metadata page]({landing})")
                st.info("Full text not found legally. Upload PDF manually if you have access.")
            if oa.get("license"):
                st.caption(f"License: {oa['license']}")
            if oa.get("evidence"):
                st.caption("Evidence: " + "; ".join(str(value) for value in oa.get("evidence") or []))


def render_local_search_diagnostics(plan: dict[str, Any]) -> None:
    rows = [
        {
            "chunks.jsonl": CHUNKS_PATH.exists(),
            "documents.jsonl": DOCUMENTS_PATH.exists(),
            "tables.jsonl": TABLES_PATH.exists(),
            "graph nodes": GRAPH_NODES_PATH.exists(),
            "graph edges": GRAPH_EDGES_PATH.exists(),
            "actual local query": (plan.get("internal_search_queries") or [plan.get("original_query") or ""])[0],
            "called search sources": ", ".join(plan.get("routes") or []),
        }
    ]
    with st.expander("Диагностика локального поиска", expanded=True):
        render_table(rows)


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


def render_knowledge_graph_tab(default_query: str) -> None:
    st.subheader("Knowledge Graph")
    if not GRAPH_NODES_PATH.exists() or not GRAPH_EDGES_PATH.exists():
        st.info("Knowledge graph is not built yet.")
        st.code(r".\.venv\Scripts\python.exe scripts\build_knowledge_graph.py", language="powershell")
        return
    nodes, edges = load_graph(GRAPH_NODES_PATH, GRAPH_EDGES_PATH)
    col1, col2, col3 = st.columns([2, 1, 1])
    with col1:
        graph_query = st.text_input("Entity search", value=default_query[:180], key="knowledge_graph_query")
    with col2:
        node_type = st.selectbox(
            "Type",
            options=["", "Publication", "Material", "Process", "Equipment", "Property", "Experiment", "Method", "Facility", "Expert", "Table"],
            index=0,
            key="knowledge_graph_type",
        )
    with col3:
        top_k = st.number_input("Top K", min_value=3, max_value=30, value=10, step=1, key="knowledge_graph_top_k")
    hits = search_entities(nodes, graph_query, node_type=node_type or None, top_k=int(top_k)) if graph_query else []
    render_table(
        [
            {
                "rank": hit.rank,
                "score": hit.score,
                "type": hit.node.get("type"),
                "label": hit.node.get("label"),
                "node_id": hit.node.get("node_id"),
                "docs": len(hit.node.get("doc_ids") or []),
            }
            for hit in hits
        ],
        empty_text="No graph entities found.",
    )
    if not hits:
        return
    selected_labels = [f"{hit.node.get('type')}: {hit.node.get('label')}" for hit in hits]
    selected = st.selectbox("Inspect entity", options=list(range(len(hits))), format_func=lambda index: selected_labels[index], key="knowledge_graph_selected")
    selected_node = hits[selected].node
    st.caption(f"node_id={selected_node.get('node_id')}")
    neighbor_rows = graph_neighbors(nodes, edges, selected_node["node_id"], limit=60)
    st.write("Neighbors")
    render_table(
        [
            {
                "relation": row["edge"].get("type"),
                "type": row["node"].get("type"),
                "label": row["node"].get("label"),
                "node_id": row["node"].get("node_id"),
                "doc_id": row["edge"].get("doc_id"),
            }
            for row in neighbor_rows
        ],
        empty_text="No neighbors.",
    )
    path_rows = paths_to_types(nodes, edges, selected_node["node_id"], limit=20)
    st.write("Paths to publications/processes/properties")
    render_table(
        [
            {
                "path": " -> ".join(str(step["node"].get("label")) for step in path),
                "types": " -> ".join(str(step["node"].get("type")) for step in path),
            }
            for path in path_rows
        ],
        empty_text="No short paths.",
    )


def render_warnings(warnings: list[str]) -> None:
    if not warnings:
        return
    with st.expander(f"Предупреждения источников ({len(warnings)})", expanded=False):
        for warning in warnings:
            st.warning(warning)


def render_query_decomposer(run: Any) -> None:
    st.subheader("Разбор запроса")
    run_key = str(run.output_dir or run.request.query)[-80:]
    rows = query_decomposition(run)
    cols = st.columns(2)
    for index, row in enumerate(rows):
        with cols[index % 2]:
            st.text_input(
                row["slot"],
                value=", ".join(row.get("values") or []),
                key=f"query_slot_{run_key}_{index}",
                help=row.get("why", ""),
            )


def query_preview_run(query: str, *, materials_only: bool) -> Any:
    plan = deterministic_query_rewrite(query, materials_only=materials_only)
    return SimpleNamespace(
        request=SimpleNamespace(query=query),
        query_plan=plan.model_dump(mode="json"),
        keywords=plan.all_keywords,
        results=[],
        local_matches=[],
        deep_results=[],
        comparison=None,
        warnings=[],
        output_dir=None,
    )


def render_pre_search_decomposer(query: str, *, materials_only: bool) -> dict[str, str]:
    preview = query_preview_run(query, materials_only=materials_only)
    intelligence_plan = plan_query(query)
    st.subheader("Query Intelligence")
    render_query_intelligence_plan(intelligence_plan.model_dump(mode="json"))
    rows = query_decomposition(preview)
    st.subheader("Query Decomposer")
    st.caption("Отредактируйте структуру запроса до запуска поиска. Эти поля добавятся к поисковой формулировке для web-search и будущего RAG.")
    slot_values: dict[str, str] = {}
    cols = st.columns(2)
    for index, row in enumerate(rows):
        slot = row["slot"]
        if slot not in SEARCH_QUERY_SLOT_ORDER:
            continue
        with cols[index % 2]:
            slot_values[slot] = st.text_input(
                slot,
                value=", ".join(row.get("values") or []),
                key=f"pre_search_slot_{slot}",
                help=row.get("why", ""),
            )
    with st.expander("Варианты поискового запроса", expanded=False):
        for row in rows:
            if row["slot"] == "Варианты поискового запроса":
                for value in row.get("values") or []:
                    st.write(f"- {value}")
    return slot_values


def render_cockpit(run: Any, corrected_query: str, search_queries: list[str]) -> None:
    st.subheader("Поиск выполнен")
    col1, col2, col3, col4 = st.columns(4)
    col1.metric("Внешние статьи", len(run.results))
    col2.metric("Локальные совпадения", len(run.local_matches))
    col3.metric("Deep Search summaries", len(run.deep_results))
    col4.metric("Методики", len(run.comparison.rows) if run.comparison else 0)
    st.markdown(f"**Запрос пользователя:** {run.request.query}")
    st.markdown(f"**Нормализованный запрос:** {corrected_query}")
    st.markdown(f"**Ключевые слова:** {', '.join(run.keywords) if run.keywords else 'n/a'}")
    if not run.local_matches:
        render_local_search_diagnostics(run.query_plan or {})

    render_query_decomposer(run)

    st.subheader("Local vs World Dashboard")
    dashboard_rows = local_vs_world_dashboard(run)
    render_local_world_cards(dashboard_rows)
    with st.expander("Dashboard data"):
        render_table(dashboard_rows)

    col1, col2 = st.columns(2)
    with col1:
        st.subheader("Coverage signals")
        render_table(local_vs_web_metrics(run))
    with col2:
        st.subheader("Gap radar")
        render_table(gap_radar_rows(run))

    heatmap = method_heatmap_rows(run)
    if heatmap:
        st.subheader("Knowledge Gap Radar: material x process")
        render_heatmap(heatmap)

    st.subheader("Evidence cards")
    render_evidence_cards(evidence_cards(run), limit=4)

    if search_queries:
        with st.expander("Варианты запроса для поиска"):
            for item in search_queries:
                st.write(f"- {item}")
    with st.expander("Краткий управленческий вывод"):
        st.markdown(executive_brief_markdown(run))
    if st.button("Save query preset", key=f"save_preset_{str(run.output_dir or run.request.query)[-80:]}"):
        presets = st.session_state.setdefault("saved_presets", [])
        if run.request.query not in presets:
            presets.append(run.request.query)
        st.toast("Preset saved")
    with st.expander("Как ранжируются статьи"):
        st.markdown(
            "- результаты выбранных API-баз объединяются и дедуплицируются по DOI или нормализованному title;\n"
            "- score растет за совпадения ключевых слов в title/abstract/venue;\n"
            "- добавляется бонус за abstract, DOI, citations и свежий год;\n"
            "- score также растет за квартиль журнала, если он известен: Q1 +5, Q2 +3, Q3 +1.5, Q4 +0.5;\n"
            "- при `Materials science only` остаются только статьи с domain-сигналами: materials, metallurgy, alloy, ore, nickel, copper, flotation, leaching и т.п."
        )
    st.subheader("Query Intelligence")
    render_query_intelligence_plan(run.query_plan or {})
    render_warnings(run.warnings)
    if run.comparison and run.comparison.gaps:
        st.write("Gaps")
        for gap in run.comparison.gaps:
            st.write(f"- {gap}")


def download_path_button(label: str, path: Any, *, file_name: str, mime: str) -> None:
    if path and Path(path).exists():
        st.download_button(label, data=Path(path).read_bytes(), file_name=file_name, mime=mime)


def render_run(run: Any) -> None:
    st.session_state["last_run"] = run
    tabs = st.tabs(["Cockpit", "Публикации", "Deep Search", "Сравнение", "Evidence", "Local Knowledge", "Knowledge Graph", "Графики", "Отчет"])
    corrected_query = query_plan_display_query(run.query_plan or {}, run.request.query)
    search_queries = query_plan_search_queries(run.query_plan or {})

    with tabs[0]:
        render_cockpit(run, corrected_query, search_queries)

    with tabs[1]:
        rows = result_rows(run)
        st.write("Найденные статьи")
        render_table(rows, empty_text="Внешние статьи не найдены.")
        if run.results:
            st.subheader("Legal full-text access")
            render_open_access_cards(run)
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
            if run.results and st.button("Запустить Deep Search по текущим результатам", type="primary"):
                with st.spinner("Запускаю Deep Search по уже найденным статьям..."):
                    updated = run_deep_search_for_existing_run(
                        run,
                        deep_search_limit=st.session_state.get("deep_search_limit_setting", run.request.deep_search_limit),
                        fetch_excerpts=st.session_state.get("fetch_excerpts_setting", run.request.fetch_excerpts),
                    )
                st.session_state["last_run"] = updated
                st.rerun()
        else:
            st.subheader("Общий вывод по найденным статьям")
            st.write(run_overall_summary(run))
            insights = comparison_insights(run)
            if insights:
                st.subheader("Выводы по сравнению локального и web-поиска")
                st.write(insights)
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
        st.subheader("Contradiction & Consensus Panel")
        render_table(consensus_panel_rows(run), empty_text="Consensus panel появится после сравнения local/web методик.")
        st.subheader("Method comparison matrix")
        render_table(method_matrix_rows(run), empty_text="Матрица методик появится после Deep Search.")
        heatmap = method_heatmap_rows(run)
        if heatmap:
            st.subheader("Knowledge Gap Radar: material x process")
            render_heatmap(heatmap)
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
        st.subheader("Evidence cards")
        render_evidence_cards(evidence_cards(run), limit=20)
        st.subheader("Numeric interval candidates")
        render_table(numeric_interval_rows(run), empty_text="Числовые диапазоны не найдены в текущих evidence snippets.")
        st.write("Local evidence")
        render_table(local_rows(run))
        if run.comparison:
            st.write("Method rows")
            render_table(run.comparison.rows)

    with tabs[5]:
        if st.button("Run route orchestrator", key=f"route_orchestrator_{str(run.output_dir or run.request.query)[-80:]}"):
            with st.spinner("Running planned retrieval routes..."):
                st.session_state["last_route_orchestration"] = run_query_orchestration(
                    run.request.query,
                    include_web=bool(run.request.sources),
                    web_sources=run.request.sources,
                    web_top_k=min(run.request.top_k, 10),
                    generate_pdf_report=False,
                )
        route_result = st.session_state.get("last_route_orchestration")
        if route_result:
            render_route_orchestration_result(route_result)
        else:
            st.info("Run route orchestrator to execute the planned raw, summary, table, graph and web routes.")

    with tabs[6]:
        render_knowledge_graph_tab(run.request.query)

    with tabs[7]:
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
        st.write("Mini knowledge map: Expert -> Publication -> Experiment -> Material -> Process -> Equipment -> Output -> Conclusion")
        edges = mini_graph_edges(run)
        if edges:
            try:
                st.graphviz_chart(graphviz_dot(run), use_container_width=True)
            except Exception:
                render_table(edges)
            else:
                render_table(edges)
        radar = pd.DataFrame(gap_radar_rows(run))
        if not radar.empty:
            numeric_radar = radar.copy()
            numeric_radar["value"] = pd.to_numeric(numeric_radar["value"], errors="coerce").fillna(0)
            st.write("Gap radar")
            st.bar_chart(numeric_radar.set_index("signal")["value"])

    with tabs[8]:
        st.subheader("Краткий управленческий вывод")
        st.markdown(run.executive_brief_markdown or executive_brief_markdown(run))
        col1, col2, col3 = st.columns(3)
        with col1:
            st.download_button(
                "Markdown brief",
                data=run.executive_brief_markdown or executive_brief_markdown(run),
                file_name="executive_brief.md",
                mime="text/markdown",
            )
        with col2:
            download_path_button("PDF brief", run.executive_brief_pdf_path, file_name="executive_brief.pdf", mime="application/pdf")
        with col3:
            download_path_button(
                "DOCX brief",
                run.executive_brief_docx_path,
                file_name="executive_brief.docx",
                mime="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            )

        st.subheader("Полный отчет")
        col1, col2, col3, col4 = st.columns(4)
        with col1:
            st.download_button("Markdown", data=run.report_markdown or "", file_name="literature_report.md", mime="text/markdown")
        with col2:
            download_path_button("PDF", run.report_pdf_path, file_name="literature_report.pdf", mime="application/pdf")
        with col3:
            download_path_button(
                "DOCX",
                run.report_docx_path,
                file_name="literature_report.docx",
                mime="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            )
        with col4:
            download_path_button("JSON", run.full_run_json_path, file_name="full_run.json", mime="application/json")

        st.subheader("Обычный отчет: только ссылки")
        col1, col2, col3 = st.columns(3)
        with col1:
            st.download_button("Markdown links", data=run.links_report_markdown or "", file_name="literature_links_report.md", mime="text/markdown")
        with col2:
            download_path_button("PDF links", run.links_report_pdf_path, file_name="literature_links_report.pdf", mime="application/pdf")
        with col3:
            download_path_button(
                "DOCX links",
                run.links_report_docx_path,
                file_name="literature_links_report.docx",
                mime="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            )

        st.subheader("Deep Search отчет: ссылки и summary")
        col1, col2, col3 = st.columns(3)
        with col1:
            st.download_button("Markdown Deep Search", data=run.deep_report_markdown or "", file_name="deep_search_report.md", mime="text/markdown")
        with col2:
            download_path_button("PDF Deep Search", run.deep_report_pdf_path, file_name="deep_search_report.pdf", mime="application/pdf")
        with col3:
            download_path_button(
                "DOCX Deep Search",
                run.deep_report_docx_path,
                file_name="deep_search_report.docx",
                mime="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            )

        st.subheader("Графики для отчета")
        year_df = pd.DataFrame(year_counts(run))
        source_df = pd.DataFrame(source_counts(run))
        col1, col2 = st.columns(2)
        with col1:
            st.write("Публикации по годам")
            if not year_df.empty:
                st.bar_chart(year_df.set_index("year"))
                st.download_button("CSV years", data=year_df.to_csv(index=False), file_name="publication_years.csv", mime="text/csv")
            else:
                st.info("Нет данных по годам.")
        with col2:
            st.write("Публикации по базам данных")
            if not source_df.empty:
                st.bar_chart(source_df.set_index("source"))
                st.download_button("CSV sources", data=source_df.to_csv(index=False), file_name="publication_sources.csv", mime="text/csv")
            else:
                st.info("Нет данных по базам.")

        insights = comparison_insights(run)
        if insights:
            st.subheader("Выводы по сравнению трендов/методик/условий")
            st.write(insights)
        st.markdown(run.report_markdown or "")


def render_history() -> None:
    for message in st.session_state["history"][-8:]:
        with st.chat_message(message["role"]):
            st.write(message["content"])


def main() -> None:
    st.set_page_config(page_title="Oreacle", layout="wide")
    render_cockpit_styles()
    render_hero()

    with st.sidebar:
        scenario_options = ["Свободный запрос"] + [item["label"] for item in DEMO_SCENARIOS]
        scenario_label = st.selectbox("Demo scenario", options=scenario_options, index=0)
        selected_scenario = next((item for item in DEMO_SCENARIOS if item["label"] == scenario_label), None)
        if selected_scenario:
            st.caption(selected_scenario["focus"])
            if st.button("Запустить сценарий", type="primary"):
                st.session_state["queued_query"] = selected_scenario["query"]
                st.rerun()
        saved_presets = st.session_state.get("saved_presets", [])
        if saved_presets:
            st.caption("Saved presets")
            for index, preset in enumerate(saved_presets[-5:]):
                if st.button(preset[:42], key=f"preset_{index}"):
                    st.session_state["queued_query"] = preset
                    st.rerun()
        st.subheader("Retrieval")
        local_search = st.checkbox("Локальный поиск", value=True)
        web_search = st.checkbox("Внешний поиск публикаций", value=True)
        safe_demo_mode = st.checkbox("Safe demo mode", value=True, help="Не падает при недоступных LLM/API/индексах, показывает понятные резервные режимы.")
        analysis_mode = st.radio("Analysis mode", options=["Quick search", "Deep analysis"], index=0)
        deep_search = analysis_mode == "Deep analysis"
        pdf_report = st.checkbox("Generate PDF report", value=True)
        materials_only = st.checkbox("Materials science only", value=True)
        with st.expander("Advanced settings", expanded=False):
            geography_filter = st.text_input("Geography", placeholder="например: Норильск, Canada")
            year_range = st.slider("Publication period", min_value=1950, max_value=2026, value=(2000, 2026), step=1)
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
            max_deep = max(1, min(top_k, 20))
            deep_search_limit = st.slider(
                "Статей для Deep Search",
                min_value=1,
                max_value=max_deep,
                value=min(5, max_deep),
                step=1,
                disabled=not deep_search,
            )
            fetch_excerpts = st.checkbox("Fetch safe excerpts", value=True, disabled=not deep_search)
            query_rewrite = st.checkbox("Rewrite/multiply query", value=True)
            llm_query_rewrite = st.checkbox("Use LLM rewrite if available", value=True, disabled=not query_rewrite)
            generate_comparison_insights = st.checkbox("Генерировать выводы по сравнению", value=True)
            language = st.selectbox("Language", options=["auto", "ru", "en"], index=0)

    st.session_state["deep_search_limit_setting"] = deep_search_limit
    st.session_state["fetch_excerpts_setting"] = fetch_excerpts

    if "history" not in st.session_state:
        st.session_state["history"] = []

    queued_query = st.session_state.pop("queued_query", None)
    if queued_query:
        st.session_state["rd_question"] = queued_query

    render_demo_scenario_gallery()
    mode_options = ["Быстрый поиск", "Сравнение методик", "Табличные данные", "Граф знаний", "Внутреннее vs внешнее"]
    mode_options.append(MARKET_MODE)
    active_mode = st.session_state.get("active_demo_mode", mode_options[0])
    if active_mode not in mode_options:
        active_mode = mode_options[0]
    st.radio("Mode", options=mode_options, index=mode_options.index(active_mode), key="active_demo_mode", horizontal=True)
    if safe_demo_mode:
        st.caption("Safe demo mode: если Yandex/API/индекс недоступны, Oreacle покажет недоступный источник и продолжит работу.")

    render_mode_cards()
    feature_tabs = st.tabs(["Быстрый поиск", "Сравнение методик", "Табличные данные", "Граф знаний", "Внутреннее vs внешнее"])
    with feature_tabs[0]:
        render_prompt_buttons(DEMO_PROMPTS["quick"], target_key="rd_question", prefix="quick")
    with feature_tabs[1]:
        render_comparison_mode_panel(include_web=web_search, source_options=source_options, top_k=top_k)
    with feature_tabs[2]:
        render_prompt_buttons(DEMO_PROMPTS["tables"], target_key="rd_question", prefix="tables")
        st.caption("Запросы про числа автоматически маршрутизируются в table_search + raw_rag.")
    with feature_tabs[3]:
        render_prompt_buttons(DEMO_PROMPTS["graph"], target_key="rd_question", prefix="graph")
        render_knowledge_graph_tab(st.session_state.get("rd_question", ""))
    with feature_tabs[4]:
        render_prompt_buttons(DEMO_PROMPTS["web_local"], target_key="rd_question", prefix="web_local")
        st.caption("Для внешних публикаций включите web search в sidebar; локальный контекст останется рядом с web evidence.")

    market_tab = st.tabs([MARKET_MODE])
    with market_tab[0]:
        render_market_radar_panel(safe_demo_mode=safe_demo_mode)

    st.subheader("R&D Decision Cockpit")
    rd_question = st.text_area(
        "Что вы хотите узнать?",
        key="rd_question",
        height=90,
        placeholder="Например: никелевая руда, кучное выщелачивание, холодный климат, извлечение Ni, 2020-2026",
    )
    pre_search_slots: dict[str, str] = {}
    if rd_question:
        pre_search_slots = render_pre_search_decomposer(rd_question, materials_only=materials_only)
    col1, col2, col_local, col3 = st.columns([1, 1, 1, 3])
    with col1:
        st.button("Decompose query")
    with col2:
        run_from_cockpit = st.button("Run search", type="primary")
    with col_local:
        run_local_from_cockpit = st.button("Run local")
    with col3:
        st.caption(f"Mode: {analysis_mode}. Отредактированные slots попадут в поисковую формулировку.")

    render_history()

    local_rendered = False
    if run_local_from_cockpit:
        if not rd_question:
            st.warning("Enter an R&D question before local search.")
        else:
            with st.spinner("Running planned retrieval routes..."):
                st.session_state["last_route_orchestration"] = run_query_orchestration(
                    rd_question,
                    include_web=web_search,
                    web_sources=source_options,
                    web_top_k=min(top_k, 10),
                    generate_pdf_report=False,
                )
            render_route_orchestration_result(st.session_state["last_route_orchestration"])
            local_rendered = True

    query = None if run_local_from_cockpit else st.chat_input("Спросите про материал, процесс, режим или свойство")
    active_query = rd_question if run_from_cockpit else query
    if run_from_cockpit and not active_query:
        st.warning("Введите R&D question перед запуском поиска.")
    if active_query:
        st.session_state["history"].append({"role": "user", "content": active_query})
        with st.chat_message("user"):
            st.write(active_query)
        filter_parts = []
        if geography_filter:
            filter_parts.append(f"география: {geography_filter}")
        if year_range != (2000, 2026):
            filter_parts.append(f"период публикаций: {year_range[0]}-{year_range[1]}")
        slot_values = dict(pre_search_slots) if run_from_cockpit else {}
        if geography_filter:
            slot_values["География"] = ", ".join(filter(None, [slot_values.get("География"), geography_filter]))
        if year_range != (2000, 2026):
            slot_values["Период"] = ", ".join(filter(None, [slot_values.get("Период"), f"{year_range[0]}-{year_range[1]}"]))
        search_query = build_search_query_from_slots(active_query, slot_values)
        backend_query = active_query

        request = LiteratureSearchRequest(
            query=backend_query,
            top_k=top_k,
            sources=source_options if web_search else [],
            deep_search="top5" if deep_search else "none",
            deep_search_limit=deep_search_limit,
            language=language,
            include_local_search=local_search,
            materials_only=materials_only,
            use_query_rewrite=query_rewrite,
            use_llm_query_rewrite=llm_query_rewrite,
            generate_comparison_insights=generate_comparison_insights,
            include_recommended_resource_links=False,
            recommended_resource_ids=[],
            fetch_excerpts=fetch_excerpts,
            generate_pdf_report=pdf_report,
        )
        with st.chat_message("assistant"):
            with st.spinner("Выполняю поиск..."):
                run = run_literature_search(request)
            answer = f"Найдено внешних источников: {len(run.results)}; локальных совпадений: {len(run.local_matches)}."
            if filter_parts or any(slot_values.values()):
                st.caption(f"Нормализованный запрос: {search_query}")
            st.write(answer)
        st.session_state["history"].append({"role": "assistant", "content": answer})
        render_run(run)
    elif st.session_state.get("last_run"):
        render_run(st.session_state["last_run"])
    elif not local_rendered:
        render_empty_state()


if __name__ == "__main__":
    main()
