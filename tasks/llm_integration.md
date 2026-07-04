# LLM integration: Yandex AI Studio

Date: 2026-07-03

## What changed

- Added reusable Yandex AI Studio client in `app/llm/yandex_client.py`.
- Reworked `scripts/test_yandex_llm.py` to use the shared client.
- Added `scripts/run_llm_query.py` for:
  - direct test LLM calls with `--no-corpus`;
  - simple corpus-grounded calls over `data/parsed/chunks.jsonl`.
- Added a small lexical retrieval helper in `app/query/simple_corpus.py`.
- Extended `.env.example` with `YANDEX_MODEL` and `YANDEX_BASE_URL`.

## How to use

Direct LLM call:

```powershell
.\.venv\Scripts\python.exe scripts\run_llm_query.py --no-corpus "Ответь коротко: API работает?"
```

Question over parsed chunks, if `data/parsed/chunks.jsonl` is present:

```powershell
.\.venv\Scripts\python.exe scripts\run_llm_query.py "методы обессоливания воды при сульфатах 200 мг/л"
```

Old smoke script still works through the shared client:

```powershell
.\.venv\Scripts\python.exe scripts\test_yandex_llm.py
```

## Environment variables

Read from local `.env` only:

- `YANDEX_API_KEY`
- `YANDEX_FOLDER_ID`
- `YANDEX_MODEL`
- `YANDEX_BASE_URL`

Do not commit `.env`.

## Current limitations

- `scripts/run_llm_query.py` uses a transparent lexical scan of `chunks.jsonl`; it is not the final RAG index.
- Next RAG step from `DEVELOPMENT_PLAN.md`: `config/retrieval/default.json`, Yandex embeddings client, `scripts/build_indexes.py`, `scripts/search_cli.py`.
- In the current local shell, `.venv` is broken and points to a Python path with corrupted Cyrillic username:
  `C:\Users\????????????\AppData\Local\Programs\Python\Python311\python.exe`.
  Real Yandex API smoke needs the project venv repaired first. Do not use system Python or `py` launcher for project checks.

## Checks to run after venv repair

```powershell
.\.venv\Scripts\python.exe -m compileall app scripts
.\.venv\Scripts\python.exe scripts\run_llm_query.py --help
.\.venv\Scripts\python.exe scripts\test_yandex_llm.py
```
