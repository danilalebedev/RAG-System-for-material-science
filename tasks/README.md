# Tasks Workspace

Эта папка - рабочая точка входа для команды. Здесь фиксируем короткие
исполняемые ТЗ по отдельным направлениям, чтобы не искать контекст по всему
репозиторию.

Главный архитектурный план проекта: [`../DEVELOPMENT_PLAN.md`](../DEVELOPMENT_PLAN.md).

## Активные задачи

- [`rag_build.md`](rag_build.md) - сборка RAG: embeddings, vector index,
  lexical baseline, retrieval CLI, контракты входов/выходов.

## Правила

- `data/parsed/*` считается read-only входом.
- Generated artifacts не коммитятся: `data/processed`, `data/indexes`,
  `reports`, `artifacts`.
- Секреты не писать в md и не выводить в логи.
- Для долгих API-задач обязателен resume/cache.
- Если меняется контракт JSONL, обновить `DEVELOPMENT_PLAN.md` и релевантный
  файл в `tasks/`.
