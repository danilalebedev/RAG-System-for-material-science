# AGENTS.md

Локальные инструкции для Codex в этом проекте. Основано на `codex-agent-kit`, приложенном пользователем.

## Принципы

- Считать проект production-кодом для хакатона: изменения должны быть воспроизводимыми и проверяемыми.
- Перед редактированием читать текущие файлы, данные, логи и отчеты.
- Делать минимальное ответственное изменение; не смешивать unrelated refactor с задачей.
- Не печатать и не сохранять секреты. `router_ai_API.docx` содержит ключ и не должен попадать в git.
- Не утверждать, что парсинг/тесты прошли, если команда не была реально запущена.
- Все артефакты данных и отчетов должны быть локально проверяемы после запуска.

## Структура проекта

- `app/` - исходный код пайплайна.
- `app/ingest/` - инвентаризация и скачивание корпуса.
- `app/parsing/` - парсеры PDF/DOCX/PPTX/XLS и chunking.
- `app/quality/` - метрики качества парсинга и отчеты.
- `scripts/` - CLI-скрипты для запуска этапов.
- `config/` - настройки источников, лимитов и путей.
- `data/raw/` - скачанные исходные файлы, не коммитить.
- `data/interim/` - промежуточные JSONL/CSV, не коммитить.
- `data/parsed/` - распарсенные документы/chunks/tables, не коммитить.
- `reports/` - отчеты по запуску и качеству парсинга.
- `hackathon_plan/` - исследовательские планы и архитектурные документы.
- `docs/agent/` - playbooks из `codex-agent-kit`.
- `.agents/skills/` - reusable Codex skills из `codex-agent-kit`.
- `.codex/rules/default.rules` - starter command policy из `codex-agent-kit`.

## Workflow routing

- Новая функциональность: `docs/agent/feature_loop.md`.
- Баги/падения: `docs/agent/repair_loop.md`.
- Тесты: `docs/agent/testing_policy.md`.
- Review: `docs/agent/code_review.md`.
- Security-sensitive изменения: `docs/agent/security_review.md`.

## Команды

- Создать окружение: `py -3.12 -m venv .venv`
- Установить зависимости: `.\.venv\Scripts\python.exe -m pip install -r requirements.txt`
- Проверить компиляцию: `.\.venv\Scripts\python.exe -m compileall app scripts`
- Инвентаризация датасета: `.\.venv\Scripts\python.exe scripts\inventory_yandex_disk.py`
- Скачать seed-подмножество: `.\.venv\Scripts\python.exe scripts\download_dataset.py --max-files 30`
- Распарсить локальные файлы: `.\.venv\Scripts\python.exe scripts\parse_corpus.py --limit 30`
- Отчет качества: `.\.venv\Scripts\python.exe scripts\build_parsing_report.py`

## Проверка и отчетность

После изменений в коде запускать минимум:

1. `.\.venv\Scripts\python.exe -m compileall app scripts`
2. релевантный CLI-скрипт на малом лимите;
3. проверку созданных отчетов в `reports/`.

Финальный ответ должен содержать:

- что изменено;
- какие файлы важны;
- какие команды запускались и результат;
- что не запускалось и почему;
- риски/следующие шаги.
