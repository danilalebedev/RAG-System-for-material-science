# 04. Query + GUI + Evaluation

Дата обновления: 2026-07-03.

Статус: будущая интеграционная зона. Сейчас не активна: сначала должны появиться
минимальные outputs из `02_summary_graph` и `03_rag`.

## Цель

Собрать пользовательский слой поверх RAG и graph:

- уточнение пользовательского вопроса;
- typed filters по материалам, процессам, свойствам, регионам, датам;
- evidence pack из документов, summaries и graph;
- GUI для поиска, просмотра источников, мини-графа и экспорта;
- evaluation loop для проверки качества ответов.

## Dependencies

От `02_summary_graph`:

- `data/processed/extraction/procedure_summaries.jsonl`
- `data/processed/extraction/numeric_conditions.jsonl`
- `data/processed/graph/nodes.jsonl`
- `data/processed/graph/edges.jsonl`
- `data/processed/graph/graph_stats.json`

От `03_rag`:

- `data/indexes/chunks/*`
- retrieval CLI/API
- top-k hits с `doc_id`, `chunk_id`, `score`, `source_path`, text preview

От parsing:

- `data/parsed/documents.jsonl`
- `data/parsed/chunks.jsonl`
- `data/parsed/full_texts/*`
- `data/parsed/spreadsheets_csv/*`

## Future Files

Можно менять в этой зоне после старта интеграции:

- `app/query/*`
- `app/ui/*`
- `app/eval/*`
- `config/eval/*`
- `scripts/run_demo_app.py`
- `scripts/evaluate_retrieval.py`
- `tasks/04_query_gui_eval/*`

Нельзя менять без согласования:

- `app/index/*`, `app/rag/*` - зона RAG.
- `app/extract/*`, `app/graph/*` - зона summary/graph.
- `data/processed/*` и `data/indexes/*` вручную.

## GUI Requirements Draft

Минимальный demo-screen:

- строка запроса;
- панель уточненных slots: material, process, property, geography, time,
  conditions;
- список evidence documents/chunks;
- вкладка graph с найденными сущностями и 1-2 hop neighbors;
- вкладка tables/source viewer;
- экспорт evidence в JSON/CSV.

GUI не должен модифицировать offline artifacts. Он только читает indexes,
graph outputs и parsed sources.

## Evaluation Draft

Минимальные проверки:

- 5-10 demo queries от команды;
- наличие цитат и `doc_id`/`chunk_id` в ответе;
- retrieval recall вручную по известным документам;
- graph query success для материалов/процессов/свойств;
- latency на warm local artifacts;
- feedback log: полезно/неверно/не хватает источников.
