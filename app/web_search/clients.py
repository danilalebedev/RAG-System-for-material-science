from __future__ import annotations

import hashlib
import html
import re
from typing import Any
from xml.etree import ElementTree

import requests
from bs4 import BeautifulSoup

from app.web_search.journal_quality import infer_quartile, quartile_score_boost
from app.web_search.keywords import keyword_hits
from app.web_search.schemas import LiteratureSearchResult, SearchSource


CROSSREF_WORKS_URL = "https://api.crossref.org/works"
SEMANTIC_SCHOLAR_SEARCH_URL = "https://api.semanticscholar.org/graph/v1/paper/search"
OPENALEX_WORKS_URL = "https://api.openalex.org/works"
EUROPE_PMC_SEARCH_URL = "https://www.ebi.ac.uk/europepmc/webservices/rest/search"
ARXIV_SEARCH_URL = "https://export.arxiv.org/api/query"
DATACITE_DOIS_URL = "https://api.datacite.org/dois"
DEFAULT_USER_AGENT = "NornickelHackathonLiteratureSearch/0.1 (mailto:example@example.com)"
WHITESPACE_RE = re.compile(r"\s+")
ATOM_NS = "{http://www.w3.org/2005/Atom}"
ARXIV_NS = "{http://arxiv.org/schemas/atom}"
MATERIALS_SCIENCE_TERMS = {
    "materials",
    "material",
    "metallurgy",
    "metallurgical",
    "hydrometallurgy",
    "pyrometallurgy",
    "mineral",
    "minerals",
    "ore",
    "ores",
    "alloy",
    "alloys",
    "nickel",
    "copper",
    "cobalt",
    "platinum",
    "palladium",
    "flotation",
    "leaching",
    "smelting",
    "roasting",
    "annealing",
    "hardness",
    "corrosion",
    "materials science",
    "mineral processing",
    "non-ferrous metallurgy",
    "nonferrous metallurgy",
    "mine water",
    "acid mine drainage",
    "mining wastewater",
    "industrial wastewater",
    "wastewater treatment",
    "water treatment",
    "heavy metal removal",
    "металлург",
    "материал",
    "материаловед",
    "руда",
    "сплав",
    "никел",
    "мед",
    "кобальт",
    "флотац",
    "выщелач",
    "обжиг",
    "плавк",
    "отжиг",
    "тверд",
    "прочност",
    "шахтн",
    "рудничн",
    "сточн",
    "водоочист",
    "очистк",
    "дренаж",
    "нейтрализац",
    "осажден",
    "сорбц",
    "адсорбц",
    "мембран",
    "тяжел",
    "горноруд",
}


class SearchClientError(RuntimeError):
    pass


def compact_text(value: Any, max_chars: int | None = None) -> str:
    text = WHITESPACE_RE.sub(" ", str(value or "")).strip()
    if max_chars is not None and len(text) > max_chars:
        return text[: max_chars - 3].rstrip() + "..."
    return text


def normalize_for_relevance(value: Any) -> str:
    return compact_text(value).casefold().replace("ё", "е")


def relevance_hits(text: str, terms: list[str]) -> list[str]:
    normalized = normalize_for_relevance(text)
    hits: list[str] = []
    for term in terms:
        clean = normalize_for_relevance(term)
        if len(clean) >= 2 and clean in normalized and term not in hits:
            hits.append(term)
    return hits


def stable_result_id(source: str, *parts: Any) -> str:
    payload = "\n".join(str(part or "") for part in parts)
    digest = hashlib.sha256(payload.encode("utf-8", errors="ignore")).hexdigest()[:16]
    return f"{source}_{digest}"


def first_text(value: Any) -> str | None:
    if isinstance(value, list):
        for item in value:
            text = compact_text(item, 500)
            if text:
                return text
        return None
    text = compact_text(value, 500)
    return text or None


def strip_markup(value: Any) -> str | None:
    text = compact_text(html.unescape(str(value or "")), 5000)
    if not text:
        return None
    return compact_text(BeautifulSoup(text, "lxml").get_text(" "), 3000)


def clean_url(value: Any) -> str | None:
    text = compact_text(value, 1000)
    if text.startswith("https://") or text.startswith("http://"):
        return text
    return None


def clean_doi(value: Any) -> str | None:
    text = compact_text(value, 300)
    if not text:
        return None
    text = re.sub(r"^https?://(dx\.)?doi\.org/", "", text, flags=re.IGNORECASE).strip()
    return text or None


def to_int(value: Any) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def extract_year_from_date_parts(value: Any) -> int | None:
    if not isinstance(value, dict):
        return None
    parts = value.get("date-parts")
    if isinstance(parts, list) and parts and isinstance(parts[0], list) and parts[0]:
        try:
            year = int(parts[0][0])
        except (TypeError, ValueError):
            return None
        if 1800 <= year <= 2100:
            return year
    return None


def openalex_abstract(index: Any) -> str | None:
    if not isinstance(index, dict) or not index:
        return None
    positions: dict[int, str] = {}
    for token, indexes in index.items():
        if not isinstance(indexes, list):
            continue
        for position in indexes:
            number = to_int(position)
            if number is not None:
                positions[number] = str(token)
    if not positions:
        return None
    return compact_text(" ".join(positions[position] for position in sorted(positions)), 3000)


def first_description(descriptions: Any) -> str | None:
    if not isinstance(descriptions, list):
        return None
    for item in descriptions:
        if not isinstance(item, dict):
            continue
        text = compact_text(item.get("description"), 3000)
        if text:
            return text
    return None


def europepmc_article_url(item: dict[str, Any]) -> str | None:
    source = compact_text(item.get("source"), 40) or "MED"
    article_id = compact_text(item.get("pmcid") or item.get("pmid") or item.get("id"), 80)
    if article_id:
        return f"https://europepmc.org/article/{source}/{article_id}"
    doi = clean_doi(item.get("doi"))
    if doi:
        return f"https://doi.org/{doi}"
    return None


def arxiv_text(entry: ElementTree.Element, name: str) -> str | None:
    child = entry.find(f"{ATOM_NS}{name}")
    return compact_text(child.text, 3000) if child is not None else None


def arxiv_doi(entry: ElementTree.Element) -> str | None:
    child = entry.find(f"{ARXIV_NS}doi")
    return clean_doi(child.text if child is not None else None)


def parse_crossref_item(item: dict[str, Any], *, keywords: list[str]) -> LiteratureSearchResult | None:
    title = first_text(item.get("title"))
    if not title:
        return None
    doi = clean_doi(item.get("DOI"))
    year = (
        extract_year_from_date_parts(item.get("published-print"))
        or extract_year_from_date_parts(item.get("published-online"))
        or extract_year_from_date_parts(item.get("published"))
        or extract_year_from_date_parts(item.get("created"))
    )
    authors = []
    for author in item.get("author") or []:
        if not isinstance(author, dict):
            continue
        name = compact_text(" ".join(part for part in [author.get("given"), author.get("family")] if part), 300)
        if name:
            authors.append(name)
    venue = first_text(item.get("container-title"))
    abstract = strip_markup(item.get("abstract"))
    links = item.get("link") if isinstance(item.get("link"), list) else []
    pdf_url = None
    for link in links:
        if not isinstance(link, dict):
            continue
        url = link.get("URL")
        content_type = str(link.get("content-type") or "").lower()
        if url and ("pdf" in content_type or str(url).lower().endswith(".pdf")):
            pdf_url = url
            break
    url = clean_url(item.get("URL") or (f"https://doi.org/{doi}" if doi else None))
    evidence_text = " ".join(part for part in [title, abstract, venue] if part)
    hits = keyword_hits(evidence_text, keywords)
    return LiteratureSearchResult(
        result_id=stable_result_id("crossref", doi, title, year),
        source="crossref",
        title=title,
        authors=authors,
        year=year,
        venue=venue,
        doi=doi,
        url=url,
        abstract=abstract,
        open_access_pdf_url=clean_url(pdf_url),
        citation_count=item.get("is-referenced-by-count"),
        reference_count=item.get("reference-count"),
        keyword_hits=hits,
        external_ids={"doi": doi} if doi else {},
        raw=item,
    )


def parse_semantic_scholar_item(item: dict[str, Any], *, keywords: list[str]) -> LiteratureSearchResult | None:
    title = compact_text(item.get("title"), 500)
    if not title:
        return None
    external_ids = item.get("externalIds") if isinstance(item.get("externalIds"), dict) else {}
    doi = clean_doi(external_ids.get("DOI"))
    authors = []
    for author in item.get("authors") or []:
        if isinstance(author, dict) and author.get("name"):
            authors.append(compact_text(author.get("name"), 300))
    abstract = compact_text(item.get("abstract"), 3000) or None
    open_access = item.get("openAccessPdf") if isinstance(item.get("openAccessPdf"), dict) else {}
    pdf_url = clean_url(open_access.get("url"))
    evidence_text = " ".join(part for part in [title, abstract, item.get("venue")] if part)
    hits = keyword_hits(evidence_text, keywords)
    normalized_external_ids = {str(key): str(value) for key, value in external_ids.items() if value}
    return LiteratureSearchResult(
        result_id=stable_result_id("semantic_scholar", item.get("paperId"), doi, title),
        source="semantic_scholar",
        title=title,
        authors=authors,
        year=item.get("year"),
        venue=compact_text(item.get("venue"), 300) or None,
        doi=doi,
        url=clean_url(item.get("url")),
        abstract=abstract,
        open_access_pdf_url=pdf_url,
        citation_count=item.get("citationCount"),
        reference_count=item.get("referenceCount"),
        keyword_hits=hits,
        external_ids=normalized_external_ids,
        raw=item,
    )


def parse_openalex_item(item: dict[str, Any], *, keywords: list[str]) -> LiteratureSearchResult | None:
    title = compact_text(item.get("display_name") or item.get("title"), 500)
    if not title:
        return None
    authors = []
    for authorship in item.get("authorships") or []:
        if not isinstance(authorship, dict):
            continue
        author = authorship.get("author") if isinstance(authorship.get("author"), dict) else {}
        name = compact_text(author.get("display_name"), 300)
        if name:
            authors.append(name)
    primary_location = item.get("primary_location") if isinstance(item.get("primary_location"), dict) else {}
    best_oa_location = item.get("best_oa_location") if isinstance(item.get("best_oa_location"), dict) else {}
    location = primary_location or best_oa_location
    source = location.get("source") if isinstance(location.get("source"), dict) else {}
    venue = compact_text(source.get("display_name"), 300) or None
    doi = clean_doi(item.get("doi"))
    url = clean_url(location.get("landing_page_url") or item.get("doi") or item.get("id"))
    pdf_url = clean_url(location.get("pdf_url") or best_oa_location.get("pdf_url"))
    abstract = openalex_abstract(item.get("abstract_inverted_index"))
    evidence_text = " ".join(part for part in [title, abstract, venue] if part)
    hits = keyword_hits(evidence_text, keywords)
    external_ids = {"openalex": str(item.get("id"))} if item.get("id") else {}
    if doi:
        external_ids["doi"] = doi
    return LiteratureSearchResult(
        result_id=stable_result_id("openalex", item.get("id"), doi, title),
        source="openalex",
        title=title,
        authors=authors,
        year=to_int(item.get("publication_year")),
        venue=venue,
        doi=doi,
        url=url,
        abstract=abstract,
        open_access_pdf_url=pdf_url,
        citation_count=to_int(item.get("cited_by_count")),
        reference_count=len(item.get("referenced_works") or []) if isinstance(item.get("referenced_works"), list) else None,
        keyword_hits=hits,
        external_ids=external_ids,
        raw=item,
    )


def parse_europepmc_item(item: dict[str, Any], *, keywords: list[str]) -> LiteratureSearchResult | None:
    title = compact_text(item.get("title"), 500)
    if not title:
        return None
    author_string = compact_text(item.get("authorString"), 1000)
    authors = [compact_text(author, 300) for author in re.split(r",\s*", author_string) if compact_text(author, 300)]
    doi = clean_doi(item.get("doi"))
    venue = compact_text(item.get("journalTitle"), 300) or None
    abstract = strip_markup(item.get("abstractText"))
    full_text_urls = ((item.get("fullTextUrlList") or {}).get("fullTextUrl") or []) if isinstance(item.get("fullTextUrlList"), dict) else []
    pdf_url = None
    for link in full_text_urls:
        if not isinstance(link, dict):
            continue
        url = compact_text(link.get("url"), 1000)
        if url and ("pdf" in str(link.get("documentStyle") or "").lower() or url.lower().endswith(".pdf")):
            pdf_url = url
            break
    evidence_text = " ".join(part for part in [title, abstract, venue] if part)
    hits = keyword_hits(evidence_text, keywords)
    external_ids = {key: compact_text(item.get(key), 300) for key in ["pmid", "pmcid", "id"] if item.get(key)}
    if doi:
        external_ids["doi"] = doi
    return LiteratureSearchResult(
        result_id=stable_result_id("europepmc", item.get("id"), doi, title),
        source="europepmc",
        title=title,
        authors=authors,
        year=to_int(item.get("pubYear")),
        venue=venue,
        doi=doi,
        url=clean_url(europepmc_article_url(item)),
        abstract=abstract,
        open_access_pdf_url=clean_url(pdf_url),
        citation_count=to_int(item.get("citedByCount")),
        keyword_hits=hits,
        external_ids=external_ids,
        raw=item,
    )


def parse_arxiv_entry(entry: ElementTree.Element, *, keywords: list[str]) -> LiteratureSearchResult | None:
    title = compact_text(arxiv_text(entry, "title"), 500)
    if not title:
        return None
    authors = []
    for author in entry.findall(f"{ATOM_NS}author"):
        name = author.find(f"{ATOM_NS}name")
        text = compact_text(name.text if name is not None else None, 300)
        if text:
            authors.append(text)
    published = arxiv_text(entry, "published")
    year = to_int(published[:4]) if published else None
    doi = arxiv_doi(entry)
    url = clean_url(arxiv_text(entry, "id"))
    pdf_url = None
    for link in entry.findall(f"{ATOM_NS}link"):
        href = link.attrib.get("href")
        if href and (link.attrib.get("title") == "pdf" or link.attrib.get("type") == "application/pdf"):
            pdf_url = href
            break
    abstract = compact_text(arxiv_text(entry, "summary"), 3000) or None
    venue = compact_text(arxiv_text(entry, "journal_ref"), 300) or "arXiv"
    evidence_text = " ".join(part for part in [title, abstract, venue] if part)
    hits = keyword_hits(evidence_text, keywords)
    arxiv_id = url.rsplit("/", 1)[-1] if url else title
    external_ids = {"arxiv": arxiv_id}
    if doi:
        external_ids["doi"] = doi
    return LiteratureSearchResult(
        result_id=stable_result_id("arxiv", arxiv_id, doi, title),
        source="arxiv",
        title=title,
        authors=authors,
        year=year,
        venue=venue,
        doi=doi,
        url=url,
        abstract=abstract,
        open_access_pdf_url=clean_url(pdf_url),
        keyword_hits=hits,
        external_ids=external_ids,
        raw={"arxiv_id": arxiv_id, "published": published},
    )


def parse_datacite_item(item: dict[str, Any], *, keywords: list[str]) -> LiteratureSearchResult | None:
    attributes = item.get("attributes") if isinstance(item.get("attributes"), dict) else {}
    title = first_text([row.get("title") for row in attributes.get("titles") or [] if isinstance(row, dict)])
    if not title:
        return None
    authors = []
    for creator in attributes.get("creators") or []:
        if isinstance(creator, dict):
            name = compact_text(creator.get("name") or creator.get("givenName") or creator.get("familyName"), 300)
            if name:
                authors.append(name)
    doi = clean_doi(attributes.get("doi") or item.get("id"))
    container = attributes.get("container") if isinstance(attributes.get("container"), dict) else {}
    venue = compact_text(attributes.get("publisher") or container.get("title"), 300) or None
    abstract = first_description(attributes.get("descriptions"))
    url = clean_url(attributes.get("url") or (f"https://doi.org/{doi}" if doi else None))
    evidence_text = " ".join(part for part in [title, abstract, venue] if part)
    hits = keyword_hits(evidence_text, keywords)
    external_ids = {"datacite": str(item.get("id"))} if item.get("id") else {}
    if doi:
        external_ids["doi"] = doi
    return LiteratureSearchResult(
        result_id=stable_result_id("datacite", item.get("id"), doi, title),
        source="datacite",
        title=title,
        authors=authors,
        year=to_int(attributes.get("publicationYear")),
        venue=venue,
        doi=doi,
        url=url,
        abstract=abstract,
        keyword_hits=hits,
        external_ids=external_ids,
        raw=item,
    )


def result_key(result: LiteratureSearchResult) -> str:
    if result.doi:
        return f"doi:{result.doi.lower().strip()}"
    normalized_title = re.sub(r"[^a-zа-яё0-9]+", "", result.title.lower())
    return f"title:{normalized_title[:120]}"


def material_domain_hits(result: LiteratureSearchResult) -> list[str]:
    text = compact_text(result.evidence_text(), 5000).lower().replace("ё", "е")
    return sorted({term for term in MATERIALS_SCIENCE_TERMS if term in text})


def is_materials_science_result(result: LiteratureSearchResult) -> bool:
    hits = material_domain_hits(result)
    if hits:
        result.raw["materials_domain_hits"] = hits[:20]
    return bool(hits)


def score_result(
    result: LiteratureSearchResult,
    keywords: list[str],
    *,
    journal_quartile_map: dict[str, str] | None = None,
    relevance_terms: list[str] | None = None,
) -> float:
    text = result.evidence_text()
    hits = keyword_hits(text, keywords)
    score = len(hits) * 5.0
    alias_hits = relevance_hits(text, relevance_terms or [])
    title_hits = relevance_hits(result.title, [*(relevance_terms or []), *keywords])
    snippet_hits = relevance_hits(" ".join([result.abstract or "", result.snippet or ""]), [*(relevance_terms or []), *keywords])
    score += len(alias_hits) * 4.0
    score += len(title_hits) * 3.0
    score += len(snippet_hits) * 1.5
    if result.abstract:
        score += 2.0
    if result.doi:
        score += 1.0
    if result.citation_count:
        score += min(float(result.citation_count), 500.0) / 100.0
    if result.year:
        score += max(0, result.year - 2000) / 100.0
    domain_hits = material_domain_hits(result)
    if domain_hits:
        score += min(len(domain_hits), 6) * 1.5
        result.raw["materials_domain_hits"] = domain_hits[:20]
    quartile = infer_quartile(result, journal_quartile_map)
    boost = quartile_score_boost(quartile)
    if quartile:
        score += boost
        result.raw["journal_quartile"] = quartile
        result.raw["journal_quartile_boost"] = boost
    result.keyword_hits = hits
    if alias_hits:
        result.raw["alias_hits"] = alias_hits[:20]
    if title_hits:
        result.raw["title_relevance_hits"] = title_hits[:20]
    if snippet_hits:
        result.raw["snippet_relevance_hits"] = snippet_hits[:20]
    result.score = round(score, 4)
    return result.score


def dedupe_and_rank_results(
    results: list[LiteratureSearchResult],
    keywords: list[str],
    *,
    top_k: int,
    materials_only: bool = False,
    journal_quartile_map: dict[str, str] | None = None,
    relevance_terms: list[str] | None = None,
) -> list[LiteratureSearchResult]:
    best_by_key: dict[str, LiteratureSearchResult] = {}
    for result in results:
        if materials_only and not is_materials_science_result(result):
            continue
        score_result(result, keywords, journal_quartile_map=journal_quartile_map, relevance_terms=relevance_terms)
        if relevance_terms and not relevance_hits(result.evidence_text(), relevance_terms):
            continue
        key = result_key(result)
        existing = best_by_key.get(key)
        if existing is None or result.score > existing.score:
            best_by_key[key] = result
    return sorted(best_by_key.values(), key=lambda item: item.score, reverse=True)[:top_k]


class LiteratureSearchClient:
    def __init__(
        self,
        *,
        session: requests.Session | None = None,
        semantic_scholar_api_key: str | None = None,
        user_agent: str = DEFAULT_USER_AGENT,
        timeout_seconds: int = 20,
        journal_quartile_map: dict[str, str] | None = None,
    ) -> None:
        self.session = session or requests.Session()
        self.semantic_scholar_api_key = semantic_scholar_api_key
        self.user_agent = user_agent
        self.timeout_seconds = timeout_seconds
        self.journal_quartile_map = journal_quartile_map or {}

    def _get_json(self, url: str, *, params: dict[str, Any], headers: dict[str, str] | None = None) -> dict[str, Any]:
        request_headers = {"User-Agent": self.user_agent, **(headers or {})}
        try:
            response = self.session.get(url, params=params, headers=request_headers, timeout=self.timeout_seconds)
        except requests.RequestException as exc:
            raise SearchClientError(f"external API request failed: {exc}") from exc
        if response.status_code == 429:
            raise SearchClientError("external API rate limit reached")
        if response.status_code >= 400:
            raise SearchClientError(f"external API returned HTTP {response.status_code}")
        payload = response.json()
        if not isinstance(payload, dict):
            raise SearchClientError("external API returned non-object JSON")
        return payload

    def _get_text(self, url: str, *, params: dict[str, Any], headers: dict[str, str] | None = None) -> str:
        request_headers = {"User-Agent": self.user_agent, **(headers or {})}
        try:
            response = self.session.get(url, params=params, headers=request_headers, timeout=self.timeout_seconds)
        except requests.RequestException as exc:
            raise SearchClientError(f"external API request failed: {exc}") from exc
        if response.status_code == 429:
            raise SearchClientError("external API rate limit reached")
        if response.status_code >= 400:
            raise SearchClientError(f"external API returned HTTP {response.status_code}")
        return response.text

    def search_crossref(self, query: str, *, keywords: list[str], top_k: int) -> list[LiteratureSearchResult]:
        params = {
            "query.bibliographic": query,
            "rows": min(max(top_k * 2, 10), 100),
        }
        payload = self._get_json(CROSSREF_WORKS_URL, params=params)
        items = ((payload.get("message") or {}).get("items") or []) if isinstance(payload.get("message"), dict) else []
        results = [parse_crossref_item(item, keywords=keywords) for item in items if isinstance(item, dict)]
        return [result for result in results if result is not None]

    def search_semantic_scholar(self, query: str, *, keywords: list[str], top_k: int) -> list[LiteratureSearchResult]:
        params = {
            "query": query,
            "limit": min(max(top_k * 2, 10), 100),
            "fields": "title,abstract,year,authors,venue,url,externalIds,citationCount,referenceCount,openAccessPdf",
        }
        headers = {}
        if self.semantic_scholar_api_key:
            headers["x-api-key"] = self.semantic_scholar_api_key
        payload = self._get_json(SEMANTIC_SCHOLAR_SEARCH_URL, params=params, headers=headers)
        items = payload.get("data") if isinstance(payload.get("data"), list) else []
        results = [parse_semantic_scholar_item(item, keywords=keywords) for item in items if isinstance(item, dict)]
        return [result for result in results if result is not None]

    def search_openalex(self, query: str, *, keywords: list[str], top_k: int) -> list[LiteratureSearchResult]:
        params = {
            "search": query,
            "per-page": min(max(top_k * 2, 10), 100),
        }
        payload = self._get_json(OPENALEX_WORKS_URL, params=params)
        items = payload.get("results") if isinstance(payload.get("results"), list) else []
        results = [parse_openalex_item(item, keywords=keywords) for item in items if isinstance(item, dict)]
        return [result for result in results if result is not None]

    def search_europepmc(self, query: str, *, keywords: list[str], top_k: int) -> list[LiteratureSearchResult]:
        params = {
            "query": query,
            "pageSize": min(max(top_k * 2, 10), 100),
            "format": "json",
            "resultType": "core",
        }
        payload = self._get_json(EUROPE_PMC_SEARCH_URL, params=params)
        result_list = payload.get("resultList") if isinstance(payload.get("resultList"), dict) else {}
        items = result_list.get("result") if isinstance(result_list.get("result"), list) else []
        results = [parse_europepmc_item(item, keywords=keywords) for item in items if isinstance(item, dict)]
        return [result for result in results if result is not None]

    def search_arxiv(self, query: str, *, keywords: list[str], top_k: int) -> list[LiteratureSearchResult]:
        params = {
            "search_query": f"all:{query}",
            "start": 0,
            "max_results": min(max(top_k * 2, 10), 50),
            "sortBy": "relevance",
            "sortOrder": "descending",
        }
        text = self._get_text(ARXIV_SEARCH_URL, params=params)
        try:
            root = ElementTree.fromstring(text)
        except ElementTree.ParseError as exc:
            raise SearchClientError(f"arXiv returned invalid XML: {exc}") from exc
        entries = root.findall(f"{ATOM_NS}entry")
        results = [parse_arxiv_entry(entry, keywords=keywords) for entry in entries]
        return [result for result in results if result is not None]

    def search_datacite(self, query: str, *, keywords: list[str], top_k: int) -> list[LiteratureSearchResult]:
        params = {
            "query": query,
            "page[size]": min(max(top_k * 2, 10), 100),
        }
        payload = self._get_json(DATACITE_DOIS_URL, params=params)
        items = payload.get("data") if isinstance(payload.get("data"), list) else []
        results = [parse_datacite_item(item, keywords=keywords) for item in items if isinstance(item, dict)]
        return [result for result in results if result is not None]

    def search(
        self,
        query: str,
        *,
        keywords: list[str],
        sources: list[SearchSource],
        top_k: int,
        query_variants: list[str] | None = None,
        materials_only: bool = False,
        relevance_terms: list[str] | None = None,
    ) -> tuple[list[LiteratureSearchResult], list[str]]:
        results: list[LiteratureSearchResult] = []
        warnings: list[str] = []
        variants = [item for item in dict.fromkeys([query, *(query_variants or [])]) if item][:8]
        for variant in variants:
            if "crossref" in sources:
                try:
                    results.extend(self.search_crossref(variant, keywords=keywords, top_k=top_k))
                except SearchClientError as exc:
                    warnings.append(f"Crossref search skipped for '{compact_text(variant, 80)}': {exc}")
            if "semantic_scholar" in sources:
                try:
                    results.extend(self.search_semantic_scholar(variant, keywords=keywords, top_k=top_k))
                except SearchClientError as exc:
                    warnings.append(f"Semantic Scholar search skipped for '{compact_text(variant, 80)}': {exc}")
            if "openalex" in sources:
                try:
                    results.extend(self.search_openalex(variant, keywords=keywords, top_k=top_k))
                except SearchClientError as exc:
                    warnings.append(f"OpenAlex search skipped for '{compact_text(variant, 80)}': {exc}")
            if "europepmc" in sources:
                try:
                    results.extend(self.search_europepmc(variant, keywords=keywords, top_k=top_k))
                except SearchClientError as exc:
                    warnings.append(f"Europe PMC search skipped for '{compact_text(variant, 80)}': {exc}")
            if "arxiv" in sources:
                try:
                    results.extend(self.search_arxiv(variant, keywords=keywords, top_k=top_k))
                except SearchClientError as exc:
                    warnings.append(f"arXiv search skipped for '{compact_text(variant, 80)}': {exc}")
            if "datacite" in sources:
                try:
                    results.extend(self.search_datacite(variant, keywords=keywords, top_k=top_k))
                except SearchClientError as exc:
                    warnings.append(f"DataCite search skipped for '{compact_text(variant, 80)}': {exc}")
        return (
            dedupe_and_rank_results(
                results,
                keywords,
                top_k=top_k,
                materials_only=materials_only,
                journal_quartile_map=self.journal_quartile_map,
                relevance_terms=relevance_terms,
            ),
            warnings,
        )
