from __future__ import annotations

from collections.abc import Iterator


def iter_chunks(text: str, target_chars: int = 3500, overlap_chars: int = 400, min_chars: int = 300) -> Iterator[str]:
    normalized = "\n".join(line for line in (line.strip() for line in text.splitlines()) if line)
    if len(normalized) <= target_chars:
        if len(normalized) >= min_chars:
            yield normalized
        return

    start = 0
    while start < len(normalized):
        end = min(start + target_chars, len(normalized))
        if end < len(normalized):
            split_at = max(normalized.rfind("\n", start, end), normalized.rfind(". ", start, end))
            if split_at > start + min_chars:
                end = split_at + 1
        chunk = normalized[start:end].strip()
        if len(chunk) >= min_chars:
            yield chunk
        if end >= len(normalized):
            break
        start = max(0, end - overlap_chars)


def chunk_text(text: str, target_chars: int = 3500, overlap_chars: int = 400, min_chars: int = 300) -> list[str]:
    return list(iter_chunks(text, target_chars=target_chars, overlap_chars=overlap_chars, min_chars=min_chars))
