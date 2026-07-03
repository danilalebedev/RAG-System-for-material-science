from __future__ import annotations

import json
import re
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable


SEVERITIES = ("error", "warning", "info")
LANGUAGES = {"ru", "en", "mixed", "unknown"}

EXPECTED_PUBLICATION_KEYS = {
    "publication_id",
    "doc_id",
    "document_kind",
    "source_type",
    "title",
    "title_confidence",
    "subtitle",
    "language",
    "year",
    "date_published",
    "authors",
    "organizations",
    "venue_name",
    "venue_type",
    "publisher",
    "volume",
    "issue",
    "pages",
    "doi",
    "isbn",
    "url",
    "keywords",
    "abstract",
    "topic_tags",
    "source_path",
    "file_name",
    "extension",
    "embedded_metadata",
    "parser_metadata",
    "emails",
    "confidence",
    "extraction_status",
    "missing_fields",
    "review_notes",
    "evidence",
    "evidence_quotes",
    "extracted_at",
}

EXPECTED_DOCUMENT_SUMMARY_KEYS = {
    "document_summary_id",
    "publication_id",
    "doc_id",
    "summary",
    "main_topic",
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
    "additional_domain_fields",
    "document_kind",
    "confidence",
    "extraction_status",
    "evidence",
    "evidence_quotes",
}

EXPECTED_PROCEDURE_SUMMARY_KEYS = {
    "procedure_summary_id",
    "publication_id",
    "doc_id",
    "source_span_ids",
    "material_name",
    "synthesis_method",
    "synthesis_or_process_method",
    "procedure_type",
    "steps",
    "key_points",
    "entities",
    "materials",
    "processes",
    "equipment",
    "properties",
    "experiments",
    "publications",
    "experts",
    "facilities",
    "input_materials",
    "outputs",
    "conditions",
    "observed_effects",
    "numerical_results",
    "geography",
    "deposits",
    "reagents",
    "validation_methods",
    "limitations",
    "graph_hints",
    "confidence",
    "extraction_status",
    "evidence",
}

EXPECTED_AUTHOR_KEYS = {
    "author_id",
    "publication_id",
    "doc_id",
    "raw_name",
    "normalized_name",
    "surname",
    "given_names",
    "initials",
    "affiliations",
    "email",
    "orcid",
    "role",
    "order",
    "confidence",
    "evidence",
}

EXPECTED_EVIDENCE_SPAN_KEYS = {
    "source_span_id",
    "doc_id",
    "publication_id",
    "field_name",
    "source_kind",
    "chunk_id",
    "table_id",
    "start_char",
    "end_char",
    "text",
    "page",
    "confidence",
}

REQUIRED_PUBLICATION_FIELDS = (
    "publication_id",
    "doc_id",
    "document_kind",
    "source_type",
    "title",
    "title_confidence",
    "source_path",
    "file_name",
    "extension",
    "extraction_status",
    "confidence",
    "evidence",
)

REQUIRED_DOCUMENT_SUMMARY_FIELDS = (
    "document_summary_id",
    "publication_id",
    "doc_id",
    "summary",
    "main_topic",
    "materials",
    "processes",
    "properties",
    "methods",
    "facilities_or_geography",
    "key_findings",
    "limitations_or_gaps",
    "document_kind",
    "confidence",
    "evidence",
)

REQUIRED_PROCEDURE_SUMMARY_FIELDS = (
    "procedure_summary_id",
    "publication_id",
    "doc_id",
    "source_span_ids",
    "material_name",
    "synthesis_or_process_method",
    "procedure_type",
    "steps",
    "key_points",
    "materials",
    "processes",
    "equipment",
    "properties",
    "outputs",
    "conditions",
    "observed_effects",
    "graph_hints",
    "confidence",
    "extraction_status",
    "evidence",
)

GENERIC_TITLE_TERMS = {
    "document",
    "untitled",
    "microsoft powerpoint",
    "powerpoint presentation",
    "\u043f\u0440\u0435\u0437\u0435\u043d\u0442\u0430\u0446\u0438\u044f powerpoint",
    "\u0434\u043e\u043a\u0443\u043c\u0435\u043d\u0442",
    "\u0431\u0435\u0437 \u043d\u0430\u0437\u0432\u0430\u043d\u0438\u044f",
}

DOMAIN_SIGNAL_RE = re.compile(
    r"(?i)(material|process|experiment|method|synthesis|leaching|flotation|"
    r"\u043c\u0430\u0442\u0435\u0440\u0438\u0430\u043b|\u0441\u043f\u043b\u0430\u0432|"
    r"\u0440\u0443\u0434\u0430|\u043d\u0438\u043a\u0435\u043b|\u043c\u0435\u0434\u044c|"
    r"\u043a\u043e\u0431\u0430\u043b\u044c\u0442|\u043f\u0440\u043e\u0446\u0435\u0441\u0441|"
    r"\u043c\u0435\u0442\u043e\u0434|\u0441\u0438\u043d\u0442\u0435\u0437|"
    r"\u0444\u043b\u043e\u0442\u0430\u0446|\u043e\u0431\u0436\u0438\u0433|"
    r"\u0432\u044b\u0449\u0435\u043b\u0430\u0447|\u0441\u0432\u043e\u0439\u0441\u0442\u0432|"
    r"\u0442\u0435\u043c\u043f\u0435\u0440\u0430\u0442\u0443\u0440)"
)
TITLE_TOPIC_RE = re.compile(r"(?i)^(\u0442\u0435\u043c\u0430\s+\u0434\u043e\u043a\u043b\u0430\u0434\u0430|topic)\s*:")
POSITION_ORG_RE = re.compile(
    r"(?i)(\u0434\u0438\u0440\u0435\u043a\u0442\u043e\u0440|"
    r"\u0440\u0443\u043a\u043e\u0432\u043e\u0434\u0438\u0442\u0435\u043b|"
    r"\u043d\u0430\u0447\u0430\u043b\u044c\u043d\u0438\u043a|"
    r"\u0441\u043f\u0435\u0446\u0438\u0430\u043b\u0438\u0441\u0442|"
    r"\u0434\u043e\u043a\u043b\u0430\u0434\u0447\u0438\u043a|prepared by|author|"
    r"\u043f\u0430\u043e\b|\u0430\u043e\b|\u043e\u043e\u043e\b|"
    r"\u0438\u043d\u0441\u0442\u0438\u0442\u0443\u0442|"
    r"\u0443\u043d\u0438\u0432\u0435\u0440\u0441\u0438\u0442\u0435\u0442|"
    r"\u043d\u043e\u0440\u043d\u0438\u043a\u0435\u043b\u044c|"
    r"\u0433\u0438\u043f\u0440\u043e\u043d\u0438\u043a\u0435\u043b\u044c)"
)
REFUSAL_RE = re.compile(
    r"(?i)(refus|cannot comply|i can't|i cannot|"
    r"\u043d\u0435\s+\u043c\u043e\u0433\u0443|"
    r"\u043e\u0442\u043a\u0430\u0437|"
    r"\u043d\u0435\s+\u0431\u0443\u0434\u0443)"
)
WHITESPACE_RE = re.compile(r"\s+")


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def compact_text(value: Any, max_chars: int | None = None) -> str:
    text = WHITESPACE_RE.sub(" ", str(value or "")).strip()
    if max_chars is not None and len(text) > max_chars:
        return text[: max_chars - 3].rstrip() + "..."
    return text


def as_list(value: Any) -> list[Any]:
    if value is None or value == "":
        return []
    if isinstance(value, list):
        return [item for item in value if item not in (None, "", [], {})]
    return [value]


def is_missing(value: Any) -> bool:
    return value is None or value == "" or value == [] or value == {}


def as_float(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def read_jsonl(path: Path) -> tuple[list[dict[str, Any]], list[str]]:
    rows: list[dict[str, Any]] = []
    errors: list[str] = []
    if not path.exists():
        return rows, [f"missing file: {path.name}"]
    with path.open("r", encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, start=1):
            line = line.strip()
            if not line:
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError as exc:
                errors.append(f"{path.name}:{line_number}: {exc}")
                continue
            if isinstance(row, dict):
                rows.append(row)
            else:
                errors.append(f"{path.name}:{line_number}: row is not an object")
    return rows, errors


def read_json_file(path: Path) -> tuple[dict[str, Any] | None, str | None]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except OSError as exc:
        return None, str(exc)
    except json.JSONDecodeError as exc:
        return None, str(exc)
    if not isinstance(data, dict):
        return None, "top-level JSON is not an object"
    return data, None


class IssueCollector:
    def __init__(self, max_samples: int) -> None:
        self.max_samples = max_samples
        self.counts_by_severity: Counter[str] = Counter()
        self.counts_by_code: Counter[str] = Counter()
        self.samples: list[dict[str, Any]] = []

    def add(
        self,
        severity: str,
        code: str,
        message: str,
        *,
        row: dict[str, Any] | None = None,
        file: str | None = None,
        field: str | None = None,
    ) -> None:
        if severity not in SEVERITIES:
            severity = "warning"
        self.counts_by_severity[severity] += 1
        self.counts_by_code[code] += 1
        if len(self.samples) >= self.max_samples:
            return
        row = row or {}
        self.samples.append(
            {
                "severity": severity,
                "code": code,
                "doc_id": row.get("doc_id"),
                "publication_id": row.get("publication_id"),
                "title": compact_text(row.get("title"), 180),
                "file": file,
                "field": field,
                "message": message,
            }
        )

    def summary(self) -> dict[str, Any]:
        return {
            "by_severity": {severity: self.counts_by_severity.get(severity, 0) for severity in SEVERITIES},
            "by_code": dict(sorted(self.counts_by_code.items())),
            "sample_limit": self.max_samples,
        }


def evidence_ids_from_refs(value: Any) -> list[str]:
    refs: list[str] = []
    for item in as_list(value):
        if isinstance(item, dict):
            span_id = item.get("source_span_id")
        else:
            span_id = item
        if span_id:
            refs.append(str(span_id))
    return refs


def row_title(row: dict[str, Any], publication_by_id: dict[str, dict[str, Any]]) -> str | None:
    if row.get("title"):
        return str(row.get("title"))
    publication = publication_by_id.get(str(row.get("publication_id") or ""))
    if publication:
        return str(publication.get("title") or "")
    return None


def issue_row(row: dict[str, Any], publication_by_id: dict[str, dict[str, Any]]) -> dict[str, Any]:
    if row.get("title"):
        return row
    enriched = dict(row)
    title = row_title(row, publication_by_id)
    if title:
        enriched["title"] = title
    return enriched


def is_bad_title(value: Any) -> tuple[bool, str]:
    title = compact_text(value)
    normalized = title.lower().strip(" .:-\u2014")
    if not normalized:
        return True, "empty title"
    if normalized in GENERIC_TITLE_TERMS:
        return True, "generic technical title"
    if TITLE_TOPIC_RE.match(normalized):
        return True, "topic label used as title"
    words = re.findall(r"[\w\u0400-\u04ff]+", title, flags=re.UNICODE)
    if len(title) < 8:
        return True, "title is too short"
    if len(words) <= 1 and not re.search(r"[\d_/\-]", title):
        return True, "single-word title"
    if POSITION_ORG_RE.search(title) and not DOMAIN_SIGNAL_RE.search(title) and len(words) <= 10:
        return True, "position or organization looks like title"
    return False, ""


def infer_language(*values: Any) -> str:
    sample = compact_text(" ".join(str(value or "") for value in values), 5000)
    cyrillic = sum("\u0400" <= char <= "\u04ff" for char in sample)
    latin = sum(("a" <= char.lower() <= "z") for char in sample)
    if cyrillic and latin and min(cyrillic, latin) / max(cyrillic, latin) >= 0.2:
        return "mixed"
    if cyrillic > latin:
        return "ru"
    if latin:
        return "en"
    return "unknown"


def collect_unknown_keys(rows: Iterable[dict[str, Any]], expected: set[str], *, limit: int = 20) -> dict[str, Any]:
    key_counts: Counter[str] = Counter()
    rows_with_unknown = 0
    for row in rows:
        unknown = sorted(set(row) - expected)
        if unknown:
            rows_with_unknown += 1
            key_counts.update(unknown)
    return {
        "rows_with_unknown_keys": rows_with_unknown,
        "top_keys": [{"key": key, "count": count} for key, count in key_counts.most_common(limit)],
    }


def coverage_ratio(count: int, total: int) -> dict[str, Any]:
    return {"count": count, "total": total, "ratio": round(count / total, 4) if total else 0.0}


def validate_required_fields(
    *,
    rows: Iterable[dict[str, Any]],
    required_fields: Iterable[str],
    file: str,
    issues: IssueCollector,
    publication_by_id: dict[str, dict[str, Any]],
) -> None:
    identity_fields = {"publication_id", "document_summary_id", "procedure_summary_id", "doc_id"}
    for row in rows:
        display_row = issue_row(row, publication_by_id)
        for field in required_fields:
            if field not in row:
                severity = "error" if field in identity_fields else "warning"
                issues.add(
                    severity,
                    "missing_required_field",
                    f"required field is absent: {field}",
                    row=display_row,
                    file=file,
                    field=field,
                )
            elif field in identity_fields and is_missing(row.get(field)):
                issues.add(
                    "error",
                    "empty_required_identifier",
                    f"required identifier is empty: {field}",
                    row=display_row,
                    file=file,
                    field=field,
                )
        if file == "publications.jsonl" and is_missing(row.get("evidence")):
            issues.add("error", "missing_evidence", "publication has no evidence refs", row=display_row, file=file, field="evidence")
        if file == "document_summaries.jsonl" and is_missing(row.get("summary")):
            issues.add("error", "missing_summary", "document summary text is empty", row=display_row, file=file, field="summary")


def validate_evidence_refs(
    *,
    rows: Iterable[dict[str, Any]],
    file: str,
    evidence_ids: set[str],
    issues: IssueCollector,
    publication_by_id: dict[str, dict[str, Any]],
) -> tuple[int, int]:
    total_refs = 0
    broken_refs = 0
    for row in rows:
        refs = evidence_ids_from_refs(row.get("evidence")) + [str(item) for item in as_list(row.get("source_span_ids")) if item]
        for span_id in refs:
            total_refs += 1
            if span_id not in evidence_ids:
                broken_refs += 1
                issues.add(
                    "error",
                    "broken_evidence_ref",
                    f"source_span_id is not present in publication_evidence_spans.jsonl: {span_id}",
                    row=issue_row(row, publication_by_id),
                    file=file,
                    field="evidence",
                )
    return total_refs, broken_refs


def embedded_creator_names(publication: dict[str, Any]) -> set[str]:
    metadata = publication.get("embedded_metadata")
    if not isinstance(metadata, dict):
        return set()
    names: set[str] = set()
    for key in ("author", "creator", "lastModifiedBy", "last_modified_by"):
        value = compact_text(metadata.get(key))
        if value:
            names.add(value.lower())
    return names


def validate_authors(
    *,
    publications: list[dict[str, Any]],
    authors: list[dict[str, Any]],
    issues: IssueCollector,
    publication_by_id: dict[str, dict[str, Any]],
) -> None:
    author_rows = authors[:]
    if not author_rows:
        for publication in publications:
            for author in as_list(publication.get("authors")):
                if isinstance(author, dict):
                    row = dict(author)
                else:
                    row = {"raw_name": author}
                row["publication_id"] = publication.get("publication_id")
                row["doc_id"] = publication.get("doc_id")
                author_rows.append(row)

    creator_by_publication = {str(row.get("publication_id")): embedded_creator_names(row) for row in publications}
    for author in author_rows:
        publication_id = str(author.get("publication_id") or "")
        creators = creator_by_publication.get(publication_id, set())
        raw_name = compact_text(author.get("raw_name") or author.get("normalized_name"))
        if not raw_name or raw_name.lower() not in creators:
            continue
        confidence = as_float(author.get("confidence"))
        has_evidence = bool(evidence_ids_from_refs(author.get("evidence")))
        if not has_evidence or confidence is None or confidence <= 0.55:
            issues.add(
                "warning",
                "suspicious_embedded_creator_author",
                "author matches embedded file creator but lacks evidence or reliable confidence",
                row=issue_row(author, publication_by_id),
                file="publication_authors.jsonl",
                field="raw_name",
            )


def validate_procedures(
    *,
    procedures: list[dict[str, Any]],
    evidence_ids: set[str],
    issues: IssueCollector,
    publication_by_id: dict[str, dict[str, Any]],
) -> None:
    for procedure in procedures:
        display_row = issue_row(procedure, publication_by_id)
        has_material = bool(procedure.get("material_name") or as_list(procedure.get("materials")))
        has_process = bool(as_list(procedure.get("processes")))
        has_method = bool(procedure.get("synthesis_or_process_method") or procedure.get("synthesis_method"))
        has_key_points = not is_missing(procedure.get("key_points"))
        refs = evidence_ids_from_refs(procedure.get("evidence")) + [str(item) for item in as_list(procedure.get("source_span_ids")) if item]
        valid_refs = [span_id for span_id in refs if span_id in evidence_ids]
        missing_parts = []
        if not has_material:
            missing_parts.append("material")
        if not has_process:
            missing_parts.append("process")
        if not has_method:
            missing_parts.append("method")
        if not has_key_points:
            missing_parts.append("key_points")
        if missing_parts:
            issues.add(
                "warning",
                "weak_procedure_summary",
                "procedure summary lacks " + ", ".join(missing_parts),
                row=display_row,
                file="procedure_summaries.jsonl",
                field=";".join(missing_parts),
            )
        if not refs:
            issues.add(
                "error",
                "procedure_without_evidence",
                "procedure summary has no evidence refs or source_span_ids",
                row=display_row,
                file="procedure_summaries.jsonl",
                field="evidence",
            )
        elif not valid_refs:
            issues.add(
                "error",
                "procedure_without_valid_evidence",
                "procedure summary has evidence refs, but none resolve to evidence spans",
                row=display_row,
                file="procedure_summaries.jsonl",
                field="evidence",
            )


def analyze_records(records_dir: Path, issues: IssueCollector) -> dict[str, Any]:
    stats: dict[str, Any] = {
        "records_total": 0,
        "record_read_errors": 0,
        "publication_status_counts": {},
        "llm_status_counts": {},
        "llm_used_counts": {},
        "partial_records": 0,
        "failed_llm_records": 0,
        "refusal_like_records": 0,
        "triaged_refusal_records": 0,
        "sample_failures": [],
    }
    if not records_dir.exists():
        issues.add("warning", "missing_records_dir", "records directory is absent", file="records")
        return stats

    publication_status: Counter[str] = Counter()
    llm_status: Counter[str] = Counter()
    llm_used: Counter[str] = Counter()
    sample_failures: list[dict[str, Any]] = []
    for path in sorted(records_dir.glob("*.json")):
        stats["records_total"] += 1
        record, error = read_json_file(path)
        if error or record is None:
            stats["record_read_errors"] += 1
            issues.add("error", "record_json_error", f"cannot read record: {error}", file=str(path.name))
            continue
        publication = record.get("publication") if isinstance(record.get("publication"), dict) else {}
        llm = record.get("llm") if isinstance(record.get("llm"), dict) else {}
        pub_status = str(publication.get("extraction_status") or "unknown")
        status = str(llm.get("status") or "unknown")
        used = str(bool(llm.get("used")))
        publication_status[pub_status] += 1
        llm_status[status] += 1
        llm_used[used] += 1
        if pub_status in {"partial", "failed", "needs_review", "no_bibliography"}:
            stats["partial_records"] += 1
        if status in {"failed", "error", "parse_error"}:
            stats["failed_llm_records"] += 1
        if status in {"refused_triaged", "refusal_triaged"}:
            stats["triaged_refusal_records"] += 1
        failure_text = " ".join(
            compact_text(llm.get(key), 1000) for key in ("status", "error", "raw_response_preview") if llm.get(key)
        )
        if status not in {"refused_triaged", "refusal_triaged"} and REFUSAL_RE.search(failure_text):
            stats["refusal_like_records"] += 1
        if (pub_status != "ok" or status not in {"ok", "ok_repaired", "not_requested"}) and len(sample_failures) < 20:
            sample_failures.append(
                {
                    "record": path.name,
                    "doc_id": publication.get("doc_id") or path.stem,
                    "publication_id": publication.get("publication_id"),
                    "publication_status": pub_status,
                    "llm_status": status,
                    "llm_error": compact_text(llm.get("error"), 220),
                }
            )
    stats["publication_status_counts"] = dict(publication_status)
    stats["llm_status_counts"] = dict(llm_status)
    stats["llm_used_counts"] = dict(llm_used)
    stats["sample_failures"] = sample_failures
    return stats


def build_quality_report(output_dir: Path, *, max_issue_samples: int = 200) -> dict[str, Any]:
    """Build a deterministic QA report for publication metadata extraction outputs."""
    output_dir = Path(output_dir)
    issues = IssueCollector(max_issue_samples)

    publications, publication_errors = read_jsonl(output_dir / "publications.jsonl")
    document_summaries, document_summary_errors = read_jsonl(output_dir / "document_summaries.jsonl")
    procedures, procedure_errors = read_jsonl(output_dir / "procedure_summaries.jsonl")
    authors, author_errors = read_jsonl(output_dir / "publication_authors.jsonl")
    evidence_spans, evidence_errors = read_jsonl(output_dir / "publication_evidence_spans.jsonl")

    for file, errors in {
        "publications.jsonl": publication_errors,
        "document_summaries.jsonl": document_summary_errors,
        "procedure_summaries.jsonl": procedure_errors,
        "publication_authors.jsonl": author_errors,
        "publication_evidence_spans.jsonl": evidence_errors,
    }.items():
        for error in errors:
            issues.add("error", "jsonl_read_error", error, file=file)

    publication_by_id = {str(row.get("publication_id")): row for row in publications if row.get("publication_id")}
    publication_by_doc = {str(row.get("doc_id")): row for row in publications if row.get("doc_id")}
    evidence_ids = {str(row.get("source_span_id")) for row in evidence_spans if row.get("source_span_id")}
    doc_summary_doc_ids = {str(row.get("doc_id")) for row in document_summaries if row.get("doc_id")}
    procedure_doc_ids = {str(row.get("doc_id")) for row in procedures if row.get("doc_id")}

    validate_required_fields(
        rows=publications,
        required_fields=REQUIRED_PUBLICATION_FIELDS,
        file="publications.jsonl",
        issues=issues,
        publication_by_id=publication_by_id,
    )
    validate_required_fields(
        rows=document_summaries,
        required_fields=REQUIRED_DOCUMENT_SUMMARY_FIELDS,
        file="document_summaries.jsonl",
        issues=issues,
        publication_by_id=publication_by_id,
    )
    validate_required_fields(
        rows=procedures,
        required_fields=REQUIRED_PROCEDURE_SUMMARY_FIELDS,
        file="procedure_summaries.jsonl",
        issues=issues,
        publication_by_id=publication_by_id,
    )

    evidence_ref_stats = {}
    for file, rows in {
        "publications.jsonl": publications,
        "document_summaries.jsonl": document_summaries,
        "procedure_summaries.jsonl": procedures,
        "publication_authors.jsonl": authors,
    }.items():
        total_refs, broken_refs = validate_evidence_refs(
            rows=rows,
            file=file,
            evidence_ids=evidence_ids,
            issues=issues,
            publication_by_id=publication_by_id,
        )
        evidence_ref_stats[file] = {"total_refs": total_refs, "broken_refs": broken_refs}

    for publication in publications:
        bad, reason = is_bad_title(publication.get("title"))
        if bad:
            issues.add(
                "warning",
                "bad_title",
                f"title looks generic or non-bibliographic: {reason}",
                row=publication,
                file="publications.jsonl",
                field="title",
            )
        language = publication.get("language")
        if language and str(language) not in LANGUAGES:
            issues.add(
                "warning",
                "invalid_language",
                f"language must be one of {sorted(LANGUAGES)}",
                row=publication,
                file="publications.jsonl",
                field="language",
            )

    validate_authors(publications=publications, authors=authors, issues=issues, publication_by_id=publication_by_id)
    validate_procedures(procedures=procedures, evidence_ids=evidence_ids, issues=issues, publication_by_id=publication_by_id)

    total_publications = len(publications)
    publications_with_authors = sum(1 for row in publications if as_list(row.get("authors")))
    if not publications_with_authors and authors:
        publications_with_authors = len({str(row.get("publication_id")) for row in authors if row.get("publication_id")})
    publications_with_evidence = sum(1 for row in publications if evidence_ids_from_refs(row.get("evidence")))
    coverage = {
        "title": coverage_ratio(sum(1 for row in publications if row.get("title")), total_publications),
        "year": coverage_ratio(sum(1 for row in publications if row.get("year")), total_publications),
        "authors": coverage_ratio(publications_with_authors, total_publications),
        "doi": coverage_ratio(sum(1 for row in publications if row.get("doi")), total_publications),
        "document_summary": coverage_ratio(len(doc_summary_doc_ids), total_publications),
        "procedure_summary": coverage_ratio(len(procedure_doc_ids), total_publications),
        "evidence": coverage_ratio(publications_with_evidence, total_publications),
    }

    declared_language_counts: Counter[str] = Counter()
    inferred_language_counts: Counter[str] = Counter()
    language_mismatches = 0
    for publication in publications:
        doc_id = str(publication.get("doc_id") or "")
        summary = next((row.get("summary") for row in document_summaries if str(row.get("doc_id") or "") == doc_id), "")
        declared = str(publication.get("language") or "unknown")
        inferred = infer_language(publication.get("title"), summary)
        declared_language_counts[declared] += 1
        inferred_language_counts[inferred] += 1
        if declared in LANGUAGES and declared != "unknown" and inferred != "unknown" and declared != inferred:
            language_mismatches += 1

    invalid_language_count = sum(count for value, count in declared_language_counts.items() if value not in LANGUAGES)
    unknown_language_count = declared_language_counts.get("unknown", 0) + declared_language_counts.get("", 0)
    mixed_docs = declared_language_counts.get("mixed", 0) + inferred_language_counts.get("mixed", 0)
    unknown_ratio = unknown_language_count / total_publications if total_publications else 0.0
    mixed_language_ready = invalid_language_count == 0 and unknown_ratio <= 0.2

    records_stats = analyze_records(output_dir / "records", issues)
    gate_reasons = []
    if issues.counts_by_severity.get("error", 0):
        gate_reasons.append("blocking QA errors are present")
    for field in ("title", "document_summary", "evidence"):
        if coverage[field]["ratio"] < 0.98:
            gate_reasons.append(f"{field} coverage is below 0.98")
    if not mixed_language_ready:
        gate_reasons.append("language labels are invalid or too often unknown")
    if records_stats.get("failed_llm_records", 0):
        gate_reasons.append("failed LLM records are present")
    if records_stats.get("refusal_like_records", 0):
        gate_reasons.append("refusal-like records are present")

    report = {
        "generated_at": utc_now(),
        "output_dir": str(output_dir),
        "counts": {
            "publications": len(publications),
            "document_summaries": len(document_summaries),
            "procedure_summaries": len(procedures),
            "publication_authors": len(authors),
            "publication_evidence_spans": len(evidence_spans),
            "unique_evidence_span_ids": len(evidence_ids),
            "unique_publication_ids": len(publication_by_id),
            "unique_doc_ids": len(publication_by_doc),
        },
        "coverage": coverage,
        "coverage_by_document_kind": {
            kind: {
                "publications": count,
                "with_procedure_summary": sum(
                    1 for row in publications if str(row.get("document_kind") or "unknown") == kind and str(row.get("doc_id") or "") in procedure_doc_ids
                ),
            }
            for kind, count in Counter(str(row.get("document_kind") or "unknown") for row in publications).items()
        },
        "evidence_refs": evidence_ref_stats,
        "unknown_keys": {
            "publications": collect_unknown_keys(publications, EXPECTED_PUBLICATION_KEYS),
            "document_summaries": collect_unknown_keys(document_summaries, EXPECTED_DOCUMENT_SUMMARY_KEYS),
            "procedure_summaries": collect_unknown_keys(procedures, EXPECTED_PROCEDURE_SUMMARY_KEYS),
            "publication_authors": collect_unknown_keys(authors, EXPECTED_AUTHOR_KEYS),
            "publication_evidence_spans": collect_unknown_keys(evidence_spans, EXPECTED_EVIDENCE_SPAN_KEYS),
        },
        "language": {
            "declared_distribution": dict(declared_language_counts),
            "inferred_distribution": dict(inferred_language_counts),
            "declared_invalid_count": invalid_language_count,
            "declared_unknown_ratio": round(unknown_ratio, 4),
            "declared_vs_inferred_mismatches": language_mismatches,
            "mixed_language_docs_estimate": mixed_docs,
            "mixed_language_ready": mixed_language_ready,
            "readiness_reason": "ok" if mixed_language_ready else "invalid or too many unknown language labels",
        },
        "records": records_stats,
        "issues": issues.summary(),
        "sample_issues": issues.samples,
        "gate": {
            "mass_run_ready": not gate_reasons,
            "blocking_error_count": issues.counts_by_severity.get("error", 0),
            "warning_count": issues.counts_by_severity.get("warning", 0),
            "reasons": gate_reasons,
        },
    }
    return report


def write_quality_report(report: dict[str, Any], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(report, ensure_ascii=False, indent=2, default=str), encoding="utf-8")


def build_and_write_quality_report(output_dir: Path, report_path: Path | None = None) -> dict[str, Any]:
    report = build_quality_report(output_dir)
    target = report_path or (Path(output_dir) / "publication_quality_report.json")
    write_quality_report(report, target)
    return report
