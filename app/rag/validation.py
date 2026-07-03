from __future__ import annotations

import json
import math
import os
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np

from app.index.embeddings import build_embedding_client, load_retrieval_config
from app.index.lexical import LexicalIndex
from app.index.vector_store import (
    MANIFEST_FILE,
    METADATA_FILE,
    VECTOR_FILE,
    load_manifest,
    load_metadata,
)
from app.rag.retrieval import dense_search, lexical_search, materialize_results, reciprocal_rank_fusion


WORD_RE = re.compile(r"[\w.+#%-]+", re.UNICODE)


@dataclass(frozen=True)
class SearchCase:
    query: str
    expected_terms: tuple[str, ...]
    min_unique_terms: int = 2
    min_top1_terms: int = 1
    min_results: int = 3


@dataclass
class ValidationIssue:
    severity: str
    code: str
    message: str
    details: dict[str, Any] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        return {
            "severity": self.severity,
            "code": self.code,
            "message": self.message,
            "details": self.details,
        }


@dataclass
class SearchValidationResult:
    query: str
    status: str
    expected_terms: list[str]
    unique_terms_found: list[str]
    top1_terms_found: list[str]
    result_count: int
    top_results: list[dict[str, Any]]
    issues: list[ValidationIssue] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return {
            "query": self.query,
            "status": self.status,
            "expected_terms": self.expected_terms,
            "unique_terms_found": self.unique_terms_found,
            "top1_terms_found": self.top1_terms_found,
            "result_count": self.result_count,
            "top_results": self.top_results,
            "issues": [issue.as_dict() for issue in self.issues],
        }


DEFAULT_SEARCH_CASES = [
    SearchCase(
        query="никелевые концентраты обжиг",
        expected_terms=("никел", "концентрат", "обжиг", "плавк"),
        min_unique_terms=2,
        min_top1_terms=1,
    ),
    SearchCase(
        query="флотация медно никелевых руд",
        expected_terms=("флотац", "мед", "никел", "руд"),
        min_unique_terms=2,
        min_top1_terms=1,
    ),
    SearchCase(
        query="выщелачивание никеля кобальта",
        expected_terms=("выщелач", "никел", "кобальт", "гидрометаллург"),
        min_unique_terms=2,
        min_top1_terms=1,
    ),
    SearchCase(
        query="платиновые металлы извлечение",
        expected_terms=("платин", "мпг", "драг", "извлеч"),
        min_unique_terms=2,
        min_top1_terms=1,
    ),
    SearchCase(
        query="серная кислота автоклавное окисление",
        expected_terms=("сернокислот", "серн", "автоклав", "окисл"),
        min_unique_terms=2,
        min_top1_terms=1,
    ),
]


def normalize_text(value: str) -> str:
    return " ".join(WORD_RE.findall(value.lower().replace("ё", "е")))


def matching_terms(text: str, expected_terms: list[str]) -> list[str]:
    normalized = normalize_text(text)
    return sorted({term for term in expected_terms if term.lower().replace("ё", "е") in normalized})


def validate_vector_artifacts(
    *,
    index_dir: Path,
    sample_size: int = 4096,
    full_vector_scan: bool = False,
) -> tuple[dict[str, Any], list[ValidationIssue]]:
    issues: list[ValidationIssue] = []
    summary: dict[str, Any] = {
        "index_dir": str(index_dir),
        "exists": index_dir.exists(),
    }
    required = [VECTOR_FILE, METADATA_FILE, MANIFEST_FILE]
    missing = [name for name in required if not (index_dir / name).exists()]
    if missing:
        issues.append(ValidationIssue("error", "missing_vector_artifact", "required vector artifacts are missing", {"missing": missing}))
        summary["missing"] = missing
        return summary, issues

    manifest = load_manifest(index_dir)
    metadata = load_metadata(index_dir)
    matrix = np.load(index_dir / VECTOR_FILE, mmap_mode="r")
    summary.update(
        {
            "manifest": manifest,
            "metadata_count": len(metadata),
            "vector_shape": list(matrix.shape),
            "vector_dtype": str(matrix.dtype),
        }
    )
    expected_count = int(manifest.get("chunk_count") or 0)
    expected_dim = int(manifest.get("dimension") or 0)
    if len(metadata) != expected_count:
        issues.append(
            ValidationIssue(
                "error",
                "metadata_count_mismatch",
                "metadata row count does not match manifest chunk_count",
                {"metadata_count": len(metadata), "manifest_chunk_count": expected_count},
            )
        )
    if tuple(matrix.shape) != (expected_count, expected_dim):
        issues.append(
            ValidationIssue(
                "error",
                "vector_shape_mismatch",
                "vector shape does not match manifest chunk_count/dimension",
                {"vector_shape": list(matrix.shape), "expected": [expected_count, expected_dim]},
            )
        )
    if str(matrix.dtype) != "float32":
        issues.append(ValidationIssue("error", "vector_dtype_mismatch", "vector matrix must be float32", {"dtype": str(matrix.dtype)}))

    row_ids = [row.get("row_id") for row in metadata]
    chunk_ids = [str(row.get("chunk_id") or "") for row in metadata]
    if row_ids != list(range(len(metadata))):
        issues.append(ValidationIssue("error", "row_id_not_contiguous", "metadata row_id must be contiguous from zero"))
    if len(set(chunk_ids)) != len(chunk_ids):
        issues.append(ValidationIssue("error", "duplicate_chunk_ids", "metadata contains duplicate chunk_id values"))

    if matrix.shape[0] > 0 and matrix.shape[1] > 0:
        sample_indices = sample_vector_rows(matrix.shape[0], sample_size=sample_size, full_scan=full_vector_scan)
        sample = np.asarray(matrix[sample_indices], dtype=np.float32)
        finite = bool(np.isfinite(sample).all())
        norms = np.linalg.norm(sample, axis=1)
        min_norm = float(norms.min()) if len(norms) else math.nan
        max_norm = float(norms.max()) if len(norms) else math.nan
        summary["sampled_rows"] = len(sample_indices)
        summary["sample_norm_min"] = min_norm
        summary["sample_norm_max"] = max_norm
        if not finite:
            issues.append(ValidationIssue("error", "vector_nonfinite", "sampled vectors contain NaN or infinite values"))
        if min_norm < 0.95 or max_norm > 1.05:
            issues.append(
                ValidationIssue(
                    "warning",
                    "vector_norm_out_of_range",
                    "sampled vectors are not close to unit norm",
                    {"min_norm": min_norm, "max_norm": max_norm},
                )
            )
    return summary, issues


def sample_vector_rows(row_count: int, *, sample_size: int, full_scan: bool) -> np.ndarray:
    if full_scan or row_count <= sample_size:
        return np.arange(row_count)
    return np.unique(np.linspace(0, row_count - 1, num=sample_size, dtype=np.int64))


def validate_lexical_artifacts(*, lexical_dir: Path) -> tuple[dict[str, Any], list[ValidationIssue]]:
    issues: list[ValidationIssue] = []
    db_path = lexical_dir / "chunks.sqlite"
    manifest_path = lexical_dir / "manifest.json"
    summary = {
        "lexical_dir": str(lexical_dir),
        "db_exists": db_path.exists(),
        "manifest_exists": manifest_path.exists(),
    }
    if not db_path.exists():
        issues.append(ValidationIssue("error", "missing_lexical_db", "SQLite FTS lexical index is missing", {"path": str(db_path)}))
    if manifest_path.exists():
        summary["manifest"] = json.loads(manifest_path.read_text(encoding="utf-8"))
    return summary, issues


def run_search_case(
    *,
    case: SearchCase,
    root: Path,
    retrieval_config: dict[str, Any],
    index_dir: Path,
    lexical_dir: Path,
    chunks_path: Path,
    mode: str,
    top_k: int,
    allow_network: bool,
) -> SearchValidationResult:
    issues: list[ValidationIssue] = []
    manifest = load_manifest(index_dir)
    search_config = retrieval_config.get("search") or {}
    dense_top_k = max(top_k, int(search_config.get("dense_top_k") or 50))
    lexical_top_k = max(top_k, int(search_config.get("lexical_top_k") or 50))
    preview_chars = int(search_config.get("snippet_chars") or 700)
    rrf_k = int(search_config.get("rrf_k") or 60)
    vector_batch_size = int(search_config.get("vector_batch_size") or 8192)
    backend = str(manifest.get("embedding_backend") or (retrieval_config.get("embedding") or {}).get("backend") or "yandex")

    dense_hits = []
    lexical_hits = []
    if mode in {"hybrid", "dense"}:
        if backend == "yandex" and not allow_network:
            issues.append(
                ValidationIssue(
                    "error",
                    "network_required",
                    "Yandex index needs a live query embedding; rerun with --allow-network or validate a local-hash index",
                )
            )
        else:
            model_selection = "fallback" if manifest.get("model_selection") == "fallback" else "query"
            client = build_embedding_client(
                backend=backend,
                retrieval_config=retrieval_config,
                kind="query",
                fallback_model=model_selection == "fallback",
                api_key=os.getenv("YANDEX_API_KEY"),
                folder_id=os.getenv("YANDEX_FOLDER_ID"),
            )
            dense_hits = dense_search(index_dir, client.embed_text(case.query), top_k=dense_top_k, batch_size=vector_batch_size)
    if mode in {"hybrid", "lexical"} and LexicalIndex(lexical_dir).exists():
        lexical_hits = lexical_search(lexical_dir, case.query, top_k=lexical_top_k)

    if mode == "dense":
        ranked_rows = [(hit.row_id, hit.score, {"dense": hit.score}) for hit in dense_hits[:top_k]]
    elif mode == "lexical":
        ranked_rows = [(hit.row_id, hit.score, {"lexical": hit.score}) for hit in lexical_hits[:top_k]]
    else:
        ranked_rows = reciprocal_rank_fusion(dense_hits=dense_hits, lexical_hits=lexical_hits, rrf_k=rrf_k, top_k=top_k)
    results = materialize_results(ranked_rows=ranked_rows, index_dir=index_dir, chunks_path=chunks_path, snippet_chars=0)

    expected = [term.lower().replace("ё", "е") for term in case.expected_terms]
    corpus = "\n".join(f"{result.source_path}\n{result.text}" for result in results)
    unique_terms = matching_terms(corpus, expected)
    top1_terms = matching_terms(f"{results[0].source_path}\n{results[0].text}", expected) if results else []

    if len(results) < case.min_results:
        issues.append(
            ValidationIssue(
                "error",
                "too_few_results",
                "search returned fewer results than expected",
                {"result_count": len(results), "min_results": case.min_results},
            )
        )
    if len(unique_terms) < case.min_unique_terms:
        issues.append(
            ValidationIssue(
                "error",
                "low_term_coverage",
                "top results do not contain enough expected domain terms",
                {"found": unique_terms, "expected": expected, "min_unique_terms": case.min_unique_terms},
            )
        )
    if len(top1_terms) < case.min_top1_terms:
        issues.append(
            ValidationIssue(
                "error",
                "top1_not_relevant",
                "top-1 result does not contain enough expected domain terms",
                {"found": top1_terms, "expected": expected, "min_top1_terms": case.min_top1_terms},
            )
        )

    top_results = []
    for result in results[:top_k]:
        row = result.as_dict()
        row["text"] = trim_text(row["text"], preview_chars)
        row["matched_terms"] = matching_terms(f"{result.source_path}\n{result.text}", expected)
        top_results.append(row)
    return SearchValidationResult(
        query=case.query,
        status="pass" if not [issue for issue in issues if issue.severity == "error"] else "fail",
        expected_terms=expected,
        unique_terms_found=unique_terms,
        top1_terms_found=top1_terms,
        result_count=len(results),
        top_results=top_results,
        issues=issues,
    )


def trim_text(text: str, max_chars: int) -> str:
    if max_chars <= 0 or len(text) <= max_chars:
        return text
    return text[: max_chars - 3].rstrip() + "..."


def run_validation(
    *,
    root: Path,
    config_path: Path,
    index_dir: Path,
    lexical_dir: Path,
    chunks_path: Path,
    cases: list[SearchCase] | None = None,
    mode: str = "hybrid",
    top_k: int = 5,
    allow_network: bool = False,
    sample_size: int = 4096,
    full_vector_scan: bool = False,
) -> dict[str, Any]:
    retrieval_config = load_retrieval_config(config_path)
    artifact_summary, artifact_issues = validate_vector_artifacts(
        index_dir=index_dir,
        sample_size=sample_size,
        full_vector_scan=full_vector_scan,
    )
    lexical_summary, lexical_issues = validate_lexical_artifacts(lexical_dir=lexical_dir)
    search_results = [
        run_search_case(
            case=case,
            root=root,
            retrieval_config=retrieval_config,
            index_dir=index_dir,
            lexical_dir=lexical_dir,
            chunks_path=chunks_path,
            mode=mode,
            top_k=top_k,
            allow_network=allow_network,
        )
        for case in (cases or DEFAULT_SEARCH_CASES)
    ]
    issues = [*artifact_issues, *lexical_issues, *(issue for result in search_results for issue in result.issues)]
    status = "pass" if not [issue for issue in issues if issue.severity == "error"] else "fail"
    return {
        "status": status,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "mode": mode,
        "top_k": top_k,
        "allow_network": allow_network,
        "artifacts": artifact_summary,
        "lexical": lexical_summary,
        "search_cases": [result.as_dict() for result in search_results],
        "issues": [issue.as_dict() for issue in issues],
    }


def write_validation_outputs(*, report: dict[str, Any], report_json: Path, results_jsonl: Path) -> None:
    report_json.parent.mkdir(parents=True, exist_ok=True)
    report_json.write_text(json.dumps(report, ensure_ascii=False, indent=2, default=str) + "\n", encoding="utf-8")
    results_jsonl.parent.mkdir(parents=True, exist_ok=True)
    with results_jsonl.open("w", encoding="utf-8", newline="\n") as f:
        for row in report.get("search_cases", []):
            f.write(json.dumps(row, ensure_ascii=False, default=str) + "\n")
