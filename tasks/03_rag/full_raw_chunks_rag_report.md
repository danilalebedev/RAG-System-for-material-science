# Full raw chunks RAG report

## Актуальный статус на 2026-07-04

Full raw-chunks vector index построен по всем `89 703` chunks из `data/parsed/chunks.jsonl`.

Подтверждение в `data/indexes/chunks/manifest.json`:

- `limit: null`;
- `chunk_count: 89703`;
- `dimension: 256`;
- `embedding_backend: yandex`;
- `embedding_model_uri: emb://<folder_id>/text-search-doc/latest`;
- `model_selection: fallback`;
- `cache_hits: 4429`;
- `new_embeddings: 85274`;
- `built_at: 2026-07-04T00:36:53.236908+00:00`.

Фактический progress-log завершился событием `complete` в `logs/rag_full_safe_20260704_004807/progress.jsonl`. Полный run занял примерно 2 часа 48 минут от старта `2026-07-04T00:48:08+03:00` до записи manifest `2026-07-04T03:36:53+03:00`; средний темп после cache warmup был около 8-9 chunks/sec.

Lexical SQLite FTS5 index также собран по всем `89 703` chunks:

- команда: `.\.venv\Scripts\python.exe scripts\build_indexes.py --resume --skip-vector`;
- manifest: `data/indexes/lexical/manifest.json`;
- `chunk_count: 89703`;
- `backend: sqlite-fts5`;
- `built_at: 2026-07-04T05:02:13.801324+00:00`.

Текущий статус RAG:

- Vector artifacts корректны: `vector.npy` shape `89703 x 256`, dtype `float32`, sampled norms около `1.0`.
- Lexical validation проходит: `scripts\validate_rag_index.py --mode lexical ...` вернул `status=pass`, `issue_count=0`.
- Domain lexical search возвращает релевантные chunks и source links.
- Dense/hybrid query search сейчас заблокирован внешним Yandex credential/model-permission состоянием: live query embedding requests возвращают `HTTP 403 Permission denied` даже для `text-search-doc/latest`/`text-search-query/latest`. В код добавлена быстрая классификация non-retryable 4xx, чтобы `403` не ретраился минутами.

Практический вывод для других разработчиков: индекс уже можно использовать через lexical mode; dense/hybrid mode включать после проверки доступа Yandex query/doc embedding endpoint для текущего `.env`.

## Что реально запускалось

Vector embeddings build:

```powershell
.\.venv\Scripts\python.exe scripts\build_indexes.py `
  --resume `
  --skip-lexical `
  --sleep-seconds 0.0 `
  --batch-size 500 `
  --progress-jsonl C:\Users\user\Desktop\Норникель_хакатон\logs\rag_full_safe_20260704_004807\progress.jsonl `
  --progress-every 1000 `
  --no-progress-bar
```

Lexical build:

```powershell
.\.venv\Scripts\python.exe scripts\build_indexes.py --resume --skip-vector
```

Hybrid validation with live Yandex query embeddings:

```powershell
.\.venv\Scripts\python.exe scripts\validate_rag_index.py --allow-network
```

Результат: `status=fail`, но причина не в index artifacts и не в lexical relevance. Все 5 search cases содержат expected terms в top-k, однако каждый case получил issue `dense_query_embedding_failed` из-за `HTTP 403 Permission denied` от Yandex.

Lexical-only validation:

```powershell
.\.venv\Scripts\python.exe scripts\validate_rag_index.py `
  --mode lexical `
  --report-json data/indexes/retrieval_validation_lexical_report.json `
  --results-jsonl data/indexes/retrieval_test_results_lexical.jsonl
```

Результат: `status=pass`, `issue_count=0`, `failed_queries=[]`.

Code checks:

```powershell
.\.venv\Scripts\python.exe -m compileall app scripts
.\.venv\Scripts\python.exe -m pytest tests\test_rag_index.py tests\test_rag_validation.py -q
```

Результат: compileall прошел; pytest прошел `6 passed`.

## QA search results

Проверенные команды:

```powershell
.\.venv\Scripts\python.exe scripts\search_cli.py "никелевые концентраты обжиг" --mode lexical --top-k 3 --json
.\.venv\Scripts\python.exe scripts\search_cli.py "флотация медно никелевых руд" --mode lexical --top-k 3 --json
.\.venv\Scripts\python.exe scripts\search_cli.py "серная кислота автоклавное окисление" --mode lexical --top-k 3 --json
```

Ручная оценка:

- `никелевые концентраты обжиг`: top-1 `Цветные металлы/2020/ЦМ № 1-2020.pdf`, chunk `c602d58a8bee0ba5`; текст прямо содержит `медно-никелевые концентраты`, `окислительный обжиг`, `электроплавка`, `плавка`.
- `флотация медно никелевых руд`: top-k содержит документы по обогащению медно-никелевых руд; top-2 `Цветные металлы/2015/CM_02_15.pdf` прямо содержит `Обогащение вкрапленных медно-никелевых руд базируется на коллективно-селективной схеме флотации`.
- `серная кислота автоклавное окисление`: top-1 `Цветные металлы/2014/CM_09_14.pdf`, chunk `c7584e631722fe9a`; текст содержит `автоклавное выщелачивание`, `окислительная` схема, `сульфидный концентрат`, `никель`, `кобальт`.

Критерий релевантности: top-k должен содержать явно совпадающие доменные термины и source path должен вести к тематически подходящему журналу/обзору. По lexical mode критерий выполнен.

## Текущий blocker

Dense/hybrid search сейчас нельзя считать полностью принятым, потому что live embedding запроса не проходит:

```powershell
.\.venv\Scripts\python.exe scripts\search_cli.py "никелевые концентраты обжиг" --mode hybrid --top-k 3 --json
```

Результат после фикса retry: команда завершается быстро с `app.index.embeddings.NonRetryableEmbeddingError: HTTP 403 Permission denied`.

Что проверено:

- `Authorization: Api-Key <secret>` дает `403`;
- `Authorization: Bearer <secret>` тоже дает `403`;
- `text-embeddings-v2-doc/query` по-прежнему возвращают `invalid model_uri`;
- `text-search-doc/latest` и `text-search-query/latest` сейчас возвращают `403` для live requests, хотя doc embeddings этим же fallback model ранее были успешно построены.

Что делать дальше:

1. Проверить в Yandex Cloud Billing/IAM, что ключ из `.env` все еще имеет доступ к Yandex Foundation Models / text embeddings.
2. Проверить, не поменялся ли folder или IAM/API key после долгого build.
3. После восстановления доступа запустить:

```powershell
.\.venv\Scripts\python.exe scripts\validate_rag_index.py --allow-network
.\.venv\Scripts\python.exe scripts\search_cli.py "никелевые концентраты обжиг" --mode hybrid --top-k 5
```

4. Если `--allow-network` пройдет, dense/hybrid RAG можно считать принятым. До этого рабочий режим для демо: `--mode lexical`.

## Файлы, важные для повторения похожего RAG

- `config/retrieval/default.json` - endpoint, model templates, limits, retry/backoff.
- `app/index/chunks.py` - streaming read chunks, stable metadata, cache key.
- `app/index/embeddings.py` - Yandex client, trimming, token-limit shrink, 429 retry, non-retryable 4xx.
- `app/index/vector_store.py` - `vector.npy`, `metadata.jsonl`, `manifest.json`.
- `app/index/lexical.py` - SQLite FTS5 lexical index.
- `app/rag/retrieval.py` - dense, lexical, RRF hybrid.
- `app/rag/validation.py` - artifact validation and relevance QA.
- `scripts/build_indexes.py` - full/resume/rebuild build CLI.
- `scripts/search_cli.py` - manual retrieval CLI.
- `scripts/validate_rag_index.py` - validation report CLI.
- `scripts/benchmark_yandex_embeddings.py` - throughput probe without writing index cache.

Generated artifacts are under `data/indexes/*` and should not be committed.

## Как пользоваться сейчас

Lexical search, работает без Yandex API:

```powershell
.\.venv\Scripts\python.exe scripts\search_cli.py "никелевые концентраты обжиг" --mode lexical --top-k 5
```

Hybrid search, требует рабочий Yandex query embedding endpoint:

```powershell
.\.venv\Scripts\python.exe scripts\search_cli.py "никелевые концентраты обжиг" --mode hybrid --top-k 5
```

Full rebuild с нуля:

```powershell
.\.venv\Scripts\python.exe scripts\build_indexes.py --rebuild
```

Resume после падения:

```powershell
.\.venv\Scripts\python.exe scripts\build_indexes.py --resume
```

Для долгого production-run лучше разделять:

```powershell
.\.venv\Scripts\python.exe scripts\build_indexes.py --resume --skip-lexical --progress-jsonl logs\rag_full\progress.jsonl --progress-every 1000 --no-progress-bar
.\.venv\Scripts\python.exe scripts\build_indexes.py --resume --skip-vector
```

Дата первичного запуска: 2026-07-04.

Исторический статус на момент первичного запуска: embeddings по `data/parsed/chunks.jsonl` были запущены в фоне; полный индекс тогда еще требовал подтверждения по финальному `data/indexes/chunks/manifest.json`. Актуальный статус см. в начале этого отчета.

## Мини-инструкция: как генерируются embeddings для RAG

### Входные данные

Основной вход для raw-chunks RAG:

- `data/parsed/chunks.jsonl` - 89 703 уже распарсенных chunks.
- Summary/document graph не нужен для старта этого индекса. Индекс строится напрямую по исходным chunks.
- `data/parsed/*` считается read-only входом, его не меняем.

Каждая строка chunks используется как отдельная единица векторизации. Для Yandex embeddings текст перед отправкой нормализуется и режется, чтобы не упираться в token limit:

- максимум `1700` символов;
- максимум `1000` whitespace-terms;
- при 400 token-limit код дополнительно ужимает текст и ретраит.

Логика подготовки текста и retry находится в `app/index/embeddings.py`.

### Конфиг Yandex embeddings

Основной конфиг:

- `config/retrieval/default.json`

Актуальные параметры:

```json
{
  "embedding": {
    "backend": "yandex",
    "default_model": "fallback",
    "endpoint": "https://llm.api.cloud.yandex.net/foundationModels/v1/textEmbedding",
    "auth_scheme": "Api-Key",
    "fallback_doc_model_uri_template": "emb://{folder_id}/text-search-doc/latest",
    "fallback_query_model_uri_template": "emb://{folder_id}/text-search-query/latest",
    "max_input_chars": 1700,
    "max_input_terms": 1000,
    "request_timeout_seconds": 60,
    "max_retries": 20,
    "retry_backoff_seconds": 2.0,
    "rate_limit_sleep_seconds": 0.1
  }
}
```

Почему `fallback`: в текущем Yandex folder модели `text-embeddings-v2-doc/query` возвращали `invalid model_uri`, а `text-search-doc/latest` и `text-search-query/latest` успешно отвечали. Folder id и API key в отчетах не раскрываем.

Нужные переменные окружения берутся из `.env`:

- `YANDEX_API_KEY`
- `YANDEX_FOLDER_ID`

`.env`, ключи и реальные model URI с folder id не коммитить и не печатать в логах.

### Команда полного фонового запуска

Полный embeddings build запущен так:

```powershell
$runDir = "logs\rag_full_safe_20260704_004807"
.\.venv\Scripts\python.exe scripts\build_indexes.py `
  --resume `
  --skip-lexical `
  --sleep-seconds 0.0 `
  --batch-size 500 `
  --progress-jsonl "$runDir\progress.jsonl" `
  --progress-every 1000 `
  --no-progress-bar
```

Фактическая команда и пути записаны в:

- `logs/rag_full_latest.json`
- `logs/rag_full_safe_20260704_004807/progress.jsonl`
- `logs/rag_full_safe_20260704_004807/stdout.log`
- `logs/rag_full_safe_20260704_004807/stderr.log`

`--resume` важен: уже полученные embeddings берутся из append-only cache и не пересчитываются.

`--skip-lexical` использован только для долгой векторизации. Lexical index собирается отдельно после завершения embeddings, чтобы не смешивать долгий API-run и локальную сборку.

### Что создается

Vector artifacts:

- `data/indexes/chunks/embedding_cache.jsonl` - append-only cache успешных embeddings;
- `data/indexes/chunks/vector.npy` - итоговая матрица vectors;
- `data/indexes/chunks/metadata.jsonl` - metadata строк в том же порядке, что vectors;
- `data/indexes/chunks/manifest.json` - manifest сборки, модель, размерность, chunk_count, source hash.

Важно: `embedding_cache.jsonl` может содержать старые или дублирующиеся строки после изменения trimming/cache key. Нельзя считать готовность по числу строк cache. Готовность подтверждается только финальным `manifest.json`, где `chunk_count` должен быть `89703` и `limit` должен быть `null` или отсутствовать как ограничение smoke-run.

### Как смотреть прогресс

Проверка живого процесса:

```powershell
Get-CimInstance Win32_Process |
  Where-Object { $_.CommandLine -like '*build_indexes.py*' } |
  Select-Object ProcessId, CreationDate, CommandLine
```

Последний progress event:

```powershell
Get-Content .\logs\rag_full_safe_20260704_004807\progress.jsonl -Tail 1
```

ETA считать по `new_embeddings / elapsed_seconds`, а не по `processed_chunks / elapsed_seconds`, потому что первые chunks могут быть cache hits и дают искусственно высокий темп.

На момент старта полного run рабочий throughput был около `6.8-7.1` новых embeddings/sec. Это дает примерно `3.5-4` часа на embeddings с момента стабильного запуска, плюс `20-40` минут на lexical index и validation.

### Resume после падения

Если процесс упал, сначала читать:

```powershell
Get-Content .\logs\rag_full_safe_20260704_004807\stderr.log -Tail 80
Get-Content .\logs\rag_full_safe_20260704_004807\progress.jsonl -Tail 5
```

Затем перезапускать той же командой с `--resume`. Уже успешные embeddings подтянутся из `embedding_cache.jsonl`.

Если падение из-за Yandex 429, снижать агрессивность не обязательно сразу: клиент ретраит 429 с backoff и jitter. Если 429 становится постоянным и прогресс не растет, можно увеличить `rate_limit_sleep_seconds` или добавить `--sleep-seconds`.

Если падение из-за token-limit 400, проверять `max_input_chars`, `max_input_terms` и dynamic shrink в `app/index/embeddings.py`.

### Что делать после embeddings

Когда `manifest.json` подтвердит полный vector index, собрать lexical index:

```powershell
.\.venv\Scripts\python.exe scripts\build_indexes.py --resume --skip-vector
```

Затем прогнать validation:

```powershell
.\.venv\Scripts\python.exe scripts\validate_rag_index.py
```

И несколько ручных поисков:

```powershell
.\.venv\Scripts\python.exe scripts\search_cli.py "никелевые концентраты обжиг" --top-k 5
.\.venv\Scripts\python.exe scripts\search_cli.py "сульфидные медно никелевые руды флотация" --top-k 5
.\.venv\Scripts\python.exe scripts\search_cli.py "температура плавления никелевого сплава" --top-k 5
```

Проверка релевантности: в top-k должны быть chunks, где явно встречается предмет запроса или близкие доменные термины; `source_path`, `doc_id`, `chunk_id` должны вести к ожидаемому документу/фрагменту, а не к случайному тексту.

### Минимальные проверки кода

```powershell
.\.venv\Scripts\python.exe -m compileall app scripts
.\.venv\Scripts\python.exe -m pytest tests\test_rag_index.py tests\test_rag_validation.py -q
```

Эти команды проверяют код, но не доказывают, что полный индекс готов. Полная готовность доказывается manifest + validation + ручные search QA.
