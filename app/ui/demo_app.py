from __future__ import annotations

import json
import inspect
import re
import sys
import time
import zipfile
from datetime import datetime
from functools import lru_cache
from html import escape
from pathlib import Path
from typing import Any

import pandas as pd
import streamlit as st
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.market.radar import detect_market_query, run_market_radar  # noqa: E402
from app.market.sources import SOURCE_REGISTRY  # noqa: E402
from app.query.cockpit import graphviz_dot as literature_graphviz_dot  # noqa: E402
from app.query.literature import (  # noqa: E402
    answer_literature_with_provider_router,
    compare_literature_with_provider_router,
    run_deep_search_for_existing_run,
    run_literature_search,
    write_run_outputs,
)
from app.query.comparison import build_method_comparison_from_orchestration  # noqa: E402
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
    report_text_blocks,
    run_overall_summary,
    routerai_budget_summary,
    safe_report_id,
    source_counts,
    year_counts,
)
from app.web_search.deep_search import build_router_completion_client_from_env  # noqa: E402
from app.web_search.schemas import ALL_SEARCH_SOURCES, DEFAULT_SEARCH_SOURCES, SEARCH_SOURCE_LABELS, LiteratureSearchRequest  # noqa: E402


load_dotenv(ROOT / ".env", encoding="utf-8-sig")

REQUEST_TYPES = {
    "Литературный поиск": ["summary_rag", "raw_rag"],
    "Анализ методик и свойств": ["summary_rag", "raw_rag", "table_search", "graph_search"],
    "Бизнес-аналитика": ["summary_rag", "raw_rag", "table_search", "graph_search"],
}
ROUTE_LABELS = {
    "raw_rag": "Raw RAG",
    "summary_rag": "Summary RAG",
    "table_search": "Tables",
    "graph_search": "Knowledge graph",
    "web_search": "Web literature",
}
MARKET_RADAR_TERMS = (
    "рынок",
    "рыноч",
    "доля",
    "доли",
    "объем рынка",
    "объём рынка",
    "производств",
    "выпуск",
    "выручк",
    "продаж",
    "компани",
    "страна",
    "экспорт",
    "импорт",
    "market",
    "share",
    "production",
    "producer",
    "company",
    "country",
    "export",
    "import",
)
ASSETS_DIR = Path(__file__).resolve().parent / "assets"
METALMIND_EMBLEM_PATH = ASSETS_DIR / "metalmind_emblem_256.png"


def should_run_market_radar(query: str) -> bool:
    detected = detect_market_query(query)
    if detected.commodities or detected.companies or detected.countries:
        return True
    folded = query.casefold()
    return any(term in folded for term in MARKET_RADAR_TERMS)


def run_query_orchestration_compat(query: str, *, local_top_k: int | None = None, **kwargs: Any) -> Any:
    call_kwargs = dict(kwargs)
    try:
        signature = inspect.signature(run_query_orchestration)
        supports_local_top_k = "local_top_k" in signature.parameters or any(
            parameter.kind is inspect.Parameter.VAR_KEYWORD for parameter in signature.parameters.values()
        )
    except (TypeError, ValueError):
        supports_local_top_k = True
    if supports_local_top_k:
        call_kwargs["local_top_k"] = local_top_k
    return run_query_orchestration(query, **call_kwargs)


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


def render_horizontal_bar_chart(
    rows: list[dict[str, Any]] | pd.DataFrame,
    *,
    label_col: str,
    value_col: str,
    empty_text: str,
    height: int = 320,
    max_rows: int = 20,
) -> None:
    df = table_df(rows) if isinstance(rows, list) else rows.copy()
    if df.empty or label_col not in df or value_col not in df:
        st.info(empty_text)
        return
    df = df[[label_col, value_col]].copy()
    df[value_col] = pd.to_numeric(df[value_col], errors="coerce")
    df = df.dropna(subset=[value_col])
    if df.empty:
        st.info(empty_text)
        return
    df[label_col] = df[label_col].map(lambda value: compact_text(value, 52))
    df = df.groupby(label_col, as_index=False)[value_col].sum().sort_values(value_col, ascending=False).head(max_rows)
    st.bar_chart(df, x=value_col, y=label_col, horizontal=True, use_container_width=True, height=height)


def numeric_score(value: Any) -> float:
    try:
        return float(value or 0.0)
    except (TypeError, ValueError):
        return 0.0


def score_out_of_10(value: Any, max_score: float) -> float:
    score = numeric_score(value)
    denominator = max(max_score, score) if max(max_score, score) > 0 else 1.0
    return round(min(10.0, max(0.0, score / denominator * 10.0)), 1)


HASH_RE = re.compile(r"^(?:[a-f0-9]{12,}|(?:raw_chunk|document_summary|procedure_summary|docsum|proc)[:_][a-f0-9_:-]+)$", re.I)


def is_hash_like(value: Any) -> bool:
    text = str(value or "").strip()
    return bool(text and HASH_RE.match(text))


@lru_cache(maxsize=1)
def publication_source_lookup() -> dict[str, dict[str, str]]:
    path = ROOT / "data" / "processed" / "publications" / "publications.jsonl"
    if not path.exists():
        return {}
    lookup: dict[str, dict[str, str]] = {}
    with path.open(encoding="utf-8") as handle:
        for line in handle:
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                continue
            item = {
                "title": compact_text(row.get("title") or row.get("file_name") or row.get("source_path"), 300),
                "source_path": str(row.get("source_path") or ""),
                "file_name": str(row.get("file_name") or ""),
            }
            for key in (row.get("doc_id"), row.get("publication_id")):
                if key:
                    lookup[str(key)] = item
    return lookup


def display_source_title(row: dict[str, Any], lookup: dict[str, str] | None = None) -> str:
    lookup = lookup or {}
    doc_id = str(row.get("doc_id") or "")
    if doc_id and lookup.get(doc_id):
        return compact_text(lookup[doc_id], 300)
    for key in ("title", "label", "source_path", "local_path", "path", "file_name"):
        value = row.get(key)
        if not value or is_hash_like(value):
            continue
        text = str(value)
        if "\\" in text or "/" in text:
            stem = Path(text).stem
            if stem and not is_hash_like(stem):
                return compact_text(stem, 300)
        return compact_text(text, 300)
    if doc_id and publication_source_lookup().get(doc_id, {}).get("title"):
        return compact_text(publication_source_lookup()[doc_id]["title"], 300)
    for key in ("doc_id", "id"):
        value = row.get(key)
        if value and not is_hash_like(value):
            return compact_text(value, 300)
    return "Источник"


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
                "Заголовок": display_source_title(row),
                "Фрагмент": row.get("preview") or row.get("summary") or row.get("source_path"),
            }
        )
    return rows


def orchestration_rows(orchestration: Any | None, section: str) -> list[dict[str, Any]]:
    if orchestration is None:
        return []
    return list((orchestration.retrieved_context.as_dict().get(section) or []))


def orchestration_title_lookup(orchestration: Any | None) -> dict[str, str]:
    if orchestration is None:
        return {}
    context = orchestration.retrieved_context.as_dict()
    lookup: dict[str, str] = {}
    for rows in context.values():
        for row in rows or []:
            doc_id = str(row.get("doc_id") or "")
            if not doc_id or lookup.get(doc_id):
                continue
            title = display_source_title(row)
            if title and title != "Источник" and not is_hash_like(title):
                lookup[doc_id] = title
    return lookup


def comparison_rows(run: Any | None, name: str) -> list[dict[str, Any]]:
    if run is None or not getattr(run, "comparison", None):
        return []
    return list(getattr(run.comparison, name, []) or [])


def evidence_label(evidence: list[dict[str, Any]], *, limit: int = 4) -> str:
    labels: list[str] = []
    for item in evidence[:limit]:
        citation = item.get("citation")
        title = display_source_title(item) if isinstance(item, dict) else ""
        if title == "Источник":
            title = item.get("locator") or ""
        if citation:
            labels.append(f"[{citation}] {compact_text(title, 80)}")
    return "; ".join(labels)


def method_comparison_rows(record: dict[str, Any]) -> list[dict[str, Any]]:
    comparison = record.get("method_comparison")
    if comparison is None:
        return []
    rows = comparison.as_dict().get("rows") if hasattr(comparison, "as_dict") else getattr(comparison, "rows", [])
    result: list[dict[str, Any]] = []
    is_business = record.get("request_type") == "Бизнес-аналитика"
    for index, row in enumerate(rows or [], start=1):
        payload = row if isinstance(row, dict) else row.as_dict()
        base = {
            "#": index,
            "Релевантность /10": payload.get("score") or "",
            "Решение / технология": payload.get("item") or "",
            "Где применимо": "; ".join(_as_text_list(payload.get("materials"), limit=4)),
            "Условия / KPI": "; ".join(_as_text_list(payload.get("conditions") or payload.get("properties") or payload.get("numeric_values"), limit=5)),
        }
        if is_business:
            base["Экономика"] = "; ".join(_as_text_list(payload.get("business_context") or payload.get("numeric_values"), limit=6))
            base["Риски / ограничения"] = "; ".join(_as_text_list(payload.get("limitations"), limit=4))
        else:
            base["Численные значения"] = "; ".join(_as_text_list(payload.get("numeric_values"), limit=5))
            base["Плюсы / эффекты"] = "; ".join(_as_text_list(payload.get("advantages"), limit=4))
        base["Источники"] = evidence_label(payload.get("evidence") or [])
        result.append(base)
    return result


def market_metric_label(row: Any) -> str:
    metric = getattr(row, "metric", "") or ""
    commodity = getattr(row, "commodity", "") or ""
    labels = {
        "production": "производство",
        "sales": "продажи",
        "revenue": "выручка",
        "capacity": "мощность",
        "capex": "CAPEX",
        "opex": "OPEX",
        "energy": "энергия",
        "reagents": "реагенты",
    }
    metric_label = labels.get(metric, metric)
    if commodity == "company financials":
        return metric_label or "финансы"
    if metric_label and metric_label != "production":
        return f"{metric_label}: {commodity}"
    return commodity or metric_label


def orchestration_source_rows(orchestration: Any | None) -> list[dict[str, Any]]:
    if orchestration is None:
        return []
    context = orchestration.retrieved_context.as_dict()
    all_rows: list[tuple[str, dict[str, Any]]] = []
    for section in ("raw", "summaries", "tables", "graph"):
        for row in context.get(section) or []:
            if row.get("source_type") == "diagnostics":
                continue
            all_rows.append((section, row))
    max_score = max([numeric_score(row.get("score")) for _, row in all_rows] or [1.0])
    labels = {"raw": "Raw RAG", "summaries": "Summary", "tables": "Excel/Table", "graph": "Graph"}
    title_lookup = orchestration_title_lookup(orchestration)
    rows: list[dict[str, Any]] = []
    for index, (section, row) in enumerate(all_rows[:60], start=1):
        rows.append(
            {
                "#": index,
                "Тип": labels.get(section, section),
                "Релевантность /10": score_out_of_10(row.get("score"), max_score),
                "Источник": display_source_title(row, title_lookup),
                "Фрагмент": row.get("preview") or row.get("summary") or row.get("path") or row.get("relation") or "",
            }
        )
    return rows


def render_orchestration_source_links(orchestration: Any | None) -> None:
    if orchestration is None:
        return
    context = orchestration.retrieved_context.as_dict()
    rows = [row for name in ("raw", "summaries", "tables") for row in (context.get(name) or []) if row.get("source_type") != "diagnostics"]
    if not rows:
        return
    title_lookup = orchestration_title_lookup(orchestration)
    render_soft_heading("Локальные источники и таблицы")
    shown = 0
    for index, row in enumerate(rows[:40], start=1):
        found = local_file_for_row(row)
        link = row.get("url") or ""
        title = display_source_title(row, title_lookup)
        cols = st.columns([7, 1.6, 1.6])
        cols[0].write(f"{index}. {compact_text(title, 240)}")
        if link and str(link).startswith(("http://", "https://")):
            shown += 1
            cols[1].link_button("Открыть", str(link), use_container_width=True)
            cols[2].download_button(
                "Скачать",
                data=web_shortcut_bytes(str(link)),
                file_name=f"{index:02d}_source.url",
                mime="application/octet-stream",
                use_container_width=True,
                key=f"orchestration_source_url_{index}_{safe_report_id(link, prefix='src')}",
            )
        elif found is not None:
            shown += 1
            cols[1].link_button("Открыть", found.resolve().as_uri(), use_container_width=True)
            cols[2].download_button(
                "Скачать",
                data=found.read_bytes(),
                file_name=found.name,
                mime="application/octet-stream",
                use_container_width=True,
                key=f"orchestration_source_file_{index}_{safe_report_id(found, prefix='src')}",
            )
        else:
            cols[1].caption("Нет файла")
            cols[2].caption("")
    if shown == 0:
        st.caption("Для найденных строк пока нет прямых файлов или web-ссылок.")


def market_radar_rows(record: dict[str, Any]) -> list[dict[str, Any]]:
    radar = record.get("market_radar")
    if radar is None:
        return []
    rows = getattr(radar, "production_rows", []) or []
    detected = getattr(radar, "detected", None)
    is_water_teo = getattr(detected, "intent", "") == "techno_economic_water_treatment"
    if is_water_teo:
        return [
            {
                "#": index,
                "Технология": getattr(row, "company_or_country", ""),
                "Показатель": getattr(row, "metric", ""),
                "Значение": getattr(row, "value", ""),
                "Ед.": getattr(row, "unit", ""),
                "Cost-драйвер / ограничение": getattr(row, "notes", ""),
                "Источник": getattr(row, "source_name", ""),
                "Уверенность": getattr(row, "confidence", ""),
            }
            for index, row in enumerate(rows[:40], start=1)
        ]
    return [
        {
            "#": index,
            "Показатель": market_metric_label(row),
            "Область": getattr(row, "commodity", ""),
            "Компания / страна": getattr(row, "company_or_country", ""),
            "Период": getattr(row, "period", ""),
            "Значение": getattr(row, "value", ""),
            "Ед.": getattr(row, "unit", ""),
            "Источник": getattr(row, "source_name", ""),
            "Уверенность": getattr(row, "confidence", ""),
        }
        for index, row in enumerate(rows[:40], start=1)
    ]


def is_techno_economic_radar(record: dict[str, Any]) -> bool:
    radar = record.get("market_radar")
    detected = getattr(radar, "detected", None) if radar is not None else None
    return getattr(detected, "intent", "") == "techno_economic_water_treatment"


def market_source_status_rows(record: dict[str, Any]) -> list[dict[str, Any]]:
    radar = record.get("market_radar")
    if radar is None:
        return []
    return [
        {
            "Источник": getattr(status, "source_name", ""),
            "Статус": getattr(status, "status", ""),
            "Строк загружено": getattr(status, "rows_loaded", ""),
            "Ссылка": getattr(status, "source_url", ""),
        }
        for status in getattr(radar, "source_status", []) or []
    ]


def market_share_rows(record: dict[str, Any]) -> list[dict[str, Any]]:
    rows = market_radar_rows(record)
    numeric_rows: list[dict[str, Any]] = []
    for row in rows:
        value = numeric_score(row.get("Значение"))
        if value <= 0:
            continue
        numeric_rows.append({**row, "_value": value})
    totals: dict[tuple[str, str], float] = {}
    for row in numeric_rows:
        key = (str(row.get("Показатель") or ""), str(row.get("Период") or ""), str(row.get("Ед.") or ""))
        totals[key] = totals.get(key, 0.0) + float(row["_value"])
    result: list[dict[str, Any]] = []
    for row in numeric_rows:
        key = (str(row.get("Показатель") or ""), str(row.get("Период") or ""), str(row.get("Ед.") or ""))
        total = totals.get(key) or 0.0
        if total <= 0:
            continue
        result.append(
            {
                "Компания / страна": row.get("Компания / страна"),
                "Показатель": row.get("Показатель"),
                "Период": row.get("Период"),
                "Доля, %": round(float(row["_value"]) / total * 100.0, 1),
                "Объем": row.get("Значение"),
                "Ед.": row.get("Ед."),
            }
        )
    return result


def business_source_registry_rows() -> list[dict[str, Any]]:
    return [
        {
            "Источник": source.source_name,
            "Тип": source.source_type,
            "Что покрывает": ", ".join(source.commodities),
            "Ссылка": source.source_url,
        }
        for source in SOURCE_REGISTRY
    ]


def market_radar_context(record: dict[str, Any], *, max_rows: int = 20) -> str:
    radar = record.get("market_radar")
    if radar is None:
        return ""
    lines = [getattr(radar, "market_summary", "") or ""]
    detected = getattr(radar, "detected", None)
    if getattr(detected, "intent", "") == "techno_economic_water_treatment":
        for row in (getattr(radar, "production_rows", []) or [])[:max_rows]:
            lines.append(
                "- "
                + "; ".join(
                    str(value)
                    for value in (
                        f"технология={getattr(row, 'company_or_country', '')}",
                        f"показатель={getattr(row, 'metric', '')}",
                        f"значение={getattr(row, 'value', '')} {getattr(row, 'unit', '')}",
                        f"cost_driver={getattr(row, 'notes', '')}",
                        f"source={getattr(row, 'source_name', '')}",
                        f"confidence={getattr(row, 'confidence', '')}",
                    )
                    if value not in (None, "")
                )
            )
        missing = getattr(radar, "missing_data", []) or []
        if missing:
            lines.append("Missing data for calculation: " + "; ".join(str(item) for item in missing[:8]))
        return "\n".join(line for line in lines if line).strip()
    for row in (getattr(radar, "production_rows", []) or [])[:max_rows]:
        lines.append(
            "- "
            + "; ".join(
                str(value)
                for value in (
                    getattr(row, "company_or_country", ""),
                    getattr(row, "commodity", ""),
                    getattr(row, "period", ""),
                    f"{getattr(row, 'value', '')} {getattr(row, 'unit', '')}",
                    getattr(row, "source_name", ""),
                    getattr(row, "source_url", ""),
                    f"confidence={getattr(row, 'confidence', '')}",
                )
                if value not in (None, "")
            )
        )
    missing = getattr(radar, "missing_data", []) or []
    if missing:
        lines.append("Missing data: " + "; ".join(str(item) for item in missing[:8]))
    return "\n".join(line for line in lines if line).strip()


def user_report_extra_sections(record: dict[str, Any]) -> list[dict[str, Any]]:
    sections: list[dict[str, Any]] = []
    method_rows = method_comparison_rows(record)
    if method_rows:
        summary_text = method_comparison_summary_text(record)
        headers = list(method_rows[0].keys())
        sections.append(
            {
                "title": "Сравнение решений",
                "paragraphs": [line for line in summary_text.splitlines() if line and not line.startswith("##")] if summary_text else [],
                "table": {"headers": headers, "rows": [[str(row.get(header, "")) for header in headers] for row in method_rows[:20]]},
            }
        )
        reference_rows = citation_reference_rows(record)
        if reference_rows:
            reference_headers = list(reference_rows[0].keys())
            sections.append(
                {
                    "title": "Источники к выводам",
                    "paragraphs": ["Номера источников соответствуют ссылкам вида [1], [2] в summary. Локальные документы лежат в ZIP-архиве под теми же номерами."],
                    "table": {
                        "headers": reference_headers,
                        "rows": [[str(row.get(header, "")) for header in reference_headers] for row in reference_rows],
                    },
                }
            )
    if record.get("request_type") != "Бизнес-аналитика":
        return sections

    radar = record.get("market_radar")
    if radar is not None:
        summary_parts = [getattr(radar, "market_summary", "") or ""]
        missing = getattr(radar, "missing_data", []) or []
        if missing:
            summary_parts.append("Недостающие данные: " + "; ".join(str(item) for item in missing[:8]))
        suggested = getattr(radar, "suggested_sources", []) or []
        if suggested:
            summary_parts.append("Что проверить дальше: " + "; ".join(str(item) for item in suggested[:8]))
        sections.append(
            {
                "title": "Рыночный summary",
                "paragraphs": [part for part in summary_parts if part],
            }
        )

    market_rows = market_radar_rows(record)
    if market_rows:
        headers = list(market_rows[0].keys())
        sections.append(
            {
                "title": "Конкретные рыночные цифры",
                "paragraphs": [],
                "table": {"headers": headers, "rows": [[str(row.get(header, "")) for header in headers] for row in market_rows[:40]]},
            }
        )
    share_rows = market_share_rows(record)
    if share_rows:
        headers = list(share_rows[0].keys())
        sections.append(
            {
                "title": "Доли в найденной выборке",
                "paragraphs": ["Доли рассчитаны только по найденным и сопоставимым строкам Market Radar."],
                "table": {"headers": headers, "rows": [[str(row.get(header, "")) for header in headers] for row in share_rows[:40]]},
            }
        )
    status_rows = market_source_status_rows(record)
    if status_rows:
        headers = list(status_rows[0].keys())
        sections.append(
            {
                "title": "Релевантные бизнес-источники",
                "paragraphs": [],
                "table": {"headers": headers, "rows": [[str(row.get(header, "")) for header in headers] for row in status_rows[:20]]},
            }
        )
    return sections


def method_comparison_summary_text(record: dict[str, Any]) -> str:
    comparison = record.get("method_comparison")
    if comparison is None:
        return ""
    rows = comparison.as_dict().get("rows") if hasattr(comparison, "as_dict") else getattr(comparison, "rows", [])
    if not rows:
        return ""
    refs = citation_ref_map(record.get("literature_run"), record.get("orchestration"))
    lines = ["## Summary по методикам и свойствам", ""]
    for index, row in enumerate(rows[:5], start=1):
        payload = row if isinstance(row, dict) else row.as_dict()
        item = payload.get("item") or f"Методика {index}"
        details: list[str] = []
        for label, key in (
            ("условия", "conditions"),
            ("свойства/KPI", "properties"),
            ("численные значения", "numeric_values"),
            ("экономика", "business_context"),
            ("эффекты", "advantages"),
            ("ограничения", "limitations"),
        ):
            values = _as_text_list(payload.get(key), limit=4)
            if values:
                details.append(f"{label}: {', '.join(values)}")
        evidence = evidence_label(payload.get("evidence") or [], limit=3)
        citation_numbers = evidence_reference_numbers(payload.get("evidence") or [], refs, limit=4)
        if citation_numbers:
            details.append(f"источники: {', '.join(citation_numbers)}")
        elif evidence:
            details.append(f"источники: {evidence}")
        if details:
            lines.append(f"{index}. {item}: " + "; ".join(details) + ".")
        else:
            lines.append(f"{index}. {item}: найдена как релевантная методика, но структурированных параметров пока мало.")
    missing = getattr(comparison, "missing_evidence", None) or []
    if missing:
        lines.extend(["", "Пробелы: часть методик не имеет полной таблицы условий/численных диапазонов в текущем evidence pack."])
    return "\n".join(lines)


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


def build_orchestration_local_sources_archive(orchestration: Any | None, output_path: Path) -> Path | None:
    if orchestration is None:
        return None
    context = orchestration.retrieved_context.as_dict()
    title_lookup = orchestration_title_lookup(orchestration)
    refs = citation_ref_map(None, orchestration)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    files: list[tuple[Path, str, str, str]] = []
    seen_paths: set[Path] = set()
    used_names: set[str] = set()
    for section in ("raw", "summaries", "tables"):
        for index, row in enumerate(context.get(section) or [], start=1):
            found = local_file_for_row(row)
            if found is None:
                continue
            resolved = found.resolve()
            if resolved in seen_paths:
                continue
            seen_paths.add(resolved)
            title = display_source_title(row, title_lookup)
            citation_number = citation_number_for_row(section, row, index, refs) or str(len(files) + 1)
            slug = safe_report_id(title, prefix="source").split("_")[0][:70].strip("_") or found.stem
            arcname = f"{int(citation_number):02d}_{slug}{found.suffix}" if citation_number.isdigit() else f"{len(files) + 1:02d}_{slug}{found.suffix}"
            while arcname.casefold() in used_names:
                arcname = f"{len(files) + 1:02d}_{slug}_{len(used_names) + 1}{found.suffix}"
            used_names.add(arcname.casefold())
            files.append((found, arcname, citation_number, title))
    if not files:
        return None
    with zipfile.ZipFile(output_path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        toc_lines = ["citation;title;file_name"]
        for path, arcname, citation_number, title in files:
            archive.write(path, arcname=arcname)
            toc_lines.append(f"[{citation_number}];{title.replace(';', ',')};{arcname}")
        archive.writestr("README.csv", "\n".join(toc_lines) + "\n")
    return output_path


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


def citation_url_map(run: Any | None, orchestration: Any | None = None) -> dict[str, str]:
    return {key: value["href"] for key, value in citation_ref_map(run, orchestration).items()}


def citation_ref_map(run: Any | None, orchestration: Any | None = None) -> dict[str, dict[str, str]]:
    mapping: dict[str, str] = {}
    refs: dict[str, dict[str, str]] = {}

    def add_ref(key: Any, href: str, label: str) -> None:
        if not key or not href:
            return
        normalized = str(key).casefold()
        if normalized not in refs:
            refs[normalized] = {"href": href, "label": compact_text(label or "Открыть источник", 120)}
        mapping[normalized] = href

    def add_key_aliases(section: str, row: dict[str, Any], href: str, label: str) -> None:
        values = [
            row.get("id"),
            row.get("chunk_id"),
            row.get("summary_id"),
            row.get("document_summary_id"),
            row.get("procedure_summary_id"),
            row.get("doc_id"),
            row.get("publication_id"),
        ]
        for value in values:
            if not value:
                continue
            text = str(value)
            add_ref(text, href, label)
            add_ref(f"{section}:{text}", href, label)
            tail = text.split(":")[-1]
            add_ref(f"{section}:{tail}", href, label)
            if section == "raw":
                add_ref(f"raw:{tail}", href, label)
            if section == "summaries":
                add_ref(f"summaries:{tail}", href, label)
                add_ref(f"document_summary:{tail}", href, label)
                add_ref(f"procedure_summary:{tail}", href, label)

    if run is not None:
        for index, result in enumerate(getattr(run, "results", []) or [], start=1):
            link = preferred_web_link(result)
            if link:
                label = getattr(result, "title", "") or "Web-источник"
                add_ref(f"web:{index}", link, label)
                result_id = getattr(result, "result_id", None)
                if result_id:
                    add_ref(f"web:{result_id}", link, label)
        for index, row in enumerate(getattr(run, "local_matches", []) or [], start=1):
            found = local_file_for_row(row)
            if found:
                add_ref(f"local:{index}", found.resolve().as_uri(), display_source_title(row))
    if orchestration is not None:
        context = getattr(orchestration, "retrieved_context", None).as_dict() if getattr(orchestration, "retrieved_context", None) else {}
        title_lookup = orchestration_title_lookup(orchestration)
        doc_links: dict[str, tuple[str, str]] = {}
        for rows in context.values():
            for row in rows or []:
                doc_id = str(row.get("doc_id") or "")
                found = local_file_for_row(row)
                if doc_id and found and doc_id not in doc_links:
                    doc_links[doc_id] = (found.resolve().as_uri(), display_source_title(row, title_lookup))
        for section, rows in context.items():
            for index, row in enumerate(rows or [], start=1):
                citation = str(row.get("id") or f"{section}:{index}")
                link = row.get("url") or ""
                if not link:
                    found = local_file_for_row(row)
                    link = found.resolve().as_uri() if found else ""
                if not link and row.get("doc_id") and str(row.get("doc_id")) in doc_links:
                    link = doc_links[str(row.get("doc_id"))][0]
                if not link and row.get("doi"):
                    link = f"https://doi.org/{row['doi']}"
                if link:
                    label = display_source_title(row, title_lookup)
                    if label == "Источник" and row.get("doc_id") and str(row.get("doc_id")) in doc_links:
                        label = doc_links[str(row.get("doc_id"))][1]
                    add_ref(citation, link, label)
                    add_ref(f"{section}:{index}", link, label)
                    add_key_aliases(section, row, link, label)
    number_by_href: dict[str, int] = {}
    next_number = 1
    for ref in refs.values():
        href = ref.get("href", "")
        identity = href or ref.get("label", "")
        if identity not in number_by_href:
            number_by_href[identity] = next_number
            next_number += 1
        ref["number"] = str(number_by_href[identity])
    return refs


def citation_number_for_row(section: str, row: dict[str, Any], index: int, refs: dict[str, dict[str, str]]) -> str:
    keys = [
        row.get("id"),
        f"{section}:{index}",
        row.get("chunk_id"),
        row.get("summary_id"),
        row.get("document_summary_id"),
        row.get("procedure_summary_id"),
        row.get("doc_id"),
        row.get("publication_id"),
    ]
    for key in keys:
        if not key:
            continue
        text = str(key).casefold()
        candidates = [text, f"{section}:{text}", text.split(":")[-1], f"{section}:{text.split(':')[-1]}"]
        if section == "raw":
            candidates.append(f"raw:{text.split(':')[-1]}")
        for candidate in candidates:
            ref = refs.get(candidate)
            if ref and ref.get("number"):
                return ref["number"]
    return ""


def evidence_reference_numbers(evidence: list[dict[str, Any]], refs: dict[str, dict[str, str]], *, limit: int = 4) -> list[str]:
    labels: list[str] = []
    seen: set[str] = set()
    for item in evidence[:limit]:
        citation = str(item.get("citation") or "")
        if not citation:
            continue
        candidates = [citation.casefold(), citation.split(":")[-1].casefold()]
        number = ""
        for candidate in candidates:
            ref = refs.get(candidate)
            if ref and ref.get("number"):
                number = ref["number"]
                break
        label = f"[{number}]" if number else f"[{citation}]"
        if label not in seen:
            labels.append(label)
            seen.add(label)
    return labels


def citation_reference_rows(record: dict[str, Any]) -> list[dict[str, str]]:
    refs = citation_ref_map(record.get("literature_run"), record.get("orchestration"))
    unique: dict[str, dict[str, str]] = {}
    for ref in refs.values():
        number = ref.get("number")
        if number and number not in unique:
            unique[number] = ref
    rows: list[dict[str, str]] = []
    for number in sorted(unique, key=lambda value: int(value) if value.isdigit() else 9999):
        ref = unique[number]
        href = ref.get("href", "")
        rows.append(
            {
                "#": f"[{number}]",
                "Источник": ref.get("label", "Источник"),
                "Ссылка / файл": href if href.startswith(("http://", "https://")) else f"см. ZIP локальных источников: {int(number):02d}_...",
            }
        )
    return rows[:40]


def linkify_citations(text: str, run: Any | None, orchestration: Any | None = None) -> str:
    refs = citation_ref_map(run, orchestration)
    refs_by_number: dict[str, dict[str, str]] = {}
    for ref in refs.values():
        number = ref.get("number")
        if number and number not in refs_by_number:
            refs_by_number[number] = ref
    safe = escape(compact_text(text, 3000))

    def replace(match: re.Match[str]) -> str:
        raw_key = match.group(1)
        key = raw_key.casefold()
        ref = refs_by_number.get(raw_key) if raw_key.isdigit() else refs.get(key)
        if not ref:
            return match.group(0)
        href = ref["href"]
        label = ref["label"]
        number = ref.get("number") or "?"
        return (
            f'<a href="{escape(href, quote=True)}" target="_blank" '
            f'title="{escape(label, quote=True)}">[{escape(number)}]</a>'
        )

    return re.sub(r"\[([A-Za-z_][A-Za-z0-9_:-]+|\d+)\]", replace, safe, flags=re.I)


def render_report_body(text: str, run: Any | None, orchestration: Any | None = None) -> None:
    blocks = report_text_blocks(text)
    if not blocks:
        st.info("Отчет пока не сгенерирован.")
        return
    for block in blocks:
        block_text = block.get("text", "")
        if block.get("type") == "heading":
            render_soft_heading(block_text)
        elif block.get("type") == "bullet":
            st.markdown(
                f'<div class="literature-soft-text">• {linkify_citations(block_text, run, orchestration)}</div>',
                unsafe_allow_html=True,
            )
        else:
            st.markdown(
                f'<div class="literature-soft-text">{linkify_citations(block_text, run, orchestration)}</div>',
                unsafe_allow_html=True,
            )


def local_file_for_row(row: dict[str, Any]) -> Path | None:
    for key in ("local_path", "source_path", "path", "file_name"):
        value = row.get(key)
        if not value:
            continue
        found = find_local_file(str(value), project_root=ROOT)
        if found:
            return found
    for key in ("doc_id", "publication_id"):
        value = row.get(key)
        if not value:
            continue
        metadata = publication_source_lookup().get(str(value)) or {}
        for candidate in (metadata.get("source_path"), metadata.get("file_name")):
            if not candidate:
                continue
            found = find_local_file(candidate, project_root=ROOT)
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
        title = display_source_title(row)
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
        title = display_source_title(row)
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
        render_report_body(text, run)


def render_literature_reports(record: dict[str, Any]) -> None:
    run = record.get("literature_run")
    answer = record.get("answer")
    comparison_answer = record.get("comparison_answer")
    query = record.get("query")
    if run is None:
        st.info("Отчет появится после поиска.")
        return

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
        render_soft_heading("Основной отчет")
        answer_exports = build_answer_exports(
            answer_output_dir(record),
            query=query,
            answer=answer,
            run=run,
            orchestration=orchestration,
            extra_sections=user_report_extra_sections(record),
        )
        cols = st.columns(2)
        with cols[0]:
            render_download(answer_exports.get("pdf"), "PDF: отчет", "application/pdf")
        with cols[1]:
            render_download(answer_exports.get("docx"), "DOCX: отчет", "application/vnd.openxmlformats-officedocument.wordprocessingml.document")
    if run is not None:
        render_soft_heading("Web-отчеты")
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
        archive_dir = Path(run.output_dir) / "user_archives" if getattr(run, "output_dir", None) else answer_output_dir(record) / "archives"
        web_archive = build_web_publications_archive(run, archive_dir / "web_publication_links.zip")
        render_download(web_archive, "ZIP: web-ссылки", "application/zip")

    if orchestration is None:
        return
    local_archive = build_orchestration_local_sources_archive(
        orchestration,
        orchestration_output_dir(record) / "user_archives" / "local_sources.zip",
    )
    if local_archive is not None:
        render_soft_heading("Архив исходных документов")
        render_download(local_archive, "ZIP: локальные статьи и таблицы ([1], [2], ...)", "application/zip")


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
        extra_sections=user_report_extra_sections(record),
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

    tabs = st.tabs(["Отчет", "Источники", "Графики", "Отчеты"])
    with tabs[0]:
        render_soft_heading("Отчет")
        if answer is not None:
            render_report_body(getattr(answer, "text", ""), run)
            render_answer_section_exports(record)
        elif run is not None:
            render_report_body(run_overall_summary(run), run)
        if comparison_answer is not None or run is not None:
            render_soft_heading("Сравнение локальных и web-источников")
            render_comparison_blocks(run, comparison_answer)
        if run is not None and getattr(run, "deep_results", None):
            render_soft_heading("Overall Summary Deep Search")
            render_report_body(run_overall_summary(run), run)

    with tabs[1]:
        render_soft_heading("Web-search: релевантные публикации")
        render_table(source_rows(run), empty_text="Web-источники не найдены.")
        render_web_source_links(run)
        render_soft_heading("Локальный поиск: релевантные публикации")
        render_table(local_rows_from_literature(run), empty_text="Локальные совпадения не найдены.")
        render_local_source_links(run)

    with tabs[2]:
        render_soft_heading("Скорость и стоимость модели")
        cols = st.columns(2)
        cols[0].metric("Время ответа модели", metrics["answer_time"])
        cols[1].metric("Стоимость запроса", metrics["cost"])

        chart_height = 320
        col_a, col_b = st.columns(2)
        years = table_df(year_counts(run)) if run is not None else pd.DataFrame()
        sources = table_df(source_counts(run)) if run is not None else pd.DataFrame()
        with col_a:
            render_soft_heading("Публикации по годам")
            if not years.empty:
                years = years.rename(columns={"year": "Год", "count": "Количество"})
                render_horizontal_bar_chart(years, label_col="Год", value_col="Количество", empty_text="Нет данных по годам публикаций.", height=chart_height)
            else:
                st.info("Нет данных по годам публикаций.")
        with col_b:
            render_soft_heading("Web-источники по базам данных")
            if not sources.empty:
                sources = sources.rename(columns={"source": "База", "count": "Количество"})
                sources["База"] = sources["База"].map(lambda value: SEARCH_SOURCE_LABELS.get(value, value))
                render_horizontal_bar_chart(sources, label_col="База", value_col="Количество", empty_text="Нет данных по базам данных.", height=chart_height)
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
        render_horizontal_bar_chart(coverage, label_col="Тип", value_col="Количество", empty_text="Нет данных по покрытию.", height=chart_height)

    with tabs[3]:
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
    metrics = answer_metrics(record)
    comparison_title = "Экономическое сравнение решений" if request_type == "Бизнес-аналитика" else "Сравнение методик и свойств"

    cols = st.columns(5)
    cols[0].metric("Web sources", len(getattr(run, "results", []) or []))
    cols[1].metric("Local evidence", len(getattr(orchestration, "evidence", []) or []))
    cols[2].metric("Таблицы", len(orchestration_rows(orchestration, "tables")))
    cols[3].metric("Confidence", f"{confidence_text} ({confidence_score:.0%})")
    cols[4].metric("Отчет модели", metrics["answer_time"])

    tabs = st.tabs(["Отчет", comparison_title, "Источники", "Графики", "Отчеты"])
    with tabs[0]:
        render_soft_heading("Отчет")
        if answer is not None:
            render_report_body(getattr(answer, "text", ""), run, orchestration)
            render_answer_section_exports(record)
        elif orchestration is not None:
            render_report_body(orchestration.answer_draft, run, orchestration)
        comparison = record.get("method_comparison")
        if comparison is not None:
            render_soft_heading("Краткий вывод по сравнению")
            render_report_body(comparison.answer_summary, run, orchestration)
            summary_text = method_comparison_summary_text(record)
            if summary_text:
                render_report_body(summary_text, run, orchestration)

    with tabs[1]:
        render_soft_heading(comparison_title)
        render_table(method_comparison_rows(record), empty_text="Методики/экономические варианты не найдены.")
        if request_type == "Бизнес-аналитика":
            render_soft_heading("Технико-экономические показатели" if is_techno_economic_radar(record) else "Рыночные и производственные показатели")
            render_table(market_radar_rows(record), empty_text="Рыночные показатели по запросу не найдены в доступном cache/fixture.")
            radar = record.get("market_radar")
            if radar is not None and getattr(radar, "market_summary", ""):
                render_soft_heading("Краткий вывод Techno-economic Radar" if is_techno_economic_radar(record) else "Краткий вывод Market Radar")
                render_soft_text(getattr(radar, "market_summary", ""))
            elif not should_run_market_radar(record.get("query", "")):
                st.caption(
                    "Market Radar не запускался: запрос выглядит как технико-экономическое сравнение решений, "
                    "а не как запрос по рынку, производству, компаниям или странам."
                )

    with tabs[2]:
        render_soft_heading("Web-search")
        render_table(source_rows(run), empty_text="Web-источники не найдены.")
        render_web_source_links(run)
        render_soft_heading("Локальный RAG, таблицы и граф")
        render_table(orchestration_source_rows(orchestration), empty_text="Локальные источники не найдены.")
        render_orchestration_source_links(orchestration)
        if request_type == "Бизнес-аналитика":
            render_soft_heading("Бизнес-источники")
            render_table(market_source_status_rows(record), empty_text="Market Radar не выбрал бизнес-источники.")
            if record.get("market_radar") is None:
                st.caption("Для текущего запроса используются локальные RAG/Excel/graph evidence; рыночный радар не применим.")
            with st.expander("Доступный registry бизнес-источников", expanded=False):
                render_table(business_source_registry_rows())

    with tabs[3]:
        render_soft_heading("Скорость и стоимость модели")
        metric_cols = st.columns(2)
        metric_cols[0].metric("Время ответа модели", metrics["answer_time"])
        metric_cols[1].metric("Стоимость запроса", metrics["cost"])
        chart_height = 320
        coverage = pd.DataFrame(
            [
                {"Тип": "Raw RAG", "Количество": len(orchestration_rows(orchestration, "raw"))},
                {"Тип": "Summary", "Количество": len(orchestration_rows(orchestration, "summaries"))},
                {"Тип": "Excel/Table", "Количество": len(orchestration_rows(orchestration, "tables"))},
                {"Тип": "Graph", "Количество": len(orchestration_rows(orchestration, "graph"))},
                {"Тип": "Web", "Количество": len(getattr(run, "results", []) or [])},
            ]
        )
        render_soft_heading("Покрытие источников")
        render_horizontal_bar_chart(coverage, label_col="Тип", value_col="Количество", empty_text="Нет данных по покрытию источников.", height=chart_height)
        if run is not None:
            sources = table_df(source_counts(run))
            if not sources.empty:
                render_soft_heading("Web-источники по базам данных")
                sources = sources.rename(columns={"source": "База", "count": "Количество"})
                sources["База"] = sources["База"].map(lambda value: SEARCH_SOURCE_LABELS.get(value, value))
                render_horizontal_bar_chart(sources, label_col="База", value_col="Количество", empty_text="Нет данных по базам данных.", height=chart_height)
        else:
            st.info("Web-поиск не запускался.")
        if request_type == "Бизнес-аналитика":
            market_rows = table_df(market_radar_rows(record))
            if not market_rows.empty:
                if is_techno_economic_radar(record):
                    render_soft_heading("Технико-экономические диапазоны")
                    chart_rows = market_rows[["Технология", "Показатель", "Значение"]].copy()
                    chart_rows["Значение"] = chart_rows["Значение"].astype(str).str.extract(r"(\d+(?:[.,]\d+)?)", expand=False)
                    chart_rows["Значение"] = pd.to_numeric(chart_rows["Значение"].str.replace(",", ".", regex=False), errors="coerce")
                    chart_rows = chart_rows.dropna(subset=["Значение"])
                    if not chart_rows.empty:
                        chart_rows["Серия"] = chart_rows["Технология"] + " / " + chart_rows["Показатель"]
                        render_horizontal_bar_chart(chart_rows, label_col="Серия", value_col="Значение", empty_text="Нет численных технико-экономических диапазонов.", height=360)
                else:
                    render_soft_heading("Производственные / рыночные показатели")
                    chart_rows = market_rows[["Компания / страна", "Показатель", "Значение"]].copy()
                    chart_rows["Значение"] = pd.to_numeric(chart_rows["Значение"], errors="coerce")
                    chart_rows = chart_rows.dropna(subset=["Значение"])
                    if not chart_rows.empty:
                        chart_rows["Серия"] = chart_rows["Компания / страна"] + " / " + chart_rows["Показатель"]
                        render_horizontal_bar_chart(chart_rows, label_col="Серия", value_col="Значение", empty_text="Нет рыночных данных для графика.", height=360)
            share_rows = table_df(market_share_rows(record))
            if not is_techno_economic_radar(record) and not share_rows.empty:
                render_soft_heading("Доли компаний / стран в найденной выборке")
                share_chart = share_rows.copy()
                share_chart["Серия"] = (
                    share_chart["Компания / страна"].astype(str)
                    + " / "
                    + share_chart["Показатель"].astype(str)
                    + " / "
                    + share_chart["Период"].astype(str)
                )
                render_horizontal_bar_chart(share_chart, label_col="Серия", value_col="Доля, %", empty_text="Нет данных по долям.", height=360)
                render_table(market_share_rows(record))
            elif record.get("market_radar") is None:
                st.caption("Рыночные графики не строились: запрос не содержит явного рыночного среза.")

    with tabs[4]:
        render_reports(record)


def execute_query(query: str, options: dict[str, Any]) -> dict[str, Any]:
    request_type = options["request_type"]
    literature_run = None
    orchestration = None
    answer = None
    comparison_answer = None
    method_comparison = None
    market_radar = None
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
        orchestration = run_query_orchestration_compat(
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
            local_top_k=options["local_top_k"],
        )
        literature_run = orchestration.web_run
        method_comparison = build_method_comparison_from_orchestration(
            query,
            orchestration,
            top_k=min(max(options["local_top_k"], 4), 12),
        )
        if request_type == "Бизнес-аналитика" and should_run_market_radar(query):
            market_radar = run_market_radar(query)
        if options["generate_answer"]:
            started_at = time.perf_counter()
            answer_mode = "business" if request_type == "Бизнес-аналитика" else "methods"
            extra_context = market_radar_context({"market_radar": market_radar}) if market_radar is not None else None
            answer = answer_with_provider_router(
                query,
                orchestration,
                project_root=ROOT,
                max_tokens=options["answer_tokens"],
                answer_mode=answer_mode,
                extra_context=extra_context,
            )
            add_elapsed_usage(answer, time.perf_counter() - started_at)
    if request_type == "Литературный поиск":
        method_comparison = None

    return {
        "query": query,
        "request_type": request_type,
        "created_at": datetime.now().strftime("%H:%M:%S"),
        "literature_run": literature_run,
        "orchestration": orchestration,
        "answer": answer,
        "comparison_answer": comparison_answer,
        "method_comparison": method_comparison,
        "market_radar": market_radar,
    }


def render_sidebar() -> dict[str, Any]:
    with st.sidebar:
        st.header("Настройки")
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


def render_app_header() -> None:
    logo_col, text_col = st.columns([0.13, 0.87], vertical_alignment="center")
    with logo_col:
        if METALMIND_EMBLEM_PATH.exists():
            st.image(str(METALMIND_EMBLEM_PATH), width=88)
    with text_col:
        st.markdown(
            """
            <div class="metalmind-title">MetalMind</div>
            <div class="metalmind-subtitle">
                AI-powered search system для материаловедения, металлургии и горного дела
            </div>
            """,
            unsafe_allow_html=True,
        )


def render_request_type_selector() -> str:
    st.session_state.setdefault("request_type", next(iter(REQUEST_TYPES)))
    request_type = st.session_state["request_type"]
    st.markdown(
        """
        <div class="request-type-panel">
            <div class="request-type-eyebrow">Тип запроса</div>
            <div class="request-type-heading">Выберите сценарий анализа перед запуском поиска</div>
        </div>
        """,
        unsafe_allow_html=True,
    )
    card_cols = st.columns(3)
    for col, title in zip(card_cols, REQUEST_TYPES):
        is_active = title == request_type
        with col:
            clicked = st.button(
                title,
                key=f"request_type_card_{safe_report_id(title, prefix='mode')}",
                use_container_width=True,
                type="primary" if is_active else "secondary",
            )
            if clicked and not is_active:
                st.session_state["request_type"] = title
                st.rerun()
    return request_type


def main() -> None:
    page_icon = str(METALMIND_EMBLEM_PATH) if METALMIND_EMBLEM_PATH.exists() else "⚙️"
    st.set_page_config(page_title="MetalMind", page_icon=page_icon, layout="wide")
    st.markdown(
        """
        <style>
        .metalmind-title {
            font-size: 2.45rem;
            font-weight: 760;
            letter-spacing: 0;
            color: #f3f7ff;
            line-height: 1.05;
        }
        .metalmind-subtitle {
            font-size: 1.02rem;
            color: #c8d4e4;
            margin-top: 0.25rem;
        }
        .request-type-panel {
            margin-top: 0.95rem;
            padding: 0.82rem 1rem 0.72rem 1rem;
            border: 1px solid rgba(93, 126, 166, 0.5);
            border-radius: 14px;
            background: linear-gradient(135deg, rgba(24, 38, 61, 0.92), rgba(35, 47, 70, 0.78));
        }
        .request-type-eyebrow {
            color: #50c7ff;
            text-transform: uppercase;
            font-size: 0.74rem;
            font-weight: 760;
            letter-spacing: 0.08em;
        }
        .request-type-heading {
            color: #f3f7ff;
            font-size: 1.18rem;
            font-weight: 680;
            margin-top: 0.15rem;
        }
        div[data-testid="stButton"] > button {
            white-space: normal;
            min-height: 3.25rem;
        }
        div[data-testid="stButton"] > button p {
            text-align: center;
            line-height: 1.25;
            margin: 0;
        }
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
    render_app_header()
    options = render_sidebar()
    options["request_type"] = render_request_type_selector()

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
        with st.status("Запрос выполняется", expanded=True) as status:
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
