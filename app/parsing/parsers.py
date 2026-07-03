from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import fitz
import pandas as pd
from docx import Document as DocxDocument
from pptx import Presentation


@dataclass
class ParsedTable:
    table_id: str
    page_or_sheet: str
    rows: list[list[str]]
    text: str


@dataclass
class ParsedDocument:
    local_path: str
    parser: str
    status: str
    title: str = ""
    text: str = ""
    page_count: int = 0
    tables: list[ParsedTable] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)


def file_sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def parse_document(path: Path) -> ParsedDocument:
    suffix = path.suffix.lower()
    try:
        if suffix == ".pdf":
            return parse_pdf(path)
        if suffix in {".docx", ".docm"}:
            return parse_docx(path)
        if suffix == ".pptx":
            return parse_pptx(path)
        if suffix == ".xlsx":
            return parse_spreadsheet(path)
        if suffix == ".xls":
            return ParsedDocument(
                str(path),
                "unsupported",
                "unsupported",
                errors=["legacy .xls parsing disabled for MVP; convert to .xlsx or add a sandboxed extractor"],
            )
        if suffix == ".txt":
            return ParsedDocument(str(path), "text", "ok", text=path.read_text(encoding="utf-8", errors="replace"))
        return ParsedDocument(str(path), "unsupported", "unsupported", errors=[f"unsupported extension: {suffix}"])
    except Exception as exc:  # noqa: BLE001
        return ParsedDocument(str(path), parser=suffix.lstrip(".") or "unknown", status="failed", errors=[str(exc)])


def parse_pdf(path: Path) -> ParsedDocument:
    doc = fitz.open(path)
    pages: list[str] = []
    metadata = {key: value for key, value in (doc.metadata or {}).items() if value}
    for i, page in enumerate(doc, start=1):
        text = page.get_text("text") or ""
        if text.strip():
            pages.append(f"\n\n--- PAGE {i} ---\n{text.strip()}")
    return ParsedDocument(
        local_path=str(path),
        parser="pymupdf",
        status="ok" if pages else "empty",
        title=metadata.get("title", "") or path.stem,
        text="\n".join(pages),
        page_count=doc.page_count,
        metadata=metadata,
    )


def parse_docx(path: Path) -> ParsedDocument:
    doc = DocxDocument(path)
    parts: list[str] = []
    tables: list[ParsedTable] = []
    for para in doc.paragraphs:
        text = para.text.strip()
        if text:
            parts.append(text)
    for idx, table in enumerate(doc.tables, start=1):
        rows = [[cell.text.strip() for cell in row.cells] for row in table.rows]
        table_text = "\n".join(" | ".join(cell for cell in row if cell) for row in rows)
        if table_text.strip():
            table_id = f"{path.stem}_table_{idx}"
            tables.append(ParsedTable(table_id=table_id, page_or_sheet=f"table_{idx}", rows=rows, text=table_text))
            parts.append(f"\n[TABLE {idx}]\n{table_text}")
    props = doc.core_properties
    metadata = {
        "author": props.author,
        "created": props.created.isoformat() if props.created else None,
        "modified": props.modified.isoformat() if props.modified else None,
    }
    text = "\n".join(parts)
    return ParsedDocument(str(path), "python-docx", "ok" if text.strip() else "empty", path.stem, text, 0, tables, [], metadata)


def parse_pptx(path: Path) -> ParsedDocument:
    prs = Presentation(path)
    slides: list[str] = []
    for i, slide in enumerate(prs.slides, start=1):
        texts: list[str] = []
        for shape in slide.shapes:
            if hasattr(shape, "text") and shape.text.strip():
                texts.append(shape.text.strip())
        if slide.has_notes_slide:
            notes_frame = slide.notes_slide.notes_text_frame
            note_text = notes_frame.text.strip() if notes_frame is not None and notes_frame.text else ""
            if note_text:
                texts.append(f"NOTES: {note_text}")
        if texts:
            slides.append(f"\n\n--- SLIDE {i} ---\n" + "\n".join(texts))
    text = "\n".join(slides)
    return ParsedDocument(str(path), "python-pptx", "ok" if text.strip() else "empty", path.stem, text, len(prs.slides))


def parse_spreadsheet(path: Path) -> ParsedDocument:
    excel = pd.ExcelFile(path)
    parts: list[str] = []
    tables: list[ParsedTable] = []
    for sheet in excel.sheet_names:
        df = pd.read_excel(excel, sheet_name=sheet, dtype=str).fillna("")
        rows = [list(map(str, df.columns.tolist()))] + df.astype(str).values.tolist()
        text = df.to_csv(index=False)
        table_id = f"{path.stem}_{sheet}".replace(" ", "_")
        tables.append(ParsedTable(table_id=table_id, page_or_sheet=sheet, rows=rows, text=text))
        parts.append(f"\n[SHEET {sheet}]\n{text}")
    return ParsedDocument(str(path), "pandas", "ok" if parts else "empty", path.stem, "\n".join(parts), len(excel.sheet_names), tables)


def parsed_document_to_row(doc: ParsedDocument, extra: dict[str, Any] | None = None) -> dict[str, Any]:
    path = Path(doc.local_path)
    row = {
        "doc_id": stable_id(str(path)),
        "local_path": doc.local_path,
        "file_name": path.name,
        "extension": path.suffix.lower(),
        "parser": doc.parser,
        "status": doc.status,
        "title": doc.title,
        "page_count": doc.page_count,
        "text_chars": len(doc.text),
        "table_count": len(doc.tables),
        "errors": "; ".join(doc.errors),
        "metadata_json": json.dumps(doc.metadata, ensure_ascii=False, default=str),
    }
    if extra:
        row.update(extra)
    return row


def stable_id(value: str) -> str:
    return hashlib.sha1(value.encode("utf-8", errors="ignore")).hexdigest()[:16]
