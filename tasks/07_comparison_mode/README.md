# Comparison Mode

## Summary

Implemented a deterministic Comparison Mode for the R&D RAG cockpit. It works without Yandex/LLM access and builds a structured comparison table from the available retrieval context.

## Implemented

- Added `app/query/comparison.py`.
- Added `scripts/compare_methods.py`.
- Extended `app/query/orchestrator.py` with `required_routes` so feature modes can force route execution while keeping the default planner behavior unchanged.
- Added focused tests in `tests/test_comparison_mode.py`.
- Wired Comparison Mode into the Streamlit GUI as a separate demo feature.

## Retrieval behavior

Comparison Mode calls QueryPlan first, then forces these routes:

- `summary_rag` for method/procedure candidates.
- `raw_rag` for evidence.
- `table_search` for numeric parameters.
- `graph_search` for related Materials / Processes / Properties.
- `web_search` only when `include_web=True`.

The returned payload includes:

- `query`
- `compared_items`
- `comparison_dimensions`
- `rows`
- `missing_evidence`
- `answer_summary`
- `plan`
- `retrieved_context`
- `evidence`
- `fallbacks`

## Deterministic fallback

No Yandex synthesis is required. If summaries are available, rows are built from summary records. If summaries are missing, the mode falls back to raw/web context. Missing indexes and partial evidence are shown explicitly in `missing_evidence`.

## Commands

```powershell
.\.venv\Scripts\python.exe -m compileall app scripts
.\.venv\Scripts\python.exe -m pytest -q
.\.venv\Scripts\python.exe scripts\compare_methods.py "Сравни методы переработки литий-ионных батарей для извлечения никеля и кобальта" --top-k 5
```

## Checks run

- `compileall app scripts` passed.
- `pytest -q` passed: `38 passed, 2 warnings`.
- `scripts\compare_methods.py ... --top-k 5` passed and returned a valid fallback result.

## Current blockers / notes

- In this working copy, `data/parsed/chunks.jsonl`, summary publication inputs, and knowledge graph artifacts were not available, so the demo CLI correctly reported route fallbacks.
- Yandex API remains an external blocker with `403 Permission denied`; this feature does not depend on it.
- No `git push` was performed.
