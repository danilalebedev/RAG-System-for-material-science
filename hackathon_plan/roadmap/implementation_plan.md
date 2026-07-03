# Implementation Plan

## До открытия хакатона

1. Подготовить каркас проекта.
   - `ingest/` для парсеров DOCX/PDF/HTML.
   - `index/` для BM25, embeddings, vector store.
   - `extract/` для JSON extraction и нормализации сущностей.
   - `graph/` для таблиц nodes/edges и визуализации.
   - `eval/` для контрольных вопросов и метрик.
   - `ui/` для Streamlit/Gradio демо.

2. Подготовить схемы данных.
   - `documents(doc_id, title, source, type, created_at)`
   - `chunks(chunk_id, doc_id, text, section, page, url, hash)`
   - `entities(entity_id, type, name, normalized_name, attrs)`
   - `relations(src_id, relation, dst_id, experiment_id, evidence_chunk_id, confidence)`
   - `experiments(experiment_id, material_id, regime_json, equipment, team, source_id)`
   - `measurements(measurement_id, experiment_id, property, value, unit, direction, evidence)`

3. Подготовить extraction JSON schema.
   - Материал и состав.
   - Режим обработки: операция, температура, время, давление, среда, скорость охлаждения/нагрева.
   - Свойство: название, значение, единица, направление изменения, метод измерения.
   - Оборудование и установка.
   - Команда/лаборатория.
   - Вывод/claim и evidence span.

4. Подготовить evaluation harness.
   - Набор demo-вопросов.
   - Скрипт подсчета Recall@k/nDCG/MRR.
   - Шаблон ручной оценки answer faithfulness.
   - Таблица latency/resource metrics.

## День 1: получение данных и быстрый baseline

1. Быстро посмотреть формат корпуса и объем.
2. Поднять B0 BM25 и B1 Dense RAG.
3. Сформировать 20-30 контрольных вопросов из документов.
4. Проверить, какие поля реально встречаются: материалы, режимы, свойства, оборудование, команды.
5. Зафиксировать первые метрики и примеры ошибок.

## День 2: усиление retrieval и граф

1. Добавить hybrid retrieval: BM25 + dense + reranker.
2. Сделать RECIPER-view: procedure summaries для документов/секций с экспериментами.
3. Запустить extraction в JSON по ключевым документам.
4. Построить experiment-centric graph.
5. Добавить graph expansion в retrieval: после нахождения материала X брать связанные режимы, свойства, claims и эксперименты.
6. Подготовить графовую визуализацию для 2-3 demo-запросов.

## Перед дедлайном

1. Выбрать финальный кандидат по таблице метрик.
2. Заморозить демо-корпус и контрольные вопросы.
3. Подготовить 3 сценария защиты:
   - точечный вопрос material X + regime Y + property Z;
   - поиск пробелов и противоречий;
   - генерация гипотезы с объяснением источников.
4. Сохранить индексы и результаты запусков как артефакты.
5. Подготовить fallback: если LLM/API недоступна, показать retrieval + graph + шаблонный answer composer.

## Рекомендуемый стек для MVP

- Python.
- Parsing: python-docx или docx через zip/xml, BeautifulSoup/trafilatura для HTML, PyMuPDF/pypdf для PDF.
- Storage: DuckDB/SQLite для метаданных и графовых таблиц.
- Vector: Qdrant local или FAISS; если время минимальное, Chroma/FAISS.
- Lexical: rank-bm25 или Whoosh/Lucene-подобный индекс.
- Graph: NetworkX + PyVis/Graphviz для MVP; Neo4j/Memgraph только если установка не съедает время.
- Embeddings: multilingual BGE-M3/E5-like model; для английских статей можно BGE-large/E5-large.
- Reranker: компактный cross-encoder/reranker, например BGE-reranker family.
- LLM: локальная open-weight модель 4B-14B в quantized режиме или разрешенный организаторами API. OpenAI/Anthropic не закладывать в финальное решение.
- UI: Streamlit/Gradio с вкладками Answer, Evidence, Graph, Gaps, Benchmark.
