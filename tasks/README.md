# Tasks Workspace

Эта папка - рабочая точка входа для команды. Каждый крупный шаг разработки
лежит в отдельной подпапке: внутри хранится короткое ТЗ, что уже сделано,
какие файлы можно менять и как дальше работать с результатом.

Главный архитектурный план проекта: [`../DEVELOPMENT_PLAN.md`](../DEVELOPMENT_PLAN.md).

## Структура

- [`00_project_context/`](00_project_context/) - общий контекст проекта, ссылки,
  роли workstreams и правила синхронизации.
- [`01_parsing/`](01_parsing/) - статус парсинга корпуса, layout артефактов и
  процедура догрузки новых файлов.
- [`02_publication_metadata/`](02_publication_metadata/) - библиографическая
  metadata и document-level RECIPER-style summaries: авторы, год,
  журнал/конференция, DOI, тип документа, procedure cards, evidence.
- [`02_summary_graph/`](02_summary_graph/) - активная зона: RECIPER-style
  summaries, extraction фактов и построение typed graph.
- [`03_rag/`](03_rag/) - зона RAG-разработчика: embeddings, vector index,
  lexical baseline, retrieval API. Отчет по Excel-поиску:
  [`03_rag/excel_spreadsheet_search_report.md`](03_rag/excel_spreadsheet_search_report.md).
- [`04_query_gui_eval/`](04_query_gui_eval/) - будущая интеграция query layer,
  GUI, evaluation и demo flows.

## Текущий фокус

Мы сейчас не трогаем RAG-реализацию. RAG находится в `tasks/03_rag/` и
разрабатывается отдельно. Наша независимая зона - metadata/graph:
`tasks/02_publication_metadata/` собирает библиографию источников и
document-level summaries; `tasks/02_summary_graph/` читает эти outputs и
строит typed facts/graph с доказательствами.

## Правила

- В `tasks/` не добавлять новые плоские md-файлы: каждый новый workstream
  получает собственную подпапку.
- `data/parsed/*` считается read-only входом.
- Generated artifacts не коммитятся: `data/processed`, `data/indexes`,
  `reports`, `artifacts`.
- Секреты не писать в md и не выводить в логи.
- Для долгих API-задач обязателен resume/cache.
- Если меняется контракт JSONL, обновить `DEVELOPMENT_PLAN.md` и релевантный
  файл в `tasks/<step>/README.md`.
