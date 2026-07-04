from __future__ import annotations

import csv
import json
import re
import zipfile
from pathlib import Path
from typing import Any
from xml.sax.saxutils import escape

from docx import Document
from docx.shared import Pt
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import cm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle


MOJIBAKE_MARKERS = ("Р", "С", "Ð", "Ñ", "в†", "В°", "Вµ")


def repair_mojibake(value: Any) -> str:
    text = str(value or "")
    if not text or not any(marker in text for marker in MOJIBAKE_MARKERS):
        return text
    try:
        fixed = text.encode("cp1251").decode("utf-8")
    except UnicodeError:
        return text
    if fixed.count("�") > text.count("�"):
        return text
    return fixed


def compact_text(value: Any, max_chars: int | None = None) -> str:
    if isinstance(value, (dict, list)):
        text = json.dumps(value, ensure_ascii=False, default=str)
    else:
        text = repair_mojibake(value)
    text = re.sub(r"\s+", " ", text).strip()
    if max_chars is not None and len(text) > max_chars:
        return text[: max_chars - 3].rstrip() + "..."
    return text


def list_values(value: Any, *, max_chars: int = 180) -> list[str]:
    if value in (None, "", [], {}):
        return []
    values = value if isinstance(value, list) else [value]
    result: list[str] = []
    for item in values:
        text = compact_text(item, max_chars)
        if text:
            result.append(text)
    return result


def unique_limited(values: list[str], limit: int = 8) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for value in values:
        text = compact_text(value, 220)
        key = text.casefold()
        if not text or key in seen:
            continue
        seen.add(key)
        result.append(text)
        if len(result) >= limit:
            break
    return result


def result_link(result: Any) -> str:
    if getattr(result, "url", None):
        return str(result.url)
    if getattr(result, "doi", None):
        doi = str(result.doi).removeprefix("https://doi.org/")
        return f"https://doi.org/{doi}"
    return ""


def display_query(run: Any) -> str:
    plan = getattr(run, "query_plan", {}) or {}
    rewrite = plan.get("llm_rewrite") if isinstance(plan.get("llm_rewrite"), dict) else {}
    return compact_text(
        rewrite.get("corrected_query")
        or plan.get("corrected_query")
        or plan.get("original_query")
        or getattr(getattr(run, "request", None), "query", "")
    )


def source_title(row: dict[str, Any]) -> str:
    return compact_text(row.get("title") or row.get("doc_id") or row.get("source_path") or row.get("local_path") or "Источник", 300)


def source_link(result: Any) -> str:
    link = result_link(result)
    return link or compact_text(getattr(result, "doi", "") or getattr(result, "result_id", ""))


def year_counts(run: Any) -> list[dict[str, Any]]:
    counts: dict[int, int] = {}
    for result in getattr(run, "results", []) or []:
        if getattr(result, "year", None):
            counts[int(result.year)] = counts.get(int(result.year), 0) + 1
    return [{"year": year, "count": counts[year]} for year in sorted(counts)]


def source_counts(run: Any) -> list[dict[str, Any]]:
    counts: dict[str, int] = {}
    for result in getattr(run, "results", []) or []:
        source = compact_text(getattr(result, "source", "unknown"), 80) or "unknown"
        counts[source] = counts.get(source, 0) + 1
    return [{"source": source, "count": count} for source, count in sorted(counts.items())]


def run_overall_summary(run: Any) -> str:
    deep_results = list(getattr(run, "deep_results", []) or [])
    if not deep_results:
        return (
            "Выполнен metadata-only поиск: сформирован ранжированный список источников и ссылок. "
            "Запустите Deep Search, чтобы извлечь краткие summary статей и сравнить методики с локальной базой."
        )

    summaries = [item.document_summary for item in deep_results if getattr(item, "document_summary", None)]
    procedures_count = sum(len(getattr(item, "procedure_summaries", []) or []) for item in deep_results)
    comparison = getattr(run, "comparison", None)
    confirmed = len(getattr(comparison, "confirmed_methods", []) or []) if comparison else 0
    web_only = len(getattr(comparison, "web_only_methods", []) or []) if comparison else 0
    local_only = len(getattr(comparison, "local_only_methods", []) or []) if comparison else 0

    paper_summaries = unique_limited(
        [compact_text(row.get("summary") or row.get("main_topic"), 320) for row in summaries if row],
        limit=4,
    )
    materials = unique_limited([item for row in summaries for item in list_values(row.get("materials"))], limit=8)
    processes = unique_limited(
        [item for row in summaries for item in list_values(row.get("processes") or row.get("methods"))],
        limit=8,
    )
    findings = unique_limited([item for row in summaries for item in list_values(row.get("key_findings"))], limit=5)

    parts = [
        f"Deep Search обработал {len(summaries)} внешних источников и извлек {procedures_count} записей о методиках."
    ]
    if paper_summaries:
        parts.append("Общий вывод по статьям: " + " ".join(paper_summaries))
    if materials:
        parts.append("Основные материалы: " + ", ".join(materials) + ".")
    if processes:
        parts.append("Основные процессы/методики: " + ", ".join(processes) + ".")
    if findings:
        parts.append("Ключевые наблюдения: " + "; ".join(findings) + ".")
    if comparison:
        parts.append(
            "Сравнение с локальной базой: "
            f"подтверждено методик {confirmed}, найдено только во внешней литературе {web_only}, "
            f"только локально {local_only}."
        )
    return " ".join(parts)


def comparison_insights(run: Any) -> str:
    request = getattr(run, "request", None)
    if request is not None and not getattr(request, "generate_comparison_insights", True):
        return ""
    comparison = getattr(run, "comparison", None)
    if comparison is None:
        return "Сравнение локального и web-поиска пока недоступно: нет comparison report."

    years = year_counts(run)
    sources = source_counts(run)
    newest = max((row["year"] for row in years), default=None)
    oldest = min((row["year"] for row in years), default=None)
    top_source = max(sources, key=lambda row: row["count"], default=None)
    confirmed = len(getattr(comparison, "confirmed_methods", []) or [])
    local_only = len(getattr(comparison, "local_only_methods", []) or [])
    web_only = len(getattr(comparison, "web_only_methods", []) or [])
    differing = len(getattr(comparison, "differing_conditions", []) or [])

    parts: list[str] = []
    if oldest and newest:
        parts.append(f"Внешняя выдача покрывает публикации за период {oldest}-{newest}.")
    if top_source:
        parts.append(f"Больше всего публикаций пришло из базы {top_source['source']} ({top_source['count']}).")
    parts.append(
        f"По методикам: подтверждено пересечений {confirmed}, локально уникальных записей {local_only}, "
        f"внешне уникальных записей {web_only}."
    )
    if differing:
        parts.append(f"Найдено {differing} случаев, где методики похожи, но условия или численные диапазоны отличаются.")
    if web_only > local_only:
        parts.append("Внешняя литература расширяет локальную базу и может дать кандидатов для пополнения графа знаний.")
    elif local_only > web_only:
        parts.append("Локальная база содержит больше уникальных методик по запросу; web-поиск полезен для подтверждения и бенчмарка.")
    else:
        parts.append("Локальная и внешняя выдача дают сопоставимый объем уникальных методик.")
    return " ".join(parts)


def build_links_report(run: Any) -> str:
    lines = [
        "# Отчет по релевантным ссылкам",
        "",
        f"Запрос: {compact_text(run.request.query)}",
        f"Поисковая формулировка: {display_query(run)}",
        "",
        "## Web-search",
    ]
    if getattr(run, "results", None):
        for index, result in enumerate(run.results, start=1):
            title = compact_text(result.title, 300)
            link = source_link(result)
            lines.append(f"{index}. [{title}]({link})" if link.startswith("http") else f"{index}. {title} - {link}")
    else:
        lines.append("Внешние публикации не найдены.")

    lines.extend(["", "## Локальный поиск"])
    local_matches = list(getattr(run, "local_matches", []) or [])
    if local_matches:
        for index, row in enumerate(local_matches[:50], start=1):
            lines.append(f"{index}. {source_title(row)}")
    else:
        lines.append("Локальные совпадения не найдены.")
    return "\n".join(lines).strip() + "\n"


def build_deep_report(run: Any) -> str:
    lines = [
        "# Deep Search отчет",
        "",
        f"Запрос: {compact_text(run.request.query)}",
        "",
        "## Общий вывод",
        "",
        run_overall_summary(run),
        "",
        "## Summary по статьям",
    ]
    deep_results = list(getattr(run, "deep_results", []) or [])
    if not deep_results:
        lines.append("Deep Search еще не запускался.")
    for index, item in enumerate(deep_results, start=1):
        summary = item.document_summary or {}
        link = source_link(item.source_result)
        text = compact_text(summary.get("summary") or summary.get("main_topic") or "Summary не извлечен.", 2000)
        lines.extend(["", f"### {index}. {compact_text(item.source_result.title, 260)}", f"Ссылка: {link or 'n/a'}", text])
    return "\n".join(lines).strip() + "\n"


def build_executive_brief_report(run: Any) -> str:
    comparison = getattr(run, "comparison", None)
    findings = [
        f"Web-источников: {len(getattr(run, 'results', []) or [])}.",
        f"Локальных совпадений: {len(getattr(run, 'local_matches', []) or [])}.",
        f"Deep Search summary: {len(getattr(run, 'deep_results', []) or [])}.",
    ]
    if comparison:
        findings.append(
            f"Методики: confirmed={len(comparison.confirmed_methods)}, local-only={len(comparison.local_only_methods)}, "
            f"web-only={len(comparison.web_only_methods)}."
        )
    lines = ["# Краткий управленческий вывод", "", f"Запрос: {compact_text(run.request.query)}", "", "## 5 ключевых выводов"]
    lines.extend(f"- {item}" for item in findings[:5])
    if getattr(run, "results", None):
        lines.extend(["", "## Самые релевантные ссылки"])
        for index, result in enumerate(run.results[:8], start=1):
            lines.append(f"{index}. {compact_text(result.title, 220)} - {source_link(result)}")
    return "\n".join(lines).strip() + "\n"


def build_literature_report(run: Any) -> str:
    lines = [
        "# Полный отчет по поиску литературы",
        "",
        f"Запрос: {compact_text(run.request.query)}",
        f"Поисковая формулировка: {display_query(run)}",
        f"Ключевые слова: {', '.join(compact_text(item, 80) for item in getattr(run, 'keywords', []) or []) or 'n/a'}",
        f"Внешние результаты: {len(getattr(run, 'results', []) or [])}",
        f"Локальные совпадения: {len(getattr(run, 'local_matches', []) or [])}",
        f"Deep Search summaries: {len(getattr(run, 'deep_results', []) or [])}",
        "",
        "## Общий вывод",
        "",
        run_overall_summary(run),
    ]
    insights = comparison_insights(run)
    if insights:
        lines.extend(["", "## Выводы по сравнению локального и web-поиска", "", insights])

    lines.extend(["", "## Локальный поиск"])
    local_matches = list(getattr(run, "local_matches", []) or [])
    if local_matches:
        for index, row in enumerate(local_matches[:50], start=1):
            lines.append(f"{index}. {source_title(row)}")
    else:
        lines.append("Локальные совпадения не найдены.")

    lines.extend(["", "## Web-search"])
    if getattr(run, "results", None):
        for index, result in enumerate(run.results, start=1):
            lines.append(f"{index}. [{compact_text(result.title, 300)}]({source_link(result)})")
    else:
        lines.append("Внешние публикации не найдены.")

    lines.extend(["", "## Графики и распределения", "", "### Публикации по годам"])
    year_rows = year_counts(run)
    lines.extend([f"- {row['year']}: {row['count']}" for row in year_rows] or ["- Нет данных по годам."])
    lines.extend(["", "### Публикации по базам данных"])
    source_rows = source_counts(run)
    lines.extend([f"- {row['source']}: {row['count']}" for row in source_rows] or ["- Нет данных по источникам."])

    if getattr(run, "deep_results", None):
        lines.extend(["", build_deep_report(run).strip()])
    warnings = list(getattr(run, "warnings", []) or [])
    if warnings:
        lines.extend(["", "## Warnings"])
        lines.extend(f"- {compact_text(warning, 500)}" for warning in warnings)
    return "\n".join(lines).strip() + "\n"


def build_full_run_payload(run: Any) -> dict[str, Any]:
    return {
        "request": run.request.model_dump(mode="json"),
        "query_plan": getattr(run, "query_plan", {}) or {},
        "keywords": list(getattr(run, "keywords", []) or []),
        "web_results": [row.model_dump(mode="json") for row in getattr(run, "results", []) or []],
        "local_matches": list(getattr(run, "local_matches", []) or []),
        "deep_results": [row.model_dump(mode="json") for row in getattr(run, "deep_results", []) or []],
        "comparison": run.comparison.model_dump(mode="json") if getattr(run, "comparison", None) else None,
        "charts": {
            "publication_years": year_counts(run),
            "sources": source_counts(run),
            "local_vs_web": [
                {"bucket": "local", "count": len(getattr(run, "local_matches", []) or [])},
                {"bucket": "web", "count": len(getattr(run, "results", []) or [])},
            ],
        },
        "overall_summary": run_overall_summary(run),
        "comparison_insights": comparison_insights(run),
        "warnings": list(getattr(run, "warnings", []) or []),
    }


def register_pdf_font() -> str:
    candidates = [
        Path("C:/Windows/Fonts/arial.ttf"),
        Path("C:/Windows/Fonts/calibri.ttf"),
        Path("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"),
    ]
    for path in candidates:
        if path.exists():
            font_name = path.stem.replace(" ", "_")
            if font_name not in pdfmetrics.getRegisteredFontNames():
                pdfmetrics.registerFont(TTFont(font_name, str(path)))
            return font_name
    return "Helvetica"


def pdf_styles() -> dict[str, ParagraphStyle]:
    font_name = register_pdf_font()
    styles = getSampleStyleSheet()
    styles.add(ParagraphStyle(name="BodyUnicode", parent=styles["BodyText"], fontName=font_name, fontSize=9, leading=12))
    styles.add(ParagraphStyle(name="TitleUnicode", parent=styles["Title"], fontName=font_name, fontSize=16, leading=20))
    styles.add(ParagraphStyle(name="HeadingUnicode", parent=styles["Heading2"], fontName=font_name, fontSize=12, leading=15))
    styles.add(ParagraphStyle(name="SmallUnicode", parent=styles["BodyText"], fontName=font_name, fontSize=8, leading=10))
    return styles


def paragraph(text: Any, style: ParagraphStyle) -> Paragraph:
    return Paragraph(escape(compact_text(text, 4000)) or " ", style)


def link_paragraph(label: str, url: str | None, style: ParagraphStyle) -> Paragraph:
    safe_label = escape(compact_text(label, 400))
    safe_url = escape(str(url or ""))
    if safe_url.startswith(("http://", "https://")):
        return Paragraph(f'<link href="{safe_url}">{safe_label}</link>', style)
    return Paragraph(safe_label, style)


def add_sources_table(story: list[Any], run: Any, styles: dict[str, ParagraphStyle]) -> None:
    story.append(paragraph("Релевантные источники", styles["HeadingUnicode"]))
    table_rows = [["#", "Заголовок", "Ссылка"]]
    for index, result in enumerate((getattr(run, "results", []) or [])[:40], start=1):
        link = source_link(result)
        table_rows.append(
            [
                str(index),
                paragraph(result.title, styles["SmallUnicode"]),
                link_paragraph("Открыть", link, styles["SmallUnicode"]) if link.startswith("http") else paragraph(link, styles["SmallUnicode"]),
            ]
        )
    if len(table_rows) == 1:
        table_rows.append(["-", paragraph("Внешние публикации не найдены", styles["SmallUnicode"]), ""])
    table = Table(table_rows, colWidths=[0.8 * cm, 11.4 * cm, 4.1 * cm], repeatRows=1)
    table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#e8eef7")),
                ("GRID", (0, 0), (-1, -1), 0.25, colors.HexColor("#c8cdd6")),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ]
        )
    )
    story.append(table)


def add_count_table(story: list[Any], title: str, headers: list[str], rows: list[dict[str, Any]], styles: dict[str, ParagraphStyle]) -> None:
    if not rows:
        return
    story.append(Spacer(1, 0.25 * cm))
    story.append(paragraph(title, styles["HeadingUnicode"]))
    table_rows = [headers] + [[compact_text(value, 160) for value in row.values()] for row in rows]
    table = Table(table_rows, colWidths=[8 * cm, 3 * cm], repeatRows=1)
    table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#e8eef7")),
                ("GRID", (0, 0), (-1, -1), 0.25, colors.HexColor("#c8cdd6")),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ]
        )
    )
    story.append(table)


def build_pdf_report(run: Any, output_path: Path, *, mode: str = "full") -> Path:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    styles = pdf_styles()
    story: list[Any] = []
    titles = {
        "full": "Полный отчет по поиску литературы",
        "links": "Отчет по релевантным ссылкам",
        "deep": "Deep Search отчет",
        "brief": "Краткий управленческий вывод",
    }
    story.append(paragraph(titles.get(mode, "Отчет по поиску литературы"), styles["TitleUnicode"]))
    story.append(paragraph(f"Запрос: {run.request.query}", styles["BodyUnicode"]))
    story.append(paragraph(f"Поисковая формулировка: {display_query(run)}", styles["BodyUnicode"]))

    if mode in {"full", "brief", "deep"}:
        story.append(Spacer(1, 0.25 * cm))
        story.append(paragraph("Общий вывод", styles["HeadingUnicode"]))
        story.append(paragraph(run_overall_summary(run), styles["BodyUnicode"]))
    if mode == "full":
        insights = comparison_insights(run)
        if insights:
            story.append(paragraph("Сравнение локального и web-поиска", styles["HeadingUnicode"]))
            story.append(paragraph(insights, styles["BodyUnicode"]))
    if mode in {"full", "links", "brief"}:
        story.append(Spacer(1, 0.25 * cm))
        add_sources_table(story, run, styles)
    if mode == "full":
        add_count_table(story, "Публикации по годам", ["Год", "Количество"], year_counts(run), styles)
        add_count_table(story, "Публикации по базам данных", ["База", "Количество"], source_counts(run), styles)
    if mode in {"full", "deep"} and getattr(run, "deep_results", None):
        story.append(Spacer(1, 0.4 * cm))
        story.append(paragraph("Deep Search summaries", styles["HeadingUnicode"]))
        for item in run.deep_results:
            summary = item.document_summary or {}
            story.append(link_paragraph(item.source_result.title, source_link(item.source_result), styles["BodyUnicode"]))
            story.append(paragraph(summary.get("summary") or summary.get("main_topic") or "Summary не извлечен.", styles["SmallUnicode"]))

    doc = SimpleDocTemplate(str(output_path), pagesize=A4, rightMargin=1.2 * cm, leftMargin=1.2 * cm, topMargin=1.2 * cm, bottomMargin=1.2 * cm)
    doc.build(story)
    return output_path


def set_docx_style(document: Document) -> None:
    style = document.styles["Normal"]
    style.font.name = "Arial"
    style.font.size = Pt(10)


def add_docx_table(document: Document, headers: list[str], rows: list[list[str]]) -> None:
    table = document.add_table(rows=1, cols=len(headers))
    table.style = "Table Grid"
    for index, header in enumerate(headers):
        table.rows[0].cells[index].text = header
    for row in rows:
        cells = table.add_row().cells
        for index, value in enumerate(row):
            cells[index].text = compact_text(value, 1200)


def build_docx_report(run: Any, output_path: Path, *, mode: str = "full") -> Path:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    document = Document()
    set_docx_style(document)
    titles = {
        "full": "Полный отчет по поиску литературы",
        "links": "Отчет по релевантным ссылкам",
        "deep": "Deep Search отчет",
        "brief": "Краткий управленческий вывод",
    }
    document.add_heading(titles.get(mode, "Отчет по поиску литературы"), level=1)
    document.add_paragraph(f"Запрос: {compact_text(run.request.query)}")
    document.add_paragraph(f"Поисковая формулировка: {display_query(run)}")

    if mode in {"full", "brief", "deep"}:
        document.add_heading("Общий вывод", level=2)
        document.add_paragraph(run_overall_summary(run))
    if mode == "full":
        insights = comparison_insights(run)
        if insights:
            document.add_heading("Сравнение локального и web-поиска", level=2)
            document.add_paragraph(insights)
    if mode in {"full", "links", "brief"}:
        document.add_heading("Релевантные ссылки", level=2)
        add_docx_table(
            document,
            ["#", "Заголовок", "Ссылка"],
            [[str(index), result.title, source_link(result)] for index, result in enumerate(getattr(run, "results", []) or [], start=1)],
        )
    if mode == "full":
        document.add_heading("Локальный поиск", level=2)
        add_docx_table(
            document,
            ["#", "Источник"],
            [[str(index), source_title(row)] for index, row in enumerate((getattr(run, "local_matches", []) or [])[:50], start=1)],
        )
        document.add_heading("Публикации по годам", level=2)
        add_docx_table(document, ["Год", "Количество"], [[str(row["year"]), str(row["count"])] for row in year_counts(run)])
        document.add_heading("Публикации по базам данных", level=2)
        add_docx_table(document, ["База", "Количество"], [[str(row["source"]), str(row["count"])] for row in source_counts(run)])
    if mode in {"full", "deep"} and getattr(run, "deep_results", None):
        document.add_heading("Deep Search summaries", level=2)
        for index, item in enumerate(run.deep_results, start=1):
            summary = item.document_summary or {}
            document.add_heading(f"{index}. {compact_text(item.source_result.title, 180)}", level=3)
            document.add_paragraph(f"Ссылка: {source_link(item.source_result) or 'n/a'}")
            document.add_paragraph(compact_text(summary.get("summary") or summary.get("main_topic") or "Summary не извлечен.", 2200))

    document.save(output_path)
    return output_path


def write_text_report(path: Path, text: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


def write_json_report(path: Path, payload: dict[str, Any]) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    return path


def write_links_csv(run: Any, output_path: Path) -> Path:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["#", "title", "year", "source", "link"])
        for index, result in enumerate(getattr(run, "results", []) or [], start=1):
            writer.writerow([index, compact_text(result.title, 500), result.year or "", result.source, source_link(result)])
    return output_path


def build_run_archive(run: Any, output_path: Path) -> Path:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    run_dir = Path(getattr(run, "output_dir", "") or output_path.parent)
    links_csv = write_links_csv(run, run_dir / "links.csv")
    candidate_paths: list[Path] = [
        run_dir / "request.json",
        run_dir / "query_plan.json",
        run_dir / "keywords.json",
        run_dir / "metadata_results.jsonl",
        run_dir / "local_matches.jsonl",
        run_dir / "resource_links.jsonl",
        run_dir / "comparison_report.json",
        run_dir / "literature_report.md",
        run_dir / "literature_links_report.md",
        run_dir / "deep_search_report.md",
        run_dir / "executive_brief.md",
        run_dir / "full_run.json",
        run_dir / "web_document_summaries.jsonl",
        run_dir / "web_procedure_summaries.jsonl",
        run_dir / "deep_search_results.jsonl",
        links_csv,
    ]
    for attr in (
        "report_pdf_path",
        "report_docx_path",
        "links_report_pdf_path",
        "links_report_docx_path",
        "deep_report_pdf_path",
        "deep_report_docx_path",
        "executive_brief_pdf_path",
        "executive_brief_docx_path",
    ):
        value = getattr(run, attr, None)
        if value:
            candidate_paths.append(Path(value))
    seen: set[Path] = set()
    with zipfile.ZipFile(output_path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        for path in candidate_paths:
            if not path or not path.exists() or path in seen:
                continue
            seen.add(path)
            try:
                arcname = path.relative_to(run_dir)
            except ValueError:
                arcname = Path(path.name)
            zf.write(path, arcname=str(arcname))
    return output_path
