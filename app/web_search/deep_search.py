from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
from typing import Any, Protocol

import requests

from app.extract.publication_metadata import ExtractionConfig, YandexCompletionClient, build_prompt, extract_json_object
from app.io_utils import write_jsonl
from app.web_search.clients import compact_text
from app.web_search.fetch import FetchedExcerpt, safe_fetch_excerpt
from app.web_search.schemas import DeepSearchResult, LiteratureSearchResult


class CompletionClient(Protocol):
    model_uri: str

    def complete(self, prompt: str) -> tuple[str, dict[str, Any]]:
        ...


def stable_web_id(prefix: str, *parts: Any) -> str:
    digest = hashlib.sha256("\n".join(str(part or "") for part in parts).encode("utf-8")).hexdigest()[:16]
    return f"{prefix}_{digest}"


def build_web_source_package(result: LiteratureSearchResult, excerpt: FetchedExcerpt | None) -> str:
    package = {
        "document_metadata": {
            "result_id": result.result_id,
            "source": result.source,
            "title": result.title,
            "authors": result.authors,
            "year": result.year,
            "venue": result.venue,
            "doi": result.doi,
            "url": str(result.url) if result.url else None,
            "open_access_pdf_url": str(result.open_access_pdf_url) if result.open_access_pdf_url else None,
            "citation_count": result.citation_count,
            "reference_count": result.reference_count,
        },
        "abstract": result.abstract,
        "snippet": result.snippet,
        "keyword_hits": result.keyword_hits,
        "safe_excerpt": {
            "url": excerpt.url if excerpt else None,
            "text": compact_text(excerpt.text if excerpt else "", 12_000),
            "content_type": excerpt.content_type if excerpt else None,
            "error": excerpt.error if excerpt else None,
        },
    }
    return json.dumps(package, ensure_ascii=False, indent=2, default=str)[:30_000]


def fallback_summary(result: LiteratureSearchResult, *, status: str, fetched: FetchedExcerpt | None = None) -> DeepSearchResult:
    publication_id = f"webpub_{result.result_id}"
    doc_id = f"web_{result.result_id}"
    summary_text = compact_text(result.abstract or result.snippet or result.title, 1200)
    document_summary = {
        "document_summary_id": f"webdocsum_{result.result_id}",
        "publication_id": publication_id,
        "doc_id": doc_id,
        "result_id": result.result_id,
        "source": result.source,
        "title": result.title,
        "summary": summary_text,
        "main_topic": result.title,
        "materials": [],
        "processes": [],
        "properties": [],
        "methods": [],
        "facilities_or_geography": [],
        "key_findings": [],
        "limitations_or_gaps": ["deep_search summary extraction was not run"],
        "document_kind": "external_literature",
        "confidence": 0.25 if summary_text else 0.1,
        "extraction_status": status,
        "evidence": [{"source_url": str(result.url)}] if result.url else [],
    }
    return DeepSearchResult(
        result_id=result.result_id,
        source_result=result,
        status=status,  # type: ignore[arg-type]
        llm_used=False,
        excerpt_chars=len(fetched.text) if fetched else 0,
        fetched_url=fetched.url if fetched and fetched.text else None,
        fetch_error=fetched.error if fetched else None,
        document_summary=document_summary,
        procedure_summaries=[],
    )


def normalize_llm_deep_result(
    *,
    result: LiteratureSearchResult,
    parsed: dict[str, Any],
    fetched: FetchedExcerpt | None,
) -> DeepSearchResult:
    publication_id = f"webpub_{result.result_id}"
    doc_id = f"web_{result.result_id}"
    llm_summary = parsed.get("document_summary") if isinstance(parsed.get("document_summary"), dict) else {}
    document_summary = {
        **llm_summary,
        "document_summary_id": f"webdocsum_{result.result_id}",
        "publication_id": publication_id,
        "doc_id": doc_id,
        "result_id": result.result_id,
        "source": result.source,
        "title": result.title,
        "document_kind": "external_literature",
        "extraction_status": "ok" if llm_summary else "metadata_only",
        "evidence": [{"source_url": str(result.url)}] if result.url else [],
    }
    procedures: list[dict[str, Any]] = []
    raw_procedures = parsed.get("procedure_summaries") if isinstance(parsed.get("procedure_summaries"), list) else []
    for index, procedure in enumerate(raw_procedures, start=1):
        if not isinstance(procedure, dict):
            continue
        procedures.append(
            {
                **procedure,
                "procedure_summary_id": f"webproc_{result.result_id}_{index:04d}",
                "publication_id": publication_id,
                "doc_id": doc_id,
                "result_id": result.result_id,
                "source": result.source,
                "publications": procedure.get("publications") or [result.title],
                "extraction_status": "ok",
                "evidence": [{"source_url": str(result.url)}] if result.url else [],
            }
        )
    return DeepSearchResult(
        result_id=result.result_id,
        source_result=result,
        status="ok" if (document_summary or procedures) else "metadata_only",
        llm_used=True,
        excerpt_chars=len(fetched.text) if fetched else 0,
        fetched_url=fetched.url if fetched and fetched.text else None,
        fetch_error=fetched.error if fetched else None,
        document_summary=document_summary,
        procedure_summaries=procedures,
    )


def build_yandex_client_from_env(config_path: Path | None = None) -> CompletionClient | None:
    api_key = os.getenv("YANDEX_API_KEY")
    folder_id = os.getenv("YANDEX_FOLDER_ID")
    if not api_key or not folder_id:
        return None
    config = ExtractionConfig.from_file(config_path or Path("config/extraction/publication_metadata.json"))
    return YandexCompletionClient(api_key=api_key, folder_id=folder_id, config=config)


def run_deep_search(
    *,
    results: list[LiteratureSearchResult],
    output_dir: Path,
    mode: str,
    client: CompletionClient | None = None,
    fetch_excerpts: bool = True,
    session: requests.Session | None = None,
    limit: int = 5,
) -> list[DeepSearchResult]:
    output_dir.mkdir(parents=True, exist_ok=True)
    if mode != "top5":
        return []

    deep_results: list[DeepSearchResult] = []
    for result in results[:limit]:
        fetched: FetchedExcerpt | None = None
        fetch_url = str(result.open_access_pdf_url or result.url or "")
        if fetch_excerpts and fetch_url:
            fetched = safe_fetch_excerpt(fetch_url, session=session)
        if client is None:
            deep_results.append(fallback_summary(result, status="no_llm_credentials", fetched=fetched))
            continue
        try:
            source_package = build_web_source_package(result, fetched)
            prompt = build_prompt(source_package)
            raw_response, usage = client.complete(prompt)
            raw_path = output_dir / "llm_raw" / f"{result.result_id}.txt"
            raw_path.parent.mkdir(parents=True, exist_ok=True)
            raw_path.write_text(raw_response, encoding="utf-8")
            parsed = extract_json_object(raw_response)
            deep_result = normalize_llm_deep_result(result=result, parsed=parsed, fetched=fetched)
            deep_result.source_result.raw["llm_usage"] = usage
            deep_results.append(deep_result)
        except Exception as exc:  # noqa: BLE001 - one external paper should not fail the run.
            failed = fallback_summary(result, status="failed", fetched=fetched)
            failed.error = compact_text(exc, 1000)
            deep_results.append(failed)

    write_deep_outputs(output_dir, deep_results)
    return deep_results


def write_deep_outputs(output_dir: Path, deep_results: list[DeepSearchResult]) -> None:
    write_jsonl(output_dir / "web_document_summaries.jsonl", [row.document_summary for row in deep_results if row.document_summary])
    write_jsonl(
        output_dir / "web_procedure_summaries.jsonl",
        [procedure for row in deep_results for procedure in row.procedure_summaries],
    )
    write_jsonl(output_dir / "deep_search_results.jsonl", [row.model_dump(mode="json") for row in deep_results])

