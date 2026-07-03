from __future__ import annotations

import csv
import heapq
import json
import re
import unicodedata
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable, Iterator, Sequence


TOKEN_RE = re.compile(r"[\w.+#%-]+", re.UNICODE)
CSV_MARKER = ("data", "parsed", "spreadsheets_csv")


@dataclass(frozen=True)
class SpreadsheetSheet:
    doc_id: str
    file_name: str
    extension: str
    parser: str
    source_path: str
    local_path: str
    sheet_index: int
    sheet_name: str
    rows: int
    columns: int
    csv_path: Path
    csv_size: int | None = None
    preview_rows: int | None = None
    preview_columns: int | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def search_text(self) -> str:
        return " ".join(
            value
            for value in (
                self.doc_id,
                self.file_name,
                self.extension,
                self.parser,
                self.source_path,
                self.local_path,
                self.sheet_name,
            )
            if value
        )

    def as_dict(self) -> dict[str, Any]:
        return {
            "doc_id": self.doc_id,
            "file_name": self.file_name,
            "extension": self.extension,
            "parser": self.parser,
            "source_path": self.source_path,
            "local_path": self.local_path,
            "sheet_index": self.sheet_index,
            "sheet_name": self.sheet_name,
            "rows": self.rows,
            "columns": self.columns,
            "csv_path": str(self.csv_path),
            "csv_size": self.csv_size,
            "preview_rows": self.preview_rows,
            "preview_columns": self.preview_columns,
        }


@dataclass(frozen=True)
class SpreadsheetSheetHit:
    rank: int
    score: float
    matched_terms: tuple[str, ...]
    sheet: SpreadsheetSheet

    def as_dict(self) -> dict[str, Any]:
        return {
            "rank": self.rank,
            "score": round(self.score, 6),
            "matched_terms": list(self.matched_terms),
            "sheet": self.sheet.as_dict(),
        }


@dataclass(frozen=True)
class SpreadsheetRowHit:
    rank: int
    score: float
    row_number: int
    matched_terms: tuple[str, ...]
    row: tuple[str, ...]
    sheet: SpreadsheetSheet

    def row_text(self) -> str:
        return " | ".join(cell for cell in self.row if cell)

    def as_dict(self) -> dict[str, Any]:
        return {
            "rank": self.rank,
            "score": round(self.score, 6),
            "row_number": self.row_number,
            "matched_terms": list(self.matched_terms),
            "row": list(self.row),
            "row_text": self.row_text(),
            "sheet": self.sheet.as_dict(),
        }


class SpreadsheetStore:
    def __init__(self, documents_path: Path, *, root: Path | None = None) -> None:
        self.documents_path = documents_path
        self.root = root or infer_project_root(documents_path)
        self._sheets: list[SpreadsheetSheet] | None = None

    def iter_sheets(self, *, doc_ids: Iterable[str] | None = None) -> Iterator[SpreadsheetSheet]:
        selected_doc_ids = set(doc_ids or [])
        for sheet in self._load_sheets():
            if selected_doc_ids and sheet.doc_id not in selected_doc_ids:
                continue
            yield sheet

    def get_workbook_sheets(self, doc_id: str) -> list[SpreadsheetSheet]:
        return list(self.iter_sheets(doc_ids=[doc_id]))

    def search_sheets(
        self,
        query: str,
        *,
        top_k: int = 20,
        doc_ids: Iterable[str] | None = None,
        sheet_name: str | None = None,
    ) -> list[SpreadsheetSheetHit]:
        terms = query_terms(query)
        if not terms or top_k <= 0:
            return []
        hits: list[tuple[float, SpreadsheetSheet, tuple[str, ...]]] = []
        for sheet in self.iter_sheets(doc_ids=doc_ids):
            if sheet_name and normalize_text(sheet_name) not in normalize_text(sheet.sheet_name):
                continue
            score, matched = score_text(sheet.search_text(), terms, phrase=query)
            if score <= 0:
                continue
            hits.append((score, sheet, tuple(matched)))
        ranked = sorted(hits, key=lambda item: item[0], reverse=True)[:top_k]
        return [
            SpreadsheetSheetHit(rank=rank, score=score, matched_terms=matched, sheet=sheet)
            for rank, (score, sheet, matched) in enumerate(ranked, start=1)
        ]

    def search_rows(
        self,
        query: str,
        *,
        top_k: int = 20,
        doc_ids: Iterable[str] | None = None,
        sheet_name: str | None = None,
        min_term_matches: int = 1,
        max_sheets: int | None = None,
        max_rows_per_sheet: int | None = None,
    ) -> list[SpreadsheetRowHit]:
        terms = query_terms(query)
        if not terms or top_k <= 0:
            return []

        hits: list[tuple[float, int, SpreadsheetRowHit]] = []
        sequence = 0
        scanned_sheets = 0
        for sheet in self.iter_sheets(doc_ids=doc_ids):
            if sheet_name and normalize_text(sheet_name) not in normalize_text(sheet.sheet_name):
                continue
            if max_sheets is not None and scanned_sheets >= max_sheets:
                break
            scanned_sheets += 1
            if not sheet.csv_path.exists():
                continue
            sheet_score, sheet_terms = score_text(sheet.search_text(), terms, phrase=query)
            for row_number, row, row_score, row_terms in find_rows(
                sheet.csv_path,
                terms,
                phrase=query,
                min_term_matches=min_term_matches,
                max_rows=max_rows_per_sheet,
            ):
                matched = tuple(sorted(set(row_terms).union(sheet_terms), key=terms.index))
                sequence += 1
                hit = SpreadsheetRowHit(
                    rank=0,
                    score=row_score + (0.25 * sheet_score),
                    row_number=row_number,
                    matched_terms=matched,
                    row=tuple(row),
                    sheet=sheet,
                )
                heap_item = (hit.score, -sequence, hit)
                if len(hits) < top_k:
                    heapq.heappush(hits, heap_item)
                elif heap_item > hits[0]:
                    heapq.heapreplace(hits, heap_item)

        ranked = [item[2] for item in sorted(hits, key=lambda item: (item[0], item[1]), reverse=True)]
        return [
            SpreadsheetRowHit(
                rank=rank,
                score=hit.score,
                row_number=hit.row_number,
                matched_terms=hit.matched_terms,
                row=hit.row,
                sheet=hit.sheet,
            )
            for rank, hit in enumerate(ranked, start=1)
        ]

    def _load_sheets(self) -> list[SpreadsheetSheet]:
        if self._sheets is None:
            self._sheets = list(iter_workbook_sheets(self.documents_path, root=self.root))
        return self._sheets


def infer_project_root(path: Path) -> Path:
    resolved = path.resolve()
    if resolved.name == "documents.jsonl" and len(resolved.parents) >= 3:
        return resolved.parents[2]
    return resolved.parent


def iter_jsonl(path: Path) -> Iterator[dict[str, Any]]:
    if not path.exists():
        return
    with path.open("r", encoding="utf-8") as file:
        for line in file:
            line = line.strip()
            if line:
                yield json.loads(line)


def iter_workbook_sheets(documents_path: Path, *, root: Path | None = None) -> Iterator[SpreadsheetSheet]:
    project_root = root or infer_project_root(documents_path)
    for row in iter_jsonl(documents_path):
        metadata = parse_metadata(row.get("metadata_json"))
        sheets = metadata.get("sheets")
        if not isinstance(sheets, list):
            continue
        doc_id = str(row.get("doc_id") or "")
        if not doc_id:
            continue
        for sheet in sheets:
            if not isinstance(sheet, dict):
                continue
            csv_path = resolve_csv_path(sheet.get("csv_path"), root=project_root)
            yield SpreadsheetSheet(
                doc_id=doc_id,
                file_name=str(row.get("file_name") or ""),
                extension=str(row.get("extension") or ""),
                parser=str(row.get("parser") or ""),
                source_path=str(row.get("source_path") or ""),
                local_path=str(row.get("local_path") or ""),
                sheet_index=to_int(sheet.get("sheet_index")),
                sheet_name=str(sheet.get("sheet_name") or ""),
                rows=to_int(sheet.get("rows")),
                columns=to_int(sheet.get("columns")),
                csv_path=csv_path,
                csv_size=to_optional_int(sheet.get("csv_size")),
                preview_rows=to_optional_int(sheet.get("preview_rows")),
                preview_columns=to_optional_int(sheet.get("preview_columns")),
                metadata=sheet,
            )


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


def resolve_csv_path(value: Any, *, root: Path) -> Path:
    raw = str(value or "")
    path = Path(raw)
    if path.is_absolute() and path.exists():
        return path
    parts = tuple(part for part in path.parts if part not in {"\\", "/"})
    marker_start = find_marker(parts, CSV_MARKER)
    if marker_start is not None:
        return root.joinpath(*parts[marker_start:])
    if path.is_absolute():
        return path
    return root / path


def find_marker(parts: Sequence[str], marker: Sequence[str]) -> int | None:
    lowered = tuple(part.casefold() for part in parts)
    marker_lowered = tuple(part.casefold() for part in marker)
    for index in range(0, len(lowered) - len(marker_lowered) + 1):
        if lowered[index : index + len(marker_lowered)] == marker_lowered:
            return index
    return None


def read_sheet_preview(csv_path: Path, *, n_rows: int = 50, max_columns: int | None = None) -> list[list[str]]:
    rows: list[list[str]] = []
    if n_rows <= 0:
        return rows
    with csv_path.open("r", encoding="utf-8-sig", newline="") as file:
        reader = csv.reader(file)
        for row in reader:
            rows.append(clean_row(row, max_columns=max_columns))
            if len(rows) >= n_rows:
                break
    return rows


def find_rows(
    csv_path: Path,
    terms: Sequence[str],
    *,
    phrase: str = "",
    min_term_matches: int = 1,
    max_rows: int | None = None,
) -> Iterator[tuple[int, list[str], float, tuple[str, ...]]]:
    with csv_path.open("r", encoding="utf-8-sig", newline="") as file:
        reader = csv.reader(file)
        for row_index, row in enumerate(reader, start=1):
            if max_rows is not None and row_index > max_rows:
                break
            cleaned = clean_row(row)
            score, matched = score_text(" ".join(cleaned), terms, phrase=phrase)
            if score <= 0 or len(matched) < min_term_matches:
                continue
            yield row_index, cleaned, score, tuple(matched)


def clean_row(row: Iterable[Any], *, max_columns: int | None = None) -> list[str]:
    values = [str(cell).strip() for cell in row]
    if max_columns is not None:
        values = values[:max_columns]
    return values


def query_terms(query: str, *, max_terms: int = 24) -> list[str]:
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


def normalize_text(value: Any) -> str:
    text = unicodedata.normalize("NFKC", str(value or "")).casefold()
    return re.sub(r"\s+", " ", text).strip()


def score_text(text: str, terms: Sequence[str], *, phrase: str = "") -> tuple[float, list[str]]:
    normalized = normalize_text(text)
    matched = [term for term in terms if term in normalized]
    if not matched:
        return 0.0, []
    score = len(matched) / max(len(terms), 1)
    normalized_phrase = normalize_text(phrase)
    if len(normalized_phrase) >= 4 and normalized_phrase in normalized:
        score += 0.5
    return score, matched


def to_int(value: Any) -> int:
    parsed = to_optional_int(value)
    return parsed if parsed is not None else 0


def to_optional_int(value: Any) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None
