from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from app.web_search.schemas import LiteratureSearchResult


QUARTILE_SCORE_BOOST = {
    "Q1": 5.0,
    "Q2": 3.0,
    "Q3": 1.5,
    "Q4": 0.5,
}
QUARTILE_KEYS = (
    "journal_quartile",
    "quartile",
    "sjr_quartile",
    "scimago_quartile",
    "jcr_quartile",
)


def normalize_venue_name(value: Any) -> str:
    text = re.sub(r"\s+", " ", str(value or "")).strip().lower().replace("ё", "е")
    return re.sub(r"[^a-zа-яе0-9]+", " ", text).strip()


def canonical_quartile(value: Any) -> str | None:
    text = str(value or "").strip().upper()
    if not text:
        return None
    match = re.search(r"\bQ\s*([1-4])\b", text)
    if match:
        return f"Q{match.group(1)}"
    match = re.search(r"\bQUARTILE\s*([1-4])\b", text)
    if match:
        return f"Q{match.group(1)}"
    if text in {"1", "2", "3", "4"}:
        return f"Q{text}"
    return None


def load_quartile_map(path: Path | None) -> dict[str, str]:
    if path is None or not path.exists():
        return {}
    payload = json.loads(path.read_text(encoding="utf-8"))
    raw_venues = payload.get("venues", payload) if isinstance(payload, dict) else {}
    if not isinstance(raw_venues, dict):
        return {}

    result: dict[str, str] = {}
    for venue, value in raw_venues.items():
        if isinstance(value, dict):
            quartile = canonical_quartile(value.get("quartile"))
        else:
            quartile = canonical_quartile(value)
        normalized = normalize_venue_name(venue)
        if normalized and quartile:
            result[normalized] = quartile
    return result


def infer_quartile(result: LiteratureSearchResult, quartile_map: dict[str, str] | None = None) -> str | None:
    for key in QUARTILE_KEYS:
        quartile = canonical_quartile(result.raw.get(key))
        if quartile:
            return quartile

    if quartile_map and result.venue:
        return quartile_map.get(normalize_venue_name(result.venue))
    return None


def quartile_score_boost(quartile: str | None) -> float:
    if not quartile:
        return 0.0
    return QUARTILE_SCORE_BOOST.get(quartile, 0.0)
