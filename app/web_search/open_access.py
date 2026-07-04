from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import quote

import requests


DEFAULT_USER_AGENT = "OreacleOpenAccessResolver/0.1"
FALLBACK_STATUS_RANK = {"metadata_only": 2, "paywalled": 1, "unknown": 0}
ARXIV_DOI_RE = re.compile(r"10\.48550/arxiv\.([0-9]{4}\.[0-9]{4,5}(?:v\d+)?)", re.IGNORECASE)


@dataclass(frozen=True)
class OpenAccessResult:
    title: str = ""
    doi: str = ""
    year: str = ""
    open_access: bool = False
    access_status: str = "unknown"
    best_pdf_url: str = ""
    landing_page_url: str = ""
    source: str = "publisher"
    license: str = ""
    evidence: list[str] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return {
            "title": self.title,
            "doi": self.doi,
            "year": self.year,
            "open_access": self.open_access,
            "access_status": self.access_status,
            "best_pdf_url": self.best_pdf_url,
            "landing_page_url": self.landing_page_url,
            "source": self.source,
            "license": self.license,
            "evidence": self.evidence,
        }


def clean_doi(value: str | None) -> str:
    text = str(value or "").strip()
    text = re.sub(r"^https?://(?:dx\.)?doi\.org/", "", text, flags=re.IGNORECASE)
    return text


def arxiv_id_from_doi(doi: str) -> str:
    match = ARXIV_DOI_RE.search(clean_doi(doi))
    return match.group(1) if match else ""


def result_from_arxiv_doi(doi: str, *, title: str = "", year: str | int | None = None) -> OpenAccessResult | None:
    arxiv_id = arxiv_id_from_doi(doi)
    if not arxiv_id:
        return None
    bare_id = re.sub(r"v\d+$", "", arxiv_id)
    return OpenAccessResult(
        title=title,
        doi=clean_doi(doi),
        year=str(year or ""),
        open_access=True,
        access_status="open",
        best_pdf_url=f"https://arxiv.org/pdf/{bare_id}",
        landing_page_url=f"https://arxiv.org/abs/{bare_id}",
        source="arxiv",
        license="arXiv open access",
        evidence=[f"DOI resolves to arXiv identifier {arxiv_id}"],
    )


def first_full_text_url(item: dict[str, Any]) -> str:
    full_text = item.get("fullTextUrlList") if isinstance(item.get("fullTextUrlList"), dict) else {}
    rows = full_text.get("fullTextUrl") if isinstance(full_text.get("fullTextUrl"), list) else []
    if not rows:
        return ""
    first = rows[0] if isinstance(rows[0], dict) else {}
    return str(first.get("url") or "")


class OpenAccessResolver:
    def __init__(
        self,
        *,
        session: requests.Session | None = None,
        timeout_seconds: int = 15,
        user_agent: str = DEFAULT_USER_AGENT,
        unpaywall_email: str | None = None,
    ) -> None:
        self.session = session or requests.Session()
        self.timeout_seconds = timeout_seconds
        self.user_agent = user_agent
        self.unpaywall_email = (unpaywall_email if unpaywall_email is not None else os.getenv("UNPAYWALL_EMAIL", "")).strip()

    def _get_json(self, url: str, *, params: dict[str, Any] | None = None) -> dict[str, Any]:
        response = self.session.get(url, params=params or {}, headers={"User-Agent": self.user_agent}, timeout=self.timeout_seconds)
        if response.status_code >= 400:
            return {}
        try:
            payload = response.json()
        except ValueError:
            return {}
        return payload if isinstance(payload, dict) else {}

    def resolve(self, *, doi: str | None = None, title: str | None = None, year: str | int | None = None) -> OpenAccessResult:
        doi_clean = clean_doi(doi)
        arxiv = result_from_arxiv_doi(doi_clean, title=title or "", year=year)
        if arxiv:
            return arxiv
        fallback: OpenAccessResult | None = None
        for resolver in (self.resolve_unpaywall, self.resolve_openalex, self.resolve_semantic_scholar, self.resolve_europe_pmc):
            try:
                result = resolver(doi=doi_clean, title=title, year=year)
            except requests.RequestException as exc:
                result = OpenAccessResult(title=title or "", doi=doi_clean, year=str(year or ""), evidence=[f"{resolver.__name__} failed: {exc}"])
            if result.open_access:
                return result
            if result.access_status in FALLBACK_STATUS_RANK and (
                fallback is None or FALLBACK_STATUS_RANK[result.access_status] > FALLBACK_STATUS_RANK[fallback.access_status]
            ):
                fallback = result
        if fallback and fallback.access_status != "unknown":
            return fallback
        return OpenAccessResult(
            title=title or "",
            doi=doi_clean,
            year=str(year or ""),
            access_status="unknown",
            landing_page_url=f"https://doi.org/{doi_clean}" if doi_clean else "",
            source="publisher",
            evidence=["No legal open full text found in configured resolvers."],
        )

    def resolve_unpaywall(self, *, doi: str, title: str | None, year: str | int | None) -> OpenAccessResult:
        if not doi:
            return OpenAccessResult(title=title or "", year=str(year or ""), access_status="unknown", evidence=["Unpaywall requires DOI."])
        if not self.unpaywall_email:
            return OpenAccessResult(
                title=title or "",
                doi=doi,
                year=str(year or ""),
                access_status="unknown",
                evidence=["Unpaywall skipped: set UNPAYWALL_EMAIL to enable this resolver."],
            )
        payload = self._get_json(f"https://api.unpaywall.org/v2/{quote(doi)}", params={"email": self.unpaywall_email})
        if not payload:
            return OpenAccessResult(title=title or "", doi=doi, year=str(year or ""), access_status="unknown", evidence=["Unpaywall returned no metadata."])
        location = payload.get("best_oa_location") if isinstance(payload.get("best_oa_location"), dict) else {}
        pdf_url = str(location.get("url_for_pdf") or "")
        landing = str(location.get("url") or payload.get("doi_url") or f"https://doi.org/{doi}")
        is_oa = bool(payload.get("is_oa"))
        return OpenAccessResult(
            title=str(payload.get("title") or title or ""),
            doi=doi,
            year=str(payload.get("year") or year or ""),
            open_access=is_oa and bool(pdf_url or landing),
            access_status="open" if is_oa and (pdf_url or landing) else "paywalled",
            best_pdf_url=pdf_url,
            landing_page_url=landing,
            source="unpaywall",
            license=str(location.get("license") or payload.get("license") or ""),
            evidence=[f"Unpaywall is_oa={is_oa}", f"oa_status={payload.get('oa_status')}"],
        )

    def resolve_openalex(self, *, doi: str, title: str | None, year: str | int | None) -> OpenAccessResult:
        params = {"filter": f"doi:{doi}"} if doi else {"search": title or "", "per-page": 1}
        payload = self._get_json("https://api.openalex.org/works", params=params)
        rows = payload.get("results") if isinstance(payload.get("results"), list) else []
        item = rows[0] if rows else {}
        if not item:
            return OpenAccessResult(title=title or "", doi=doi, year=str(year or ""), access_status="unknown", evidence=["OpenAlex returned no work."])
        oa = item.get("open_access") if isinstance(item.get("open_access"), dict) else {}
        primary = item.get("primary_location") if isinstance(item.get("primary_location"), dict) else {}
        pdf_url = str(primary.get("pdf_url") or oa.get("oa_url") or "")
        landing = str(primary.get("landing_page_url") or item.get("doi") or "")
        is_oa = bool(oa.get("is_oa"))
        return OpenAccessResult(
            title=str(item.get("title") or title or ""),
            doi=doi or str(item.get("doi") or "").replace("https://doi.org/", ""),
            year=str(item.get("publication_year") or year or ""),
            open_access=is_oa and bool(pdf_url or landing),
            access_status="open" if is_oa and (pdf_url or landing) else "metadata_only",
            best_pdf_url=pdf_url,
            landing_page_url=landing,
            source="openalex",
            license=str(primary.get("license") or ""),
            evidence=[f"OpenAlex is_oa={is_oa}", f"oa_status={oa.get('oa_status')}"],
        )

    def resolve_semantic_scholar(self, *, doi: str, title: str | None, year: str | int | None) -> OpenAccessResult:
        query = doi or title or ""
        if not query:
            return OpenAccessResult(access_status="unknown", evidence=["Semantic Scholar requires DOI or title."])
        payload = self._get_json(
            "https://api.semanticscholar.org/graph/v1/paper/search",
            params={"query": query, "limit": 1, "fields": "title,year,url,externalIds,openAccessPdf"},
        )
        rows = payload.get("data") if isinstance(payload.get("data"), list) else []
        item = rows[0] if rows else {}
        if not item:
            return OpenAccessResult(title=title or "", doi=doi, year=str(year or ""), access_status="unknown", evidence=["Semantic Scholar returned no paper."])
        open_pdf = item.get("openAccessPdf") if isinstance(item.get("openAccessPdf"), dict) else {}
        pdf_url = str(open_pdf.get("url") or "")
        return OpenAccessResult(
            title=str(item.get("title") or title or ""),
            doi=doi or str((item.get("externalIds") or {}).get("DOI") or ""),
            year=str(item.get("year") or year or ""),
            open_access=bool(pdf_url),
            access_status="open" if pdf_url else "metadata_only",
            best_pdf_url=pdf_url,
            landing_page_url=str(item.get("url") or ""),
            source="semantic_scholar",
            license=str(open_pdf.get("license") or ""),
            evidence=["Semantic Scholar openAccessPdf found." if pdf_url else "Semantic Scholar metadata only."],
        )

    def resolve_europe_pmc(self, *, doi: str, title: str | None, year: str | int | None) -> OpenAccessResult:
        query = f'DOI:"{doi}"' if doi else title or ""
        if not query:
            return OpenAccessResult(access_status="unknown", evidence=["Europe PMC requires DOI or title."])
        payload = self._get_json("https://www.ebi.ac.uk/europepmc/webservices/rest/search", params={"query": query, "format": "json", "pageSize": 1})
        result_list = payload.get("resultList") if isinstance(payload.get("resultList"), dict) else {}
        rows = result_list.get("result") if isinstance(result_list.get("result"), list) else []
        item = rows[0] if rows else {}
        if not item:
            return OpenAccessResult(title=title or "", doi=doi, year=str(year or ""), access_status="unknown", evidence=["Europe PMC returned no publication."])
        pdf_url = first_full_text_url(item)
        is_oa = str(item.get("isOpenAccess") or "").upper() == "Y"
        return OpenAccessResult(
            title=str(item.get("title") or title or ""),
            doi=doi or str(item.get("doi") or ""),
            year=str(item.get("pubYear") or year or ""),
            open_access=is_oa and bool(pdf_url),
            access_status="open" if is_oa and pdf_url else "metadata_only",
            best_pdf_url=pdf_url,
            landing_page_url=pdf_url,
            source="europe_pmc",
            evidence=[f"Europe PMC isOpenAccess={item.get('isOpenAccess')}"],
        )


def resolve_open_access(*, doi: str | None = None, title: str | None = None, year: str | int | None = None) -> OpenAccessResult:
    return OpenAccessResolver().resolve(doi=doi, title=title, year=year)
