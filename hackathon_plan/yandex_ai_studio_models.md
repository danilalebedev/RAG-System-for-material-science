# Yandex AI Studio Model Choice

Дата обновления: 2026-07-03.

Приватные значения `YANDEX_API_KEY` и `YANDEX_FOLDER_ID` лежат только в локальном `.env`, который исключен из git. В репозиторий добавлены только placeholder-ы в `.env.example`.

## 1. Что берем для MVP

| Роль | Модель | URI-шаблон | Почему |
|---|---|---|---|
| Embeddings документов/chunks | Yandex Text Embeddings v2 doc | `emb://<folder_ID>/text-embeddings-v2-doc/` | документная embedding-модель для больших текстовых фрагментов; можно выбрать размерность 256/512/768 |
| Embeddings запросов | Yandex Text Embeddings v2 query | `emb://<folder_ID>/text-embeddings-v2-query/` | отдельная query-модель для коротких пользовательских запросов |
| Быстрый fallback embeddings | Yandex Text Embeddings v1 doc/query | `emb://<folder_ID>/text-search-doc/latest`, `emb://<folder_ID>/text-search-query/latest` | стабильные URI, 256-мерные вектора, проще для первого FAISS/BM25 baseline |
| JSON extraction, answer, summaries | YandexGPT Pro 5.1 | `gpt://<folder_ID>/yandexgpt-5.1` | официально подходит для RAG, анализа документов и extraction; 32k контекст |
| Дешевые классификации/переформулировки | YandexGPT Lite 5 | `gpt://<folder_ID>/yandexgpt-5-lite` | быстрые простые задачи: intent, slots, короткие rewrite |
| Длинные документы/сложный reasoning, если нужен | DeepSeek V4 Flash | `gpt://<folder_ID>/deepseek-v4-flash` | 1M context через OpenAI-compatible API; использовать точечно, не для массового extraction |

## 2. Практическая стратегия

Для первого рабочего pipeline:

1. Индексировать chunks через `text-search-doc/latest` или `text-embeddings-v2-doc/` с размерностью 256.
2. Запросы кодировать через соответствующую query-модель: `text-search-query/latest` или `text-embeddings-v2-query/`.
3. Хранить embeddings в FAISS/Qdrant; payload держать отдельно: `chunk_id`, `doc_id`, `source_path`, `page`, entity ids, numeric ranges.
4. Для extraction вызывать YandexGPT Pro 5.1 только по candidate chunks, а не по всему корпусу.
5. Для простого query rewrite/intent можно использовать YandexGPT Lite 5.
6. DeepSeek V4 Flash не использовать как базовую модель из-за стоимости/latency; оставить для редких длинных контекстов или сложной проверки противоречий.

Локальная проверка доступа выполнена 2026-07-03: `text-search-query/latest` через `https://llm.api.cloud.yandex.net/foundationModels/v1/textEmbedding` вернул HTTP 200 и embedding длиной 256.

## 3. Почему embeddings нужны отдельно от LLM

Embedding-модель не "читает" chunks в смысле генерации ответа. Она переводит chunk и query в векторы, чтобы быстро найти похожие фрагменты. После поиска:

1. vector/BM25/graph retrieval выбирает evidence candidates;
2. reranker сортирует candidates;
3. LLM читает только компактный evidence pack и генерирует ответ с источниками.

Числа и диапазоны нельзя надежно искать только в embeddings. Температуры, давления, концентрации, регионы и единицы должны идти через typed metadata filters.

## 4. Ссылки на официальные docs

- Text vectorization models: https://yandex.cloud/en/docs/ai-studio/concepts/embeddings
- Embeddings REST API: https://aistudio.yandex.ru/docs/en/ai-studio/embeddings/api-ref/Embeddings/textEmbedding.html
- Available generative models: https://aistudio.yandex.ru/docs/en/ai-studio/concepts/generation/models.html
- Model overview and use cases: https://aistudio.yandex.ru/docs/en/ai-studio/concepts/generation/
