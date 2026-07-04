# 08. Yandex Summary Vectorization Watcher

Date: 2026-07-04

## Goal

Default retrieval stays Yandex-first. Since the contest Yandex key can return
`403 Permission denied`, this workstream adds a reproducible watcher:

1. probe Yandex embedding API with a small query/doc embedding request;
2. if the probe succeeds, trigger the summary vectorization agent;
3. keep progress and status logs under `logs/`;
4. keep generated indexes under `data/indexes/`, outside git.

RouterAI is not the primary embedding path for this workstream. It remains an
emergency fallback if Yandex is not restored in time.

## Development Zone

Can change:

- `app/index/summaries.py`
- `app/index/embeddings.py` only for provider/auth fixes
- `app/index/vector_store.py` only for generic index storage fixes
- `scripts/build_summary_indexes.py`
- `scripts/watch_yandex_and_build_summary_index.py`
- `config/retrieval/*`
- `tests/test_summary_index.py`
- `tasks/08_yandex_summary_vectorization/*`

Read-only inputs:

- `data/processed/publications/publications.jsonl`
- `data/processed/publications/document_summaries.jsonl`
- `data/processed/publications/procedure_summaries.jsonl`
- `data/processed/publications/publication_evidence_spans.jsonl`
- `data/parsed/*`

Do not change without coordination:

- `app/extract/*`
- `app/graph/*`
- `app/query/*`
- `data/processed/publications/*.jsonl` schema
- raw chunk index code except shared embedding/storage helpers

Generated outputs:

- `data/indexes/document_summaries/*`
- `data/indexes/procedure_summaries/*`
- `logs/yandex_summary_watch/*`

These outputs are ignored by git.

## Commands

One-shot Yandex probe without building:

```powershell
.\.venv\Scripts\python.exe scripts\watch_yandex_and_build_summary_index.py `
  --max-attempts 1 `
  --no-build `
  --no-progress-bar
```

Watch until Yandex works, then build both summary indexes:

```powershell
.\.venv\Scripts\python.exe scripts\watch_yandex_and_build_summary_index.py `
  --interval-seconds 300 `
  --build-kind both `
  --no-progress-bar
```

Direct summary index build, when Yandex is already confirmed:

```powershell
.\.venv\Scripts\python.exe scripts\build_summary_indexes.py `
  --kind both `
  --resume `
  --model fallback `
  --progress-jsonl logs\yandex_summary_watch\summary_index_progress.jsonl
```

Offline smoke without API:

```powershell
.\.venv\Scripts\python.exe scripts\build_summary_indexes.py `
  --kind both `
  --limit 5 `
  --embedding-backend local-hash `
  --rebuild `
  --no-progress-bar
```

## Data Contract

`document_summaries.jsonl` and `procedure_summaries.jsonl` are converted into
`SummaryRecord` rows with:

- `summary_id`
- `kind`
- `doc_id`
- `publication_id`
- `title`
- `source_path`
- domain-rich embedding text

The embedding text intentionally includes summary, materials, processes,
equipment, properties, process parameters, observed effects, numerical results,
geography and source fields.

## Acceptance Criteria

- watcher records every probe in `logs/yandex_summary_watch/status.jsonl`;
- on successful Yandex probe, watcher starts `scripts/build_summary_indexes.py`;
- generated manifests exist:
  - `data/indexes/document_summaries/manifest.json`
  - `data/indexes/procedure_summaries/manifest.json`
- repeated build with `--resume` reuses cache;
- secrets are not printed;
- `python -m compileall app scripts` passes;
- `pytest tests/test_summary_index.py tests/test_rag_index.py` passes.

## Handoff

After indexes are built, the RAG owner can wire dense summary retrieval into:

- `app/query/local_orchestrator.py`
- `app/query/orchestrator.py`
- GUI evidence tabs

Until then the existing lexical summary search remains the fallback.
