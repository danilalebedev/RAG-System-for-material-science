# Legal Open Access Resolver

## What changed

- Added `app/web_search/open_access.py`.
- Added `scripts/resolve_open_access.py`.
- Added `open_access` metadata field to web search results.
- Web literature search now enriches top results with legal full-text status.
- GUI publication results show legal access cards:
  - Open full text
  - Metadata only
  - Paywalled
  - Access unknown
- GUI shows source of legal full text and a disabled placeholder button:
  - `Add legal full text to corpus`
- If no legal full text is found, GUI shows:
  - `Full text not found legally. Upload PDF manually if you have access.`

## Supported legal sources

- arXiv DOI/link detection.
- Unpaywall by DOI.
- OpenAlex by DOI/title.
- Semantic Scholar by DOI/title.
- Europe PMC by DOI/title.
- Publisher landing page metadata fallback.

## Explicit exclusions

The resolver does not integrate:

- Sci-Hub
- LibGen
- mirrors
- pirated PDF scraping
- copyright-bypassing services

It does not auto-download PDFs. It only returns URLs and metadata; PDF ingestion remains a future explicit/manual step.

## Output shape

```json
{
  "title": "...",
  "doi": "...",
  "year": "...",
  "open_access": true,
  "access_status": "open",
  "best_pdf_url": "...",
  "landing_page_url": "...",
  "source": "arxiv",
  "license": "...",
  "evidence": []
}
```

## Check

```powershell
.\.venv\Scripts\python.exe scripts\resolve_open_access.py --doi "10.48550/arXiv.2604.11229"
```

Result: arXiv DOI resolves locally to open full text:

- `https://arxiv.org/pdf/2604.11229`
- `https://arxiv.org/abs/2604.11229`

## Known blockers

- Unpaywall/OpenAlex/Semantic Scholar/Europe PMC require network availability.
- Resolver failures are converted to metadata-only/unknown status in GUI-safe mode.

No `git push` was performed.
