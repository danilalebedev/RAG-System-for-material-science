from __future__ import annotations


def chunk_text(text: str, target_chars: int = 3500, overlap_chars: int = 400, min_chars: int = 300) -> list[str]:
    normalized = "\n".join(line.strip() for line in text.splitlines())
    normalized = "\n".join(line for line in normalized.splitlines() if line)
    if len(normalized) <= target_chars:
        return [normalized] if len(normalized) >= min_chars else []

    chunks: list[str] = []
    start = 0
    while start < len(normalized):
        end = min(start + target_chars, len(normalized))
        if end < len(normalized):
            split_at = max(normalized.rfind("\n", start, end), normalized.rfind(". ", start, end))
            if split_at > start + min_chars:
                end = split_at + 1
        chunk = normalized[start:end].strip()
        if len(chunk) >= min_chars:
            chunks.append(chunk)
        if end >= len(normalized):
            break
        start = max(0, end - overlap_chars)
    return chunks

