from __future__ import annotations

import json
import random
import re
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Protocol


SEVERITIES = ("error", "warning", "info")
VERDICTS = {"pass", "warn", "fail"}
HALLUCINATION_RISKS = {"low", "medium", "high", "unknown"}
SUMMARY_REPORT_NAME = "summary_quality_report.json"

WHITESPACE_RE = re.compile(r"\s+")
TOKEN_RE = re.compile(r"[A-Za-zА-Яа-яЁё0-9][A-Za-zА-Яа-яЁё0-9_+.-]*", re.UNICODE)
FENCED_JSON_RE = re.compile(r"```(?:json)?\s*(.*?)```", re.IGNORECASE | re.DOTALL)

DOMAIN_SIGNAL_RE = re.compile(
    r"(?i)(material|process|experiment|method|synthesis|leaching|flotation|"
    r"nickel|copper|cobalt|ore|alloy|temperature|pressure|property|"
    r"материал|сплав|руда|никел|мед|кобальт|процесс|метод|синтез|"
    r"флотац|обжиг|выщелач|свойств|температур|давлен)"
)
GENERIC_SUMMARY_RE = re.compile(
    r"(?i)^(document|summary|text|source|this document|"
    r"документ|текст|краткое описание|сводка|аннотация)\b"
)
STOPWORDS = {
    "and",
    "or",
    "the",
    "this",
    "that",
    "with",
    "from",
    "for",
    "are",
    "was",
    "were",
    "about",
    "into",
    "при",
    "для",
    "или",
    "это",
    "что",
    "как",
    "дан",
    "данный",
    "документ",
    "материал",
    "работа",
    "исследование",
    "описан",
    "описание",
    "котор",
    "the",
}


class CompletionClient(Protocol):
    model_uri: str

    def complete(self, prompt: str) -> tuple[str, dict[str, Any]]:
        ...


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def compact_text(value: Any, max_chars: int | None = None) -> str:
    text = WHITESPACE_RE.sub(" ", str(value or "")).strip()
    if max_chars is not None and len(text) > max_chars:
        return text[: max_chars - 3].rstrip() + "..."
    return text


def as_list(value: Any) -> list[Any]:
    if value in (None, "", [], {}):
        return []
    if isinstance(value, list):
        return [item for item in value if item not in (None, "", [], {})]
    return [value]


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
                errors.append(f"{path.name}:{line_number}: row is not a JSON object")
    return rows, errors


def write_summary_quality_report(report: dict[str, Any], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(report, ensure_ascii=False, indent=2, default=str), encoding="utf-8")


def issue(
    severity: str,
    code: str,
    message: str,
    *,
    doc_id: str | None = None,
    row_id: str | None = None,
    source: str | None = None,
    field: str | None = None,
) -> dict[str, Any]:
    if severity not in SEVERITIES:
        severity = "warning"
    return {
        "severity": severity,
        "code": code,
        "message": message,
        "doc_id": doc_id,
        "row_id": row_id,
        "source": source,
        "field": field,
    }


def count_issues(issues: list[dict[str, Any]]) -> dict[str, Any]:
    by_severity = Counter(str(row.get("severity") or "warning") for row in issues)
    by_code = Counter(str(row.get("code") or "unknown") for row in issues)
    return {
        "by_severity": {severity: by_severity.get(severity, 0) for severity in SEVERITIES},
        "by_code": dict(sorted(by_code.items())),
        "total": len(issues),
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


def row_id(row: dict[str, Any]) -> str | None:
    for key in ("document_summary_id", "procedure_summary_id", "publication_id", "source_span_id"):
        if row.get(key):
            return str(row.get(key))
    return None


def text_tokens(value: Any) -> set[str]:
    tokens: set[str] = set()
    for raw in TOKEN_RE.findall(compact_text(value).lower()):
        token = raw.strip("._-+")
        if len(token) < 3 and not token.isdigit():
            continue
        if token in STOPWORDS:
            continue
        tokens.add(token)
    return tokens


def lexical_overlap(summary: str, evidence_text: str) -> dict[str, Any]:
    summary_tokens = text_tokens(summary)
    evidence_tokens = text_tokens(evidence_text)
    if not summary_tokens or not evidence_tokens:
        return {
            "summary_token_count": len(summary_tokens),
            "evidence_token_count": len(evidence_tokens),
            "overlap_count": 0,
            "summary_coverage": 0.0,
            "jaccard": 0.0,
        }
    overlap = summary_tokens & evidence_tokens
    union = summary_tokens | evidence_tokens
    return {
        "summary_token_count": len(summary_tokens),
        "evidence_token_count": len(evidence_tokens),
        "overlap_count": len(overlap),
        "summary_coverage": round(len(overlap) / len(summary_tokens), 4),
        "jaccard": round(len(overlap) / len(union), 4),
    }


def entity_values(row: dict[str, Any]) -> list[tuple[str, str]]:
    values: list[tuple[str, str]] = []
    for field in ("materials", "processes", "properties"):
        for item in as_list(row.get(field)):
            if isinstance(item, dict):
                text = compact_text(item.get("name") or item.get("value") or json.dumps(item, ensure_ascii=False), 160)
            else:
                text = compact_text(item, 160)
            if text:
                values.append((field, text))
    return values


def row_support_text(row: dict[str, Any], evidence_texts: list[str]) -> str:
    parts = [
        row.get("summary"),
        row.get("main_topic"),
        row.get("key_points"),
        " ".join(as_list(row.get("key_findings"))),
        " ".join(as_list(row.get("observed_effects"))),
        " ".join(evidence_texts),
    ]
    for step in as_list(row.get("steps")):
        if isinstance(step, dict):
            parts.append(step.get("description"))
            parts.append(json.dumps(step.get("parameters") or {}, ensure_ascii=False))
        else:
            parts.append(step)
    return " ".join(compact_text(part) for part in parts if part)


def resolved_evidence_for_row(row: dict[str, Any], evidence_by_id: dict[str, dict[str, Any]]) -> tuple[list[str], list[str]]:
    refs = evidence_ids_from_refs(row.get("evidence"))
    refs.extend(str(item) for item in as_list(row.get("source_span_ids")) if item)
    refs = list(dict.fromkeys(refs))
    texts = [compact_text(evidence_by_id[span_id].get("text"), 1600) for span_id in refs if span_id in evidence_by_id]
    return refs, [text for text in texts if text]


def deterministic_check_document(
    *,
    doc_id: str,
    document_summary: dict[str, Any] | None,
    procedures: list[dict[str, Any]],
    evidence_by_id: dict[str, dict[str, Any]],
    include_procedures: bool,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    issues: list[dict[str, Any]] = []
    metrics: dict[str, Any] = {
        "doc_id": doc_id,
        "document_summary_present": bool(document_summary),
        "procedure_count": len(procedures),
        "broken_evidence_refs": 0,
        "missing_evidence_rows": 0,
        "entity_coverage_missing": 0,
    }

    rows: list[tuple[str, dict[str, Any]]] = []
    if document_summary:
        rows.append(("document_summary", document_summary))
    else:
        issues.append(issue("error", "missing_document_summary", "document summary row is absent", doc_id=doc_id))
    if include_procedures:
        rows.extend(("procedure_summary", row) for row in procedures)

    for source, row in rows:
        refs, evidence_texts = resolved_evidence_for_row(row, evidence_by_id)
        broken_refs = [span_id for span_id in refs if span_id not in evidence_by_id]
        metrics["broken_evidence_refs"] += len(broken_refs)
        if broken_refs:
            issues.append(
                issue(
                    "error",
                    "broken_evidence_ref",
                    "evidence refs are absent from publication_evidence_spans.jsonl: " + ", ".join(broken_refs[:5]),
                    doc_id=doc_id,
                    row_id=row_id(row),
                    source=source,
                    field="evidence",
                )
            )
        if not refs:
            metrics["missing_evidence_rows"] += 1
            issues.append(
                issue(
                    "error",
                    "missing_evidence",
                    "summary row has no evidence refs",
                    doc_id=doc_id,
                    row_id=row_id(row),
                    source=source,
                    field="evidence",
                )
            )

        if source == "document_summary":
            summary = compact_text(row.get("summary"))
            metrics["summary_chars"] = len(summary)
            metrics["summary_words"] = len(TOKEN_RE.findall(summary))
            if len(summary) < 80:
                issues.append(
                    issue(
                        "warning",
                        "summary_too_short",
                        "document summary is shorter than 80 characters",
                        doc_id=doc_id,
                        row_id=row_id(row),
                        source=source,
                        field="summary",
                    )
                )
            if len(summary) > 2200:
                issues.append(
                    issue(
                        "warning",
                        "summary_too_long",
                        "document summary is longer than 2200 characters",
                        doc_id=doc_id,
                        row_id=row_id(row),
                        source=source,
                        field="summary",
                    )
                )
            if GENERIC_SUMMARY_RE.match(summary) and not DOMAIN_SIGNAL_RE.search(summary):
                issues.append(
                    issue(
                        "warning",
                        "generic_summary",
                        "summary looks generic and has no domain signal",
                        doc_id=doc_id,
                        row_id=row_id(row),
                        source=source,
                        field="summary",
                    )
                )

            evidence_blob = " ".join(evidence_texts)
            overlap = lexical_overlap(summary, evidence_blob)
            metrics["summary_evidence_overlap"] = overlap
            if refs and not evidence_texts:
                issues.append(
                    issue(
                        "error",
                        "missing_evidence_text",
                        "evidence refs resolve but evidence text is empty",
                        doc_id=doc_id,
                        row_id=row_id(row),
                        source=source,
                        field="evidence",
                    )
                )
            elif overlap["summary_token_count"] >= 10 and overlap["summary_coverage"] < 0.12:
                issues.append(
                    issue(
                        "warning",
                        "low_summary_evidence_overlap",
                        "summary has weak lexical overlap with resolved evidence",
                        doc_id=doc_id,
                        row_id=row_id(row),
                        source=source,
                        field="summary",
                    )
                )

        support_tokens = text_tokens(row_support_text(row, evidence_texts))
        for field, value in entity_values(row):
            entity_tokens = text_tokens(value)
            if entity_tokens and support_tokens.isdisjoint(entity_tokens):
                metrics["entity_coverage_missing"] += 1
                issues.append(
                    issue(
                        "info",
                        "entity_without_text_support",
                        f"{field} value is not covered by summary or evidence text: {value}",
                        doc_id=doc_id,
                        row_id=row_id(row),
                        source=source,
                        field=field,
                    )
                )

    return metrics, issues


def extract_json_object(text: str) -> dict[str, Any]:
    cleaned = compact_text(text)
    candidates = [cleaned]
    candidates.extend(match.group(1).strip() for match in FENCED_JSON_RE.finditer(text or ""))
    decoder = json.JSONDecoder()
    for candidate in candidates:
        try:
            parsed = json.loads(candidate)
            if isinstance(parsed, dict):
                return parsed
        except json.JSONDecodeError:
            pass
        for match in re.finditer(r"\{", candidate):
            try:
                parsed, _ = decoder.raw_decode(candidate[match.start() :])
            except json.JSONDecodeError:
                continue
            if isinstance(parsed, dict):
                return parsed
    raise ValueError("model response does not contain a JSON object")


def build_llm_judge_prompt(
    *,
    publication: dict[str, Any] | None,
    document_summary: dict[str, Any] | None,
    procedures: list[dict[str, Any]],
    evidence_texts: list[str],
) -> str:
    payload = {
        "publication": {
            "doc_id": (publication or document_summary or {}).get("doc_id"),
            "title": compact_text((publication or {}).get("title"), 500),
            "document_kind": (publication or {}).get("document_kind"),
            "year": (publication or {}).get("year"),
        },
        "document_summary": document_summary or {},
        "procedure_summaries": procedures[:10],
        "resolved_evidence_texts": [compact_text(text, 1200) for text in evidence_texts[:20]],
    }
    return f"""
You are auditing extracted publication summaries against evidence snippets.

Judge whether the document_summary and procedure_summaries are faithful, specific, and useful for metadata/knowledge-graph extraction.
Do not rewrite the summary. Do not suggest replacement text.

Return one strict JSON object with this schema:
{{
  "score": 1,
  "verdict": "pass",
  "issues": [{{"code": "string", "severity": "info|warning|error", "message": "string"}}],
  "missing_critical_fields": ["string"],
  "hallucination_risk": "low|medium|high"
}}

Scoring:
5 = evidence-grounded, specific, covers key materials/processes/properties.
3 = usable but has omissions or weak specificity.
1 = misleading, generic, or likely hallucinated.

Input:
{json.dumps(payload, ensure_ascii=False, indent=2, default=str)}
""".strip()


def normalize_llm_judge_response(parsed: dict[str, Any], *, doc_id: str) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    issues: list[dict[str, Any]] = []
    try:
        score = int(parsed.get("score"))
    except (TypeError, ValueError):
        score = 0
    if score < 1 or score > 5:
        issues.append(issue("warning", "invalid_llm_score", "LLM judge returned score outside 1-5", doc_id=doc_id))
        score = max(1, min(5, score or 1))

    verdict = str(parsed.get("verdict") or "").lower()
    if verdict not in VERDICTS:
        issues.append(issue("warning", "invalid_llm_verdict", "LLM judge returned invalid verdict", doc_id=doc_id))
        verdict = "warn"

    hallucination_risk = str(parsed.get("hallucination_risk") or "unknown").lower()
    if hallucination_risk not in HALLUCINATION_RISKS:
        issues.append(
            issue("warning", "invalid_hallucination_risk", "LLM judge returned invalid hallucination_risk", doc_id=doc_id)
        )
        hallucination_risk = "unknown"

    model_issues: list[dict[str, Any]] = []
    for item in as_list(parsed.get("issues")):
        if not isinstance(item, dict):
            continue
        severity = str(item.get("severity") or "warning").lower()
        if severity not in SEVERITIES:
            severity = "warning"
        model_issues.append(
            issue(
                severity,
                compact_text(item.get("code") or "llm_judge_issue", 80),
                compact_text(item.get("message") or "LLM judge issue", 500),
                doc_id=doc_id,
                source="llm_judge",
            )
        )

    result = {
        "doc_id": doc_id,
        "score": score,
        "verdict": verdict,
        "issues": model_issues,
        "missing_critical_fields": [compact_text(item, 120) for item in as_list(parsed.get("missing_critical_fields"))],
        "hallucination_risk": hallucination_risk,
    }
    return result, issues + model_issues


def collect_doc_evidence_texts(
    *,
    document_summary: dict[str, Any] | None,
    procedures: list[dict[str, Any]],
    evidence_by_id: dict[str, dict[str, Any]],
) -> list[str]:
    refs: list[str] = []
    if document_summary:
        refs.extend(evidence_ids_from_refs(document_summary.get("evidence")))
    for procedure in procedures:
        refs.extend(evidence_ids_from_refs(procedure.get("evidence")))
        refs.extend(str(item) for item in as_list(procedure.get("source_span_ids")) if item)
    texts = []
    for span_id in dict.fromkeys(refs):
        span = evidence_by_id.get(span_id)
        if span and span.get("text"):
            texts.append(compact_text(span.get("text"), 1600))
    return texts


def run_llm_judge(
    *,
    client: CompletionClient,
    sampled_doc_ids: list[str],
    publication_by_doc: dict[str, dict[str, Any]],
    document_by_doc: dict[str, dict[str, Any]],
    procedures_by_doc: dict[str, list[dict[str, Any]]],
    evidence_by_id: dict[str, dict[str, Any]],
    include_procedures: bool,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    judge_issues: list[dict[str, Any]] = []
    results: list[dict[str, Any]] = []
    usage: list[dict[str, Any]] = []

    for doc_id in sampled_doc_ids:
        document_summary = document_by_doc.get(doc_id)
        procedures = procedures_by_doc.get(doc_id, []) if include_procedures else []
        evidence_texts = collect_doc_evidence_texts(
            document_summary=document_summary,
            procedures=procedures,
            evidence_by_id=evidence_by_id,
        )
        prompt = build_llm_judge_prompt(
            publication=publication_by_doc.get(doc_id),
            document_summary=document_summary,
            procedures=procedures,
            evidence_texts=evidence_texts,
        )
        try:
            raw_response, raw_usage = client.complete(prompt)
            usage.append({"doc_id": doc_id, "usage": raw_usage})
            parsed = extract_json_object(raw_response)
            result, result_issues = normalize_llm_judge_response(parsed, doc_id=doc_id)
            result["raw_response_preview"] = compact_text(raw_response, 800)
            results.append(result)
            judge_issues.extend(result_issues)
        except Exception as exc:  # noqa: BLE001 - one judge failure should not fail the audit.
            parse_issue = issue(
                "warning",
                "llm_judge_failed",
                f"LLM judge failed for sampled document: {compact_text(exc, 300)}",
                doc_id=doc_id,
                source="llm_judge",
            )
            judge_issues.append(parse_issue)
            results.append(
                {
                    "doc_id": doc_id,
                    "score": None,
                    "verdict": "warn",
                    "issues": [parse_issue],
                    "missing_critical_fields": [],
                    "hallucination_risk": "unknown",
                }
            )

    return {
        "used": True,
        "model_uri": getattr(client, "model_uri", None),
        "results": results,
        "usage": usage,
        "issue_counts": count_issues(judge_issues),
    }, judge_issues


def sample_doc_ids(doc_ids: list[str], *, sample_size: int, seed: int) -> list[str]:
    ordered = sorted({doc_id for doc_id in doc_ids if doc_id})
    if sample_size <= 0:
        return []
    rng = random.Random(seed)
    rng.shuffle(ordered)
    return sorted(ordered[: min(sample_size, len(ordered))])


def build_summary_quality_report(
    output_dir: Path,
    *,
    client: CompletionClient | None = None,
    sample_size: int = 10,
    seed: int = 1729,
    include_procedures: bool = True,
) -> dict[str, Any]:
    """Build a sampled QA report for document and procedure summaries."""
    output_dir = Path(output_dir)
    publications, publication_errors = read_jsonl(output_dir / "publications.jsonl")
    document_summaries, document_errors = read_jsonl(output_dir / "document_summaries.jsonl")
    procedure_summaries, procedure_errors = read_jsonl(output_dir / "procedure_summaries.jsonl")
    evidence_spans, evidence_errors = read_jsonl(output_dir / "publication_evidence_spans.jsonl")

    setup_issues: list[dict[str, Any]] = []
    for file_name, errors in {
        "publications.jsonl": publication_errors,
        "document_summaries.jsonl": document_errors,
        "procedure_summaries.jsonl": procedure_errors if include_procedures else [],
        "publication_evidence_spans.jsonl": evidence_errors,
    }.items():
        for error in errors:
            setup_issues.append(issue("error", "jsonl_read_error", error, source=file_name))

    publication_by_doc = {str(row.get("doc_id")): row for row in publications if row.get("doc_id")}
    document_by_doc = {str(row.get("doc_id")): row for row in document_summaries if row.get("doc_id")}
    procedures_by_doc: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in procedure_summaries:
        if row.get("doc_id"):
            procedures_by_doc[str(row.get("doc_id"))].append(row)
    evidence_by_id = {str(row.get("source_span_id")): row for row in evidence_spans if row.get("source_span_id")}

    candidate_doc_ids = list(document_by_doc)
    if include_procedures:
        candidate_doc_ids.extend(procedures_by_doc)
    sampled_doc_ids = sample_doc_ids(candidate_doc_ids, sample_size=sample_size, seed=seed)

    deterministic_issues = setup_issues[:]
    document_metrics: list[dict[str, Any]] = []
    for doc_id in sampled_doc_ids:
        metrics, row_issues = deterministic_check_document(
            doc_id=doc_id,
            document_summary=document_by_doc.get(doc_id),
            procedures=procedures_by_doc.get(doc_id, []),
            evidence_by_id=evidence_by_id,
            include_procedures=include_procedures,
        )
        document_metrics.append(metrics)
        deterministic_issues.extend(row_issues)

    llm_judge = {"used": False, "reason": "client was not provided", "results": [], "issue_counts": count_issues([])}
    llm_issues: list[dict[str, Any]] = []
    if client is not None and sampled_doc_ids:
        llm_judge, llm_issues = run_llm_judge(
            client=client,
            sampled_doc_ids=sampled_doc_ids,
            publication_by_doc=publication_by_doc,
            document_by_doc=document_by_doc,
            procedures_by_doc=procedures_by_doc,
            evidence_by_id=evidence_by_id,
            include_procedures=include_procedures,
        )

    all_issues = deterministic_issues + llm_issues
    counts = count_issues(all_issues)
    gate_reasons: list[str] = []
    if counts["by_severity"].get("error", 0):
        gate_reasons.append("deterministic summary audit has blocking errors")
    failed_judgements = [
        row
        for row in llm_judge.get("results", [])
        if row.get("verdict") == "fail" or row.get("hallucination_risk") == "high"
    ]
    if failed_judgements:
        gate_reasons.append("LLM judge found failed or high hallucination-risk summaries")
    if not sampled_doc_ids and sample_size > 0:
        gate_reasons.append("no document ids were available for summary audit")

    return {
        "generated_at": utc_now(),
        "output_dir": str(output_dir),
        "sample_size": len(sampled_doc_ids),
        "requested_sample_size": sample_size,
        "seed": seed,
        "include_procedures": include_procedures,
        "sampled_doc_ids": sampled_doc_ids,
        "counts": {
            "publications": len(publications),
            "document_summaries": len(document_summaries),
            "procedure_summaries": len(procedure_summaries),
            "publication_evidence_spans": len(evidence_spans),
        },
        "deterministic_checks": {
            "checked_doc_ids": sampled_doc_ids,
            "document_metrics": document_metrics,
            "issue_counts": count_issues(deterministic_issues),
            "issues": deterministic_issues,
        },
        "llm_judge": llm_judge,
        "issue_counts": counts,
        "gate": {
            "summary_audit_ready": not gate_reasons,
            "reasons": gate_reasons,
            "blocking_error_count": counts["by_severity"].get("error", 0),
            "warning_count": counts["by_severity"].get("warning", 0),
        },
    }


def build_and_write_summary_quality_report(
    output_dir: Path,
    *,
    client: CompletionClient | None = None,
    sample_size: int = 10,
    seed: int = 1729,
    include_procedures: bool = True,
    report_path: Path | None = None,
) -> dict[str, Any]:
    report = build_summary_quality_report(
        output_dir,
        client=client,
        sample_size=sample_size,
        seed=seed,
        include_procedures=include_procedures,
    )
    write_summary_quality_report(report, report_path or (Path(output_dir) / SUMMARY_REPORT_NAME))
    return report


def audit_summary_quality(
    output_dir: Path,
    *,
    client: CompletionClient | None = None,
    sample_size: int = 10,
    seed: int = 1729,
    include_procedures: bool = True,
) -> dict[str, Any]:
    """Run the sampled audit and save summary_quality_report.json in output_dir."""
    return build_and_write_summary_quality_report(
        output_dir,
        client=client,
        sample_size=sample_size,
        seed=seed,
        include_procedures=include_procedures,
    )
