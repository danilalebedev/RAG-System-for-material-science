# 00. Project Context

Дата обновления: 2026-07-03.

Цель папки: держать короткий общий контекст, чтобы новые участники быстро
понимали, где лежит план, данные, исследования и границы разработки.

## Основные ссылки

- Главный план: [`../../DEVELOPMENT_PLAN.md`](../../DEVELOPMENT_PLAN.md).
- README проекта: [`../../README.md`](../../README.md).
- Распарсенные данные: https://disk.yandex.ru/d/LmU3jske9NQlOA
- Layout parsed-данных: [`../../docs/parsing_data_layout.md`](../../docs/parsing_data_layout.md).
- Передача данных без git: [`../../docs/data_sharing.md`](../../docs/data_sharing.md).
- Модели Yandex AI Studio: [`../../hackathon_plan/yandex_ai_studio_models.md`](../../hackathon_plan/yandex_ai_studio_models.md).
- Официальные требования Task 2:
  [`../../hackathon_plan/task2_actual/official_task2_requirements.md`](../../hackathon_plan/task2_actual/official_task2_requirements.md).

## Research References

- Локальный PDF RECIPER:
  `Литература/Material Science/2604.11229v1.pdf`
- Индекс источников и ссылки:
  [`../../hackathon_plan/sources/source_index.md`](../../hackathon_plan/sources/source_index.md).
- RECIPER paper: https://arxiv.org/abs/2604.11229v1
- RECIPER code/data: https://github.com/ReaganWu/RECIPER
- GraphRAG paper: https://arxiv.org/abs/2404.16130
- LightRAG paper: https://arxiv.org/abs/2410.05779
- RAGAS paper: https://arxiv.org/abs/2309.15217

## Workstream Ownership

На текущий этап зоны разделены так, чтобы не было конфликтов в одних и тех же
файлах:

- Summary + graph: активная зона текущей работы. Документация:
  [`../02_summary_graph/`](../02_summary_graph/).
- RAG: отдельная зона другого разработчика. Документация:
  [`../03_rag/`](../03_rag/).
- Parsing: уже сделан, трогаем только при новых файлах или исправлении парсера.
  Документация: [`../01_parsing/`](../01_parsing/).
- Query/GUI/eval: интеграционная зона после готовности graph и RAG.
  Документация: [`../04_query_gui_eval/`](../04_query_gui_eval/).

## Общие Контракты

- `doc_id` связывает документ, чанки, full text, таблицы, summaries, facts,
  graph nodes/edges и future retrieval hits.
- `chunk_id` связывает конкретный фрагмент текста с extraction evidence.
- `source_span_id` должен появиться в extraction layer, чтобы любой факт или
  ребро можно было открыть в исходном тексте.
- Граф строится только из типов сущностей и отношений, заданных условием
  хакатона. Числа, единицы, география и confidence являются атрибутами или
  отдельными fact records, а не новыми типами узлов.

## Правила Изменений

- Не коммитить `data/*`, `reports/*`, `artifacts/*`, `.env`, ключи API.
- Не менять чужую workstream-зону без согласования через md-контракт.
- Если меняется JSONL-схема, обновить сначала task-doc, затем код.
- Любой долгий API-процесс должен иметь cache/resume и лимиты нагрузки.
