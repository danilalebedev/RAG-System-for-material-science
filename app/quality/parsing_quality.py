from __future__ import annotations

from collections import Counter
from statistics import median


def quality_label(row: dict) -> str:
    status = row.get("status")
    text_chars = int(row.get("text_chars") or 0)
    extension = row.get("extension", "")
    if status == "unsupported":
        return "unsupported"
    if status == "failed":
        return "failed"
    if text_chars == 0:
        return "empty"
    if extension == ".pdf" and text_chars < 200:
        return "low_text_pdf"
    if text_chars < 500:
        return "low_text"
    return "ok"


def summarize_manifest(rows: list[dict]) -> dict:
    labels = Counter(quality_label(row) for row in rows)
    statuses = Counter(row.get("status", "") for row in rows)
    extensions = Counter(row.get("extension", "") for row in rows)
    text_lengths = [int(row.get("text_chars") or 0) for row in rows if int(row.get("text_chars") or 0) > 0]
    return {
        "file_count": len(rows),
        "statuses": dict(statuses),
        "quality_labels": dict(labels),
        "extensions": dict(extensions),
        "total_text_chars": sum(text_lengths),
        "median_text_chars": int(median(text_lengths)) if text_lengths else 0,
    }

