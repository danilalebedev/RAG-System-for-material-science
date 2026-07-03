# Четкий план разработки решения для Task 2 "Научный клубок"

Дата обновления: 2026-07-02.

Основа: актуальное условие https://nornickel-ai-hackathon.ru/task-2, датасет с Яндекс.Диска, предыдущий обзор RAG/GraphRAG/materials science и RouterAI.

## 1. Целевая концепция

Финальное решение: **Scientific Knowledge Mesh: Hybrid Search + Typed Knowledge Graph + Evidence-grounded LLM**.

Это не обычный RAG и не только графовая БД. Система должна:

- быстро искать по большому корпусу научно-технических документов;
- извлекать сущности и связи: материал, процесс, режим, оборудование, свойство, KPI, география, команда, вывод;
- поддерживать числовые фильтры и диапазоны;
- показывать граф связей и цепочки решений;
- отвечать за 3-5 секунд на уже построенном индексе;
- доказывать каждый вывод источниками;
- находить пробелы, противоречия и версии фактов;
- иметь понятный план RBAC/аудита/экспорта.

## 2. Архитектура

### Offline pipeline

1. **Data registry**
   - Рекурсивно скачать/зарегистрировать файлы из Яндекс.Диска.
   - Посчитать hash, размер, тип, путь, раздел корпуса.
   - Таблица: `documents`.

2. **Parsing**
   - PDF: PyMuPDF/pypdf; fallback OCR/RouterAI PDF parser для плохих документов.
   - DOCX/DOCM: python-docx или unzip XML.
   - PPTX: python-pptx для слайдов и speaker notes.
   - XLS/XLSX: pandas/openpyxl/xlrd.
   - ZIP/RAR/001/002: отдельный staging, распаковка только если успеваем и безопасно.
   - Выход: `chunks`, `tables`, `figures`, `slides`.

3. **Chunking**
   - Базовый chunk: 600-1000 tokens, overlap 100-150.
   - Отдельные chunks для таблиц и caption.
   - Сохранять section/page/slide/source path.

4. **Metadata extraction**
   - Быстрый слой: regex/rules для чисел, температур, давлений, концентраций, единиц, географии.
   - LLM слой: extraction в JSON только по candidate chunks, а не по всему корпусу.
   - Procedure summaries в стиле RECIPER для секций с режимами/экспериментами.
   - Валидация: Pydantic/JSON Schema.

5. **Normalization**
   - Alias tables для материалов, месторождений, стран, регионов, свойств, единиц.
   - Unit normalization: температура, давление, время, концентрация, содержание металлов.
   - Дедупликация сущностей с ручным override.

6. **Index build**
   - Full-text: BM25/OpenSearch/SQLite FTS для точных терминов.
   - Vector: FAISS/Qdrant для semantic retrieval.
   - Typed metadata: DuckDB/Postgres для numeric/date/geo filters.
   - Graph: Neo4j/Memgraph или tabular graph + NetworkX для MVP.

### Online query pipeline

1. Query parser выделяет intent и slots:
   - объект: материал/сплав/руда/процесс/месторождение;
   - условия: режим, диапазон температур/давлений/концентраций;
   - свойство/KPI;
   - география;
   - период/версия/источник;
   - тип ответа: факт, сравнение, история, пробел, гипотеза.

2. Если слотов не хватает, UI задает уточнение из справочников и графа.

3. Planner выбирает стратегию:
   - keyword-heavy для марок, чисел, формул;
   - vector-heavy для смысловых вопросов;
   - graph-heavy для цепочек и связанных сущностей;
   - metadata-heavy для диапазонов и географии.

4. Retrieval:
   - BM25 top-k;
   - vector top-k;
   - procedure summary top-k;
   - metadata filters;
   - graph expansion на 1-2 hops.

5. Rerank:
   - lexical overlap;
   - dense score;
   - graph proximity;
   - typed constraint match;
   - source reliability.

6. Answer composer:
   - LLM получает только compact evidence pack;
   - ответ строится с citations;
   - факты без evidence не выводятся как утверждение;
   - если данных мало, выводится "пробел".

## 3. Предметная модель графа

Для MVP берем ровно онтологию из условия как каноническую модель графа.

Типы узлов:

- `Material`
- `Process`
- `Equipment`
- `Property`
- `Experiment`
- `Publication`
- `Expert`
- `Facility`

Типы ребер:

- `uses_material`
- `operates_at_condition`
- `produces_output`
- `described_in`
- `validated_by`
- `contradicts`

Расширенные понятия из раннего плана (`Location`, `Measurement`, `Claim`, `Version`, `Chunk`) не делаем отдельными graph nodes в MVP. Их храним как атрибуты, typed metadata и provenance:

- числовые условия: атрибуты ребра `operates_at_condition` и таблица `numeric_conditions`;
- география: атрибут `Facility.location` и таблица нормализации географии;
- источники: `Publication` + таблица `source_spans`;
- версии: атрибуты `source_date`, `extracted_at`, `version_label`;
- утверждения/выводы: атрибуты `Property`, `Experiment` и evidence spans.

Подробный дизайн extraction JSON, vector search и graph build вынесен в `task2_actual/graph_retrieval_entity_design.md`.

## 4. Хранилища для MVP и масштабирования

### MVP за время хакатона

| Слой | Инструмент | Почему |
|---|---|---|
| Metadata/numeric | DuckDB или SQLite | быстро, локально, простые SQL range filters |
| Full-text | SQLite FTS5/BM25 или Whoosh | быстро стартует без сервера |
| Vector | FAISS или Qdrant local | быстрый semantic retrieval |
| Graph | NetworkX + таблицы nodes/edges | простая сборка и визуализация |
| UI | Streamlit/Gradio | быстро показать Answer/Evidence/Graph/Gaps |
| LLM | локальная open-weight или RouterAI при разрешении | extraction/summaries/answer |

### Масштабирование до 1 млн сущностей

| Слой | Production-вариант |
|---|---|
| Full-text + vector + filters | OpenSearch/Elasticsearch/Vespa или Qdrant + OpenSearch |
| Graph | Neo4j/Memgraph/TigerGraph/JanusGraph |
| Metadata | Postgres + pgvector/PostGIS или ClickHouse/DuckDB для аналитики |
| Queue | Celery/RQ/Prefect для ingestion |
| Cache | Redis для top queries и evidence packs |
| Access control | Postgres/RBAC + audit log |

3-5 секунд достигаются не LLM-агентом, а индексами:

- все документы распарсены заранее;
- embeddings и граф построены заранее;
- numeric/geo filters работают в typed DB;
- LLM генерирует только финальный короткий ответ;
- frequent queries кэшируются.

## 5. RouterAI в этом плане

RouterAI можно использовать как API-ускоритель, если это разрешено правилами и не нарушает ограничения по провайдерам.

Рекомендуемые роли:

- JSON extraction по candidate chunks;
- procedure summaries;
- финальный grounded answer;
- embeddings через `baai/bge-m3` или `intfloat/multilingual-e5-large`, если локальная модель не успевает;
- PDF fallback через file parser для плохих PDF.

Обязательная конфигурация:

```json
{
  "provider": {
    "country": "ru",
    "allow_fallbacks": false
  }
}
```

OpenAI/Anthropic не закладывать в финальное решение. Даже через RouterAI нужно явно фиксировать model id, provider policy и fallback behavior.

## 6. Baseline-системы

| ID | Система | Что проверяет | Deadline |
|---|---|---|---|
| B0 | BM25 по chunks | нижняя граница поиска | первые 2-3 часа |
| B1 | Dense RAG | семантический поиск | день 1 |
| B2 | Hybrid BM25 + dense | сильный поиск без графа | день 1 |
| B3 | Hybrid + numeric filters | соответствие новым требованиям по диапазонам | день 1-2 |
| B4 | Hybrid + graph expansion | связанные сущности и цепочки | день 2 |
| B5 | Hybrid + procedure summaries | вопросы про режимы и эксперименты | день 2 |
| B6 | Full Scientific Mesh | B3+B4+B5+UI+metrics | финал |

Финальный кандидат: B6. Если не успеваем, защищать B3+B4: это лучше соответствует условию, чем красивый чат без range filters и graph evidence.

## 7. Метрики

### Retrieval

- Recall@5/10 по размеченным вопросам.
- nDCG@10.
- MRR.
- Context precision.
- Citation hit rate.

### Graph

- Entity precision/F1 на ручной выборке.
- Relation precision/F1.
- Evidence coverage: доля ребер с источником.
- Graph query success: нашлась ли цепочка material-process-property.
- Conflict detection precision.

### Numeric/geo

- Range filter accuracy.
- Unit normalization accuracy.
- Geo alias accuracy.

### Answer

- Faithfulness.
- Answer relevance.
- Completeness.
- Abstention quality.
- Contradiction handling.

### Performance

- P50/P95 latency.
- Время cold/warm query.
- Время индексации демо-подмножества.
- RAM/VRAM.
- Размер индекса.
- Стоимость RouterAI/API запроса, если используется.

## 8. План работ по времени

### Этап 0: прямо сейчас

1. Зафиксировать требования из Task 2.
2. Сформировать dataset inventory.
3. Подготовить skeleton проекта.
4. Подготовить evaluation questions template.
5. Подготовить prompt/schema для extraction.

### Этап 1: быстрый корпус и baseline

1. Скачать или подключить подмножество: 100-200 файлов из разных разделов.
2. Распарсить PDF/DOCX/PPTX.
3. Построить chunks/tables/documents.
4. Поднять BM25 и dense search.
5. Сделать UI: вопрос -> top sources -> answer.
6. Сделать 20 контрольных вопросов.

### Этап 2: typed metadata

1. Извлечь числовые параметры regex/rules:
   - температура;
   - давление;
   - концентрация;
   - содержание металлов;
   - время;
   - география.
2. Сохранить typed fields в DuckDB/SQLite.
3. Добавить фильтры в UI.
4. Проверить вопросы с диапазонами.

### Этап 3: graph

1. Запустить extraction в JSON по релевантным chunks.
2. Построить nodes/edges вокруг `ExperimentOrObservation`.
3. Добавить graph expansion в retrieval.
4. Сгенерировать mini-graph для ответа.
5. Добавить вкладку `Graph`.

### Этап 4: procedure summaries и качество

1. Найти procedure candidate chunks.
2. Сгенерировать procedure summaries.
3. Добавить отдельный index stream.
4. Сравнить B2/B3/B4/B5 по Recall@k и latency.
5. Добавить detection of gaps/contradictions.

### Этап 5: защита

Подготовить 3 демо:

1. Range query:
   - "Найди эксперименты/наблюдения по процессу X при температуре 900-1100 C и эффект на KPI Z."
2. Graph query:
   - "Какие материалы/месторождения/команды связаны с проблемой Y и какие выводы противоречат друг другу?"
3. Hypothesis/gap query:
   - "Какие пробелы есть по объекту X и какой следующий эксперимент предложить?"

Подготовить финальный slide/table:

- архитектура;
- dataset coverage;
- baseline comparison;
- latency;
- примеры ответов;
- ограничения и roadmap до 1 млн сущностей.

## 9. Минимальный состав репозитория

```text
app/
  ingest/
    yandex_disk.py
    parsers_pdf.py
    parsers_office.py
    chunking.py
  extract/
    schemas.py
    numeric_rules.py
    llm_extract.py
    normalize.py
  index/
    bm25_index.py
    vector_index.py
    metadata_store.py
  graph/
    build_graph.py
    graph_queries.py
    export_graph.py
  query/
    parse_query.py
    retrieve.py
    rerank.py
    answer.py
  eval/
    questions.yaml
    metrics.py
  ui/
    streamlit_app.py
data/
  raw/
  parsed/
  indexes/
  exports/
```

## 10. Главные риски и контрмеры

| Риск | Контрмера |
|---|---|
| 4.98 GB корпуса не успеет обработаться полностью | индексировать representative subset + показать scalable pipeline |
| PDF плохо парсятся | fallback OCR/RouterAI parser + ручной quality report |
| LLM медленная/дорогая | extraction только по candidate chunks, кэш, batch |
| Галлюцинации | answer только по evidence, citations, abstain mode |
| Граф шумный | confidence thresholds, manual alias table, edge evidence requirement |
| 3-5 сек не выполняются | offline indexes, cache, ограниченный top-k, LLM only final answer |
| API ограничения | local fallback + RouterAI provider.country/allow_fallbacks |

## 11. Приоритеты реализации

Если времени мало:

1. **Обязательно:** parsing -> chunks -> BM25+dense -> answer with citations.
2. **Обязательно по новому условию:** typed numeric filters и evidence provenance.
3. **Очень желательно:** graph around ExperimentOrObservation.
4. **Очень желательно:** gap/contradiction view.
5. **Усиление:** procedure summaries в стиле RECIPER.
6. **Архитектурный слайд:** RBAC/audit/export/scale-to-1M, даже если в MVP упрощено.

Главная линия защиты: "Мы построили не чат по PDF, а индексируемую поисково-аналитическую систему с typed facts, graph evidence и быстрым online retrieval".

## 12. Разделение независимых областей разработки

Чтобы параллельная работа не пересекалась, проект делится на независимые workstreams. Подробный контракт по данным и файлам находится в `task2_actual/workstream_contracts.md`, граф связей - в `architecture/workstream_contracts.mmd`.

| Область | Границы задачи | Основные файлы |
|---|---|---|
| A. Corpus parsing | скачать/зарегистрировать корпус, извлечь текст/таблицы, сделать chunks/full_texts и отчет качества | `app/ingest/*`, `app/parsing/*`, `app/quality/*`, `scripts/parse_corpus.py`, `scripts/build_parsing_report.py` |
| B. Normalization | нормализовать материалы, месторождения, страны, регионы, свойства, единицы и alias tables | `app/normalization/*`, `config/normalization/*`, `scripts/build_normalization.py` |
| C. Metadata extraction + graph | извлечь RECIPER summaries, факты, условия, числовые параметры, official graph nodes/edges и provenance | `app/extract/*`, `app/graph/*`, `config/extraction/*`, `scripts/extract_metadata.py`, `scripts/build_graph.py` |
| D. RAG retrieval/index | построить BM25/vector/procedure indexes, embeddings чанков, filters, reranking и retrieval API | `app/rag/*`, `app/index/*`, `config/retrieval/*`, `scripts/build_indexes.py`, `scripts/search_cli.py` |
| E. Query and answer UX | понять пользовательский сценарий, переформулировать вопрос, задать уточнение, собрать grounded answer и UI views | `app/query/*`, `app/ui/*`, `config/query/*`, `scripts/run_demo.py`, `hackathon_plan/ux/*` |
| F. Evaluation | контрольные вопросы, метрики, latency/cost, сравнение baseline B0-B6 | `app/eval/*`, `scripts/evaluate_*.py`, `eval/*`, `hackathon_plan/benchmarks/*` |

Главный контракт: `data/parsed/*` является read-only входом для всех downstream-модулей; каждый модуль пишет свои результаты в отдельную директорию `data/processed/<module>/` или `data/indexes/`. Общие JSONL-схемы меняются только вместе с обновлением `workstream_contracts.md`.
