# Full raw chunks RAG report

Дата первичного запуска: 2026-07-04.

Статус: embeddings по `data/parsed/chunks.jsonl` запущены в фоне, полный индекс еще нужно подтвердить по финальному `data/indexes/chunks/manifest.json`.

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
