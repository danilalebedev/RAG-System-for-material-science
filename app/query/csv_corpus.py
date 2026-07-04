from __future__ import annotations

import json
import re
import unicodedata
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable, Iterator


TABLE_EXTENSIONS = {".csv", ".xlsx", ".xls"}
TOKEN_RE = re.compile(r"[\w.+#%-]+", re.UNICODE)


@dataclass(frozen=True)
class TableSummary:
    path: Path
    sheet: str
    columns: tuple[str, ...]
    row_count: int | None
    source: str = "file"
    doc_id: str = ""
    table_id: str = ""
    source_path: str = ""
    preview: str = ""

    def search_text(self) -> str:
        return " ".join(
            str(value)
            for value in (
                self.path,
                self.sheet,
                self.source,
                self.doc_id,
                self.table_id,
                self.source_path,
                " ".join(self.columns),
                self.preview,
            )
            if value
        )

    def as_dict(self) -> dict[str, Any]:
        return {
            "path": str(self.path),
            "sheet": self.sheet,
            "columns": list(self.columns),
            "row_count": self.row_count,
            "source": self.source,
            "doc_id": self.doc_id,
            "table_id": self.table_id,
            "source_path": self.source_path,
            "preview": self.preview,
        }


@dataclass(frozen=True)
class TableHit:
    rank: int
    score: float
    summary: TableSummary
    matched_terms: tuple[str, ...] = ()
    rows: tuple[dict[str, Any], ...] = field(default_factory=tuple)

    def as_dict(self) -> dict[str, Any]:
        return {
            "rank": self.rank,
            "score": round(self.score, 6),
            "matched_terms": list(self.matched_terms),
            "summary": self.summary.as_dict(),
            "rows": list(self.rows),
        }


def require_polars() -> Any:
    try:
        import polars as pl
    except ModuleNotFoundError as exc:
        raise RuntimeError("polars is required for CSV/table query; install requirements.txt") from exc
    return pl


def is_table_read_error(exc: Exception) -> bool:
    return isinstance(exc, (OSError, RuntimeError, ValueError)) or exc.__class__.__module__.startswith("polars.")


def normalize_text(value: Any) -> str:
    text = unicodedata.normalize("NFKC", str(value or "")).casefold()
    return re.sub(r"\s+", " ", text).strip()


def query_terms(query: str, *, max_terms: int = 32) -> list[str]:
    terms: list[str] = []
    seen: set[str] = set()
    for token in TOKEN_RE.findall(normalize_text(query)):
        token = token.strip(".+#%-_")
        if len(token) < 2 or token in seen:
            continue
        seen.add(token)
        terms.append(token)
        if len(terms) >= max_terms:
            break
    return terms


def score_text(text: str, terms: Iterable[str]) -> tuple[float, tuple[str, ...]]:
    terms = tuple(terms)
    normalized = normalize_text(text)
    matched = tuple(term for term in terms if term in normalized)
    if not matched:
        return 0.0, ()
    return len(matched) / max(len(terms), 1), matched


def find_table_files(roots: Iterable[Path]) -> Iterator[Path]:
    seen: set[Path] = set()
    for root in roots:
        if root.is_file() and root.suffix.casefold() in TABLE_EXTENSIONS:
            resolved = root.resolve()
            if resolved not in seen:
                seen.add(resolved)
                yield root
            continue
        if not root.exists():
            continue
        for path in root.rglob("*"):
            if path.is_file() and path.suffix.casefold() in TABLE_EXTENSIONS:
                resolved = path.resolve()
                if resolved in seen:
                    continue
                seen.add(resolved)
                yield path


def iter_jsonl(path: Path) -> Iterator[dict[str, Any]]:
    if not path.exists():
        return
    with path.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                yield json.loads(line)


def parse_metadata(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    if not value:
        return {}
    try:
        parsed = json.loads(str(value))
    except json.JSONDecodeError:
        return {}
    return parsed if isinstance(parsed, dict) else {}


def resolve_path(value: Any, *, root: Path) -> Path:
    path = Path(str(value or ""))
    if path.is_absolute() and path.exists():
        return path
    if path.is_absolute():
        parts = list(path.parts)
        lowered = [part.casefold() for part in parts]
        marker = ["data", "parsed", "spreadsheets_csv"]
        for index in range(0, len(parts) - len(marker) + 1):
            if lowered[index : index + len(marker)] == marker:
                return root.joinpath(*parts[index:])
        return path
    return root / path


def summaries_from_documents(documents_path: Path, *, root: Path) -> list[TableSummary]:
    summaries: list[TableSummary] = []
    for row in iter_jsonl(documents_path):
        metadata = parse_metadata(row.get("metadata_json"))
        for sheet in metadata.get("sheets") or []:
            if not isinstance(sheet, dict):
                continue
            csv_path = resolve_path(sheet.get("csv_path"), root=root)
            columns = sheet.get("columns")
            column_count = int(columns) if isinstance(columns, int) else None
            summaries.append(
                TableSummary(
                    path=csv_path,
                    sheet=str(sheet.get("sheet_name") or sheet.get("sheet_index") or ""),
                    columns=tuple(f"column_{index + 1}" for index in range(column_count or 0)),
                    row_count=to_optional_int(sheet.get("rows")),
                    source="documents",
                    doc_id=str(row.get("doc_id") or ""),
                    source_path=str(row.get("source_path") or ""),
                )
            )
    return summaries


def summaries_from_tables(tables_path: Path, *, root: Path) -> list[TableSummary]:
    summaries: list[TableSummary] = []
    for row in iter_jsonl(tables_path):
        text = str(row.get("text") or "")
        columns = infer_columns_from_text(text)
        summaries.append(
            TableSummary(
                path=root / "data" / "parsed" / "tables.jsonl",
                sheet=str(row.get("page_or_sheet") or ""),
                columns=tuple(columns),
                row_count=to_optional_int(row.get("row_count")),
                source="tables_jsonl",
                doc_id=str(row.get("doc_id") or ""),
                table_id=str(row.get("table_id") or ""),
                source_path=str(row.get("local_path") or ""),
                preview=text[:1500],
            )
        )
    return summaries


def infer_columns_from_text(text: str, *, max_columns: int = 24) -> list[str]:
    first_line = next((line.strip() for line in text.splitlines() if line.strip()), "")
    if not first_line:
        return []
    separators = ("\t", "|", ";", ",")
    for separator in separators:
        if separator in first_line:
            return [part.strip() for part in first_line.split(separator) if part.strip()][:max_columns]
    return first_line.split()[:max_columns]


def read_table(path: Path, *, sheet: str | None = None, n_rows: int | None = None) -> Any:
    pl = require_polars()
    suffix = path.suffix.casefold()
    if suffix == ".csv":
        return pl.read_csv(path, n_rows=n_rows, ignore_errors=True)
    if suffix in {".xlsx", ".xls"}:
        kwargs: dict[str, Any] = {}
        if sheet:
            kwargs["sheet_name"] = sheet
        df = pl.read_excel(path, **kwargs)
        return df.head(n_rows) if n_rows else df
    raise ValueError(f"unsupported table extension: {path.suffix}")


def schema_summary_for_file(path: Path, *, sample_rows: int = 50) -> TableSummary:
    try:
        df = read_table(path, n_rows=sample_rows)
    except Exception as exc:
        if not is_table_read_error(exc):
            raise
        return TableSummary(
            path=path,
            sheet="" if path.suffix.casefold() == ".csv" else "default",
            columns=(),
            row_count=None,
            source="file",
        )
    row_count: int | None = None
    if path.suffix.casefold() == ".csv":
        row_count = count_csv_rows(path)
    return TableSummary(
        path=path,
        sheet="" if path.suffix.casefold() == ".csv" else "default",
        columns=tuple(str(column) for column in df.columns),
        row_count=row_count if row_count is not None else df.height,
        source="file",
    )


def path_summary_for_file(path: Path) -> TableSummary:
    return TableSummary(
        path=path,
        sheet="" if path.suffix.casefold() == ".csv" else "default",
        columns=(),
        row_count=None,
        source="file",
        preview=path.stem.replace("_", " "),
    )


def count_csv_rows(path: Path) -> int | None:
    try:
        with path.open("rb") as f:
            count = sum(1 for _ in f)
    except OSError:
        return None
    return max(count - 1, 0)


def row_to_text(row: dict[str, Any]) -> str:
    return " | ".join(f"{key}: {value}" for key, value in row.items() if value not in (None, ""))


def search_table_rows(
    summary: TableSummary,
    query: str,
    *,
    max_rows: int = 500,
    top_rows: int = 3,
) -> tuple[float, tuple[str, ...], tuple[dict[str, Any], ...]]:
    terms = query_terms(query)
    table_score, table_matches = score_text(summary.search_text(), terms)
    rows: list[tuple[float, tuple[str, ...], dict[str, Any]]] = []
    if table_score > 0 and summary.path.exists() and summary.path.suffix.casefold() in TABLE_EXTENSIONS:
        try:
            df = read_table(summary.path, sheet=summary.sheet or None, n_rows=max_rows)
        except Exception as exc:
            if not is_table_read_error(exc):
                raise
            df = None
        if df is None:
            return table_score, table_matches, ()
        for row in df.iter_rows(named=True):
            score, matched = score_text(row_to_text(row), terms)
            if score > 0:
                rows.append((score, matched, {str(key): value for key, value in row.items()}))
    rows.sort(key=lambda item: item[0], reverse=True)
    selected = tuple(item[2] for item in rows[:top_rows])
    row_score = rows[0][0] if rows else 0.0
    matched = tuple(sorted(set(table_matches).union(*(set(item[1]) for item in rows[:top_rows]))))
    return table_score + row_score, matched, selected


def build_table_summaries(
    *,
    roots: Iterable[Path],
    documents_path: Path | None = None,
    tables_path: Path | None = None,
    project_root: Path,
    sample_rows: int = 50,
    inspect_files: bool = False,
) -> list[TableSummary]:
    summaries: list[TableSummary] = []
    if documents_path:
        summaries.extend(summaries_from_documents(documents_path, root=project_root))
    if tables_path:
        summaries.extend(summaries_from_tables(tables_path, root=project_root))
    known = {summary.path.resolve() for summary in summaries if summary.path.exists()}
    for path in find_table_files(roots):
        if path.resolve() in known:
            continue
        if inspect_files:
            summaries.append(schema_summary_for_file(path, sample_rows=sample_rows))
        else:
            summaries.append(path_summary_for_file(path))
    return summaries


def search_tables(
    query: str,
    *,
    roots: Iterable[Path],
    documents_path: Path | None,
    tables_path: Path | None,
    project_root: Path,
    top_k: int = 8,
    top_rows: int = 3,
    max_rows_per_table: int = 500,
    sample_rows: int = 50,
) -> list[TableHit]:
    summaries = build_table_summaries(
        roots=roots,
        documents_path=documents_path,
        tables_path=tables_path,
        project_root=project_root,
        sample_rows=sample_rows,
    )
    terms = query_terms(query)
    candidates: list[tuple[float, tuple[str, ...], TableSummary]] = []
    for summary in summaries:
        score, matched = score_text(summary.search_text(), terms)
        if score > 0:
            candidates.append((score, matched, summary))

    candidates.sort(key=lambda item: item[0], reverse=True)
    candidate_count = max(top_k * 8, 32)

    hits: list[TableHit] = []
    for base_score, base_matched, summary in candidates[:candidate_count]:
        enriched = summary
        if summary.source == "file" and summary.path.exists():
            enriched = schema_summary_for_file(summary.path, sample_rows=sample_rows)
        score, matched, rows = search_table_rows(
            enriched,
            query,
            max_rows=max_rows_per_table,
            top_rows=top_rows,
        )
        if score <= 0:
            score, matched = base_score, base_matched
        if score <= 0:
            continue
        hits.append(TableHit(rank=0, score=score, summary=enriched, matched_terms=matched, rows=rows))
    hits.sort(key=lambda hit: hit.score, reverse=True)
    return [
        TableHit(rank=rank, score=hit.score, summary=hit.summary, matched_terms=hit.matched_terms, rows=hit.rows)
        for rank, hit in enumerate(hits[:top_k], start=1)
    ]


def format_table_context(hits: list[TableHit], *, max_chars: int = 10_000) -> str:
    parts: list[str] = []
    used = 0
    for hit in hits:
        summary = hit.summary
        lines = [
            f"[T{hit.rank}] source={summary.source}; doc_id={summary.doc_id}; path={summary.path}",
            f"sheet={summary.sheet}; rows={summary.row_count}; columns={', '.join(summary.columns[:30])}",
        ]
        for index, row in enumerate(hit.rows, start=1):
            lines.append(f"row {index}: {row_to_text(row)}")
        if not hit.rows and summary.preview:
            lines.append(f"preview: {summary.preview[:1000]}")
        block = "\n".join(lines)
        if used + len(block) + 2 > max_chars:
            break
        parts.append(block)
        used += len(block) + 2
    return "\n\n".join(parts)


def to_optional_int(value: Any) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None
