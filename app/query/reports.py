from __future__ import annotations

import json
import re
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

from app.query import cockpit


def compact_text(value: Any, max_chars: int | None = None) -> str:
    text = re.sub(r"\s+", " ", str(value or "")).strip()
    if max_chars is not None and len(text) > max_chars:
        return text[: max_chars - 3].rstrip() + "..."
    return text


def result_link(result: Any) -> str:
    if getattr(result, "url", None):
        return str(result.url)
    if getattr(result, "doi", None):
        return f"https://doi.org/{result.doi}"
    return ""


def display_query(run: Any) -> str:
    plan = getattr(run, "query_plan", {}) or {}
    return str(plan.get("original_query") or plan.get("corrected_query") or getattr(getattr(run, "request", None), "query", ""))


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


def paragraph(text: Any, style: ParagraphStyle) -> Paragraph:
    escaped = escape(compact_text(text, 4000)).replace("\n", "<br/>")
    return Paragraph(escaped or " ", style)


def link_paragraph(label: str, url: str | None, style: ParagraphStyle) -> Paragraph:
    safe_label = escape(compact_text(label, 500))
    safe_url = escape(str(url or ""))
    if safe_url.startswith(("http://", "https://")):
        return Paragraph(f'<link href="{safe_url}">{safe_label}</link>', style)
    return Paragraph(safe_label, style)


def list_values(value: Any) -> list[str]:
    if isinstance(value, list):
        return [compact_text(item, 160) for item in value if compact_text(item, 160)]
    text = compact_text(value, 160)
    return [text] if text else []


def unique_limited(values: list[str], limit: int = 8) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for value in values:
        key = value.lower()
        if key in seen:
            continue
        seen.add(key)
        result.append(value)
        if len(result) >= limit:
            break
    return result


def year_counts(run: Any) -> list[dict[str, Any]]:
    counts: dict[int, int] = {}
    for result in run.results:
        if result.year:
            counts[int(result.year)] = counts.get(int(result.year), 0) + 1
    return [{"year": year, "count": counts[year]} for year in sorted(counts)]


def source_counts(run: Any) -> list[dict[str, Any]]:
    counts: dict[str, int] = {}
    for result in run.results:
        counts[result.source] = counts.get(result.source, 0) + 1
    return [{"source": source, "count": count} for source, count in sorted(counts.items())]


def run_overall_summary(run: Any) -> str:
    if not run.deep_results:
        return (
            "Выполнен metadata-only поиск: сформирован ранжированный список публикаций. "
            "Запустите Deep Search, чтобы получить summary статей и сравнение методик."
        )
    summaries = [item.document_summary for item in run.deep_results if item.document_summary]
    procedures = sum(len(item.procedure_summaries) for item in run.deep_results)
    confirmed = len(run.comparison.confirmed_methods) if run.comparison else 0
    web_only = len(run.comparison.web_only_methods) if run.comparison else 0
    local_only = len(run.comparison.local_only_methods) if run.comparison else 0

    paper_summaries = unique_limited(
        [compact_text(row.get("summary") or row.get("main_topic"), 280) for row in summaries if row],
        limit=4,
    )
    materials = unique_limited([item for row in summaries for item in list_values(row.get("materials"))], limit=8)
    processes = unique_limited([item for row in summaries for item in list_values(row.get("processes") or row.get("methods"))], limit=8)
    findings = unique_limited([item for row in summaries for item in list_values(row.get("key_findings"))], limit=5)

    parts = [f"Deep Search обработал {len(summaries)} внешних источников и извлек {procedures} записей о методиках."]
    if paper_summaries:
        parts.append("Общий вывод по статьям: " + " ".join(paper_summaries))
    if materials:
        parts.append("Основные материалы: " + ", ".join(materials) + ".")
    if processes:
        parts.append("Основные процессы/методики: " + ", ".join(processes) + ".")
    if findings:
        parts.append("Ключевые наблюдения: " + "; ".join(findings) + ".")
    parts.append(
        f"Сравнение с локальной базой: подтверждено методик {confirmed}, найдено только во внешней литературе {web_only}, только локально {local_only}."
    )
    return " ".join(parts)


def comparison_insights(run: Any) -> str:
    if not getattr(run.request, "generate_comparison_insights", True):
        return ""
    if not run.comparison:
        return "Сравнение локального и внешнего поиска пока недоступно: нет comparison report."

    years = year_counts(run)
    sources = source_counts(run)
    newest = max((row["year"] for row in years), default=None)
    oldest = min((row["year"] for row in years), default=None)
    top_source = max(sources, key=lambda row: row["count"], default=None)
    confirmed = len(run.comparison.confirmed_methods)
    local_only = len(run.comparison.local_only_methods)
    web_only = len(run.comparison.web_only_methods)
    differing = len(run.comparison.differing_conditions)

    parts = []
    if oldest and newest:
        parts.append(f"Внешняя выдача покрывает публикации за период {oldest}-{newest}.")
    if top_source:
        parts.append(f"Больше всего публикаций пришло из базы {top_source['source']} ({top_source['count']}).")
    parts.append(
        f"По методикам: подтверждено пересечений {confirmed}, локально уникальных записей {local_only}, внешне уникальных записей {web_only}."
    )
    if differing:
        parts.append(f"Найдено {differing} случаев, где методики похожи, но условия/диапазоны отличаются.")
    if web_only > local_only:
        parts.append("Внешняя литература расширяет локальную базу: стоит использовать web findings как кандидатов на пополнение графа.")
    elif local_only > web_only:
        parts.append("Локальная база содержит больше уникальных методик по запросу; внешние источники полезны в основном для подтверждения.")
    else:
        parts.append("Локальная и внешняя выдача дают сопоставимый объем уникальных методик.")
    return " ".join(parts)


def build_links_report(run: Any) -> str:
    lines = [
        "# Отчет по релевантным ссылкам",
        "",
        f"Запрос: {run.request.query}",
        f"Переформулированный запрос: {display_query(run)}",
        "",
        "## Web-search",
    ]
    if run.results:
        for index, result in enumerate(run.results, start=1):
            lines.append(f"{index}. [{result.title}]({result_link(result)})")
    else:
        lines.append("Внешние публикации не найдены.")
    lines.extend(["", "## Локальный поиск"])
    if run.local_matches:
        for index, row in enumerate(run.local_matches[:30], start=1):
            title = compact_text(row.get("title") or row.get("doc_id") or row.get("source_path"), 240)
            lines.append(f"{index}. {title}")
    else:
        lines.append("Локальные совпадения не найдены.")
    return "\n".join(lines).strip() + "\n"


def build_deep_report(run: Any) -> str:
    lines = [
        "# Deep Search отчет",
        "",
        f"Запрос: {run.request.query}",
        "",
        "## Общий вывод",
        "",
        run_overall_summary(run),
        "",
        "## Summary по статьям",
    ]
    if not run.deep_results:
        lines.append("Deep Search не запускался.")
    for index, item in enumerate(run.deep_results, start=1):
        summary = item.document_summary or {}
        link = result_link(item.source_result)
        lines.extend(
            [
                "",
                f"### {index}. {item.source_result.title}",
                f"Ссылка: {link or 'n/a'}",
                compact_text(summary.get("summary") or summary.get("main_topic") or "Summary не извлечен.", 1500),
            ]
        )
    return "\n".join(lines).strip() + "\n"


def build_executive_brief_report(run: Any) -> str:
    return cockpit.executive_brief_markdown(run)


def build_literature_report(run: Any) -> str:
    lines = [
        "# Полный отчет по поиску литературы",
        "",
        f"Запрос: {run.request.query}",
        f"Переформулированный запрос: {display_query(run)}",
        f"Ключевые слова: {', '.join(run.keywords) if run.keywords else 'n/a'}",
        f"Внешние результаты: {len(run.results)}",
        f"Локальные совпадения: {len(run.local_matches)}",
        f"Deep Search summaries: {len(run.deep_results)}",
        "",
        "## Общий вывод",
        "",
        run_overall_summary(run),
    ]
    lines.extend(["", "## Демо cockpit", "", "### Разбор запроса"])
    for row in cockpit.query_decomposition(run):
        values = ", ".join(row.get("values") or []) or "n/a"
        lines.append(f"- {row['slot']}: {values}")
    lines.extend(["", "### Local vs web coverage"])
    for row in cockpit.local_vs_web_metrics(run):
        lines.append(f"- {row['metric']}: local={row['local']}, web={row['web']} - {row['interpretation']}")
    lines.extend(["", "### Local vs World Dashboard"])
    for row in cockpit.local_vs_world_dashboard(run):
        lines.append(
            f"- {row['side']}: sources={row['sources']}, methods={row['top_methods']}, ranges={row['numeric_ranges']}, "
            f"years={row['years']}, confidence={row['confidence']}"
        )
    lines.extend(["", "### Gap radar"])
    for row in cockpit.gap_radar_rows(run):
        lines.append(f"- {row['signal']}: {row['value']} ({row['level']}) - {row['recommendation']}")
    lines.extend(["", "### Contradiction & Consensus"])
    for row in cockpit.consensus_panel_rows(run):
        lines.append(f"- {row['bucket']}: {row['count']} - {row['action']}")
    lines.extend(["", "### Evidence highlights"])
    for row in cockpit.evidence_cards(run)[:8]:
        lines.append(f"- {row['kind']}: {compact_text(row['title'], 160)}; confidence={row['confidence']}; link={row['link']}")

    insights = comparison_insights(run)
    if insights:
        lines.extend(["", "## Выводы по сравнению локального и web-поиска", "", insights])

    lines.extend(["", "## Локальный поиск"])
    if run.local_matches:
        for index, row in enumerate(run.local_matches[:30], start=1):
            title = compact_text(row.get("title") or row.get("doc_id") or row.get("source_path"), 240)
            lines.append(f"{index}. {title}")
    else:
        lines.append("Локальные совпадения не найдены.")

    lines.extend(["", "## Web-search"])
    if run.results:
        for index, result in enumerate(run.results, start=1):
            lines.append(f"{index}. [{result.title}]({result_link(result)})")
    else:
        lines.append("Внешние публикации не найдены.")

    lines.extend(["", "## Графики и распределения", "", "### По годам"])
    for row in year_counts(run):
        lines.append(f"- {row['year']}: {row['count']}")
    lines.extend(["", "### По базам данных"])
    for row in source_counts(run):
        lines.append(f"- {row['source']}: {row['count']}")

    if run.deep_results:
        lines.extend(["", build_deep_report(run).strip()])
    if run.warnings:
        lines.extend(["", "## Warnings"])
        lines.extend(f"- {warning}" for warning in run.warnings)
    return "\n".join(lines).strip() + "\n"


def build_full_run_payload(run: Any) -> dict[str, Any]:
    return {
        "request": run.request.model_dump(mode="json"),
        "query_plan": run.query_plan,
        "keywords": run.keywords,
        "web_results": [row.model_dump(mode="json") for row in run.results],
        "local_matches": run.local_matches,
        "deep_results": [row.model_dump(mode="json") for row in run.deep_results],
        "comparison": run.comparison.model_dump(mode="json") if run.comparison else None,
        "charts": {
            "publication_years": year_counts(run),
            "sources": source_counts(run),
            "local_vs_web": [
                {"bucket": "local", "count": len(run.local_matches)},
                {"bucket": "web", "count": len(run.results)},
            ],
        },
        "cockpit": {
            "query_decomposition": cockpit.query_decomposition(run),
            "local_vs_web_metrics": cockpit.local_vs_web_metrics(run),
            "local_vs_world_dashboard": cockpit.local_vs_world_dashboard(run),
            "method_matrix": cockpit.method_matrix_rows(run),
            "method_heatmap": cockpit.method_heatmap_rows(run),
            "consensus_panel": cockpit.consensus_panel_rows(run),
            "evidence_cards": cockpit.evidence_cards(run),
            "numeric_intervals": cockpit.numeric_interval_rows(run),
            "mini_graph_edges": cockpit.mini_graph_edges(run),
            "gap_radar": cockpit.gap_radar_rows(run),
            "executive_brief_markdown": cockpit.executive_brief_markdown(run),
        },
        "comparison_insights": comparison_insights(run),
        "warnings": run.warnings,
    }


def pdf_styles() -> tuple[str, dict[str, ParagraphStyle]]:
    font_name = register_pdf_font()
    styles = getSampleStyleSheet()
    styles.add(ParagraphStyle(name="BodyUnicode", parent=styles["BodyText"], fontName=font_name, fontSize=9, leading=12))
    styles.add(ParagraphStyle(name="TitleUnicode", parent=styles["Title"], fontName=font_name, fontSize=16, leading=20))
    styles.add(ParagraphStyle(name="HeadingUnicode", parent=styles["Heading2"], fontName=font_name, fontSize=12, leading=15))
    styles.add(ParagraphStyle(name="SmallUnicode", parent=styles["BodyText"], fontName=font_name, fontSize=8, leading=10))
    return font_name, styles


def add_sources_table(story: list[Any], run: Any, styles: dict[str, ParagraphStyle]) -> None:
    story.append(paragraph("Релевантные источники", styles["HeadingUnicode"]))
    table_rows = [["#", "Title", "Link"]]
    for index, result in enumerate(run.results[:30], start=1):
        link = result_link(result)
        table_rows.append(
            [
                str(index),
                paragraph(result.title, styles["SmallUnicode"]),
                link_paragraph("Открыть", link, styles["SmallUnicode"]) if link else "",
            ]
        )
    table = Table(table_rows, colWidths=[0.8 * cm, 12.2 * cm, 3.5 * cm], repeatRows=1)
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
    table_rows = [headers] + [[str(value) for value in row.values()] for row in rows]
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
    _, styles = pdf_styles()
    story: list[Any] = []
    title = {
        "full": "Полный отчет по поиску литературы",
        "links": "Отчет по релевантным ссылкам",
        "deep": "Deep Search отчет",
        "brief": "Краткий управленческий вывод",
    }.get(mode, "Отчет по поиску литературы")
    story.append(paragraph(title, styles["TitleUnicode"]))
    story.append(paragraph(f"Запрос: {run.request.query}", styles["BodyUnicode"]))
    story.append(paragraph(f"Переформулированный запрос: {display_query(run)}", styles["BodyUnicode"]))

    if mode == "brief":
        brief_text = re.sub(r"^# .+\n\n?", "", cockpit.executive_brief_markdown(run), count=1)
        story.append(Spacer(1, 0.25 * cm))
        story.append(paragraph(brief_text, styles["BodyUnicode"]))
        if run.results:
            add_sources_table(story, run, styles)
        doc = SimpleDocTemplate(str(output_path), pagesize=A4, rightMargin=1.2 * cm, leftMargin=1.2 * cm, topMargin=1.2 * cm, bottomMargin=1.2 * cm)
        doc.build(story)
        return output_path

    if mode in {"full", "deep"}:
        story.append(paragraph("Общий вывод", styles["HeadingUnicode"]))
        story.append(paragraph(run_overall_summary(run), styles["BodyUnicode"]))
        insights = comparison_insights(run)
        if mode == "full" and insights:
            story.append(paragraph("Выводы по сравнению", styles["HeadingUnicode"]))
            story.append(paragraph(insights, styles["BodyUnicode"]))

    if mode in {"full", "links"}:
        add_sources_table(story, run, styles)
    if mode == "full":
        add_count_table(story, "Публикации по годам", ["Year", "Count"], year_counts(run), styles)
        add_count_table(story, "Публикации по базам данных", ["Source", "Count"], source_counts(run), styles)
    if mode in {"full", "deep"} and run.deep_results:
        story.append(Spacer(1, 0.4 * cm))
        story.append(paragraph("Deep Search summaries", styles["HeadingUnicode"]))
        for item in run.deep_results:
            summary = item.document_summary or {}
            story.append(link_paragraph(item.source_result.title, result_link(item.source_result), styles["BodyUnicode"]))
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


def add_markdownish_docx(document: Document, text: str) -> None:
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        if line.startswith("## "):
            document.add_heading(line[3:], level=2)
        elif line.startswith("# "):
            document.add_heading(line[2:], level=1)
        elif line.startswith("- "):
            document.add_paragraph(line[2:], style="List Bullet")
        elif re.match(r"^\d+\.\s", line):
            document.add_paragraph(line, style="List Number")
        else:
            document.add_paragraph(line)


def build_docx_report(run: Any, output_path: Path, *, mode: str = "full") -> Path:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    document = Document()
    set_docx_style(document)
    document.add_heading(
        {
            "full": "Полный отчет по поиску литературы",
            "links": "Отчет по релевантным ссылкам",
            "deep": "Deep Search отчет",
            "brief": "Краткий управленческий вывод",
        }.get(mode, "Отчет по поиску литературы"),
        level=1,
    )
    document.add_paragraph(f"Запрос: {run.request.query}")
    document.add_paragraph(f"Переформулированный запрос: {display_query(run)}")

    if mode == "brief":
        brief_text = re.sub(r"^# .+\n\n?", "", cockpit.executive_brief_markdown(run), count=1)
        add_markdownish_docx(document, brief_text)
        if run.results:
            document.add_heading("Релевантные ссылки", level=2)
            add_docx_table(
                document,
                ["#", "Заголовок", "Ссылка"],
                [[str(index), result.title, result_link(result)] for index, result in enumerate(run.results[:30], start=1)],
            )
        document.save(output_path)
        return output_path

    if mode in {"full", "deep"}:
        document.add_heading("Общий вывод", level=2)
        document.add_paragraph(run_overall_summary(run))
        insights = comparison_insights(run)
        if mode == "full" and insights:
            document.add_heading("Выводы по сравнению локального и web-поиска", level=2)
            document.add_paragraph(insights)

    if mode in {"full", "links"}:
        document.add_heading("Web-search", level=2)
        add_docx_table(
            document,
            ["#", "Заголовок", "Ссылка"],
            [[str(index), result.title, result_link(result)] for index, result in enumerate(run.results, start=1)],
        )
    if mode == "full":
        document.add_heading("Локальный поиск", level=2)
        local_rows = [
            [str(index), compact_text(row.get("title") or row.get("doc_id") or row.get("source_path"), 600)]
            for index, row in enumerate(run.local_matches[:50], start=1)
        ]
        add_docx_table(document, ["#", "Источник"], local_rows)
        document.add_heading("Публикации по годам", level=2)
        add_docx_table(document, ["Year", "Count"], [[str(row["year"]), str(row["count"])] for row in year_counts(run)])
        document.add_heading("Публикации по базам данных", level=2)
        add_docx_table(document, ["Source", "Count"], [[str(row["source"]), str(row["count"])] for row in source_counts(run)])

    if mode in {"full", "deep"} and run.deep_results:
        document.add_heading("Deep Search summaries", level=2)
        for index, item in enumerate(run.deep_results, start=1):
            summary = item.document_summary or {}
            document.add_heading(f"{index}. {item.source_result.title}", level=3)
            document.add_paragraph(f"Ссылка: {result_link(item.source_result) or 'n/a'}")
            document.add_paragraph(compact_text(summary.get("summary") or summary.get("main_topic") or "Summary не извлечен.", 2000))

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
