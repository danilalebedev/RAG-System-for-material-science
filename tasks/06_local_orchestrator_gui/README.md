# Local Orchestrator and GUI Integration

Date: 2026-07-04

## Context

The QA/product feedback says the demo will be judged mostly through the GUI, so the local RAG, summary RAG, tables, and knowledge graph need to look like one usable research cockpit.

Two design inputs were used:

- RECIPER-style dual-view retrieval: keep raw text retrieval and procedure/document summary retrieval as separate evidence streams, then combine them for answer generation.
- Query-rewrite layer from RAG practice: rewrite/classify/decompose the user question before retrieval, so raw RAG, summary RAG, graph search, table search, and web search can share one intent.

## What changed

- Added `app/query/local_orchestrator.py`.
  - Combines deterministic query rewrite, raw chunk scan, document/procedure summary search, table search, and knowledge graph search.
  - Produces a single `LocalKnowledgeBundle` with `raw_chunks`, `summary_hits`, `table_hits`, `graph_hits`, graph neighbors/paths, combined evidence context, and markdown brief.
  - Does not call Yandex LLM and degrades gracefully when optional artifacts are missing.
- Added `scripts/run_local_knowledge.py`.
  - CLI smoke/demo entrypoint for local orchestration.
  - Supports `--json` and `--context`.
- Updated `app/ui/demo_app.py`.
  - Added a `Local Knowledge` tab to completed search runs.
  - Added a `Run local` button in the R&D cockpit for quick local-only demo.
  - Local panel shows raw chunks, summaries, tables, graph hits, graph neighbors, combined context, and rewrite plan.

## Commands

Local orchestrator CLI:

```powershell
.\.venv\Scripts\python.exe scripts\run_local_knowledge.py "nickel extraction ore flotation recovery" --context
```

JSON payload:

```powershell
.\.venv\Scripts\python.exe scripts\run_local_knowledge.py "nickel extraction ore flotation recovery" --json
```

GUI:

```powershell
.\.venv\Scripts\python.exe scripts\run_demo_app.py
```

Then use either:

- `Run local` in the R&D cockpit;
- or run a normal search and open the `Local Knowledge` tab.

## Checks run

Succeeded before implementation, while `.venv` was still runnable:

```powershell
.\.venv\Scripts\python.exe -m compileall app scripts
```

Succeeded after implementation:

```powershell
git diff --check
```

Blocked in the current Desktop environment:

```powershell
.\.venv\Scripts\python.exe --version
.\.venv\Scripts\python.exe scripts\run_local_knowledge.py "nickel" --json
.\.venv\Scripts\python.exe scripts\run_csv_query.py nickel --top-k 2 --top-rows 1 --max-rows-per-table 10
.\.venv\Scripts\python.exe scripts\search_graph.py nickel --top-k 3 --paths --json
.\.venv\Scripts\python.exe -m pytest ...
```

Observed blocker:

- `.venv\pyvenv.cfg` points to a base Python path with mojibake in the username.
- The venv executable currently fails with `No Python at '"C:\Users\????????????\AppData\Local\Programs\Python\Python311\python.exe'`.
- `.venv` was intentionally not edited.
- `pytest` is also not installed in this `.venv`.

Existing external blocker:

- Yandex AI Studio still returns `403 Permission denied`; this remains an API key / Folder ID / billing / model-access issue, not a code issue.

## Data safety

No rebuild command was run for:

- `data/parsed`
- `data/index`
- `data/raw`
- `artifacts`
- `reports`

The new orchestrator only reads those inputs when present.

## Next steps

1. Fix or recreate `.venv` outside this task, then run:
   - `scripts/run_local_knowledge.py ... --json`
   - `scripts/run_csv_query.py ...`
   - `scripts/search_graph.py ...`
   - GUI smoke test.
2. Add a summary vector index over `data/processed/publications/document_summaries.jsonl` and `procedure_summaries.jsonl`.
3. Connect `LocalKnowledgeBundle.context` to the final LLM answer once Yandex access is unblocked.
4. Add demo presets for:
   - nickel ore flotation and recovery;
   - mine water treatment;
   - matte-slag precious metals distribution;
   - cold climate heap leaching.
