# Workstream Technical Specs

Дата обновления: 2026-07-03.

Этот документ дополняет `workstream_contracts.md`: здесь описано техническое ТЗ по каждому независимому блоку, библиотеки, варианты решений, критерии готовности и ссылки на работы. Цель - чтобы два разработчика могли брать разные блоки без пересечения файлов и без расхождения по архитектуре.

## 0. Технические требования организаторов

Источник задания: https://nornickel-ai-hackathon.ru/task-2

| Требование | Что обязано быть в решении | Где реализуем |
|---|---|---|
| Естественный аналитический запрос | пользователь задает вопрос текстом, система извлекает intent/slots и при нехватке данных задает уточнение | E. Query backend, G. GUI |
| Поиск по документам | ответ опирается на chunks/tables/full texts, показывает источники | A. Parsing, D. RAG |
| Связанные сущности | материалы, процессы, оборудование, свойства, эксперименты, публикации, эксперты, площадки связаны в графе | B. Normalization, C. Extraction + Graph |
| Числовые диапазоны | температура, давление, концентрации, коэффициенты ищутся как typed metadata, а не только embedding similarity | B. Normalization, C. Extraction, D. RAG |
| География | страны, регионы, месторождения, площадки нормализуются и доступны в фильтрах | B. Normalization, C. Extraction, G. GUI |
| Пробелы и противоречия | система явно показывает, где данных нет или источники расходятся | C. Graph, E. Answer backend, G. GUI |
| Графовая визуализация | ответ сопровождается mini-graph и возможностью раскрыть соседние сущности | C. Graph, G. GUI |
| Источники и достоверность | каждый факт/ребро/ответ имеет `doc_id`, `chunk_id`, source span и confidence | A. Parsing, C. Extraction, D. RAG |
| Экспертная корректировка | пользователь может отметить неверную сущность/связь/нормализацию | B. Normalization, C. Graph, G. GUI |
| Дашборды и экспорт | показываем coverage, качество парсинга, baseline metrics; экспорт CSV/JSON/GraphML/PNG/PDF | F. Evaluation, G. GUI |
| Скорость 3-5 секунд online | все тяжелое делается offline; online только lookup, graph expansion, rerank, короткий LLM answer | D. RAG, E. Query backend |
| Масштаб до 1 млн сущностей | в плане должен быть путь от локального MVP к Qdrant/OpenSearch/Neo4j/Postgres | D. RAG, C. Graph |
| RBAC/аудит | для MVP достаточно архитектурной заготовки: роли, audit log, masking/export controls | G. GUI, E. Query backend |

## 1. Ответ на вопрос про RECIPER

Да, RECIPER добавляет отдельную retrieval-view, но это не отдельный полноценный RAG-бот и не отдельный финальный ответчик.

Правильная схема:

1. C. Extraction находит секции/чанки, похожие на режимы, методики, эксперименты, synthesis/processing recipes.
2. LLM делает краткий `procedure_summary` по этим секциям: материал, процесс, режим, параметры, выход/свойство, источник.
3. D. RAG строит отдельный индекс `procedure_summary_vectors`.
4. Online retrieval ищет одновременно:
   - обычные chunks;
   - BM25;
   - typed metadata;
   - graph neighbors;
   - procedure summaries.
5. Reranker объединяет кандидатов.
6. E. Answer backend генерирует один grounded answer по объединенному evidence pack.

То есть RECIPER-view можно назвать "дополнительным RAG-потоком для procedural summaries", но финальный RAG остается один: hybrid retrieval + graph expansion + answer over evidence.

## 2. A. Corpus Parsing

### Цель

Получить воспроизводимый корпус:

- `documents.jsonl`;
- `chunks.jsonl`;
- `tables.jsonl`;
- `full_texts/*.txt`;
- `parse_manifest.csv`;
- quality report.

### Текущий статус

- 1343 локальных файла обработаны.
- 1177 `ok`, 5 `empty`, 3 `failed`, 158 `unsupported`.
- 73 293 chunks, 1390 tables.
- Legacy `.xls` отключены как `unsupported`, потому что один файл зависал в `pandas/xlrd`.

### Файлы

Можно менять:

- `app/ingest/*`
- `app/parsing/*`
- `app/quality/*`
- `scripts/inventory_yandex_disk.py`
- `scripts/download_dataset.py`
- `scripts/parse_corpus.py`
- `scripts/build_parsing_report.py`

Нельзя менять без согласования:

- JSONL-схему `data/parsed/documents.jsonl`, `chunks.jsonl`, `tables.jsonl`.

### Библиотеки

Уже используем:

- `requests`, `tqdm` - скачивание и прогресс;
- `PyMuPDF` / `fitz` - PDF text extraction;
- `pypdf` - потенциальный fallback;
- `python-docx` - DOCX/DOCM;
- `python-pptx` - PPTX slides/notes;
- `pandas`, `openpyxl` - XLSX;
- `py7zr`, `rarfile` - будущая распаковка архивов;
- `pydantic` - будущие схемы;
- `rich` - читаемые CLI reports.

Что можно добавить позже:

- `pdfplumber` - таблицы и layout-aware PDF extraction;
- `pytesseract`/`easyocr`/Yandex OCR - scan PDF fallback;
- LibreOffice CLI - `.doc` -> `.docx`, `.xls` -> `.xlsx`.

### Решения, которые пробуем

1. MVP: текущий text extraction + chunking.
2. Улучшение PDF: `PyMuPDF` + `pdfplumber` для таблиц/страниц.
3. Улучшение старых Office: LibreOffice headless conversion.
4. OCR fallback: только для `empty/low_text_pdf`, чтобы не тратить время на весь корпус.

### Done

- Полный parse run проходит без зависаний.
- `quality_label` есть у каждого файла.
- У каждого chunk есть `chunk_id`, `doc_id`, `source_path`.
- Full text есть для каждого локального файла, даже если он пустой/unsupported.

## 3. B. Normalization

### Цель

Схлопнуть сырой текст в канонические сущности и единицы:

- материалы;
- месторождения;
- страны/регионы;
- свойства;
- единицы измерения;
- процессы/оборудование;
- alias tables.

### Файлы

Можно менять:

- `app/normalization/*`
- `config/normalization/*`
- `scripts/build_normalization.py`
- `data/processed/normalization/*`

Нельзя менять:

- parser outputs;
- extraction facts без согласования схемы.

### Библиотеки

Используем/планируем:

- `pandas` - CSV/JSONL dictionaries;
- `pydantic` - schema validation;
- `re`/`regex` - unit/numeric patterns;
- `rapidfuzz` - alias/fuzzy matching;
- `pint` - нормализация единиц;
- `natasha` или `pymorphy3` - русские имена/география, если хватит времени;
- `pycountry` - страны;
- `duckdb` или `sqlite` - typed tables.

### Минимальные выходы

- `canonical_entities.jsonl`
- `entity_aliases.jsonl`
- `unit_mappings.jsonl`
- `geo_aliases.jsonl`
- `normalization_overrides.csv`

### Решения, которые пробуем

1. Rules-first: словари + exact/fuzzy aliases.
2. Unit normalization: `C`, `°C`, `г/л`, `%`, `wt%`, `ppm`, `МПа`.
3. География: ручной словарь для Норильск/Мончегорск/Кольский/Новая Каледония и т.п.
4. Entity resolution: exact normalized name -> alias -> fuzzy candidate -> manual override.

### Done

- Есть deterministic `canonical_id`.
- Все downstream-модули могут получить `canonical_id` по `raw_text`.
- Спорные match-и не схлопываются автоматически без confidence/override.

## 4. C. Metadata Extraction + RECIPER + Graph

### Цель

Извлечь факты и построить официальный граф:

Узлы:

- `Material`
- `Process`
- `Equipment`
- `Property`
- `Experiment`
- `Publication`
- `Expert`
- `Facility`

Ребра:

- `uses_material`
- `operates_at_condition`
- `produces_output`
- `described_in`
- `validated_by`
- `contradicts`

### Файлы

Можно менять:

- `app/extract/*`
- `app/graph/*`
- `config/extraction/*`
- `scripts/extract_metadata.py`
- `scripts/build_graph.py`
- `data/processed/extraction/*`
- `data/processed/graph/*`

Нельзя менять:

- normalization dictionaries как источник истины;
- RAG scoring и index internals.

### Библиотеки

Используем/планируем:

- `pydantic` - строгие JSON-схемы extraction output;
- `jsonschema` или Pydantic validation - проверка LLM JSON;
- `openai` client - OpenAI-compatible вызовы RouterAI/Yandex, если нужен единый интерфейс;
- `requests` - прямые вызовы Yandex AI Studio;
- `pandas` - JSONL/CSV processing;
- `networkx` - локальный MVP graph;
- `duckdb`/`sqlite` - source spans/numeric facts;
- `neo4j` driver - optional production path, если захотим показать graph DB.

### RECIPER как технический блок

RECIPER: A Dual-View Retrieval Pipeline for Procedure-Oriented Materials Question Answering.

Идея: материалыедческие ответы часто зависят от процедур и режимов, которые размазаны по документу. Обычные paragraph chunks могут не поднять все параметры в top-k. Поэтому RECIPER строит вторую view:

- обычные paragraph chunks;
- LLM-generated procedure summaries.

В нашем MVP:

- C генерирует `procedure_summaries.jsonl`;
- D строит `procedure_summary_vectors`;
- E получает procedure evidence вместе с chunks/graph.

### Минимальные выходы

- `facts.jsonl`
- `relations.jsonl`
- `procedure_summaries.jsonl`
- `nodes.jsonl`
- `edges.jsonl`
- `source_spans.jsonl`
- `numeric_conditions.jsonl`

### Решения, которые пробуем

1. Rule extraction для чисел/единиц/температур/давлений/концентраций.
2. LLM JSON extraction только по candidate chunks.
3. RECIPER summaries только для procedure candidates, а не для всего корпуса.
4. Graph build через NetworkX + JSONL export.
5. Contradiction detection только для пар с одинаковыми Material/Process/Property и близкими условиями.

### Done

- Каждый факт/ребро имеет `source_span_id`, `doc_id`, `chunk_id`.
- Graph nodes используют только 8 официальных типов.
- Graph edges используют только 6 официальных отношений.
- Procedure summaries не заменяют source chunks, а ссылаются на них.

## 5. D. RAG Retrieval / Index Build

### Цель

Построить гибридный retrieval:

- lexical/BM25;
- vector embeddings;
- procedure summary index;
- typed filters;
- graph expansion;
- reranking.

### Файлы

Можно менять:

- `app/rag/*`
- `app/index/*`
- `config/retrieval/*`
- `scripts/build_indexes.py`
- `scripts/search_cli.py`
- `data/indexes/*`

Нельзя менять:

- extraction/graph schemas без согласования.

### Библиотеки

Используем/планируем:

- `numpy`, `scikit-learn` - baseline TF-IDF/cosine;
- `rank-bm25` или SQLite FTS5 - lexical baseline;
- `faiss-cpu` или `qdrant-client` - vector index;
- Yandex AI Studio embeddings:
  - `text-search-doc/latest`;
  - `text-search-query/latest`;
  - или `text-embeddings-v2-doc/query`;
- `pandas`/`duckdb`/`sqlite` - filters and payloads;
- `rapidfuzz` - lexical/entity fallback;
- optional reranker: YandexGPT Lite/Pro as slow verifier only for top-N.

### Индексы

- `chunk_text_vectors`: обычные chunks;
- `procedure_summary_vectors`: RECIPER summaries;
- `entity_context_vectors`: entity linking/search;
- `bm25_index`: точные термины, марки, числа;
- `metadata_store`: numeric/geo/source filters.

### Решения, которые пробуем

1. B0: BM25/SQLite FTS по chunks.
2. B1: dense vectors по chunks.
3. B2: hybrid BM25 + dense.
4. B3: hybrid + typed filters.
5. B4: hybrid + graph expansion.
6. B5: hybrid + procedure summaries.

### Done

- Query возвращает `candidate_id`, `doc_id`, `chunk_id`, text, scores, source.
- Top-k retrieval работает без LLM.
- Online lookup укладывается в 3-5 секунд на демо-индексе.

## 6. E. Query Backend / Answer Composer

### Цель

Понять вопрос пользователя и собрать grounded answer.

### Файлы

Можно менять:

- `app/query/*`
- `config/query/*`
- `scripts/run_query.py`

Не менять:

- UI layout;
- index builders.

### Библиотеки

Используем/планируем:

- `pydantic` - query slots schema;
- `rapidfuzz` - entity alias lookup;
- YandexGPT Lite - query rewrite/intent/slots;
- YandexGPT Pro - final answer over evidence;
- `jinja2` - prompt templates, если добавим;
- `sqlite/duckdb` - audit/query logs.

### Query slots

- intent: `fact|compare|graph|gap|hypothesis|source_lookup`;
- material/process/property/equipment/facility/expert;
- numeric constraints: parameter, min, max, unit;
- geo constraints;
- source/date/version constraints;
- answer mode: concise/full/table.

### Done

- Если slots недостаточно, backend возвращает `clarification_question`.
- Если evidence слабый, ответ не выдумывает, а показывает gaps.
- Ответ содержит citations и confidence.

## 7. G. GUI / Demo Application

### Почему это отдельный workstream

GUI пересекается с query backend, но не должен менять retrieval/extraction internals. Его задача - показать ценность системы жюри и эксперту: вопрос, фильтры, evidence, graph, gaps, экспорт.

### Файлы

Можно менять:

- `app/ui/*`
- `scripts/run_demo.py`
- `config/ui/*`
- `hackathon_plan/ux/*`

Не менять:

- parser/extraction/index internals;
- JSONL schemas без контракта.

### Библиотеки

MVP:

- `streamlit` - самый быстрый demo UI;
- `plotly` - графики coverage/latency;
- `pyvis` или `networkx` + `plotly` - mini-graph;
- `pandas` - tables;
- `requests` - вызов backend, если разнесем UI/API.

Альтернатива:

- `gradio` - быстрее для chat-like demo, слабее для сложного dashboard;
- FastAPI + React - красиво, но рискованно по времени.

### Экран MVP

1. Верхняя строка: вопрос + кнопка поиска.
2. Левая панель: фильтры material/process/property, диапазоны, география, source type.
3. Вкладки:
   - `Answer`: краткий ответ с citations;
   - `Evidence`: chunks/tables/procedure summaries;
   - `Graph`: mini-graph вокруг найденных сущностей;
   - `Gaps`: чего не хватает, где противоречия;
   - `Sources`: документы и full text snippets;
   - `Benchmarks`: latency, top-k, coverage.
4. Экспорт: CSV/JSON/GraphML/PNG/PDF report.
5. Feedback: "верно/неверно", исправить entity/relation.

### Done

- Один demo question проходит end-to-end.
- Graph view открывается без ручной подготовки.
- Ответ показывает источники.
- Можно экспортировать evidence table.
- UI не скрывает случаи `no evidence`.

## 8. F. Evaluation

### Цель

Сравнить baseline-ы и показать, что граф/metadata/procedure summaries дают пользу.

### Файлы

Можно менять:

- `app/eval/*`
- `eval/*`
- `scripts/evaluate_*.py`
- `hackathon_plan/benchmarks/*`

### Библиотеки

Используем/планируем:

- `pytest` - regression tests;
- `pandas` - metric tables;
- `scikit-learn` - ranking metrics;
- `ragas` - optional automatic answer evaluation;
- `plotly` - benchmark charts.

### Метрики

- Retrieval: Recall@5/10, nDCG@10, MRR, citation hit rate.
- Extraction: JSON validity, entity precision, relation precision, evidence coverage.
- Numeric/geo: range filter accuracy, unit normalization accuracy.
- Graph: graph query success, contradiction precision.
- Answer: faithfulness, completeness, abstention quality.
- Performance: P50/P95 latency, index size, API cost.

### Done

- Есть 20-30 ручных контрольных вопросов.
- Есть baseline table B0-B5.
- Есть latency/cost report для демо.

## 9. Библиография и ссылки

- Официальное задание Task 2: https://nornickel-ai-hackathon.ru/task-2
- RECIPER paper: https://arxiv.org/abs/2604.11229
- RECIPER code/data: https://github.com/ReaganWu/RECIPER
- Microsoft GraphRAG: https://arxiv.org/abs/2404.16130
- LightRAG: https://arxiv.org/abs/2410.05779
- RAPTOR: https://arxiv.org/abs/2401.18059
- RAGAS: https://arxiv.org/abs/2309.15217
- NirDiamant RAG techniques: https://github.com/NirDiamant/RAG_Techniques
- Yandex AI Studio embeddings: https://yandex.cloud/en/docs/ai-studio/concepts/embeddings
- Yandex AI Studio generation models: https://aistudio.yandex.ru/docs/en/ai-studio/concepts/generation/models.html

