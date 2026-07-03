from __future__ import annotations

import re
from pathlib import Path
from typing import Any
from xml.sax.saxutils import escape

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import cm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle


def compact_text(value: Any, max_chars: int | None = None) -> str:
    text = re.sub(r"\s+", " ", str(value or "")).strip()
    if max_chars is not None and len(text) > max_chars:
        return text[: max_chars - 3].rstrip() + "..."
    return text


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
    escaped = escape(compact_text(text, 3000)).replace("\n", "<br/>")
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


def run_overall_summary(run: Any) -> str:
    if not run.deep_results:
        return "Выполнен metadata-only поиск: сформирован ранжированный список публикаций. Включите Deep Search, чтобы получить summary статей и сравнение методик."
    summaries = [item.document_summary for item in run.deep_results if item.document_summary]
    procedures = sum(len(item.procedure_summaries) for item in run.deep_results)
    confirmed = len(run.comparison.confirmed_methods) if run.comparison else 0
    web_only = len(run.comparison.web_only_methods) if run.comparison else 0
    local_only = len(run.comparison.local_only_methods) if run.comparison else 0

    paper_summaries = unique_limited(
        [compact_text(row.get("summary") or row.get("main_topic"), 260) for row in summaries if row],
        limit=4,
    )
    materials = unique_limited([item for row in summaries for item in list_values(row.get("materials"))], limit=8)
    processes = unique_limited([item for row in summaries for item in list_values(row.get("processes") or row.get("methods"))], limit=8)
    findings = unique_limited([item for row in summaries for item in list_values(row.get("key_findings"))], limit=5)

    parts = [
        f"Deep Search обработал {len(summaries)} внешних источников и извлек {procedures} записей о методиках.",
    ]
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


def build_pdf_report(run: Any, output_path: Path) -> Path:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    font_name = register_pdf_font()
    styles = getSampleStyleSheet()
    styles.add(ParagraphStyle(name="BodyUnicode", parent=styles["BodyText"], fontName=font_name, fontSize=9, leading=12))
    styles.add(ParagraphStyle(name="TitleUnicode", parent=styles["Title"], fontName=font_name, fontSize=16, leading=20))
    styles.add(ParagraphStyle(name="HeadingUnicode", parent=styles["Heading2"], fontName=font_name, fontSize=12, leading=15))
    styles.add(ParagraphStyle(name="SmallUnicode", parent=styles["BodyText"], fontName=font_name, fontSize=8, leading=10))

    story: list[Any] = []
    story.append(paragraph("Literature Search Report", styles["TitleUnicode"]))
    story.append(paragraph(f"Query: {run.request.query}", styles["BodyUnicode"]))
    if run.query_plan:
        story.append(paragraph(f"Corrected query: {run.query_plan.get('corrected_query')}", styles["BodyUnicode"]))
        story.append(paragraph("Search variants: " + "; ".join(run.query_plan.get("search_queries") or []), styles["SmallUnicode"]))
    story.append(paragraph("Overall Summary", styles["HeadingUnicode"]))
    story.append(paragraph(run_overall_summary(run), styles["BodyUnicode"]))
    story.append(Spacer(1, 0.3 * cm))

    story.append(paragraph("Relevant Sources", styles["HeadingUnicode"]))
    table_rows = [["#", "Title", "Year", "Q", "Source", "Link"]]
    for index, result in enumerate(run.results[:20], start=1):
        quartile = result.raw.get("journal_quartile", "") if result.raw else ""
        table_rows.append(
            [
                str(index),
                paragraph(result.title, styles["SmallUnicode"]),
                str(result.year or ""),
                str(quartile or ""),
                result.source,
                link_paragraph(result.doi or str(result.url or ""), str(result.url) if result.url else None, styles["SmallUnicode"]),
            ]
        )
    table = Table(table_rows, colWidths=[0.8 * cm, 7.4 * cm, 1.3 * cm, 0.8 * cm, 2.4 * cm, 5 * cm], repeatRows=1)
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

    if getattr(run, "resource_links", None):
        story.append(Spacer(1, 0.4 * cm))
        story.append(paragraph("Recommended Resource Search Links", styles["HeadingUnicode"]))
        link_rows = [["Resource", "Category", "Query", "Link"]]
        for row in run.resource_links[:30]:
            link_rows.append(
                [
                    paragraph(str(row.get("name") or ""), styles["SmallUnicode"]),
                    paragraph(str(row.get("category") or ""), styles["SmallUnicode"]),
                    paragraph(str(row.get("query") or row.get("note") or ""), styles["SmallUnicode"]),
                    link_paragraph(str(row.get("url") or ""), str(row.get("url") or ""), styles["SmallUnicode"]),
                ]
            )
        links_table = Table(link_rows, colWidths=[3.2 * cm, 2.5 * cm, 6.5 * cm, 5 * cm], repeatRows=1)
        links_table.setStyle(
            TableStyle(
                [
                    ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#e8eef7")),
                    ("GRID", (0, 0), (-1, -1), 0.25, colors.HexColor("#c8cdd6")),
                    ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ]
            )
        )
        story.append(links_table)

    if run.deep_results:
        story.append(Spacer(1, 0.4 * cm))
        story.append(paragraph("Deep Search Summaries", styles["HeadingUnicode"]))
        for item in run.deep_results:
            summary = item.document_summary or {}
            story.append(link_paragraph(item.source_result.title, str(item.source_result.url) if item.source_result.url else None, styles["BodyUnicode"]))
            story.append(paragraph(summary.get("summary") or summary.get("main_topic") or "No summary extracted.", styles["SmallUnicode"]))
            if item.procedure_summaries:
                methods = []
                for proc in item.procedure_summaries[:5]:
                    methods.append(compact_text(proc.get("synthesis_or_process_method") or proc.get("synthesis_method") or proc.get("key_points"), 240))
                story.append(paragraph("Methods: " + "; ".join(method for method in methods if method), styles["SmallUnicode"]))

    if run.comparison:
        story.append(Spacer(1, 0.4 * cm))
        story.append(paragraph("Comparison Summary", styles["HeadingUnicode"]))
        story.append(paragraph(f"Confirmed methods: {len(run.comparison.confirmed_methods)}", styles["BodyUnicode"]))
        story.append(paragraph(f"Local-only methods: {len(run.comparison.local_only_methods)}", styles["BodyUnicode"]))
        story.append(paragraph(f"Web-only methods: {len(run.comparison.web_only_methods)}", styles["BodyUnicode"]))
        for gap in run.comparison.gaps[:10]:
            story.append(paragraph("- " + gap, styles["SmallUnicode"]))

    doc = SimpleDocTemplate(str(output_path), pagesize=A4, rightMargin=1.2 * cm, leftMargin=1.2 * cm, topMargin=1.2 * cm, bottomMargin=1.2 * cm)
    doc.build(story)
    return output_path
