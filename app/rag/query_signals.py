from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from typing import Any, Iterable


TOKEN_RE = re.compile(r"[\w.+#%-]+", re.UNICODE)
SLOT_NOISE_RE = re.compile(
    r"\b(?:procedure\s+summary|document\s+summary|materials\s+science|metallurgy\s+publication|publication\s+summary)\b",
    re.IGNORECASE,
)


DEFAULT_DOMAIN_LEXICON: dict[str, tuple[str, ...]] = {
    "nickel": (
        "nickel",
        "ni",
        "никель",
        "никеля",
        "никелю",
        "никелем",
        "никелев",
        "никелевый",
        "никелевая",
        "никелевые",
        "никелевых",
        "никелевого",
        "никелист",
        "никелистый",
        "никелистого",
    ),
    "copper": ("copper", "cu", "медь", "меди", "медный", "медная", "медные", "медных"),
    "cobalt": ("cobalt", "co", "кобальт", "кобальта", "кобальтовый", "кобальтовые"),
    "ore": ("ore", "ores", "руда", "руды", "руде", "руд", "рудный", "рудная", "рудные", "рудного", "сырье", "сырья"),
    "concentrate": (
        "concentrate",
        "concentrates",
        "концентрат",
        "концентрата",
        "концентраты",
        "концентратов",
        "концентрирование",
    ),
    "leaching": (
        "leaching",
        "выщелачивание",
        "выщелачивания",
        "выщелачиван",
        "гидрометаллургия",
        "гидрометаллургический",
    ),
    "flotation": ("flotation", "floatation", "флотация", "флотации", "флотационный", "флотационная", "флотационн"),
    "gold": ("gold", "au", "золото", "золота", "золотой", "золотые", "драгметалл", "драгоценный"),
}

DEFAULT_PHRASES_BY_CONCEPTS: dict[frozenset[str], tuple[str, ...]] = {
    frozenset({"nickel", "ore"}): (
        "nickel ore",
        "nickel ores",
        "ni ore",
        "никелевая руда",
        "никелевые руды",
        "никелевых руд",
        "никелевой руды",
        "медно никелевые руды",
        "медно-никелевые руды",
        "медно-никелевых руд",
    ),
    frozenset({"nickel", "concentrate"}): (
        "nickel concentrate",
        "nickel concentrates",
        "ni concentrate",
        "никелевый концентрат",
        "никелевые концентраты",
        "никелевых концентратов",
    ),
    frozenset({"copper", "ore"}): ("copper ore", "copper ores", "медная руда", "медные руды", "медных руд"),
    frozenset({"cobalt", "leaching"}): ("cobalt leaching", "выщелачивание кобальта", "кобальтовое выщелачивание"),
}


@dataclass(frozen=True)
class QuerySignals:
    original_query: str
    search_query: str
    tokens: tuple[str, ...]
    domain_concepts: tuple[str, ...]
    domain_terms: tuple[str, ...]
    phrases: tuple[str, ...]

    def as_dict(self) -> dict[str, Any]:
        return {
            "original_query": self.original_query,
            "search_query": self.search_query,
            "tokens": list(self.tokens),
            "domain_concepts": list(self.domain_concepts),
            "domain_terms": list(self.domain_terms),
            "phrases": list(self.phrases),
        }


@dataclass(frozen=True)
class TextSignalScore:
    phrase: float = 0.0
    domain: float = 0.0
    field: float = 0.0
    freshness: float = 0.0
    confidence: float = 0.0
    matched_terms: tuple[str, ...] = ()
    matched_phrases: tuple[str, ...] = ()
    matched_concepts: tuple[str, ...] = ()
    reasons: tuple[str, ...] = ()

    def components(self) -> dict[str, float]:
        return {
            "phrase": self.phrase,
            "domain": self.domain,
            "field": self.field,
            "freshness": self.freshness,
            "confidence": self.confidence,
        }


@dataclass(frozen=True)
class SignalWeights:
    dense: float = 1.0
    lexical: float = 1.0
    summary_lexical: float = 1.0
    summary_vector: float = 1.0
    phrase: float = 0.05
    domain: float = 0.08
    field: float = 0.03
    table: float = 1.0
    graph: float = 1.0
    freshness: float = 0.01
    confidence: float = 0.01

    @classmethod
    def from_config(cls, config: dict[str, Any] | None) -> "SignalWeights":
        raw = ((config or {}).get("search") or {}).get("weights") or {}
        values = {}
        for field_name in cls.__dataclass_fields__:
            if field_name in raw:
                values[field_name] = float(raw[field_name])
        return cls(**values)


def normalize_text(value: Any) -> str:
    text = unicodedata.normalize("NFKC", str(value or "")).casefold().replace("ё", "е")
    text = SLOT_NOISE_RE.sub(" ", text)
    text = text.replace("медно-никел", "медно никел")
    text = re.sub(r"\s+", " ", text).strip()
    return text


def tokenize(value: Any, *, max_terms: int = 64) -> tuple[str, ...]:
    tokens: list[str] = []
    seen: set[str] = set()
    for token in TOKEN_RE.findall(normalize_text(value)):
        token = token.strip(".+#%-_")
        if len(token) < 2 or token in seen:
            continue
        seen.add(token)
        tokens.append(token)
        if len(tokens) >= max_terms:
            break
    return tuple(tokens)


def clean_search_query(value: str) -> str:
    cleaned = normalize_text(value)
    cleaned = SLOT_NOISE_RE.sub(" ", cleaned)
    cleaned = re.sub(r"\b(?:raw_rag|summary_rag|table_search|graph_search|internal_rag|web_search)\b", " ", cleaned)
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    return cleaned


def _aliases_from_config(config: dict[str, Any] | None) -> dict[str, tuple[str, ...]]:
    configured = ((config or {}).get("domain_lexicon") or {})
    aliases = {key: tuple(values) for key, values in DEFAULT_DOMAIN_LEXICON.items()}
    for concept, values in configured.items():
        if isinstance(values, str):
            values = [values]
        if not isinstance(values, list):
            continue
        normalized_values = tuple(str(value) for value in values if str(value).strip())
        if normalized_values:
            aliases[str(concept)] = tuple(dict.fromkeys((*aliases.get(str(concept), ()), *normalized_values)))
    return aliases


def alias_matches_text(alias: str, normalized_text: str, tokens: set[str]) -> bool:
    normalized_alias = normalize_text(alias)
    if not normalized_alias:
        return False
    if len(normalized_alias) <= 3 and normalized_alias.isascii():
        return normalized_alias in tokens
    if " " in normalized_alias or "-" in normalized_alias:
        return normalized_alias in normalized_text
    return any(token == normalized_alias or token.startswith(normalized_alias) for token in tokens)


def concepts_in_text(text: Any, aliases: dict[str, tuple[str, ...]]) -> dict[str, tuple[str, ...]]:
    normalized = normalize_text(text)
    tokens = set(tokenize(normalized, max_terms=10000))
    matches: dict[str, tuple[str, ...]] = {}
    for concept, concept_aliases in aliases.items():
        matched = tuple(alias for alias in concept_aliases if alias_matches_text(alias, normalized, tokens))
        if matched:
            matches[concept] = matched
    return matches


def extract_phrases(query: str, concepts: Iterable[str], *, max_phrases: int = 24) -> tuple[str, ...]:
    phrases: list[str] = []
    normalized_query = clean_search_query(query)
    query_tokens = list(tokenize(normalized_query, max_terms=12))
    for size in (3, 2):
        for index in range(0, max(0, len(query_tokens) - size + 1)):
            phrase = " ".join(query_tokens[index : index + size])
            if phrase and phrase not in phrases:
                phrases.append(phrase)
    concept_set = set(concepts)
    for required, values in DEFAULT_PHRASES_BY_CONCEPTS.items():
        if required.issubset(concept_set):
            for value in values:
                normalized = normalize_text(value)
                if normalized and normalized not in phrases:
                    phrases.append(normalized)
    return tuple(phrases[:max_phrases])


def extract_query_signals(query: str, config: dict[str, Any] | None = None) -> QuerySignals:
    search_query = clean_search_query(query)
    aliases = _aliases_from_config(config)
    concept_matches = concepts_in_text(search_query, aliases)
    concepts = tuple(concept for concept in aliases if concept in concept_matches)
    domain_terms = tuple(dict.fromkeys(alias for concept in concepts for alias in concept_matches[concept]))
    tokens = tokenize(search_query)
    phrases = extract_phrases(search_query, concepts)
    return QuerySignals(
        original_query=query,
        search_query=search_query,
        tokens=tokens,
        domain_concepts=concepts,
        domain_terms=domain_terms,
        phrases=phrases,
    )


def rank_component(rank: int, *, rrf_k: int = 60, weight: float = 1.0) -> float:
    if rank <= 0:
        return 0.0
    return weight / float(rrf_k + rank)


def field_text(*values: Any) -> str:
    return " ".join(str(value or "") for value in values if value not in (None, "", [], {}))


def text_signal_score(
    *,
    signals: QuerySignals,
    body_text: str,
    field_values: Iterable[Any] = (),
    row: dict[str, Any] | None = None,
    config: dict[str, Any] | None = None,
    weights: SignalWeights | None = None,
) -> TextSignalScore:
    weights = weights or SignalWeights.from_config(config)
    aliases = _aliases_from_config(config)
    combined = f"{field_text(*field_values)}\n{body_text}"
    normalized = normalize_text(combined)
    normalized_body = normalize_text(body_text)
    normalized_fields = normalize_text(field_text(*field_values))
    tokens = set(tokenize(normalized, max_terms=20000))

    matched_terms = tuple(term for term in signals.tokens if alias_matches_text(term, normalized, tokens))
    matched_phrases = tuple(phrase for phrase in signals.phrases if phrase and phrase in normalized)
    candidate_concepts = concepts_in_text(combined, aliases)
    matched_concepts = tuple(concept for concept in signals.domain_concepts if concept in candidate_concepts)

    phrase_score = 0.0
    if signals.phrases:
        phrase_score = min(1.0, len(matched_phrases) / max(len(signals.phrases[:4]), 1)) * weights.phrase
    domain_score = 0.0
    if signals.domain_concepts:
        domain_score = len(matched_concepts) / max(len(signals.domain_concepts), 1) * weights.domain
    field_matches = tuple(term for term in (*signals.tokens, *signals.domain_terms) if term and term in normalized_fields)
    field_score = min(1.0, len(set(field_matches)) / max(len(signals.tokens), 1)) * weights.field if normalized_fields else 0.0

    freshness_score = freshness_component(row or {}) * weights.freshness
    confidence_score = confidence_component(row or {}, matched_terms=matched_terms, matched_concepts=matched_concepts) * weights.confidence

    reasons: list[str] = []
    if matched_concepts:
        reasons.append("domain concepts: " + ", ".join(matched_concepts))
    if matched_phrases:
        reasons.append("phrases: " + ", ".join(matched_phrases[:4]))
    if field_score > 0:
        reasons.append("metadata/source fields match query")
    if freshness_score > 0:
        reasons.append("freshness/date signal")
    if confidence_score > 0:
        reasons.append("confidence signal")
    if matched_terms and not (matched_concepts or matched_phrases):
        reasons.append("query terms: " + ", ".join(matched_terms[:6]))

    # Keep body normalization referenced so static checkers do not flag it when debug code is removed.
    _ = normalized_body
    return TextSignalScore(
        phrase=phrase_score,
        domain=domain_score,
        field=field_score,
        freshness=freshness_score,
        confidence=confidence_score,
        matched_terms=matched_terms,
        matched_phrases=matched_phrases,
        matched_concepts=matched_concepts,
        reasons=tuple(reasons),
    )


def freshness_component(row: dict[str, Any]) -> float:
    raw_values = [
        row.get("source_actualization_date"),
        row.get("publication_date"),
        row.get("date"),
        row.get("year"),
        (row.get("additional_domain_fields") or {}).get("source_actualization_date")
        if isinstance(row.get("additional_domain_fields"), dict)
        else None,
    ]
    year: int | None = None
    for value in raw_values:
        if value in (None, ""):
            continue
        parsed = parse_year(value)
        if parsed:
            year = parsed
            break
    if year is None:
        return 0.0
    current_year = datetime.now(timezone.utc).year
    age = max(0, current_year - year)
    if age <= 3:
        return 1.0
    if age >= 20:
        return 0.1
    return max(0.1, 1.0 - (age - 3) / 20.0)


def parse_year(value: Any) -> int | None:
    if isinstance(value, (datetime, date)):
        return int(value.year)
    text = str(value)
    match = re.search(r"(19|20)\d{2}", text)
    if not match:
        return None
    year = int(match.group(0))
    if 1900 <= year <= 2100:
        return year
    return None


def confidence_component(
    row: dict[str, Any],
    *,
    matched_terms: tuple[str, ...] = (),
    matched_concepts: tuple[str, ...] = (),
) -> float:
    raw = row.get("confidence")
    if raw is None and isinstance(row.get("additional_domain_fields"), dict):
        raw = (row.get("additional_domain_fields") or {}).get("confidence")
    try:
        confidence = float(raw)
    except (TypeError, ValueError):
        confidence = 0.5
    evidence_bonus = min(0.4, 0.1 * len(matched_terms) + 0.15 * len(matched_concepts))
    return max(0.0, min(1.0, confidence + evidence_bonus))


def merge_reasons(existing: tuple[str, ...], additions: Iterable[str], *, limit: int = 8) -> tuple[str, ...]:
    result = list(existing)
    for item in additions:
        if item and item not in result:
            result.append(item)
        if len(result) >= limit:
            break
    return tuple(result)
