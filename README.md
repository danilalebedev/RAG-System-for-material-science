# Норникель AI Hackathon: Task 2 "Научный клубок"

Локальный проект для подготовки поисково-аналитической системы по научно-техническому корпусу.

## Быстрый старт

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe scripts\inventory_yandex_disk.py
.\.venv\Scripts\python.exe scripts\download_dataset.py --max-files 30
.\.venv\Scripts\python.exe scripts\parse_corpus.py --limit 30
.\.venv\Scripts\python.exe scripts\build_parsing_report.py
```

## Что где хранится

- `app/` - исходный код пайплайна.
- `scripts/` - CLI-команды.
- `config/task2_sources.json` - публичная ссылка на датасет и настройки.
- `data/raw/` - скачанные исходные файлы, не коммитится.
- `data/interim/` - inventory/download manifest, не коммитится.
- `data/parsed/` - JSONL с документами, chunks и таблицами, не коммитится.
- `data/parsed/full_texts/` - полный извлеченный текст по каждому документу, не коммитится.
- `reports/parsing/` - отчеты о покрытии и качестве парсинга, не коммитится.
- `docs/parsing_data_layout.md` - коммитимая инструкция по локальным parsing-артефактам и текущему качеству.
- `docs/data_sharing.md` - как передавать parsed-артефакты между разработчиками без git.
- `hackathon_plan/` - архитектурные и исследовательские документы.

## Секреты

`router_ai_API.docx` содержит API-ключ RouterAI и исключен из git через `.gitignore`.
Yandex AI Studio credentials хранятся только в локальном `.env`; в git попадает только `.env.example` с placeholder-ами.

## Текущий первый этап

1. Инвентаризировать датасет на Яндекс.Диске.
2. Скачать seed-подмножество.
3. Локально распарсить PDF/DOCX/PPTX/XLSX; legacy `.xls` пока маркируются как `unsupported`.
4. Сформировать отчет качества парсинга.

## Текущий статус полного локального парсинга

Последний полный локальный прогон:

- 1453 файла найдено в inventory Яндекс.Диска.
- 1343 файла скачано/доступно локально; 110 не докачались из-за `429 Too Many Requests`.
- 1343 файла прошли parser pipeline.
- 1177 файлов `ok`, 5 `empty`, 3 `failed`, 158 `unsupported`.
- 73 293 chunks создано.
- 1390 таблиц извлечено.
- 227 577 988 символов текста извлечено.
- 1343 full-text файла лежат в `data/parsed/full_texts/`.

Основные `unsupported`: архивы `.zip/.rar/.001/.002`, legacy `.doc`, legacy `.xls`, `.gif`.

Подробности:

- `reports/parsing/data_storage_guide.md`
- `reports/parsing/parsing_quality_report.md`
- `reports/parsing/quality_assessment_plan.md`
- `docs/parsing_data_layout.md`
- `hackathon_plan/task2_actual/workstream_contracts.md`
- `hackathon_plan/yandex_ai_studio_models.md`
