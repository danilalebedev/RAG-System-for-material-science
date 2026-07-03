from __future__ import annotations

from dataclasses import dataclass
from typing import Any
from urllib.parse import quote_plus


@dataclass(frozen=True)
class ResourceSearchProvider:
    resource_id: str
    name: str
    homepage: str
    search_template: str | None
    category: str
    enabled: bool = True
    note: str = ""

    def build_url(self, query: str) -> str | None:
        if not self.enabled or not self.search_template:
            return None
        return self.search_template.format(q=quote_plus(query))


RECOMMENDED_RESOURCES: tuple[ResourceSearchProvider, ...] = (
    ResourceSearchProvider(
        resource_id="researchgate",
        name="ResearchGate",
        homepage="https://www.researchgate.net/",
        search_template="https://www.researchgate.net/search/publication?q={q}",
        category="publications",
        note="May require login for full functionality.",
    ),
    ResourceSearchProvider(
        resource_id="elibrary",
        name="eLIBRARY.RU",
        homepage="https://www.elibrary.ru/",
        search_template="https://www.elibrary.ru/query_results.asp?querybox={q}",
        category="publications",
        note="Russian academic index; access may be IP/rules restricted.",
    ),
    ResourceSearchProvider(
        resource_id="springer",
        name="Springer Nature Link",
        homepage="https://link.springer.com/",
        search_template="https://link.springer.com/search?query={q}",
        category="publisher",
    ),
    ResourceSearchProvider(
        resource_id="google_patents",
        name="Google Patents",
        homepage="https://patents.google.com/",
        search_template="https://patents.google.com/?q={q}",
        category="patents",
    ),
    ResourceSearchProvider(
        resource_id="mdpi",
        name="MDPI",
        homepage="https://www.mdpi.com/",
        search_template="https://www.mdpi.com/search?q={q}",
        category="publisher",
    ),
    ResourceSearchProvider(
        resource_id="cyberleninka",
        name="CyberLeninka",
        homepage="https://cyberleninka.ru/",
        search_template="https://cyberleninka.ru/search?q={q}",
        category="publications",
    ),
    ResourceSearchProvider(
        resource_id="wiley",
        name="Wiley Online Library",
        homepage="https://onlinelibrary.wiley.com/",
        search_template="https://onlinelibrary.wiley.com/action/doSearch?AllField={q}",
        category="publisher",
    ),
    ResourceSearchProvider(
        resource_id="sciencedirect",
        name="ScienceDirect",
        homepage="https://www.sciencedirect.com/",
        search_template="https://www.sciencedirect.com/search?qs={q}",
        category="publisher",
        note="Often requires institutional access for full texts.",
    ),
    ResourceSearchProvider(
        resource_id="scihub",
        name="Sci-Hub",
        homepage="https://sci-hub.ru/",
        search_template=None,
        category="unsupported",
        enabled=False,
        note="Not integrated: copyright/legal risk. Use publisher/open-access links instead.",
    ),
)


def provider_names() -> dict[str, str]:
    return {provider.resource_id: provider.name for provider in RECOMMENDED_RESOURCES}


def enabled_provider_ids() -> list[str]:
    return [provider.resource_id for provider in RECOMMENDED_RESOURCES if provider.enabled]


def build_resource_links(
    *,
    corrected_query: str,
    search_queries: list[str],
    selected_resource_ids: list[str] | None = None,
    include_disabled: bool = True,
) -> list[dict[str, Any]]:
    selected = set(selected_resource_ids or enabled_provider_ids())
    query_variants = [item for item in dict.fromkeys([corrected_query, *search_queries]) if item][:3]
    rows: list[dict[str, Any]] = []
    for provider in RECOMMENDED_RESOURCES:
        if provider.resource_id not in selected and not (include_disabled and not provider.enabled):
            continue
        if not provider.enabled:
            rows.append(
                {
                    "resource_id": provider.resource_id,
                    "name": provider.name,
                    "category": provider.category,
                    "query": "",
                    "url": provider.homepage,
                    "enabled": False,
                    "note": provider.note,
                }
            )
            continue
        for query in query_variants:
            url = provider.build_url(query)
            if url:
                rows.append(
                    {
                        "resource_id": provider.resource_id,
                        "name": provider.name,
                        "category": provider.category,
                        "query": query,
                        "url": url,
                        "enabled": True,
                        "note": provider.note,
                    }
                )
    return rows

