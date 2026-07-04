from __future__ import annotations

import json
import re
import sys
import time
from datetime import datetime
from html import escape
from pathlib import Path
from typing import Any

import pandas as pd
import streamlit as st
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.query.cockpit import graphviz_dot as literature_graphviz_dot  # noqa: E402
from app.query.literature import (  # noqa: E402
    answer_literature_with_provider_router,
    compare_literature_with_provider_router,
    run_deep_search_for_existing_run,
    run_literature_search,
    write_run_outputs,
)
from app.query.orchestrator import answer_with_provider_router, run_query_orchestration  # noqa: E402
from app.query.reports import (  # noqa: E402
    build_answer_exports,
    build_local_publications_archive,
    build_orchestration_archive,
    build_orchestration_exports,
    build_section_exports,
    build_run_archive,
    build_web_publications_archive,
    comparison_insights,
    compact_text,
    find_local_file,
    preferred_web_link,
    repair_mojibake,
    run_overall_summary,
    routerai_budget_summary,
    safe_report_id,
    source_counts,
    source_title,
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
ROUTE_LABELS = {
    "raw_rag": "Raw RAG",
    "summary_rag": "Summary RAG",
    "table_search": "Tables",
    "graph_search": "Knowledge graph",
    "web_search": "Web literature",
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


def numeric_score(value: Any) -> float:
    try:
        return float(value or 0.0)
    except (TypeError, ValueError):
        return 0.0


def score_out_of_10(value: Any, max_score: float) -> float:
    score = numeric_score(value)
    denominator = max(max_score, score) if max(max_score, score) > 0 else 1.0
    return round(min(10.0, max(0.0, score / denominator * 10.0)), 1)


def format_seconds(value: Any) -> str:
    try:
        seconds = float(value)
    except (TypeError, ValueError):
        return "n/a"
    if seconds < 1:
        return f"{seconds:.2f} c"
    return f"{seconds:.1f} c"


def add_elapsed_usage(answer: Any | None, elapsed_seconds: float) -> Any | None:
    if answer is not None and hasattr(answer, "usage") and isinstance(answer.usage, dict):
        answer.usage["elapsed_seconds"] = round(elapsed_seconds, 3)
    return answer


def answer_budget(answer: Any | None) -> dict[str, Any]:
    return routerai_budget_summary(answer)


def cost_label(summary: dict[str, Any]) -> str:
    if summary.get("reported_cost_rub") is not None:
        return f"{summary['reported_cost_rub']} ₽"
    if summary.get("estimated_cost_rub") is not None:
        return f"{summary['estimated_cost_rub']} ₽"
    return "n/a"


def answer_metrics(record: dict[str, Any]) -> dict[str, str]:
    answer = record.get("answer")
    comparison_answer = record.get("comparison_answer")
    summary = answer_budget(answer)
    comparison_summary = answer_budget(comparison_answer)
    total_cost = 0.0
    has_cost = False
    for item in (summary, comparison_summary):
        value = item.get("reported_cost_rub")
        if value is None:
            value = item.get("estimated_cost_rub")
        if value is not None:
            total_cost += float(value)
            has_cost = True
    elapsed_values = [
        numeric_score(item.get("elapsed_seconds"))
        for item in (summary, comparison_summary)
        if item.get("elapsed_seconds") not in (None, "")
    ]
    return {
        "model": compact_text(summary.get("model") or comparison_summary.get("model") or "n/a", 80),
        "answer_time": format_seconds(summary.get("elapsed_seconds")),
        "comparison_time": format_seconds(comparison_summary.get("elapsed_seconds")),
        "total_model_time": format_seconds(sum(elapsed_values)) if elapsed_values else "n/a",
        "tokens": str(summary.get("total_tokens") or "n/a"),
        "cost": f"{round(total_cost, 4)} ₽" if has_cost else cost_label(summary),
    }


def source_rows(run: Any) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    results = list(getattr(run, "results", []) or [])
    max_score = max([numeric_score(getattr(result, "score", 0.0)) for result in results] or [1.0])
    for index, result in enumerate(results, start=1):
        raw = getattr(result, "raw", None) or {}
        rows.append(
            {
                "#": index,
                "Релевантность /10": score_out_of_10(getattr(result, "score", 0.0), max_score),
                "Год": result.year,
                "База": SEARCH_SOURCE_LABELS.get(result.source, result.source),
                "Q": getattr(result, "journal_quartile", None) or raw.get("journal_quartile") or "",
                "Заголовок": result.title,
            }
        )
    return rows


def local_rows_from_literature(run: Any) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    local_matches = list(getattr(run, "local_matches", []) or [])
    max_score = max([numeric_score(row.get("score")) for row in local_matches] or [1.0])
    for index, row in enumerate(local_matches, start=1):
        rows.append(
            {
                "#": index,
                "Релевантность /10": score_out_of_10(row.get("score"), max_score),
                "Заголовок": row.get("title") or row.get("doc_id") or row.get("source_path"),
                "Фрагмент": row.get("preview") or row.get("summary") or row.get("source_path"),
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


def plan_routes(orchestration: Any | None) -> list[str]:
    if orchestration is None:
        return []
    plan = getattr(orchestration, "plan", None)
    if plan is None:
        return []
    if isinstance(plan, dict):
        return list(plan.get("routes") or [])
    routes = getattr(plan, "routes", None)
    if routes is not None:
        return list(routes or [])
    if hasattr(plan, "model_dump"):
        return list((plan.model_dump(mode="json") or {}).get("routes") or [])
    return []


def workflow_summary_rows(record: dict[str, Any]) -> list[dict[str, Any]]:
    run = record.get("literature_run")
    orchestration = record.get("orchestration")
    answer = record.get("answer")
    request_type = record.get("request_type") or "n/a"
    routes = plan_routes(orchestration) or REQUEST_TYPES.get(request_type, [])
    rows: list[dict[str, Any]] = [
        {"Шаг": "Сценарий", "Что сделано": request_type, "Объем": ""},
    ]
    if routes:
        rows.append(
            {
                "Шаг": "Маршрут",
                "Что сделано": " -> ".join(ROUTE_LABELS.get(route, route) for route in routes),
                "Объем": f"{len(routes)} streams",
            }
        )
    if orchestration is not None:
        context = orchestration.retrieved_context.as_dict()
        local_counts = {
            "raw": len(context.get("raw") or []),
            "summary": len(context.get("summaries") or []),
            "tables": len(context.get("tables") or []),
            "graph": len(context.get("graph") or []),
        }
        rows.append(
            {
                "Шаг": "Локальный RAG",
                "Что сделано": "raw chunks + summaries + tables + graph evidence",
                "Объем": "; ".join(f"{name}: {count}" for name, count in local_counts.items()),
            }
        )
        fallbacks = len(getattr(orchestration, "fallbacks", []) or [])
        rows.append(
            {
                "Шаг": "Fallback-и",
                "Что сделано": "нет критичных fallback-ов" if fallbacks == 0 else "есть fallback rows, см. Evidence",
                "Объем": str(fallbacks),
            }
        )
    local_matches = len(getattr(run, "local_matches", []) or []) if run is not None else 0
    if local_matches:
        rows.append({"Шаг": "Локальные публикации", "Что сделано": "найдены совпадения в локальной базе", "Объем": str(local_matches)})
    web_results = list(getattr(run, "results", []) or []) if run is not None else []
    if web_results:
        sources = sorted({SEARCH_SOURCE_LABELS.get(result.source, result.source) for result in web_results if getattr(result, "source", None)})
        rows.append(
            {
                "Шаг": "Web literature",
                "Что сделано": "metadata search + ranking + confidence",
                "Объем": f"{len(web_results)} источников" + (f"; {', '.join(sources[:5])}" if sources else ""),
            }
        )
    deep_results = len(getattr(run, "deep_results", []) or []) if run is not None else 0
    rows.append(
        {
            "Шаг": "Deep Search",
            "Что сделано": "summary extraction выполнен" if deep_results else "не запускался или еще нет summaries",
            "Объем": str(deep_results),
        }
    )
    if answer is not None:
        metadata = answer.metadata() if hasattr(answer, "metadata") else {}
        provider = metadata.get("provider") or getattr(answer, "provider", None) or "RouterAI"
        model = metadata.get("model") or getattr(answer, "model", None) or ""
        rows.append({"Шаг": "Финальный ответ", "Что сделано": f"сформулирован через {provider}", "Объем": model})
    return rows


def _as_text_list(value: Any, *, limit: int = 8) -> list[str]:
    if value in (None, "", [], {}):
        return []
    if isinstance(value, str):
        return [repair_mojibake(value)]
    if isinstance(value, dict):
        rows: list[str] = []
        for item in value.values():
            rows.extend(_as_text_list(item, limit=limit))
            if len(rows) >= limit:
                break
        return list(dict.fromkeys(rows))[:limit]
    if isinstance(value, (list, tuple, set)):
        rows = []
        for item in value:
            rows.extend(_as_text_list(item, limit=limit))
            if len(rows) >= limit:
                break
        return list(dict.fromkeys(rows))[:limit]
    return [repair_mojibake(value)]


def search_context_rows(run: Any | None, orchestration: Any | None) -> list[dict[str, Any]]:
    plan = getattr(run, "query_plan", None) if run else None
    orchestration_rewrite = getattr(orchestration, "query_rewrite", None) if orchestration is not None else None
    if not plan and orchestration is not None:
        plan = orchestration.plan.model_dump(mode="json")
    plan = plan or {}
    rewrite = plan.get("llm_rewrite") if isinstance(plan.get("llm_rewrite"), dict) else orchestration_rewrite or {}
    original_query = getattr(getattr(run, "request", None), "query", None) or plan.get("original_query") or plan.get("original_user_query")
    corrected_query = rewrite.get("corrected_query") or plan.get("corrected_query") or original_query
    web_queries = list(dict.fromkeys(_as_text_list(rewrite.get("search_queries")) + _as_text_list(plan.get("web_search_queries"))))
    local_queries = list(
        dict.fromkeys(
            _as_text_list(plan.get("internal_search_queries"))
            + _as_text_list((plan.get("rewritten_queries") or {}).get("raw_rag") if isinstance(plan.get("rewritten_queries"), dict) else None)
            + _as_text_list((plan.get("rewritten_queries") or {}).get("summary_rag") if isinstance(plan.get("rewritten_queries"), dict) else None)
        )
    )
    keywords = _as_text_list(getattr(run, "keywords", None), limit=16)
    if not keywords and isinstance(plan.get("entities"), dict):
        keywords = _as_text_list(plan.get("entities"), limit=16)
    rows = [
        {"Что используется": "Исходный запрос", "Значение": original_query or "n/a"},
        {"Что используется": "Поисковая формулировка", "Значение": corrected_query or "n/a"},
    ]
    if keywords:
        rows.append({"Что используется": "Ключевые слова", "Значение": ", ".join(keywords[:16])})
    if web_queries:
        rows.append({"Что используется": "Web-поиск", "Значение": " | ".join(web_queries[:5])})
    if local_queries:
        rows.append({"Что используется": "Локальный RAG", "Значение": " | ".join(local_queries[:5])})
    if rewrite:
        rows.append({"Что используется": "Переформулировка LLM", "Значение": "да" if rewrite.get("rewrite_used_llm") else "нет, deterministic fallback"})
    return rows


def dot_label(value: Any, max_chars: int = 80) -> str:
    if isinstance(value, list):
        text = ", ".join(compact_text(item, max_chars) for item in value[:4] if compact_text(item, max_chars))
    else:
        text = compact_text(value, max_chars)
    text = text or "n/a"
    return text.replace("\\", "\\\\").replace('"', '\\"')


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
            left = dot_label(row.get("relation") or "relation", 50)
            right = dot_label(row.get("label") or row.get("node_id"), 80)
            lines.append(f'"{left}" -> "{right}";')
        elif row.get("kind") == "entity":
            label = dot_label(row.get("label") or row.get("node_id"), 80)
            node_type = dot_label(row.get("type") or "entity", 40)
            lines.append(f'"{node_type}" -> "{label}";')
    lines.append("}")
    return "\n".join(lines)


def knowledge_graph_dot(run: Any | None, orchestration: Any | None) -> str:
    rows = orchestration_rows(orchestration, "graph")
    if rows:
        return graph_dot_from_orchestration(orchestration)
    if run is not None:
        return literature_graphviz_dot(run)
    return "digraph G { rankdir=LR; empty [label=\"Нет графовых связей\"]; }"


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
        material = dot_label(row.get("material") or "material", 60)
        method = dot_label(row.get("method") or row.get("synthesis_or_process_method") or "method", 70)
        scope = dot_label(row.get("scope") or "source", 40)
        title = dot_label(row.get("title") or row.get("doc_id") or scope, 80)
        lines.append(f'"Material: {material}" -> "Method: {method}" [label="{scope}"];')
        lines.append(f'"Method: {method}" -> "Source: {title}";')
    lines.append("}")
    return "\n".join(lines)


def property_graph_dot(run: Any | None, orchestration: Any | None) -> str:
    rows = property_rows(run, orchestration)
    if not rows:
        return "digraph G { rankdir=LR; empty [label=\"Нет данных по свойствам\"]; }"
    lines = [
        "digraph G {",
        "rankdir=LR;",
        "node [shape=box, style=\"rounded,filled\", fontname=\"Arial\", color=\"#b7c7d8\", fillcolor=\"#eef6ff\"];",
    ]
    for row in rows[:40]:
        scope = dot_label(row.get("scope") or "source", 40)
        material = dot_label(row.get("material") or "material", 60)
        output = dot_label(row.get("outputs") or "property", 80)
        numeric = dot_label(row.get("numeric_results") or "numeric result", 80)
        evidence = dot_label(row.get("evidence") or scope, 80)
        lines.append(f'"Material: {material}" -> "Property: {output}" [label="{scope}"];')
        if numeric != "numeric result":
            lines.append(f'"Property: {output}" -> "Value/range: {numeric}";')
        lines.append(f'"Property: {output}" -> "Source: {evidence}";')
    lines.append("}")
    return "\n".join(lines)


def comparison_graph_dot(run: Any | None, orchestration: Any | None, request_type: str | None) -> str:
    if request_type and "свойств" in request_type.casefold():
        return property_graph_dot(run, orchestration)
    return method_graph_dot(run)


def comparison_graph_title(request_type: str | None) -> str:
    if request_type and "свойств" in request_type.casefold():
        return "**Свойства: local vs web**"
    return "**Методики: local vs web**"


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
    sequence = int(st.session_state.get("_download_button_sequence", 0)) + 1
    st.session_state["_download_button_sequence"] = sequence
    key = f"download_{sequence}_{safe_report_id(f'{label}_{Path(path)}', prefix='download')}"
    st.download_button(label, data=data, file_name=Path(path).name, mime=mime, use_container_width=True, key=key)


def orchestration_output_dir(record: dict[str, Any]) -> Path:
    run_id = safe_report_id(f"{record.get('created_at', '')}_{record.get('query', '')}", prefix="rag")
    return ROOT / "data" / "processed" / "rag_runs" / run_id


def answer_output_dir(record: dict[str, Any]) -> Path:
    run = record.get("literature_run")
    if run is not None and getattr(run, "output_dir", None):
        return Path(run.output_dir) / "answer_report"
    return orchestration_output_dir(record) / "answer_report"


def web_shortcut_bytes(url: str) -> bytes:
    return f"[InternetShortcut]\r\nURL={url}\r\n".encode("utf-8")


def render_soft_heading(text: str) -> None:
    st.markdown(f'<div class="literature-section-title">{escape(text)}</div>', unsafe_allow_html=True)


def render_soft_text(text: str) -> None:
    safe = escape(compact_text(text, 8000)).replace("\n", "<br>")
    st.markdown(f'<div class="literature-soft-text">{safe}</div>', unsafe_allow_html=True)


def local_file_for_row(row: dict[str, Any]) -> Path | None:
    for key in ("local_path", "source_path", "path", "file_name"):
        value = row.get(key)
        if not value:
            continue
        found = find_local_file(str(value), project_root=ROOT)
        if found:
            return found
    return None


def render_web_source_links(run: Any | None) -> None:
    if run is None:
        return
    results = list(getattr(run, "results", []) or [])
    if not results:
        return
    render_soft_heading("Ссылки по найденным web-источникам")
    for index, result in enumerate(results[:40], start=1):
        link = preferred_web_link(result)
        if not link:
            continue
        cols = st.columns([7, 1.6, 1.6])
        cols[0].write(f"{index}. {compact_text(getattr(result, 'title', ''), 240)}")
        if link.startswith(("http://", "https://")):
            cols[1].link_button("Открыть", link, use_container_width=True)
        cols[2].download_button(
            "Скачать",
            data=web_shortcut_bytes(link),
            file_name=f"{index:02d}_web_source.url",
            mime="application/octet-stream",
            use_container_width=True,
            key=f"web_source_url_{index}_{safe_report_id(getattr(result, 'result_id', index), prefix='web')}",
        )


def render_local_source_links(run: Any | None) -> None:
    if run is None:
        return
    rows = list(getattr(run, "local_matches", []) or [])
    if not rows:
        return
    render_soft_heading("Локальные источники")
    shown = 0
    for index, row in enumerate(rows[:40], start=1):
        found = local_file_for_row(row)
        title = source_title(row)
        cols = st.columns([7, 1.6, 1.6])
        cols[0].write(f"{index}. {compact_text(title, 240)}")
        if found is None:
            cols[1].caption("Файл не найден")
            cols[2].caption("")
            continue
        shown += 1
        cols[1].link_button("Открыть", found.resolve().as_uri(), use_container_width=True)
        cols[2].download_button(
            "Скачать",
            data=found.read_bytes(),
            file_name=found.name,
            mime="application/octet-stream",
            use_container_width=True,
            key=f"local_source_file_{index}_{safe_report_id(found, prefix='local')}",
        )
    if shown == 0:
        st.caption("Для найденных локальных совпадений исходные файлы пока не обнаружены.")


def local_summary_text(run: Any | None) -> str:
    rows = list(getattr(run, "local_matches", []) or []) if run is not None else []
    if not rows:
        return "Локальные источники по запросу не найдены."
    titles = []
    for row in rows[:6]:
        title = source_title(row)
        if title:
            titles.append(title)
    fragments = [
        compact_text(row.get("preview") or row.get("summary") or row.get("source_path"), 260)
        for row in rows[:4]
        if row.get("preview") or row.get("summary") or row.get("source_path")
    ]
    parts = [f"Найдено локальных совпадений: {len(rows)}."]
    if titles:
        parts.append("Ключевые локальные работы: " + "; ".join(titles[:5]) + ".")
    if fragments:
        parts.append("Основные фрагменты evidence: " + " ".join(fragments))
    return " ".join(parts)


def web_summary_text(run: Any | None) -> str:
    results = list(getattr(run, "results", []) or []) if run is not None else []
    if not results:
        return "Web-поиск не нашел внешние источники по запросу."
    years = [int(result.year) for result in results if getattr(result, "year", None)]
    sources = source_counts(run)
    source_text = ", ".join(f"{SEARCH_SOURCE_LABELS.get(row['source'], row['source'])}: {row['count']}" for row in sources[:6])
    top_titles = [compact_text(getattr(result, "title", ""), 220) for result in results[:5]]
    parts = [f"Найдено web-источников: {len(results)}."]
    if years:
        parts.append(f"Период публикаций: {min(years)}-{max(years)}.")
    if source_text:
        parts.append(f"Базы данных: {source_text}.")
    if top_titles:
        parts.append("Первые релевантные работы: " + "; ".join(top_titles) + ".")
    return " ".join(parts)


def comparison_difference_text(run: Any | None, comparison_answer: Any | None) -> str:
    answer_text = compact_text(getattr(comparison_answer, "text", ""), 8000) if comparison_answer is not None else ""
    if answer_text:
        return answer_text.replace("**", "")
    if run is not None:
        return comparison_insights(run).replace("**", "")
    return "Сравнение пока не сформировано."


def comparison_answer_sections(comparison_answer: Any | None) -> dict[str, str]:
    text = getattr(comparison_answer, "text", "") if comparison_answer is not None else ""
    if not text:
        return {}
    sections: dict[str, list[str]] = {"local": [], "web": [], "diff": []}
    current: str | None = None
    for raw_line in str(text).splitlines():
        line = raw_line.strip()
        if not line:
            continue
        heading = re.sub(r"^[#*\-\s\d.)]+", "", line).strip(" :.-").lower().replace("ё", "е")
        if "резюме по локаль" in heading:
            current = "local"
            continue
        if "резюме по web" in heading or "резюме по веб" in heading:
            current = "web"
            continue
        if "сравнение источников" in heading or "поиск отличий" in heading:
            current = "diff"
            continue
        if current is not None:
            sections[current].append(line)
    parsed = {key: compact_text("\n".join(value), 6000).replace("**", "") for key, value in sections.items() if value}
    if parsed:
        return parsed
    return {"diff": compact_text(text, 6000).replace("**", "")}


def render_comparison_blocks(run: Any | None, comparison_answer: Any | None) -> None:
    sections = comparison_answer_sections(comparison_answer)
    for title, text in (
        ("Резюме по локальным источникам", sections.get("local") or local_summary_text(run)),
        ("Резюме по web-источникам", sections.get("web") or web_summary_text(run)),
        ("Сравнение источников: отличия и пробелы", sections.get("diff") or comparison_difference_text(run, comparison_answer)),
    ):
        render_soft_heading(title)
        render_soft_text(text)


def render_literature_reports(record: dict[str, Any]) -> None:
    run = record.get("literature_run")
    answer = record.get("answer")
    comparison_answer = record.get("comparison_answer")
    query = record.get("query")
    if run is None:
        st.info("Отчет появится после поиска.")
        return

    metrics = answer_metrics(record)
    render_soft_heading("Метрики запроса")
    cols = st.columns(4)
    cols[0].metric("Отчет модели", metrics["answer_time"])
    cols[1].metric("Сравнение", metrics["comparison_time"])
    cols[2].metric("Токены отчета", metrics["tokens"])
    cols[3].metric("Оценка стоимости", metrics["cost"])

    if answer is not None:
        answer_exports = build_answer_exports(
            answer_output_dir(record),
            query=query,
            answer=answer,
            run=run,
            orchestration=None,
        )
        render_soft_heading("Отчет и обзор")
        cols = st.columns(2)
        with cols[0]:
            render_download(answer_exports.get("pdf"), "PDF: отчет", "application/pdf")
        with cols[1]:
            render_download(answer_exports.get("docx"), "DOCX: отчет", "application/vnd.openxmlformats-officedocument.wordprocessingml.document")

    if comparison_answer is not None:
        comparison_exports = build_answer_exports(
            answer_output_dir(record) / "comparison",
            query=query,
            answer=comparison_answer,
            run=run,
            orchestration=None,
            prefix="comparison_review",
        )
        render_soft_heading("Сравнение local vs web")
        cols = st.columns(2)
        with cols[0]:
            render_download(comparison_exports.get("pdf"), "PDF: сравнение", "application/pdf")
        with cols[1]:
            render_download(
                comparison_exports.get("docx"),
                "DOCX: сравнение",
                "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            )

    render_soft_heading("Отчеты по источникам")
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

    if getattr(run, "output_dir", None):
        archive_dir = Path(run.output_dir) / "user_archives"
        local_archive = build_local_publications_archive(run, archive_dir / "local_publications.zip", project_root=ROOT)
        web_archive = build_web_publications_archive(run, archive_dir / "web_publication_links.zip")
        render_soft_heading("Архивы статей и ссылок")
        cols = st.columns(2)
        with cols[0]:
            render_download(local_archive, "ZIP: локальные статьи", "application/zip")
        with cols[1]:
            render_download(web_archive, "ZIP: web-ссылки", "application/zip")


def render_reports(record: dict[str, Any]) -> None:
    run = record.get("literature_run")
    orchestration = record.get("orchestration")
    answer = record.get("answer")
    query = record.get("query")
    if run is None and orchestration is None:
        st.info("Отчет появится после поиска.")
        return
    if record.get("request_type") == "Литературный поиск":
        render_literature_reports(record)
        return
    if answer is not None:
        st.markdown("**Answer report**")
        answer_exports = build_answer_exports(
            answer_output_dir(record),
            query=query,
            answer=answer,
            run=run,
            orchestration=orchestration,
        )
        cols = st.columns(2)
        with cols[0]:
            render_download(answer_exports.get("pdf"), "PDF: отчет", "application/pdf")
        with cols[1]:
            render_download(answer_exports.get("docx"), "DOCX: отчет", "application/vnd.openxmlformats-officedocument.wordprocessingml.document")
    if run is not None:
        st.markdown("**Web / literature reports**")
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
        if getattr(run, "output_dir", None):
            archive = build_run_archive(run, Path(run.output_dir) / "run_artifacts.zip", answer=answer, query=query, project_root=ROOT)
            render_download(archive, "ZIP: web/literature artifacts", "application/zip")

    if orchestration is None:
        return
    render_soft_heading("Local RAG / orchestration reports")
    output_dir = orchestration_output_dir(record)
    full_exports = build_orchestration_exports(orchestration, "full", output_dir / "section_reports", answer=answer, query=query)
    archive = build_orchestration_archive(orchestration, output_dir / "orchestration_artifacts.zip", answer=answer, query=query, project_root=ROOT)
    cols = st.columns(2)
    with cols[0]:
        render_download(full_exports.get("pdf"), "PDF: local RAG полный", "application/pdf")
    with cols[1]:
        render_download(full_exports.get("docx"), "DOCX: local RAG полный", "application/vnd.openxmlformats-officedocument.wordprocessingml.document")
    render_download(archive, "ZIP: local RAG artifacts", "application/zip")


def render_answer_section_exports(record: dict[str, Any]) -> None:
    answer = record.get("answer")
    if answer is None:
        return
    exports = build_answer_exports(
        answer_output_dir(record),
        query=record.get("query"),
        answer=answer,
        run=record.get("literature_run"),
        orchestration=record.get("orchestration"),
    )
    cols = st.columns(2)
    with cols[0]:
        render_download(exports.get("pdf"), "PDF: отчет", "application/pdf")
    with cols[1]:
        render_download(exports.get("docx"), "DOCX: отчет", "application/vnd.openxmlformats-officedocument.wordprocessingml.document")


def render_section_exports(run: Any | None, section: str, label: str) -> None:
    if run is None or not getattr(run, "output_dir", None):
        return
    exports = build_section_exports(run, section, Path(run.output_dir) / "section_reports")
    cols = st.columns(2)
    with cols[0]:
        render_download(exports.get("pdf"), f"PDF: {label}", "application/pdf")
    with cols[1]:
        render_download(exports.get("docx"), f"DOCX: {label}", "application/vnd.openxmlformats-officedocument.wordprocessingml.document")


def render_orchestration_section_exports(record: dict[str, Any], section: str, label: str) -> None:
    orchestration = record.get("orchestration")
    if orchestration is None:
        return
    exports = build_orchestration_exports(
        orchestration,
        section,
        orchestration_output_dir(record) / "section_reports",
        answer=record.get("answer"),
        query=record.get("query"),
    )
    cols = st.columns(2)
    with cols[0]:
        render_download(exports.get("pdf"), f"PDF: RAG {label}", "application/pdf")
    with cols[1]:
        render_download(exports.get("docx"), f"DOCX: RAG {label}", "application/vnd.openxmlformats-officedocument.wordprocessingml.document")


def render_literature_result(record: dict[str, Any]) -> None:
    run = record.get("literature_run")
    answer = record.get("answer")
    comparison_answer = record.get("comparison_answer")
    confidence_text, confidence_score = confidence_label(run, None)
    metrics = answer_metrics(record)

    cols = st.columns(5)
    cols[0].metric("Web sources", len(getattr(run, "results", []) or []))
    cols[1].metric("Local evidence", len(getattr(run, "local_matches", []) or []))
    cols[2].metric("Deep Search summaries", len(getattr(run, "deep_results", []) or []))
    cols[3].metric("Confidence", f"{confidence_text} ({confidence_score:.0%})")
    cols[4].metric("Отчет модели", metrics["answer_time"])

    tabs = st.tabs(["Отчет", "Источники", "Сравнение", "Графики", "Отчеты"])
    with tabs[0]:
        render_soft_heading("Поисковая формулировка")
        render_table(search_context_rows(run, None), empty_text="Поисковая формулировка не найдена.")
        render_soft_heading("Отчет")
        if answer is not None:
            render_soft_text(getattr(answer, "text", ""))
            render_answer_section_exports(record)
        elif run is not None:
            st.write(run_overall_summary(run))
        if run is not None and getattr(run, "deep_results", None):
            render_soft_heading("Overall Summary Deep Search")
            render_soft_text(run_overall_summary(run))

    with tabs[1]:
        render_soft_heading("Web-search: релевантные публикации")
        render_table(source_rows(run), empty_text="Web-источники не найдены.")
        render_web_source_links(run)
        render_soft_heading("Локальный поиск: релевантные публикации")
        render_table(local_rows_from_literature(run), empty_text="Локальные совпадения не найдены.")
        render_local_source_links(run)

    with tabs[2]:
        render_comparison_blocks(run, comparison_answer)

    with tabs[3]:
        render_soft_heading("Скорость и стоимость модели")
        cols = st.columns(4)
        cols[0].metric("Отчет", metrics["answer_time"])
        cols[1].metric("Сравнение", metrics["comparison_time"])
        cols[2].metric("Токены отчета", metrics["tokens"])
        cols[3].metric("Стоимость запроса", metrics["cost"])

        chart_height = 280
        col_a, col_b = st.columns(2)
        years = table_df(year_counts(run)) if run is not None else pd.DataFrame()
        sources = table_df(source_counts(run)) if run is not None else pd.DataFrame()
        with col_a:
            render_soft_heading("Публикации по годам")
            if not years.empty:
                years = years.rename(columns={"year": "Год", "count": "Количество"})
                st.bar_chart(years.set_index("Год"), use_container_width=True, height=chart_height)
            else:
                st.info("Нет данных по годам публикаций.")
        with col_b:
            render_soft_heading("Web-источники по базам данных")
            if not sources.empty:
                sources = sources.rename(columns={"source": "База", "count": "Количество"})
                sources["База"] = sources["База"].map(lambda value: SEARCH_SOURCE_LABELS.get(value, value))
                st.bar_chart(sources.set_index("База"), use_container_width=True, height=chart_height)
            else:
                st.info("Нет данных по базам данных.")

        render_soft_heading("Покрытие local vs web")
        coverage = pd.DataFrame(
            [
                {"Тип": "Local", "Количество": len(getattr(run, "local_matches", []) or [])},
                {"Тип": "Web", "Количество": len(getattr(run, "results", []) or [])},
                {"Тип": "Deep Search", "Количество": len(getattr(run, "deep_results", []) or [])},
            ]
        )
        st.bar_chart(coverage.set_index("Тип"), use_container_width=True, height=chart_height)

    with tabs[4]:
        render_reports(record)


def generate_literature_comparison(query: str, run: Any, options: dict[str, Any]) -> tuple[Any, Any | None]:
    if run is None or not options.get("comparison_insights"):
        return run, None
    try:
        started_at = time.perf_counter()
        comparison_answer = compare_literature_with_provider_router(
            query,
            run,
            project_root=ROOT,
            max_tokens=min(max(options.get("answer_tokens", 900), 500), 1200),
        )
        add_elapsed_usage(comparison_answer, time.perf_counter() - started_at)
        query_plan = dict(getattr(run, "query_plan", {}) or {})
        query_plan["llm_comparison_summary"] = getattr(comparison_answer, "text", "")
        query_plan["llm_comparison_usage"] = comparison_answer.metadata() if hasattr(comparison_answer, "metadata") else {}
        updated = run.model_copy(update={"query_plan": query_plan}, deep=True)
        if getattr(updated, "output_dir", None):
            updated = write_run_outputs(updated, Path(updated.output_dir))
        return updated, comparison_answer
    except Exception as exc:  # noqa: BLE001 - comparison should not break the whole demo query.
        warnings = list(getattr(run, "warnings", []) or [])
        warnings.append(f"LLM comparison skipped: {compact_text(exc, 300)}")
        updated = run.model_copy(update={"warnings": warnings}, deep=True)
        if getattr(updated, "output_dir", None):
            updated = write_run_outputs(updated, Path(updated.output_dir))
        return updated, None


def render_result(record: dict[str, Any]) -> None:
    run = record.get("literature_run")
    orchestration = record.get("orchestration")
    answer = record.get("answer")
    request_type = record.get("request_type")
    if request_type == "Литературный поиск":
        render_literature_result(record)
        return
    confidence_text, confidence_score = confidence_label(run, orchestration)

    cols = st.columns(4)
    cols[0].metric("Web sources", len(getattr(run, "results", []) or []))
    cols[1].metric("Local evidence", len(getattr(run, "local_matches", []) or []) + len(getattr(orchestration, "evidence", []) or []))
    cols[2].metric("Deep Search summaries", len(getattr(run, "deep_results", []) or []))
    cols[3].metric("Confidence", f"{confidence_text} ({confidence_score:.0%})")

    tabs = st.tabs(["Отчет", "Источники", "Сравнение", "Evidence", "Графы", "Графики", "Отчеты"])
    with tabs[0]:
        if answer is not None:
            st.markdown(compact_text(getattr(answer, "text", ""), 6000))
            render_answer_section_exports(record)
        elif run is not None:
            st.write(run_overall_summary(run))
            insights = comparison_insights(run)
            if insights:
                st.write(insights)
        elif orchestration is not None:
            st.text(orchestration.answer_draft)

    with tabs[1]:
        render_section_exports(run, "sources", "источники")
        render_orchestration_section_exports(record, "sources", "источники")
        st.markdown("**Web-search**")
        render_table(source_rows(run), empty_text="Web-источники не найдены.")
        st.markdown("**Локальный поиск**")
        render_table(local_rows_from_literature(run), empty_text="Локальные совпадения не найдены в literature layer.")
        if run is not None and getattr(run, "resource_links", None):
            st.markdown("**Дополнительные ссылки**")
            render_table(run.resource_links)

    with tabs[2]:
        render_section_exports(run, "comparison", "сравнение")
        render_section_exports(run, "properties", "свойства")
        render_orchestration_section_exports(record, "comparison", "сравнение")
        render_orchestration_section_exports(record, "properties", "свойства")
        st.markdown("**Подтверждается локально и во внешней литературе**")
        render_table(comparison_rows(run, "confirmed_methods"))
        st.markdown("**Только локально**")
        render_table(comparison_rows(run, "local_only_methods"))
        st.markdown("**Только во внешней литературе**")
        render_table(comparison_rows(run, "web_only_methods"))
        st.markdown("**Свойства и численные результаты**")
        render_table(property_rows(run, orchestration))

    with tabs[3]:
        render_section_exports(run, "evidence", "evidence")
        render_orchestration_section_exports(record, "evidence", "evidence")
        if orchestration is None:
            st.info("Local RAG evidence появится для режимов методик/свойств или при генерации отчета.")
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
        render_section_exports(run, "graphs", "графы")
        render_orchestration_section_exports(record, "graphs", "графы")
        col_a, col_b = st.columns(2)
        with col_a:
            st.markdown("**Knowledge graph**")
            st.graphviz_chart(knowledge_graph_dot(run, orchestration), use_container_width=True)
        with col_b:
            st.markdown(comparison_graph_title(request_type))
            st.graphviz_chart(comparison_graph_dot(run, orchestration, request_type), use_container_width=True)

    with tabs[5]:
        render_section_exports(run, "charts", "графики")
        render_orchestration_section_exports(record, "charts", "графики")
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
        render_reports(record)


def execute_query(query: str, options: dict[str, Any]) -> dict[str, Any]:
    request_type = options["request_type"]
    literature_run = None
    orchestration = None
    answer = None
    comparison_answer = None
    llm_client = build_router_completion_client_from_env(ROOT) if options["use_llm_rewrite"] or options["deep_search"] else None

    if request_type == "Литературный поиск":
        request = LiteratureSearchRequest(
            query=query,
            top_k=max(options["web_top_k"], options["local_top_k"]),
            web_top_k=options["web_top_k"],
            local_top_k=options["local_top_k"],
            sources=options["sources"] if options["web_search"] else [],
            deep_search="top5" if options["deep_search"] else "none",
            deep_search_limit=options["deep_limit"],
            deep_search_max_seconds=options["deep_search_max_seconds"],
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
        if options["generate_answer"]:
            started_at = time.perf_counter()
            answer = answer_literature_with_provider_router(query, literature_run, project_root=ROOT, max_tokens=options["answer_tokens"])
            add_elapsed_usage(answer, time.perf_counter() - started_at)
        literature_run, comparison_answer = generate_literature_comparison(query, literature_run, options)
    else:
        orchestration = run_query_orchestration(
            query,
            project_root=ROOT,
            include_web=options["web_search"],
            web_sources=options["sources"],
            web_top_k=options["web_top_k"],
            web_deep_search=options["deep_search"],
            web_deep_search_limit=options["deep_limit"],
            generate_pdf_report=options["generate_pdf"],
            required_routes=REQUEST_TYPES[request_type],
            retrieval_profile=options["retrieval_profile"],
            use_query_rewrite=True,
            use_llm_query_rewrite=options["use_llm_rewrite"],
            rewrite_client=llm_client if options["use_llm_rewrite"] else None,
        )
        literature_run = orchestration.web_run
        if options["generate_answer"]:
            started_at = time.perf_counter()
            answer = answer_with_provider_router(query, orchestration, project_root=ROOT, max_tokens=options["answer_tokens"])
            add_elapsed_usage(answer, time.perf_counter() - started_at)

    return {
        "query": query,
        "request_type": request_type,
        "created_at": datetime.now().strftime("%H:%M:%S"),
        "literature_run": literature_run,
        "orchestration": orchestration,
        "answer": answer,
        "comparison_answer": comparison_answer,
    }


def render_sidebar() -> dict[str, Any]:
    with st.sidebar:
        st.header("Настройки")
        request_type = st.radio("Тип запроса", list(REQUEST_TYPES), horizontal=False)
        local_search = st.checkbox("Local search", value=True)
        web_search = st.checkbox("Web literature search", value=True)
        deep_search = st.checkbox("Deep Search", value=False)
        deep_limit = st.slider("Статей для Deep Search", min_value=1, max_value=20, value=5)
        web_top_k = st.slider("Web top-K", min_value=3, max_value=60, value=20)
        local_top_k = st.slider("Local top-K", min_value=3, max_value=60, value=20)
        sources = st.multiselect(
            "Search resources",
            options=ALL_SEARCH_SOURCES,
            default=DEFAULT_SEARCH_SOURCES,
            format_func=lambda item: SEARCH_SOURCE_LABELS.get(item, item),
        )
        with st.expander("Advanced", expanded=False):
            retrieval_profile = st.selectbox("RAG profile", ["routerai_bge_m3", "yandex", "default"], index=0)
            use_llm_rewrite = st.checkbox("LLM rewrite запроса", value=True)
            generate_answer = st.checkbox("Генерировать отчет моделью", value=True)
            answer_tokens = st.slider("Длина отчета", min_value=300, max_value=1800, value=900, step=100)
            generate_pdf = st.checkbox("Генерировать PDF", value=True)
            comparison_insights = st.checkbox("Сравнение local vs web через LLM", value=True)
            fetch_excerpts = st.checkbox("Загружать excerpts сайтов (медленнее)", value=False)
            deep_search_max_seconds = st.slider("Лимит Deep Search, сек", min_value=30, max_value=900, value=180, step=30)
    return {
        "request_type": request_type,
        "retrieval_profile": None if retrieval_profile == "default" else retrieval_profile,
        "local_search": local_search,
        "web_search": web_search,
        "use_llm_rewrite": use_llm_rewrite,
        "deep_search": deep_search,
        "deep_limit": deep_limit,
        "web_top_k": web_top_k,
        "local_top_k": local_top_k,
        "top_k": max(web_top_k, local_top_k),
        "sources": sources or DEFAULT_SEARCH_SOURCES.copy(),
        "generate_answer": generate_answer,
        "answer_tokens": answer_tokens,
        "generate_pdf": generate_pdf,
        "comparison_insights": comparison_insights,
        "fetch_excerpts": fetch_excerpts,
        "deep_search_max_seconds": deep_search_max_seconds,
    }


def main() -> None:
    st.set_page_config(page_title="Oreacle", layout="wide")
    st.markdown(
        """
        <style>
        .literature-section-title {
            font-size: 0.98rem;
            font-weight: 400;
            color: #cbd3df;
            margin: 0.85rem 0 0.35rem 0;
        }
        .literature-soft-text {
            font-size: 0.95rem;
            font-weight: 400;
            line-height: 1.55;
            color: #c8d0dc;
            margin-bottom: 0.85rem;
        }
        </style>
        """,
        unsafe_allow_html=True,
    )
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
                        try:
                            started_at = time.perf_counter()
                            llm_client = build_router_completion_client_from_env(ROOT)
                            updated = run_deep_search_for_existing_run(
                                run,
                                project_root=ROOT,
                                deep_search_limit=options["deep_limit"],
                                deep_search_max_seconds=options["deep_search_max_seconds"],
                                fetch_excerpts=options["fetch_excerpts"],
                                yandex_client=llm_client,
                            )
                            record["literature_run"] = updated
                            if options["generate_answer"]:
                                answer_started_at = time.perf_counter()
                                record["answer"] = answer_literature_with_provider_router(
                                    record.get("query") or updated.request.query,
                                    updated,
                                    project_root=ROOT,
                                    max_tokens=options["answer_tokens"],
                                )
                                add_elapsed_usage(record["answer"], time.perf_counter() - answer_started_at)
                            updated, comparison_answer = generate_literature_comparison(record.get("query") or updated.request.query, updated, options)
                            record["literature_run"] = updated
                            record["comparison_answer"] = comparison_answer
                            status.update(label=f"Deep Search готов за {format_seconds(time.perf_counter() - started_at)}", state="complete")
                        except Exception as exc:  # noqa: BLE001 - keep Streamlit alive on external source errors.
                            status.update(label="Deep Search не завершился", state="error")
                            st.error(f"Deep Search остановлен: {compact_text(exc, 500)}")
                            return
                    st.rerun()
            with col2:
                st.write(f"Последний запрос: {record['query']}")
        render_result(record)
    else:
        st.info("Введите запрос в чат. Текущий экран сохраняет историю сообщений и не очищает запрос после поиска.")


if __name__ == "__main__":
    main()
