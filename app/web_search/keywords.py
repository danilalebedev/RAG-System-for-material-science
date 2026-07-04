from __future__ import annotations

import re
from collections import Counter
from typing import Any


TOKEN_RE = re.compile(r"[A-Za-zА-Яа-яЁё0-9][A-Za-zА-Яа-яЁё0-9_+.-]*", re.UNICODE)
QUOTE_RE = re.compile(r'"([^"]{2,120})"|«([^»]{2,120})»')

RU_STOPWORDS = {
    "а",
    "без",
    "бы",
    "в",
    "во",
    "для",
    "до",
    "если",
    "же",
    "за",
    "из",
    "или",
    "как",
    "к",
    "ко",
    "на",
    "над",
    "не",
    "но",
    "о",
    "об",
    "от",
    "по",
    "под",
    "при",
    "про",
    "с",
    "со",
    "у",
    "что",
    "чем",
    "это",
    "этот",
    "эта",
    "эти",
    "который",
    "какие",
    "какой",
    "можно",
    "нужно",
    "найти",
    "сравнить",
    "покажи",
    "показать",
    "данные",
    "выполнить",
    "литературный",
    "литературного",
    "литературная",
    "обзор",
    "обзора",
    "отечественная",
    "отечественный",
    "отечественных",
    "мировая",
    "мировой",
    "мировых",
    "зарубежная",
    "зарубежной",
    "зарубежных",
    "практика",
    "практики",
    "предприятие",
    "предприятия",
    "предприятий",
    "цветной",
    "цветная",
    "цветных",
    "метод",
    "методы",
    "методов",
    "методики",
}

EN_STOPWORDS = {
    "a",
    "an",
    "and",
    "are",
    "as",
    "at",
    "be",
    "by",
    "for",
    "from",
    "how",
    "in",
    "into",
    "is",
    "it",
    "of",
    "on",
    "or",
    "the",
    "this",
    "to",
    "was",
    "were",
    "what",
    "which",
    "with",
    "find",
    "compare",
    "method",
    "methods",
    "review",
    "literature",
    "world",
    "domestic",
    "practice",
    "practices",
}

DOMAIN_TERMS = {
    "nickel",
    "copper",
    "cobalt",
    "platinum",
    "palladium",
    "alloy",
    "ore",
    "flotation",
    "leaching",
    "roasting",
    "smelting",
    "annealing",
    "hardness",
    "strength",
    "temperature",
    "pressure",
    "concentration",
    "metallurgy",
    "metallurgical",
    "hydrometallurgy",
    "pyrometallurgy",
    "mining",
    "mine",
    "wastewater",
    "water",
    "acid",
    "drainage",
    "remediation",
    "purification",
    "treatment",
    "neutralization",
    "precipitation",
    "sorption",
    "adsorption",
    "membrane",
    "heavy",
    "metal",
    "никель",
    "никелевые",
    "медь",
    "медные",
    "кобальт",
    "платина",
    "палладий",
    "сплав",
    "руда",
    "флотация",
    "выщелачивание",
    "обжиг",
    "плавка",
    "отжиг",
    "твердость",
    "прочность",
    "температура",
    "давление",
    "концентрация",
    "металлургия",
    "металлургии",
    "горно",
    "рудных",
    "горнорудных",
    "шахтных",
    "шахтные",
    "шахтная",
    "вод",
    "воды",
    "водоочистка",
    "очистка",
    "очистки",
    "нейтрализация",
    "осаждение",
    "сорбция",
    "адсорбция",
    "мембранная",
    "дренаж",
    "сточные",
    "тяжелые",
    "металлы",
}


def normalize_token(value: Any) -> str:
    token = str(value or "").strip().lower().strip(".,;:!?()[]{}")
    return token.replace("ё", "е")


def is_keyword_token(token: str) -> bool:
    if not token:
        return False
    if token in RU_STOPWORDS or token in EN_STOPWORDS:
        return False
    if len(token) < 3 and not token.isdigit():
        return False
    return True


def extract_keywords(query: str, *, max_keywords: int = 12) -> list[str]:
    """Extract deterministic literature-search keywords from a user query."""
    quoted = []
    for match in QUOTE_RE.finditer(query or ""):
        phrase = normalize_token(match.group(1) or match.group(2))
        if phrase and phrase not in quoted:
            quoted.append(phrase)

    tokens = [normalize_token(token) for token in TOKEN_RE.findall(query or "")]
    filtered = [token for token in tokens if is_keyword_token(token)]
    counts = Counter(filtered)

    def score(item: tuple[str, int]) -> tuple[int, int, str]:
        token, count = item
        domain_bonus = 3 if token in DOMAIN_TERMS else 0
        number_bonus = 2 if any(char.isdigit() for char in token) else 0
        return (domain_bonus + number_bonus + count, len(token), token)

    ranked = [token for token, _ in sorted(counts.items(), key=score, reverse=True)]
    result: list[str] = []
    for item in quoted + ranked:
        if item not in result:
            result.append(item)
        if len(result) >= max_keywords:
            break
    return result


def keyword_hits(text: str, keywords: list[str]) -> list[str]:
    haystack = normalize_token(text)
    hits = []
    for keyword in keywords:
        normalized = normalize_token(keyword)
        if normalized and normalized in haystack:
            hits.append(keyword)
    return list(dict.fromkeys(hits))

