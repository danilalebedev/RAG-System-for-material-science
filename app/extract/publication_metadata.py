from __future__ import annotations

import hashlib
import json
import os
import re
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

import requests


DOCUMENT_KIND_BY_SOURCE_TYPE = {
    "Журналы": "journal_article",
    "Материалы конференций": "conference_paper",
    "Обзоры": "review_article",
    "Статьи": "journal_article",
    "Доклады": "presentation_report",
}

TECHNICAL_TITLES = {
    "презентация powerpoint",
    "microsoft powerpoint",
    "powerpoint presentation",
    "document",
    "untitled",
    "результат обучения",
    "ключевая информация",
    "цель",
    "цели",
    "задачи",
    "методология",
    "содержание",
    "оглавление",
    "аннотация",
}

DOMAIN_KEYWORDS = [
    "материал",
    "сплав",
    "руда",
    "концентрат",
    "никель",
    "медь",
    "кобальт",
    "платин",
    "паллад",
    "эксперимент",
    "лаборатор",
    "метод",
    "методика",
    "процесс",
    "технолог",
    "режим",
    "услов",
    "температур",
    "давлен",
    "концентрац",
    "выщелач",
    "обжиг",
    "плавк",
    "флотац",
    "синтез",
    "отжиг",
    "испытан",
    "оборудован",
    "установк",
    "свойств",
    "прочност",
    "твердост",
    "извлечен",
    "выход",
    "продукт",
    "образец",
    "месторожд",
    "facility",
    "material",
    "process",
    "experiment",
    "temperature",
    "pressure",
    "synthesis",
    "annealing",
    "leaching",
    "flotation",
    "property",
    "equipment",
]

UNIT_RE = re.compile(
    r"(?i)(\d+(?:[,.]\d+)?)\s*(°C|℃|C\b|K\b|MPa|GPa|Pa\b|бар|атм|%|г/л|мг/л|mol|M\b|ч\b|мин\b|сек\b|h\b|min\b|rpm|об/мин)"
)
DOI_RE = re.compile(r"\b10\.\d{4,9}/[-._;()/:A-Z0-9]+\b", re.IGNORECASE)
YEAR_RE = re.compile(r"\b(19[5-9]\d|20[0-3]\d)\b")
EMAIL_RE = re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+")
WHITESPACE_RE = re.compile(r"\s+")
SIGNATURE_TITLE_RE = re.compile(
    r"(?i)\b("
    r"директор|заместитель|руководитель|начальник|главный специалист|"
    r"ведущий специалист|подготовил|подготовила|исполнитель|утверждаю|"
    r"согласовано|докладчик|prepared by|author"
    r")\b"
)
SECTION_TITLE_RE = re.compile(
    r"(?i)^(о курсе|результат обучения|цель курса|цели курса|тема доклада|эксперты|курс для|"
    r"команда\b|содержание|оглавление|модуль\s+\d+|раздел\s+\d+)\b"
)
INITIALS_NAME_RE = re.compile(r"^[А-ЯЁA-Z][а-яёa-z-]+\s+[А-ЯЁA-Z]\.?\s*(?:[А-ЯЁA-Z]\.?)?$")
THREE_WORD_NAME_RE = re.compile(r"^[А-ЯЁA-Z][а-яёa-z-]+(?:\s+[А-ЯЁA-Z][а-яёa-z-]+){2}$")
FILENAME_LIKE_TITLE_RE = re.compile(
    r"(?i)^(доклад|статья|обзор)\s+[А-ЯЁA-Z][а-яёa-z-]+\s+[А-ЯЁA-Z]\.?\s*(?:[А-ЯЁA-Z]\.?)?\.?$"
)


@dataclass(frozen=True)
class ExtractionConfig:
    model_uri_template: str
    fallback_model_uri_template: str
    completion_endpoint: str
    temperature: float
    max_tokens: int
    request_timeout_seconds: int
    max_retries: int
    retry_backoff_seconds: float
    sleep_seconds: float
    max_header_chars: int
    max_chunk_chars: int
    max_table_chars: int
    top_chunk_count: int
    top_table_count: int
    source_package_max_chars: int

    @classmethod
    def from_file(cls, path: Path) -> "ExtractionConfig":
        raw = json.loads(path.read_text(encoding="utf-8"))
        return cls(**raw)


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def stable_id(prefix: str, *parts: Any) -> str:
    raw = "\n".join("" if part is None else str(part) for part in parts)
    digest = hashlib.sha256(raw.encode("utf-8", errors="ignore")).hexdigest()[:16]
    return f"{prefix}_{digest}"


def compact_text(text: Any, max_chars: int | None = None) -> str:
    cleaned = WHITESPACE_RE.sub(" ", str(text or "")).strip()
    if max_chars is not None and len(cleaned) > max_chars:
        return cleaned[: max_chars - 3].rstrip() + "..."
    return cleaned


def as_float(value: Any, default: float) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def is_generic_title(value: Any) -> bool:
    title = compact_text(value).lower().strip(" .:-—")
    if not title:
        return True
    if title in TECHNICAL_TITLES:
        return True
    if len(title) < 8:
        return True
    if re.fullmatch(r"(page|slide|страница|слайд)\s*\d+", title):
        return True
    return False


def has_domain_signal(value: Any) -> bool:
    lower = compact_text(value).lower()
    return any(keyword in lower for keyword in DOMAIN_KEYWORDS)


def is_bad_title_candidate(value: Any) -> bool:
    title = compact_text(value)
    if is_generic_title(title):
        return True
    if title[:1].islower():
        return True
    if len(title.split()) < 2 and not re.search(r"[\d_/\\-]", title):
        return True
    lower = title.lower()
    if SECTION_TITLE_RE.search(lower):
        return True
    if SIGNATURE_TITLE_RE.search(lower):
        return True
    if INITIALS_NAME_RE.fullmatch(title):
        return True
    if THREE_WORD_NAME_RE.fullmatch(title) and not has_domain_signal(title):
        return True
    return False


def title_confidence_cap(value: Any) -> float:
    title = compact_text(value)
    if FILENAME_LIKE_TITLE_RE.fullmatch(title):
        return 0.55
    return 0.95


def title_from_labeled_header(header: str) -> str | None:
    lines = [compact_text(line, 220) for line in header.splitlines()[:40]]
    lines = [line for line in lines if line and not line.startswith("--- PAGE")]
    stop_re = re.compile(r"(?i)^(докладчик|команда проекта|эксперты|авторы|исполнители|цель|задачи)\b")
    label_re = re.compile(r"(?i)^(тема\s+(?:доклада|работы|исследования)|title|topic)\s*:?\s*(.*)$")
    for index, line in enumerate(lines):
        match = label_re.match(line)
        if not match:
            continue
        inline_title = compact_text(match.group(2), 220)
        if inline_title and not is_bad_title_candidate(inline_title):
            return inline_title
        collected: list[str] = []
        for next_line in lines[index + 1 : index + 5]:
            if stop_re.match(next_line):
                break
            if not collected and is_bad_title_candidate(next_line):
                continue
            collected.append(next_line)
        title = compact_text(" ".join(collected), 220)
        if title and not is_bad_title_candidate(title):
            return title
    return None


def as_list(value: Any) -> list[Any]:
    if value is None:
        return []
    if isinstance(value, list):
        return [item for item in value if item not in (None, "", [], {})]
    if value in ("", {}, []):
        return []
    return [value]


def read_jsonl_iter(path: Path) -> Iterable[dict[str, Any]]:
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if line:
                yield json.loads(line)


def write_json(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2, default=str), encoding="utf-8")


def write_jsonl(path: Path, rows: Iterable[dict[str, Any]]) -> int:
    path.parent.mkdir(parents=True, exist_ok=True)
    count = 0
    with path.open("w", encoding="utf-8", newline="\n") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False, default=str) + "\n")
            count += 1
    return count


def parse_metadata_json(value: Any) -> dict[str, Any]:
    if not value:
        return {}
    if isinstance(value, dict):
        return value
    try:
        return json.loads(str(value))
    except json.JSONDecodeError:
        return {}


def best_title_from_doc(doc: dict[str, Any], header: str) -> tuple[str, float, str]:
    metadata = parse_metadata_json(doc.get("metadata_json"))
    candidates: list[tuple[str, float, str]] = []
    labeled_title = title_from_labeled_header(header)
    if labeled_title:
        candidates.append((labeled_title, 0.82, "labeled_full_text_header"))
    for line in header.splitlines()[:25]:
        line = compact_text(line, 180)
        if 12 <= len(line) <= 180 and not line.startswith("--- PAGE"):
            if not re.fullmatch(r"[\d\s|.-]+", line) and not is_bad_title_candidate(line):
                candidates.append((line, 0.72, "full_text_header"))
                break
    raw_filename_title = compact_text(Path(str(doc.get("file_name") or "")).stem.replace("_", " "), 220)
    filename_title = re.sub(r"^(Доклад|Статья|Обзор|Журнал|Материалы)[_\s-]+", "", raw_filename_title, flags=re.IGNORECASE)
    if filename_title and not is_bad_title_candidate(filename_title):
        candidates.append((compact_text(filename_title, 220), 0.55, "file_name"))
    elif raw_filename_title and not is_generic_title(raw_filename_title):
        candidates.append((raw_filename_title, 0.35, "file_name"))
    for key in ("title", "Title"):
        raw_title = compact_text(metadata.get(key) or doc.get("title"), 220)
        if raw_title:
            score = 0.2 if is_generic_title(raw_title) else 0.45
            candidates.append((raw_title, score, "embedded_metadata"))
    if not candidates:
        return "Untitled source", 0.1, "fallback"
    return max(candidates, key=lambda item: item[1])


def guess_document_kind(doc: dict[str, Any]) -> str:
    source_type = str(doc.get("source_type") or "")
    extension = str(doc.get("extension") or "").lower()
    if extension in {".xls", ".xlsx"}:
        return "spreadsheet_dataset"
    if source_type == "Журналы" and (
        int(doc.get("page_count") or 0) >= 50 or "№" in str(doc.get("file_name") or "")
    ):
        return "journal_issue"
    if extension in {".pptx"} or source_type == "Доклады":
        return "presentation_report"
    return DOCUMENT_KIND_BY_SOURCE_TYPE.get(source_type, "unknown")


def guess_language(text: str) -> str:
    sample = text[:4000]
    cyrillic = sum("а" <= ch.lower() <= "я" or ch.lower() == "ё" for ch in sample)
    latin = sum("a" <= ch.lower() <= "z" for ch in sample)
    if cyrillic and latin and min(cyrillic, latin) / max(cyrillic, latin) > 0.2:
        return "mixed"
    if cyrillic > latin:
        return "ru"
    if latin:
        return "en"
    return "unknown"


def extract_year_candidates(*texts: str) -> list[int]:
    years: list[int] = []
    for text in texts:
        for match in YEAR_RE.findall(text or ""):
            year = int(match)
            if 1950 <= year <= 2035 and year not in years:
                years.append(year)
    return years


def extract_doi_candidates(*texts: str) -> list[str]:
    dois: list[str] = []
    for text in texts:
        for match in DOI_RE.findall(text or ""):
            value = match.rstrip(".,);")
            if value.lower() not in [doi.lower() for doi in dois]:
                dois.append(value)
    return dois


def score_candidate_text(text: str, chunk_index: int = 9999) -> float:
    lower = text.lower()
    score = 0.0
    score += sum(1.0 for keyword in DOMAIN_KEYWORDS if keyword in lower)
    score += min(len(UNIT_RE.findall(text)), 12) * 1.8
    if re.search(r"(?i)(методика|эксперимент|experimental|method|procedure|режим|условия|результат|таблица)", text):
        score += 5.0
    if chunk_index <= 2:
        score += 1.5
    return score


def keep_top(items: list[dict[str, Any]], item: dict[str, Any], limit: int) -> list[dict[str, Any]]:
    items.append(item)
    items.sort(key=lambda row: (-as_float(row.get("score"), 0.0), int(row.get("order", 999999))))
    del items[limit:]
    return items


def collect_candidate_maps(
    *,
    doc_ids: set[str],
    chunks_path: Path,
    tables_path: Path,
    top_chunk_count: int,
    top_table_count: int,
    max_chunk_chars: int,
    max_table_chars: int,
) -> tuple[dict[str, list[dict[str, Any]]], dict[str, list[dict[str, Any]]]]:
    chunks: dict[str, list[dict[str, Any]]] = {doc_id: [] for doc_id in doc_ids}
    if chunks_path.exists():
        for row in read_jsonl_iter(chunks_path):
            doc_id = str(row.get("doc_id") or "")
            if doc_id not in doc_ids:
                continue
            text = str(row.get("text") or "")
            chunk_index = int(row.get("chunk_index") or 9999)
            score = score_candidate_text(text, chunk_index)
            if score <= 0 and chunk_index > 2:
                continue
            keep_top(
                chunks[doc_id],
                {
                    "chunk_id": row.get("chunk_id"),
                    "chunk_index": chunk_index,
                    "score": round(score, 3),
                    "order": chunk_index,
                    "text": compact_text(text, max_chunk_chars),
                },
                top_chunk_count,
            )

    tables: dict[str, list[dict[str, Any]]] = {doc_id: [] for doc_id in doc_ids}
    if tables_path.exists():
        for order, row in enumerate(read_jsonl_iter(tables_path)):
            doc_id = str(row.get("doc_id") or "")
            if doc_id not in doc_ids:
                continue
            text = str(row.get("text") or "")
            score = score_candidate_text(text) + min(int(row.get("row_count") or 0), 25) * 0.05
            keep_top(
                tables[doc_id],
                {
                    "table_id": row.get("table_id"),
                    "page_or_sheet": row.get("page_or_sheet"),
                    "row_count": row.get("row_count"),
                    "score": round(score, 3),
                    "order": order,
                    "text": compact_text(text, max_table_chars),
                },
                top_table_count,
            )
    return chunks, tables


def load_header_text(doc: dict[str, Any], max_chars: int) -> str:
    full_text_path = doc.get("full_text_path")
    if not full_text_path:
        return str(doc.get("text_preview") or "")[:max_chars]
    path = Path(str(full_text_path))
    if not path.exists():
        return str(doc.get("text_preview") or "")[:max_chars]
    return path.read_text(encoding="utf-8", errors="ignore")[:max_chars]


def make_evidence_span(
    *,
    doc_id: str,
    publication_id: str,
    field_name: str,
    source_kind: str,
    text: str,
    confidence: float,
    chunk_id: str | None = None,
    table_id: str | None = None,
) -> dict[str, Any]:
    span_id = stable_id("pubspan", doc_id, field_name, source_kind, text[:500], chunk_id or "", table_id or "")
    return {
        "source_span_id": span_id,
        "doc_id": doc_id,
        "publication_id": publication_id,
        "field_name": field_name,
        "source_kind": source_kind,
        "chunk_id": chunk_id,
        "table_id": table_id,
        "start_char": None,
        "end_char": None,
        "page": None,
        "text": compact_text(text, 1200),
        "confidence": confidence,
    }


def build_baseline_bundle(
    doc: dict[str, Any],
    *,
    header_text: str,
    chunk_candidates: list[dict[str, Any]],
    table_candidates: list[dict[str, Any]],
) -> dict[str, Any]:
    doc_id = str(doc.get("doc_id"))
    publication_id = f"pub_{doc_id}"
    metadata = parse_metadata_json(doc.get("metadata_json"))
    title, title_confidence, title_source = best_title_from_doc(doc, header_text)
    source_blob = "\n".join(
        [
            str(doc.get("file_name") or ""),
            str(doc.get("source_path") or ""),
            str(doc.get("title") or ""),
            header_text[:4000],
        ]
    )
    years = extract_year_candidates(source_blob)
    dois = extract_doi_candidates(source_blob)
    emails = EMAIL_RE.findall(header_text[:5000])
    language = guess_language(header_text)
    year = years[0] if years else None
    title_evidence = make_evidence_span(
        doc_id=doc_id,
        publication_id=publication_id,
        field_name="title",
        source_kind=title_source,
        text=title,
        confidence=title_confidence,
    )
    evidence = [title_evidence]
    if chunk_candidates:
        for chunk in chunk_candidates[:3]:
            evidence.append(
                make_evidence_span(
                    doc_id=doc_id,
                    publication_id=publication_id,
                    field_name="candidate_chunk",
                    source_kind="chunk",
                    chunk_id=str(chunk.get("chunk_id") or ""),
                    text=str(chunk.get("text") or ""),
                    confidence=min(0.7, 0.25 + as_float(chunk.get("score"), 0.0) / 30),
                )
            )
    publication = {
        "publication_id": publication_id,
        "doc_id": doc_id,
        "document_kind": guess_document_kind(doc),
        "source_type": doc.get("source_type"),
        "title": title,
        "title_confidence": title_confidence,
        "subtitle": None,
        "language": language,
        "year": year,
        "date_published": None,
        "authors": [],
        "organizations": [],
        "venue_name": None,
        "venue_type": None,
        "publisher": None,
        "volume": None,
        "issue": None,
        "pages": None,
        "doi": dois[0] if dois else None,
        "isbn": None,
        "url": None,
        "keywords": [],
        "abstract": None,
        "topic_tags": [],
        "source_path": doc.get("source_path"),
        "file_name": doc.get("file_name"),
        "extension": doc.get("extension"),
        "embedded_metadata": metadata,
        "parser_metadata": {
            "parser": doc.get("parser"),
            "status": doc.get("status"),
            "quality_label": doc.get("quality_label"),
            "page_count": doc.get("page_count"),
            "text_chars": doc.get("text_chars"),
            "table_count": doc.get("table_count"),
            "source_mime_type": doc.get("source_mime_type"),
            "source_size": doc.get("source_size"),
        },
        "emails": emails,
        "confidence": 0.35 if title_confidence < 0.6 else 0.55,
        "extraction_status": "partial",
        "missing_fields": ["authors", "venue_name"] + ([] if year else ["year"]) + ([] if dois else ["doi"]),
        "review_notes": [],
        "evidence": [{"source_span_id": title_evidence["source_span_id"], "field_name": "title"}],
        "extracted_at": utc_now(),
    }
    document_summary = {
        "document_summary_id": f"docsum_{doc_id}",
        "publication_id": publication_id,
        "doc_id": doc_id,
        "summary": compact_text(header_text or title, 900),
        "main_topic": None,
        "materials": [],
        "processes": [],
        "properties": [],
        "methods": [],
        "equipment": [],
        "experiments": [],
        "experts": [],
        "facilities": [],
        "facilities_or_geography": [],
        "key_findings": [],
        "limitations_or_gaps": [],
        "additional_domain_fields": {
            "numeric_conditions": [],
            "geography": [],
            "deposits": [],
            "reagents": [],
            "input_materials": [],
            "outputs": [],
            "software_models": [],
            "economic_indicators": [],
            "environmental_safety": [],
            "validation_methods": [],
            "data_gaps": [],
            "contradiction_candidates": [],
            "table_references": [],
            "experimental_protocols": [],
            "technology_solutions": [],
            "equipment_details": [],
            "process_parameters": [],
            "analysis_results": [],
            "numeric_ranges": [],
            "domestic_foreign_practice": [],
            "temporal_scope": [],
            "source_actualization_date": None,
            "recommendations": [],
        },
        "document_kind": publication["document_kind"],
        "confidence": 0.25,
        "extraction_status": "baseline",
        "evidence": [{"source_span_id": item["source_span_id"]} for item in evidence[:3]],
    }
    return {
        "publication": publication,
        "authors": [],
        "venues": [],
        "document_summary": document_summary,
        "procedure_summaries": [],
        "evidence_spans": evidence,
        "source_package": {
            "header_text": compact_text(header_text, 4000),
            "chunk_candidates": chunk_candidates,
            "table_candidates": table_candidates,
        },
        "llm": {"used": False, "status": "not_requested"},
    }


def build_source_package(
    doc: dict[str, Any],
    bundle: dict[str, Any],
    *,
    max_chars: int,
) -> str:
    publication = bundle["publication"]
    source_package = bundle["source_package"]
    metadata_view = {
        "doc_id": doc.get("doc_id"),
        "file_name": doc.get("file_name"),
        "source_path": doc.get("source_path"),
        "source_type": doc.get("source_type"),
        "extension": doc.get("extension"),
        "parser_title": doc.get("title"),
        "embedded_metadata": publication.get("embedded_metadata"),
        "baseline_title": publication.get("title"),
        "baseline_document_kind": publication.get("document_kind"),
        "baseline_year": publication.get("year"),
        "baseline_doi": publication.get("doi"),
    }
    chunks = source_package.get("chunk_candidates") or []
    tables = source_package.get("table_candidates") or []
    package = {
        "document_metadata": metadata_view,
        "header_text": source_package.get("header_text") or "",
        "candidate_chunks": chunks,
        "candidate_tables": tables,
    }
    text = json.dumps(package, ensure_ascii=False, indent=2, default=str)
    if len(text) > max_chars:
        package["header_text"] = compact_text(package["header_text"], 8000)
        package["candidate_chunks"] = [
            {**chunk, "text": compact_text(chunk.get("text"), 1800)} for chunk in chunks[:5]
        ]
        package["candidate_tables"] = [
            {**table, "text": compact_text(table.get("text"), 1600)} for table in tables[:2]
        ]
        text = json.dumps(package, ensure_ascii=False, indent=2, default=str)
    return text[:max_chars]


def build_prompt(source_package: str) -> str:
    return f"""
Ты extraction engine для R&D корпуса по металлургии и materials science.
Верни только валидный JSON без markdown.

Нужно извлечь максимум полезной информации для будущего knowledge graph и RAG.
Официальные graph entity types: Material, Process, Equipment, Property,
Experiment, Publication, Expert, Facility. Помимо них можно сохранять поля:
conditions, numeric_conditions, units, geography, deposits, reagents,
input_materials, outputs, methods, software_models, economic_indicators,
environmental_safety, validation_methods, data_gaps, contradiction_candidates,
table_references, experimental_protocols, technology_solutions,
equipment_details, process_parameters, analysis_results, numeric_ranges,
domestic_foreign_practice, temporal_scope, source_actualization_date,
recommendations.

Используй RECIPER-style recipe fields: material_name, synthesis_method,
steps[].description, steps[].parameters, key_points, entities.

Правила:
- Не выдумывай. Если поля нет в evidence, верни null или [].
- Сохраняй короткие evidence_quotes для важных полей.
- Procedure summaries должны описывать материал/процесс/условия/выход/эффект.
- Если процедур/экспериментов нет, верни пустой procedure_summaries.
- Авторы файла/PowerPoint creator не равны авторам публикации без evidence.
- Технические title типа "Презентация PowerPoint" не считать надежным title.
- Сохраняй названия материалов, процессов, установок, организаций и цитаты на
  языке источника; не переводи факты, если перевод не нужен для краткого summary.
- Для англоязычных источников можно добавить русские/английские синонимы в
  keywords/topic_tags, но evidence_quotes должны оставаться дословными.
- Если документ про промышленные взрывы, горные работы или опасные процессы,
  извлекай только библиографию, сущности, условия и high-level factual summary;
  не формируй инструкции, рецепты или operational guidance.

Верни JSON строго такой формы:
{{
  "publication": {{
    "title": string|null,
    "subtitle": string|null,
    "document_kind": string|null,
    "language": "ru"|"en"|"mixed"|"unknown",
    "year": number|null,
    "date_published": string|null,
    "authors": [{{"raw_name": string, "normalized_name": string|null, "role": string|null, "affiliations": [string], "email": string|null, "order": number|null, "confidence": number}}],
    "organizations": [string],
    "venue_name": string|null,
    "venue_type": string|null,
    "publisher": string|null,
    "volume": string|null,
    "issue": string|null,
    "pages": string|null,
    "doi": string|null,
    "isbn": string|null,
    "url": string|null,
    "keywords": [string],
    "abstract": string|null,
    "topic_tags": [string],
    "confidence": number,
    "missing_fields": [string],
    "evidence_quotes": [string]
  }},
  "document_summary": {{
    "summary": string,
    "main_topic": string|null,
    "materials": [string],
    "processes": [string],
    "equipment": [string],
    "properties": [string],
    "experiments": [string],
    "experts": [string],
    "facilities": [string],
    "methods": [string],
    "facilities_or_geography": [string],
    "key_findings": [string],
    "limitations_or_gaps": [string],
    "additional_domain_fields": {{
      "numeric_conditions": [object],
      "geography": [string],
      "deposits": [string],
      "reagents": [string],
      "input_materials": [string],
      "outputs": [string],
      "software_models": [string],
      "economic_indicators": [string],
      "environmental_safety": [string],
      "validation_methods": [string],
      "data_gaps": [string],
      "contradiction_candidates": [string],
      "table_references": [string],
      "experimental_protocols": [object],
      "technology_solutions": [object],
      "equipment_details": [object],
      "process_parameters": [object],
      "analysis_results": [object],
      "numeric_ranges": [object],
      "domestic_foreign_practice": [object],
      "temporal_scope": [object],
      "source_actualization_date": string|null,
      "recommendations": [string]
    }},
    "confidence": number,
    "evidence_quotes": [string]
  }},
  "procedure_summaries": [
    {{
      "material_name": string|null,
      "synthesis_method": string|null,
      "synthesis_or_process_method": string|null,
      "procedure_type": string|null,
      "steps": [{{"step_number": number, "description": string, "parameters": object}}],
      "key_points": string|null,
      "entities": [{{"text": string, "category": string, "score": number|null}}],
      "materials": [string],
      "processes": [string],
      "equipment": [string],
      "properties": [string],
      "experiments": [string],
      "publications": [string],
      "experts": [string],
      "facilities": [string],
      "input_materials": [string],
      "outputs": [string],
      "conditions": [object],
      "process_parameters": [object],
      "observed_effects": [string],
      "numerical_results": [object],
      "analysis_results": [object],
      "geography": [string],
      "deposits": [string],
      "reagents": [string],
      "validation_methods": [string],
      "equipment_details": [object],
      "technology_solutions": [object],
      "design_features": [string],
      "sample_ids": [string],
      "scale": string|null,
      "temporal_scope": [object],
      "limitations": [string],
      "graph_hints": [object],
      "confidence": number,
      "evidence_quotes": [string]
    }}
  ]
}}

SOURCE_PACKAGE:
{source_package}
""".strip()


def build_json_repair_prompt(raw_response: str, error: str) -> str:
    return f"""
Исправь ответ модели в валидный JSON.
Не добавляй новых фактов и не меняй смысл. Верни только JSON без markdown.

Ошибка парсинга:
{error}

Сломанный JSON/ответ:
{raw_response[:30000]}
""".strip()


class YandexCompletionClient:
    def __init__(
        self,
        *,
        api_key: str,
        folder_id: str,
        config: ExtractionConfig,
        use_fallback_model: bool = False,
    ) -> None:
        self.api_key = api_key
        self.folder_id = folder_id
        self.config = config
        template = config.fallback_model_uri_template if use_fallback_model else config.model_uri_template
        self.model_uri = template.format(folder_id=folder_id)

    def complete(self, prompt: str) -> tuple[str, dict[str, Any]]:
        payload = {
            "modelUri": self.model_uri,
            "completionOptions": {
                "stream": False,
                "temperature": self.config.temperature,
                "maxTokens": self.config.max_tokens,
            },
            "messages": [
                {
                    "role": "system",
                    "text": "You return only valid JSON. No markdown, no explanations.",
                },
                {"role": "user", "text": prompt},
            ],
        }
        headers = {
            "Authorization": f"Api-Key {self.api_key}",
            "Content-Type": "application/json",
        }
        last_error: Exception | None = None
        for attempt in range(self.config.max_retries + 1):
            try:
                response = requests.post(
                    self.config.completion_endpoint,
                    headers=headers,
                    json=payload,
                    timeout=self.config.request_timeout_seconds,
                )
                if response.status_code in {429, 500, 502, 503, 504}:
                    raise RuntimeError(f"transient HTTP {response.status_code}: {response.text[:500]}")
                response.raise_for_status()
                data = response.json()
                alternatives = data.get("result", {}).get("alternatives", [])
                if not alternatives:
                    raise RuntimeError(f"no alternatives in response: {data}")
                text = alternatives[0].get("message", {}).get("text", "")
                return text, data.get("result", {}).get("usage", {})
            except Exception as exc:  # noqa: BLE001 - CLI should keep running with retries.
                last_error = exc
                if attempt >= self.config.max_retries:
                    break
                time.sleep(self.config.retry_backoff_seconds * (attempt + 1))
        raise RuntimeError(str(last_error))


def extract_json_object(text: str) -> dict[str, Any]:
    cleaned = text.strip()
    if cleaned.startswith("```"):
        cleaned = re.sub(r"^```(?:json)?", "", cleaned).strip()
        cleaned = re.sub(r"```$", "", cleaned).strip()
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        start = cleaned.find("{")
        end = cleaned.rfind("}")
        if start >= 0 and end > start:
            return json.loads(cleaned[start : end + 1])
        raise


def is_refusal_response(text: Any) -> bool:
    lower = compact_text(text, 2000).lower()
    return any(
        marker in lower
        for marker in (
            "не могу обсуждать",
            "не могу помочь",
            "не могу предоставить",
            "давайте поговорим",
            "i can't",
            "i cannot",
            "cannot comply",
            "refuse",
        )
    )


def merge_list_values(*values: Any) -> list[Any]:
    result: list[Any] = []
    seen: set[str] = set()
    for value in values:
        if not value:
            continue
        source = value if isinstance(value, list) else [value]
        for item in source:
            key = json.dumps(item, ensure_ascii=False, sort_keys=True, default=str)
            if key not in seen:
                seen.add(key)
                result.append(item)
    return result


def add_evidence_ref(container: dict[str, Any], span: dict[str, Any], field_name: str | None = None) -> None:
    span_id = span.get("source_span_id")
    if not span_id:
        return
    evidence = container.get("evidence")
    if not isinstance(evidence, list):
        evidence = []
    if any(isinstance(item, dict) and item.get("source_span_id") == span_id for item in evidence):
        container["evidence"] = evidence
        return
    ref = {"source_span_id": span_id}
    if field_name:
        ref["field_name"] = field_name
    evidence.append(ref)
    container["evidence"] = evidence


def dedupe_evidence_spans(spans: list[dict[str, Any]]) -> list[dict[str, Any]]:
    deduped: list[dict[str, Any]] = []
    seen: set[str] = set()
    for span in spans:
        span_id = str(span.get("source_span_id") or "")
        if not span_id or span_id in seen:
            continue
        seen.add(span_id)
        deduped.append(span)
    return deduped


def author_name_variants(author: dict[str, Any]) -> list[str]:
    raw_name = compact_text(author.get("raw_name"))
    normalized_name = compact_text(author.get("normalized_name"))
    variants = [item for item in (raw_name, normalized_name) if item]
    surname = compact_text(author.get("surname"))
    initials = compact_text(author.get("initials"))
    if surname and initials:
        variants.append(f"{surname} {initials}")
    for name in (raw_name, normalized_name):
        parts = name.split()
        if len(parts) >= 2:
            surname = parts[0]
            initials = "".join(f"{part[0]}." for part in parts[1:] if part)
            if initials:
                variants.append(f"{surname} {initials}")
    deduped: list[str] = []
    seen: set[str] = set()
    for item in variants:
        key = item.casefold()
        if key not in seen:
            seen.add(key)
            deduped.append(item)
    return deduped


def evidence_refs_for_author(author: dict[str, Any], evidence_spans: list[dict[str, Any]], *, limit: int = 3) -> list[dict[str, str]]:
    variants = [variant.casefold() for variant in author_name_variants(author)]
    if not variants:
        return []
    refs: list[dict[str, str]] = []
    seen: set[str] = set()
    for span in evidence_spans:
        text = compact_text(span.get("text")).casefold()
        if not text:
            continue
        if not any(variant and variant in text for variant in variants):
            continue
        span_id = str(span.get("source_span_id") or "")
        if not span_id or span_id in seen:
            continue
        seen.add(span_id)
        refs.append({"source_span_id": span_id, "field_name": "author"})
        if len(refs) >= limit:
            break
    return refs


def merge_llm_bundle(baseline: dict[str, Any], llm_data: dict[str, Any]) -> dict[str, Any]:
    doc_id = baseline["publication"]["doc_id"]
    publication_id = baseline["publication"]["publication_id"]
    merged = json.loads(json.dumps(baseline, ensure_ascii=False, default=str))
    llm_pub = llm_data.get("publication") if isinstance(llm_data.get("publication"), dict) else {}
    publication = merged["publication"]
    accepted_llm_title: str | None = None
    for key, value in llm_pub.items():
        if value not in (None, "", [], {}):
            if key == "title":
                if is_bad_title_candidate(value):
                    continue
                accepted_llm_title = compact_text(value, 220)
                publication[key] = accepted_llm_title
                continue
            publication[key] = value
    publication["publication_id"] = publication_id
    publication["doc_id"] = doc_id
    publication["source_path"] = baseline["publication"].get("source_path")
    publication["file_name"] = baseline["publication"].get("file_name")
    publication["extension"] = baseline["publication"].get("extension")
    publication["embedded_metadata"] = baseline["publication"].get("embedded_metadata")
    publication["parser_metadata"] = baseline["publication"].get("parser_metadata")
    publication["authors"] = as_list(llm_pub.get("authors") or publication.get("authors"))
    publication["organizations"] = as_list(publication.get("organizations"))
    publication["keywords"] = as_list(publication.get("keywords"))
    publication["topic_tags"] = as_list(publication.get("topic_tags"))
    publication["missing_fields"] = as_list(llm_pub.get("missing_fields") or publication.get("missing_fields"))
    publication["extraction_status"] = "ok" if llm_pub else "partial"
    publication["extracted_at"] = utc_now()
    if accepted_llm_title:
        current_confidence = as_float(publication.get("title_confidence"), 0.0)
        llm_confidence = as_float(llm_pub.get("confidence") or publication.get("confidence"), 0.75)
        cap = title_confidence_cap(accepted_llm_title)
        publication["title_confidence"] = min(cap, max(current_confidence, min(0.95, llm_confidence)))

    evidence_spans = merged.get("evidence_spans") or []
    if accepted_llm_title:
        span = make_evidence_span(
            doc_id=doc_id,
            publication_id=publication_id,
            field_name="title",
            source_kind="llm_title",
            text=accepted_llm_title,
            confidence=as_float(publication.get("title_confidence"), 0.75),
        )
        evidence_spans.append(span)
        add_evidence_ref(publication, span, "title")
    for quote in merge_list_values(llm_pub.get("evidence_quotes"))[:8]:
        span = make_evidence_span(
            doc_id=doc_id,
            publication_id=publication_id,
            field_name="publication_llm_quote",
            source_kind="llm_quote",
            text=str(quote),
            confidence=as_float(publication.get("confidence"), 0.5),
        )
        evidence_spans.append(span)
        add_evidence_ref(publication, span, "publication_llm_quote")

    authors = []
    embedded_author = compact_text((publication.get("embedded_metadata") or {}).get("author")).lower()
    for order, author in enumerate(publication.get("authors") or [], start=1):
        if isinstance(author, str):
            author = {"raw_name": author, "normalized_name": author}
        if not isinstance(author, dict) or not author.get("raw_name"):
            continue
        raw_name = compact_text(author.get("raw_name"))
        if (
            embedded_author
            and raw_name.lower() == embedded_author
            and not as_list(author.get("affiliations"))
            and not author.get("role")
            and as_float(author.get("confidence"), 0.0) <= 0.55
        ):
            continue
        author_id = stable_id("author", author.get("normalized_name") or author.get("raw_name"), author.get("affiliations"))
        author_row = {
            "author_id": author_id,
            "publication_id": publication_id,
            "doc_id": doc_id,
            "raw_name": author.get("raw_name"),
            "normalized_name": author.get("normalized_name") or author.get("raw_name"),
            "surname": author.get("surname"),
            "given_names": author.get("given_names"),
            "initials": author.get("initials"),
            "affiliations": author.get("affiliations") or [],
            "email": author.get("email"),
            "orcid": author.get("orcid"),
            "role": author.get("role") or "author",
            "order": author.get("order") or order,
            "confidence": author.get("confidence") or publication.get("confidence") or 0.5,
            "evidence": [],
        }
        author_row["evidence"] = evidence_refs_for_author(author_row, evidence_spans)
        authors.append(author_row)

    venues = []
    if publication.get("venue_name"):
        venues.append(
            {
                "venue_id": stable_id("venue", publication.get("venue_name"), publication.get("venue_type")),
                "raw_name": publication.get("venue_name"),
                "normalized_name": publication.get("venue_name"),
                "venue_type": publication.get("venue_type"),
                "issn": None,
                "publisher": publication.get("publisher"),
                "country": None,
                "city": None,
                "aliases": [],
                "confidence": publication.get("confidence") or 0.5,
                "evidence": [],
            }
        )

    llm_doc_summary = llm_data.get("document_summary") if isinstance(llm_data.get("document_summary"), dict) else {}
    document_summary = merged["document_summary"]
    for key, value in llm_doc_summary.items():
        if value not in (None, "", [], {}):
            document_summary[key] = value
    document_summary["document_summary_id"] = f"docsum_{doc_id}"
    document_summary["publication_id"] = publication_id
    document_summary["doc_id"] = doc_id
    document_summary["document_kind"] = publication.get("document_kind")
    document_summary["extraction_status"] = "ok" if llm_doc_summary else "baseline"
    for key in (
        "materials",
        "processes",
        "properties",
        "methods",
        "equipment",
        "experiments",
        "experts",
        "facilities",
        "facilities_or_geography",
        "key_findings",
        "limitations_or_gaps",
    ):
        document_summary[key] = as_list(document_summary.get(key))
    additional = document_summary.get("additional_domain_fields")
    if not isinstance(additional, dict):
        additional = {}
    for key in (
        "numeric_conditions",
        "geography",
        "deposits",
        "reagents",
        "input_materials",
        "outputs",
        "software_models",
        "economic_indicators",
        "environmental_safety",
        "validation_methods",
        "data_gaps",
        "contradiction_candidates",
        "table_references",
        "experimental_protocols",
        "technology_solutions",
        "equipment_details",
        "process_parameters",
        "analysis_results",
        "numeric_ranges",
        "domestic_foreign_practice",
        "temporal_scope",
        "recommendations",
    ):
        additional[key] = as_list(additional.get(key))
    additional["source_actualization_date"] = additional.get("source_actualization_date")
    document_summary["additional_domain_fields"] = additional
    for quote in merge_list_values(llm_doc_summary.get("evidence_quotes"))[:8]:
        span = make_evidence_span(
            doc_id=doc_id,
            publication_id=publication_id,
            field_name="document_summary_llm_quote",
            source_kind="llm_quote",
            text=str(quote),
            confidence=as_float(document_summary.get("confidence"), 0.5),
        )
        evidence_spans.append(span)
        add_evidence_ref(document_summary, span, "document_summary_llm_quote")

    procedures: list[dict[str, Any]] = []
    raw_procedures = llm_data.get("procedure_summaries") if isinstance(llm_data.get("procedure_summaries"), list) else []
    for index, proc in enumerate(raw_procedures):
        if not isinstance(proc, dict):
            continue
        proc_id = f"proc_{doc_id}_{index + 1:04d}"
        material_name = proc.get("material_name") or (proc.get("materials") or [None])[0]
        method = proc.get("synthesis_method") or proc.get("synthesis_or_process_method")
        procedure = {
            "procedure_summary_id": proc_id,
            "publication_id": publication_id,
            "doc_id": doc_id,
            "source_span_ids": [],
            "material_name": material_name,
            "synthesis_method": proc.get("synthesis_method") or method,
            "synthesis_or_process_method": proc.get("synthesis_or_process_method") or method,
            "procedure_type": proc.get("procedure_type") or "unknown",
            "steps": as_list(proc.get("steps")),
            "key_points": proc.get("key_points"),
            "entities": as_list(proc.get("entities")),
            "materials": as_list(proc.get("materials")) or ([material_name] if material_name else []),
            "processes": as_list(proc.get("processes")),
            "equipment": as_list(proc.get("equipment")),
            "properties": as_list(proc.get("properties")),
            "experiments": as_list(proc.get("experiments")),
            "publications": as_list(proc.get("publications")) or [publication.get("title")],
            "experts": as_list(proc.get("experts")),
            "facilities": as_list(proc.get("facilities")),
            "input_materials": as_list(proc.get("input_materials")),
            "outputs": as_list(proc.get("outputs")),
            "conditions": as_list(proc.get("conditions")),
            "process_parameters": as_list(proc.get("process_parameters")),
            "observed_effects": as_list(proc.get("observed_effects")),
            "numerical_results": as_list(proc.get("numerical_results")),
            "analysis_results": as_list(proc.get("analysis_results")),
            "geography": as_list(proc.get("geography")),
            "deposits": as_list(proc.get("deposits")),
            "reagents": as_list(proc.get("reagents")),
            "validation_methods": as_list(proc.get("validation_methods")),
            "equipment_details": as_list(proc.get("equipment_details")),
            "technology_solutions": as_list(proc.get("technology_solutions")),
            "design_features": as_list(proc.get("design_features")),
            "sample_ids": as_list(proc.get("sample_ids")),
            "scale": proc.get("scale"),
            "temporal_scope": as_list(proc.get("temporal_scope")),
            "limitations": as_list(proc.get("limitations")),
            "graph_hints": as_list(proc.get("graph_hints")),
            "confidence": proc.get("confidence") or 0.5,
            "extraction_status": "ok",
            "evidence": [],
        }
        for quote in merge_list_values(proc.get("evidence_quotes"))[:8]:
            span = make_evidence_span(
                doc_id=doc_id,
                publication_id=publication_id,
                field_name="procedure_summary_llm_quote",
                source_kind="llm_quote",
                text=str(quote),
                confidence=as_float(procedure.get("confidence"), 0.5),
            )
            evidence_spans.append(span)
            procedure["source_span_ids"].append(span["source_span_id"])
            procedure["evidence"].append({"source_span_id": span["source_span_id"]})
        procedures.append(procedure)

    merged["authors"] = authors
    merged["venues"] = venues
    merged["procedure_summaries"] = procedures
    merged["evidence_spans"] = dedupe_evidence_spans(evidence_spans)
    return merged


def load_completed_record(path: Path) -> dict[str, Any] | None:
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return None


def attach_author_evidence(bundle: dict[str, Any]) -> None:
    evidence_spans = bundle.get("evidence_spans") if isinstance(bundle.get("evidence_spans"), list) else []
    authors = bundle.get("authors") if isinstance(bundle.get("authors"), list) else []
    for author in authors:
        if not isinstance(author, dict):
            continue
        evidence = author.get("evidence") if isinstance(author.get("evidence"), list) else []
        seen = {str(item.get("source_span_id")) for item in evidence if isinstance(item, dict) and item.get("source_span_id")}
        for ref in evidence_refs_for_author(author, evidence_spans):
            span_id = str(ref.get("source_span_id") or "")
            if span_id and span_id not in seen:
                evidence.append(ref)
                seen.add(span_id)
        author["evidence"] = evidence


def aggregate_records(records_dir: Path, output_dir: Path) -> dict[str, int]:
    bundles = []
    for path in sorted(records_dir.glob("*.json")):
        data = load_completed_record(path)
        if data:
            attach_author_evidence(data)
            bundles.append(data)
    publications = [bundle["publication"] for bundle in bundles if bundle.get("publication")]
    authors = [row for bundle in bundles for row in bundle.get("authors", [])]
    venues = [row for bundle in bundles for row in bundle.get("venues", [])]
    evidence = [row for bundle in bundles for row in bundle.get("evidence_spans", [])]
    document_summaries = [bundle["document_summary"] for bundle in bundles if bundle.get("document_summary")]
    procedure_summaries = [row for bundle in bundles for row in bundle.get("procedure_summaries", [])]

    counts = {
        "records": len(bundles),
        "publications": write_jsonl(output_dir / "publications.jsonl", publications),
        "publication_authors": write_jsonl(output_dir / "publication_authors.jsonl", authors),
        "publication_venues": write_jsonl(output_dir / "publication_venues.jsonl", venues),
        "publication_evidence_spans": write_jsonl(output_dir / "publication_evidence_spans.jsonl", evidence),
        "document_summaries": write_jsonl(output_dir / "document_summaries.jsonl", document_summaries),
        "procedure_summaries": write_jsonl(output_dir / "procedure_summaries.jsonl", procedure_summaries),
    }
    status_counts: dict[str, int] = {}
    kind_counts: dict[str, int] = {}
    source_type_counts: dict[str, int] = {}
    for publication in publications:
        status_counts[str(publication.get("extraction_status") or "unknown")] = (
            status_counts.get(str(publication.get("extraction_status") or "unknown"), 0) + 1
        )
        kind_counts[str(publication.get("document_kind") or "unknown")] = (
            kind_counts.get(str(publication.get("document_kind") or "unknown"), 0) + 1
        )
        source_type_counts[str(publication.get("source_type") or "unknown")] = (
            source_type_counts.get(str(publication.get("source_type") or "unknown"), 0) + 1
        )
    report = {
        "generated_at": utc_now(),
        "counts": counts,
        "publication_status_counts": status_counts,
        "document_kind_counts": kind_counts,
        "source_type_counts": source_type_counts,
        "coverage": {
            "with_title": sum(1 for row in publications if row.get("title")),
            "with_year": sum(1 for row in publications if row.get("year")),
            "with_authors": sum(1 for row in publications if row.get("authors")),
            "with_doi": sum(1 for row in publications if row.get("doi")),
            "with_procedures": len({row.get("doc_id") for row in procedure_summaries}),
        },
    }
    write_json(output_dir / "publication_metadata_report.json", report)
    return counts


def process_documents(
    *,
    docs: list[dict[str, Any]],
    chunks_path: Path,
    tables_path: Path,
    output_dir: Path,
    config: ExtractionConfig,
    client: YandexCompletionClient | None,
    resume: bool,
    no_llm: bool,
    retry_failed: bool = False,
) -> dict[str, Any]:
    records_dir = output_dir / "records"
    raw_dir = output_dir / "llm_raw"
    records_dir.mkdir(parents=True, exist_ok=True)
    raw_dir.mkdir(parents=True, exist_ok=True)
    doc_ids = {str(doc.get("doc_id")) for doc in docs}
    chunk_map, table_map = collect_candidate_maps(
        doc_ids=doc_ids,
        chunks_path=chunks_path,
        tables_path=tables_path,
        top_chunk_count=config.top_chunk_count,
        top_table_count=config.top_table_count,
        max_chunk_chars=config.max_chunk_chars,
        max_table_chars=config.max_table_chars,
    )
    processed = 0
    skipped = 0
    failed = 0
    llm_used = 0
    for position, doc in enumerate(docs, start=1):
        doc_id = str(doc.get("doc_id"))
        record_path = records_dir / f"{doc_id}.json"
        if resume and record_path.exists():
            existing = load_completed_record(record_path)
            if not retry_failed or (existing or {}).get("llm", {}).get("status") != "failed":
                skipped += 1
                continue
        header_text = load_header_text(doc, config.max_header_chars)
        baseline = build_baseline_bundle(
            doc,
            header_text=header_text,
            chunk_candidates=chunk_map.get(doc_id, []),
            table_candidates=table_map.get(doc_id, []),
        )
        bundle = baseline
        raw_response = None
        raw_path: Path | None = None
        if not no_llm and client is not None and str(doc.get("status")) == "ok":
            try:
                source_package = build_source_package(doc, baseline, max_chars=config.source_package_max_chars)
                prompt = build_prompt(source_package)
                raw_response, usage = client.complete(prompt)
                raw_path = raw_dir / f"{doc_id}.txt"
                raw_path.write_text(raw_response, encoding="utf-8")
                repair_usage = None
                try:
                    llm_data = extract_json_object(raw_response)
                    llm_status = "ok"
                except Exception as parse_exc:
                    if "{" not in raw_response or "не могу обсуждать" in raw_response.lower():
                        raise
                    repair_prompt = build_json_repair_prompt(raw_response, str(parse_exc))
                    repaired_response, repair_usage = client.complete(repair_prompt)
                    repair_path = raw_dir / f"{doc_id}.repair.txt"
                    repair_path.write_text(repaired_response, encoding="utf-8")
                    llm_data = extract_json_object(repaired_response)
                    llm_status = "ok_repaired"
                bundle = merge_llm_bundle(baseline, llm_data)
                bundle["llm"] = {
                    "used": True,
                    "status": llm_status,
                    "model_uri": client.model_uri,
                    "usage": usage,
                    "repair_usage": repair_usage,
                    "raw_response_path": str(raw_path),
                }
                llm_used += 1
                time.sleep(config.sleep_seconds)
            except Exception as exc:  # noqa: BLE001 - per-document failure should not stop the corpus.
                bundle["publication"]["extraction_status"] = "partial"
                if is_refusal_response(raw_response):
                    bundle["publication"].setdefault("review_notes", []).append(
                        "llm_refusal_triaged: metadata-only baseline retained"
                    )
                    bundle["llm"] = {
                        "used": True,
                        "status": "refused_triaged",
                        "error": str(exc)[:1000],
                        "raw_response_path": str(raw_path) if raw_path else None,
                        "fallback": "metadata_only_baseline",
                    }
                elif raw_response and "{" in raw_response:
                    bundle["publication"].setdefault("review_notes", []).append(
                        "llm_parse_failed_triaged: metadata-only baseline retained; raw response saved"
                    )
                    bundle["llm"] = {
                        "used": True,
                        "status": "parse_failed_triaged",
                        "error": str(exc)[:1000],
                        "raw_response_path": str(raw_path) if raw_path else None,
                        "raw_response_preview": compact_text(raw_response, 1000),
                        "fallback": "metadata_only_baseline",
                    }
                else:
                    failed += 1
                    bundle["publication"].setdefault("review_notes", []).append(f"llm_error: {exc}")
                    bundle["llm"] = {
                        "used": True,
                        "status": "failed",
                        "error": str(exc)[:1000],
                        "raw_response_preview": compact_text(raw_response, 1000) if raw_response else None,
                    }
        write_json(record_path, bundle)
        processed += 1
        if position % 10 == 0:
            print(
                f"processed={processed} skipped={skipped} failed={failed} llm_used={llm_used} current={position}/{len(docs)}",
                flush=True,
            )
    counts = aggregate_records(records_dir, output_dir)
    manifest = {
        "generated_at": utc_now(),
        "selected_documents": len(docs),
        "processed_this_run": processed,
        "skipped_existing": skipped,
        "llm_used_this_run": llm_used,
        "failed_this_run": failed,
        "output_counts": counts,
        "config": config.__dict__,
        "no_llm": no_llm,
    }
    write_json(output_dir / "publication_metadata_manifest.json", manifest)
    return manifest


def load_documents(path: Path, *, limit: int | None = None, source_type: str | None = None) -> list[dict[str, Any]]:
    docs = []
    for row in read_jsonl_iter(path):
        if source_type and row.get("source_type") != source_type:
            continue
        docs.append(row)
        if limit is not None and len(docs) >= limit:
            break
    return docs
