# Query Intelligence Layer

Date: 2026-07-04

## What changed

- Added deterministic query planner in `app/query/planner.py`.
  - Outputs the required JSON shape with `intent`, `domain`, `entities`, route-specific `rewritten_queries`, `decomposed_questions`, `routes`, `answer_format`, and clarification fields.
  - Supports the requested intents and route rules without Yandex or any external LLM call.
- Added public facade `app/query/orchestrator.py`.
  - Calls `plan_query` first.
  - Maps planned routes to local raw/summary/table/graph retrieval through the existing local orchestrator.
  - Keeps web retrieval opt-in to avoid surprise network calls.
- Added CLI `scripts/plan_query.py`.
  - Prints pretty JSON and never prints credentials.
- Updated GUI.
  - Shows Query Intelligence preview before retrieval in the R&D cockpit.
  - Shows the full plan alongside completed search/local knowledge results.
- Updated web/local query paths to preserve the new query plan JSON in run payloads.
- Added focused planner tests in `tests/test_query_planner.py`.

## Commands

Plan only:

```powershell
.\.venv\Scripts\python.exe scripts\plan_query.py "compare nickel leaching at 80 C and 20% acid" --json
```

Russian evidence query:

```powershell
.\.venv\Scripts\python.exe scripts\plan_query.py "где написано про извлечение никеля из хвостов" --json
```

Expected dev dependency install, if missing:

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
```

## Verification

Installed missing dev dependencies into the existing `.venv`:

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
```

Checks run:

```powershell
.\.venv\Scripts\python.exe -m compileall app scripts
.\.venv\Scripts\python.exe scripts\plan_query.py "compare nickel leaching at 80 C and 20% acid" --json
.\.venv\Scripts\python.exe scripts\plan_query.py "где написано про извлечение никеля из хвостов" --json
.\.venv\Scripts\python.exe scripts\run_local_knowledge.py nickel --no-raw --no-summaries --no-tables --no-graph --json
.\.venv\Scripts\python.exe -m pytest tests\test_query_planner.py tests\test_web_search.py tests\test_spreadsheet_store.py tests\test_rag_index.py tests\test_rag_validation.py -q
```

Results:

- `compileall`: passed.
- English `plan_query.py` example: passed and produced required JSON.
- Russian `plan_query.py` example: command completed; current PowerShell/tool output displays mojibake for Cyrillic argv, while Python source/tests with Cyrillic literals work.
- Local orchestrator smoke without data scans: passed and preserved the new query plan JSON.
- `pytest`: `35 passed, 2 warnings`.
- `git diff --check`: passed; Git reported only CRLF normalization warnings for edited text files.

## Notes

- Planner v1 is deterministic because Yandex AI Studio is still externally blocked by `403 Permission denied`.
- Route names are normalized as `raw_rag`, `summary_rag`, `graph_search`, `table_search`, `web_search`, and `internal_rag`.
- `app/query/rewrite.py` remains for backward compatibility, but new code should prefer `app/query/planner.py`.
- No API keys are printed by the planner or CLI.
- No `git push` should be performed for this task.
