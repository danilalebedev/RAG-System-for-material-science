# 03. RAG Index Build

Дата: 2026-07-03.

Статус: отдельная зона RAG-разработчика. Текущая active workstream для нас -
`../02_summary_graph/`; RAG-код сейчас не трогаем. Этот документ сохранен как
handoff: в нем описаны входы, модель embeddings, индексы и acceptance criteria,
чтобы второй разработчик мог двигаться независимо.

Цель: построить первый воспроизводимый RAG-слой поверх уже распарсенного корпуса:
dense embeddings по chunks, локальную векторную базу, lexical baseline и CLI
поиска. Этот документ должен быть достаточным, чтобы новый разработчик быстро
понял, что уже сделано, где лежат данные и что именно надо реализовать дальше.

## 1. Что уже готово

Парсинг завершен и считается read-only входом:

- `1862/1862` файлов обработано.
- `0 failed`, `0 unsupported`.
- `89 703` chunks.
- `5 507` table previews.
- `1 862` full-text files.
- `4 190` CSV-файлов с полными Excel-листами.

Архив для команды:

- Yandex Disk: https://disk.yandex.ru/d/LmU3jske9NQlOA
- Локально у текущего разработчика:
  `C:\Users\user\YandexDisk\Норникель_хакатон\parsed_artifacts\parsed_corpus_full.zip`

Основные входы в репозитории:

- `data/parsed/documents.jsonl` - metadata по документам.
- `data/parsed/chunks.jsonl` - основной корпус для embeddings.
- `data/parsed/tables.jsonl` - preview таблиц и листов.
- `data/parsed/full_texts/*.txt` - полный текст документов.
- `data/parsed/spreadsheets_csv/**/*.csv` - полные Excel-листы.

Важные docs:

- `DEVELOPMENT_PLAN.md` - главный план и границы зон разработки.
- `docs/parsing_data_layout.md` - структура parsed-артефактов.
- `docs/data_sharing.md` - как передавать данные без git.
- `hackathon_plan/yandex_ai_studio_models.md` - выбранные Yandex AI Studio models.

## 2. Границы RAG-задачи

Можно менять:

- `app/rag/*`
- `app/index/*`
- `config/retrieval/*`
- `scripts/build_indexes.py`
- `scripts/search_cli.py`

Можно писать generated artifacts:

- `data/indexes/chunks/vector.npy`
- `data/indexes/chunks/metadata.jsonl`
- `data/indexes/chunks/manifest.json`
- `data/indexes/chunks/embedding_cache.jsonl`
- `data/indexes/lexical/*`
- `data/indexes/retrieval_test_results.jsonl`

Нельзя менять без согласования:

- `data/parsed/*`
- `app/extract/*`
- `app/graph/*`
- `data/processed/extraction/*`
- `data/processed/graph/*`
- JSONL-схемы metadata/graph.

RAG читает outputs metadata/graph, когда они появятся, но не строит их сам.

## 3. Модель embeddings

Основной выбор:

- chunks/documents: `emb://<folder_id>/text-embeddings-v2-doc/`
- user query: `emb://<folder_id>/text-embeddings-v2-query/`

Fallback:

- chunks/documents: `emb://<folder_id>/text-search-doc/latest`
- user query: `emb://<folder_id>/text-search-query/latest`

API:

- endpoint: `https://ai.api.cloud.yandex.net/foundationModels/v1/textEmbedding`
- auth: `Authorization: Bearer <YANDEX_API_KEY>`
- folder: `x-folder-id: <YANDEX_FOLDER_ID>`

Секреты:

- `YANDEX_API_KEY` и `YANDEX_FOLDER_ID` уже должны лежать в `.env`.
- `.env` не коммитится.
- Ключи не печатать в stdout/logs.

Рекомендация для первого индекса:

- использовать v2 doc/query;
- размерность оставить default, если API не требует параметр;
- сохранять vectors как `float32`;
- L2-нормализовать vectors перед сохранением;
- cosine similarity считать как dot product.

## 4. Индекс и хранение

Первый MVP без FAISS/Qdrant:

- `numpy` matrix в `vector.npy`;
- metadata отдельно в `metadata.jsonl`;
- `manifest.json` с model id, dim, chunk count, build time, source file hash;
- поиск через `numpy.memmap` или обычный `np.load(..., mmap_mode="r")`;
- top-k через chunked dot product, чтобы не грузить лишнее в RAM.

Почему без FAISS на первом шаге:

- меньше зависимостей на Windows;
- `89 703 x 256/512/768` vectors помещаются в локальный numpy index;
- проще отлаживать и воспроизводить;
- позже можно заменить storage на FAISS/Qdrant без изменения retrieval API.

Ожидаемый metadata row:

```json
{
  "row_id": 0,
  "chunk_id": "chunk_id",
  "doc_id": "doc_id",
  "chunk_index": 1,
  "text_chars": 3200,
  "source_path": "source path",
  "local_path": "local path"
}
```

## 5. Build pipeline

Нужно реализовать `scripts/build_indexes.py`.

Минимальные параметры:

- `--limit N` - построить индекс по первым N chunks для smoke.
- `--resume` - не пересчитывать embeddings, которые уже есть в cache.
- `--rebuild` - удалить старый индекс и пересобрать.
- `--batch-size N` - размер батча API вызовов, если API поддержит batching; иначе использовать как checkpoint interval.
- `--model doc|fallback` - выбрать v2 или fallback model.
- `--sleep-seconds X` - пауза между запросами при rate limit.

Алгоритм:

1. Прочитать `.env`.
2. Прочитать `data/parsed/chunks.jsonl` потоково.
3. Для каждого chunk сформировать стабильный cache key:
   `sha256(model_uri + "\n" + chunk_id + "\n" + text)`.
4. Если embedding есть в `embedding_cache.jsonl`, использовать cache.
5. Иначе вызвать Yandex AI Studio embedding API.
6. Писать cache append-only после каждого успешного embedding.
7. Периодически сохранять checkpoint.
8. После прохода собрать `vector.npy`, `metadata.jsonl`, `manifest.json`.
9. Нормализовать vectors до unit norm.

Ошибка API:

- при 429/5xx сделать retry с backoff;
- после нескольких неудач сохранить прогресс и завершиться с понятной ошибкой;
- не терять уже посчитанный cache.

## 6. Search CLI

Нужно реализовать `scripts/search_cli.py`.

Минимальная команда:

```powershell
.\.venv\Scripts\python.exe scripts\search_cli.py "никелевые сплавы температура обжига"
```

Параметры:

- positional `query`;
- `--top-k 10`;
- `--index-dir data/indexes/chunks`;
- `--model query|fallback`;
- `--json` для machine-readable вывода.

Алгоритм:

1. Прочитать query.
2. Посчитать query embedding через query model.
3. L2-нормализовать.
4. Посчитать similarity к vector matrix.
5. Вернуть top-k candidates.
6. Подтянуть metadata и text chunk из `chunks.jsonl` или сохраненного payload.

Минимальный output candidate:

```json
{
  "rank": 1,
  "score": 0.8123,
  "chunk_id": "chunk_id",
  "doc_id": "doc_id",
  "source_path": "source path",
  "text": "chunk preview..."
}
```

## 7. Lexical baseline

После dense MVP добавить lexical baseline.

Вариант 1, быстрый:

- `sklearn.feature_extraction.text.TfidfVectorizer`;
- сохранить vectorizer через pickle/joblib в `data/indexes/lexical/`;
- cosine search по TF-IDF matrix.

Вариант 2, лучше для продакшена:

- SQLite FTS5;
- таблица chunks с `chunk_id`, `doc_id`, `text`, `source_path`;
- query через `MATCH`.

Для первого demo достаточно варианта 1, если не хотим добавлять новые зависимости.

Hybrid scoring:

- dense top-50;
- lexical top-50;
- объединить через Reciprocal Rank Fusion:
  `score = sum(1 / (k + rank))`, где `k=60`;
- вернуть top-k.

## 8. CSV и таблицы в RAG

CSV не индексируем полностью dense embeddings.

Правило:

- embeddings строятся по chunks, где Excel представлен compact preview;
- полный CSV открывается только после retrieval, когда найден релевантный `doc_id`
  или sheet preview;
- answer layer получает только выбранные строки/колонки, не весь CSV.

Будущий helper:

- `app/index/spreadsheet_store.py`;
- `get_workbook_sheets(doc_id)`;
- `read_sheet_preview(csv_path, n_rows=50)`;
- `find_rows(csv_path, query_terms, numeric_filters)`.

## 9. Интеграция с metadata/graph

Когда второй разработчик подготовит extraction/graph outputs, RAG должен только
читать их:

- `data/processed/extraction/numeric_conditions.jsonl`
- `data/processed/publications/document_summaries.jsonl`
- `data/processed/publications/procedure_summaries.jsonl`
- `data/processed/graph/nodes.jsonl`
- `data/processed/graph/edges.jsonl`

Не строить graph внутри RAG.

Следующий индекс:

- `data/indexes/procedure_summaries/vector.npy`;
- строится по `procedure_summaries.key_points + steps[].description`;
- model тот же `text-embeddings-v2-doc/`;
- search объединяется с chunk vectors через hybrid/RRF.

## 10. Acceptance criteria

Smoke готов, если:

```powershell
.\.venv\Scripts\python.exe scripts\build_indexes.py --limit 1000 --resume
.\.venv\Scripts\python.exe scripts\search_cli.py "никелевые сплавы температура обжига" --top-k 5
```

и выполняется:

- создается `data/indexes/chunks/manifest.json`;
- создается `data/indexes/chunks/vector.npy`;
- создается `data/indexes/chunks/metadata.jsonl`;
- повторный запуск с `--resume` не пересчитывает уже готовые embeddings;
- search возвращает top-k с `doc_id`, `chunk_id`, `score`, `source_path`, text preview;
- в git не попадают `data/indexes/*`, `.env`, API keys;
- `python -m compileall app scripts` проходит.

Full build готов, если:

- индекс построен по всем `89 703` chunks;
- manifest содержит фактический `chunk_count`;
- search latency на warm local index укладывается в несколько секунд;
- есть простой benchmark на 5-10 demo queries.

## 11. Ближайшие шаги

1. Создать `config/retrieval/default.json`.
2. Реализовать Yandex embedding client в `app/index/embeddings.py`.
3. Реализовать vector storage/search в `app/index/vector_store.py`.
4. Реализовать `scripts/build_indexes.py`.
5. Реализовать `scripts/search_cli.py`.
6. Проверить smoke на `--limit 100`.
7. Проверить smoke на `--limit 1000`.
8. Добавить lexical baseline.
9. Добавить hybrid RRF.
10. После готовности graph/procedure outputs подключить их как дополнительные retrieval streams.
