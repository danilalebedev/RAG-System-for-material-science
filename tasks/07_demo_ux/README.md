# Demo UX Polish

## Summary

Updated the Streamlit GUI toward a demo-first R&D Knowledge Cockpit. The goal was to make the product easier to sell in a hackathon demo: clearer entry point, visible modes, clickable scenarios, QueryPlan transparency, and structured results instead of one technical chat block.

## Implemented in `app/ui/demo_app.py`

- Added hero block:
  - `R&D Knowledge Cockpit`
  - Russian subtitle about internal base, tables, knowledge graph, and external publications.
- Added large mode cards:
  - Быстрый поиск
  - Сравнение методик
  - Табличные данные
  - Граф знаний
  - Внутреннее vs внешнее
- Added mode tabs with demo prompt buttons.
- Added a dedicated `Сравнение методик` tab with:
  - query input
  - `include_web` option
  - generated comparison table
  - evidence per row
  - missing evidence / fallbacks
  - graph context
  - full structured JSON
- Reworked QueryPlan display into compact chips:
  - intent
  - domain
  - answer format
  - entities
  - routes
- Added result sections:
  - Executive summary
  - Sources actually used
  - Comparison table
  - Evidence & sources
  - Missing evidence / fallbacks
  - Graph context
  - Query plan JSON
- Simplified sidebar:
  - primary retrieval toggles stay visible
  - Top K, search resources, publication period, rewrite, language, and deep-search parameters moved into `Advanced settings`.
- Added an empty state with four clickable demo scenarios.

## UX notes

- No new frontend dependencies were added.
- Styling is implemented with Streamlit plus CSS via `st.markdown`.
- Visual tone is intentionally restrained: cockpit/product UI, not a generic AI landing page.

## Commands

```powershell
.\.venv\Scripts\python.exe -m compileall app scripts
.\.venv\Scripts\python.exe scripts\run_demo_app.py
```

## Checks run

- `compileall app scripts` passed.
- `scripts\run_demo_app.py` started Streamlit successfully:
  - `Local URL: http://localhost:8501`
- The smoke Streamlit process was stopped after startup verification.

## Current blockers / notes

- GUI can display route fallbacks when local indexes or graph artifacts are missing.
- Yandex API remains externally blocked by `403 Permission denied`; GUI comparison mode uses deterministic fallback and does not require Yandex.
- No `git push` was performed.
