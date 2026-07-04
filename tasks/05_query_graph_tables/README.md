# Query, Tables, Knowledge Graph Integration

Date: 2026-07-04

## What changed

- Added `app/query/csv_corpus.py` and `scripts/run_csv_query.py`.
- Updated `scripts/run_llm_query.py`:
  - uses ready RAG indexes when available;
  - falls back to lexical scan over `data/parsed/chunks.jsonl`;
  - can add compact table context with `--include-tables`;
  - uses shared `YandexLLMClient`.
- Added `app/graph/build_graph.py` and `app/graph/search.py`.
- Added `scripts/build_knowledge_graph.py` and `scripts/search_graph.py`.
- Added GUI tab `Knowledge Graph` in `app/ui/demo_app.py`.
- Added generated graph artifacts to `.gitignore`: `data/index/`.
- Installed `polars==1.18.0` into the existing project venv.
- Optimized table query: it now ranks table metadata/preview first and reads rows with polars only for top candidates.
- Initialized a local Git repo inside the project directory and added `origin`.

## Data contracts

Read-only inputs:

- `data/parsed/chunks.jsonl`
- `data/parsed/documents.jsonl`
- `data/parsed/tables.jsonl`
- `data/parsed/spreadsheets_csv/**/*`
- optional: `data/processed/publications/*.jsonl`

Generated outputs:

- `data/index/knowledge_graph_nodes.jsonl`
- `data/index/knowledge_graph_edges.jsonl`
- `data/index/knowledge_graph_manifest.json`

## Commands

Build graph:

```powershell
.\.venv\Scripts\python.exe scripts\build_knowledge_graph.py
```

Search graph:

```powershell
.\.venv\Scripts\python.exe scripts\search_graph.py nickel --top-k 5 --paths
```

Ask over text RAG with scan fallback:

```powershell
.\.venv\Scripts\python.exe -X utf8 scripts\run_llm_query.py --retrieval scan --max-scan-rows 1000 --top-k 2 --question "What is known about nickel?"
```

Ask directly to LLM:

```powershell
.\.venv\Scripts\python.exe -X utf8 scripts\run_llm_query.py --no-corpus --question "Answer briefly: does the LLM work?"
```

Table search:

```powershell
.\.venv\Scripts\python.exe -X utf8 scripts\run_csv_query.py nickel --top-k 5 --top-rows 3
```

## Checks run

```powershell
.\.venv\Scripts\python.exe -m compileall app scripts
.\.venv\Scripts\python.exe scripts\run_csv_query.py --help
.\.venv\Scripts\python.exe scripts\run_llm_query.py --help
.\.venv\Scripts\python.exe scripts\build_knowledge_graph.py
.\.venv\Scripts\python.exe scripts\search_graph.py nickel --top-k 5 --paths
.\.venv\Scripts\python.exe -X utf8 scripts\run_csv_query.py nickel --top-k 2 --top-rows 1 --max-rows-per-table 10
```

Extra checks:

- `polars` import works from `.\.venv\Scripts\python.exe`.
- CSV/table query works on real files from `data/parsed/spreadsheets_csv`.
- Table query with Russian query `nikel`/`nickel` equivalent content returns compact table previews from `tables.jsonl`.
- Initial full recursive row scan was too slow; after optimization the same smoke query takes about 11.5 seconds locally.

## Current results

- `compileall` passes.
- Graph build succeeded on currently available parsed artifacts:
  - nodes: `10294`
  - edges: `9697`
- Graph builder warned that `data/processed/publications/*` is not present in this local tree yet.
- CSV/table query now extracts table context with polars and handles empty CSV files without crashing.
- `scripts/test_yandex_llm.py` currently fails with Yandex `403 Permission denied`.
  - `.env` contains Yandex key and folder id, but values were not printed.
  - Current model/base config: `YANDEX_MODEL=yandexgpt/latest`, `YANDEX_BASE_URL=https://ai.api.cloud.yandex.net/v1`.
  - This looks like key/folder/model permission, billing, or quota issue rather than query integration.
- `scripts/run_llm_query.py --include-tables` reaches the same Yandex API error after building context.

## Git state

- Project now has its own Git root:
  - `C:/Users/Пользователь/Documents/New project/хакатон/RAG-System-for-material-science-CODEX`
- Remote:
  - `origin https://github.com/danilalebedev/RAG-System-for-material-science.git`
- No commit and no push were made.
- The parent directory still has an old empty `.git` that Windows refused to rename even outside the sandbox.
  The nested project Git root works correctly when commands are run from the project directory.

## Demo scenarios

1. Nickel recovery from ore
   - Query: `nickel extraction ore flotation recovery`
   - Shows: raw evidence, local source path, graph entities around nickel.

2. Nickel product composition table
   - Query: `nickel pellets electrolytic nickel composition`
   - Shows: table previews and compact chemistry rows instead of dumping full spreadsheets.

3. Matte-slag precious metals
   - Query: `gold silver PGM distribution matte slag`
   - Shows: local evidence, table drill-down, graph paths.

4. Mine water treatment
   - Query: `mine water treatment sulfates chlorides calcium magnesium`
   - Shows: table search, evidence rows, and gaps.

## Next steps

- Fix Yandex AI Studio permission issue and rerun:
  - `scripts/test_yandex_llm.py`
  - `scripts/run_llm_query.py --include-tables`
- Put `data/processed/publications/*.jsonl` into this repo copy, then rerun `scripts/build_knowledge_graph.py` for Material/Process/Experiment-rich graph.
- Add summary-RAG index over `document_summaries.jsonl` and `procedure_summaries.jsonl`.
- Add a lightweight persistent table schema cache for instant GUI response.
- In GUI, connect raw RAG answer + table context + graph paths into one `Local Knowledge` panel.
