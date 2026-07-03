# Норникель AI Hackathon: Task 2 "Научный клубок"

Локальный проект для подготовки поисково-аналитической системы по научно-техническому корпусу.

## Главный план разработки

Актуальный план, технические требования, разделение зон ответственности и
контракты между RAG и metadata/graph лежат в [`DEVELOPMENT_PLAN.md`](DEVELOPMENT_PLAN.md).
Рабочие задачи и короткие технические ТЗ для команды лежат в [`tasks/`](tasks/).

Если подключается новый разработчик, начинать нужно с этого файла. Старые
исследовательские планы из `hackathon_plan/` не являются источником истины.

## Быстрый старт

Рекомендуемый воспроизводимый entrypoint для дальнейшей догрузки новых файлов:

```powershell
.\.venv\Scripts\python.exe scripts\update_parsed_corpus.py --dry-run --mode incremental --batch-size 10 --max-batches 1 --package
.\.venv\Scripts\python.exe scripts\update_parsed_corpus.py --mode incremental --batch-size 10 --max-cpu-percent 70 --max-memory-percent 70 --max-disk-active-percent 70
```

Полная пересборка из уже скачанных `data/raw/`:

```powershell
.\.venv\Scripts\python.exe scripts\update_parsed_corpus.py --mode fresh --skip-inventory --skip-download --batch-size 10 --max-cpu-percent 70 --max-memory-percent 70 --max-disk-active-percent 70
```

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe scripts\inventory_yandex_disk.py
.\.venv\Scripts\python.exe scripts\download_dataset.py --max-files 30
.\.venv\Scripts\python.exe scripts\prepare_derived_files.py
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
- `data/parsed/spreadsheets_csv/` - полные листы Excel, выгруженные в CSV, не коммитятся.
- Распарсенные данные на Яндекс.Диске: https://disk.yandex.ru/d/LmU3jske9NQlOA
- `reports/parsing/` - отчеты о покрытии и качестве парсинга, не коммитится.
- `docs/parsing_data_layout.md` - коммитимая инструкция по локальным parsing-артефактам и текущему качеству.
- `docs/data_sharing.md` - как передавать parsed-артефакты между разработчиками без git.
- `hackathon_plan/` - архитектурные и исследовательские документы.

## Секреты

`router_ai_API.docx` содержит API-ключ RouterAI и исключен из git через `.gitignore`.
Yandex AI Studio credentials хранятся только в локальном `.env`; в git попадает только `.env.example` с placeholder-ами.

## Исторический первый этап до доработки парсера

1. Инвентаризировать датасет на Яндекс.Диске.
2. Скачать seed-подмножество.
3. Локально распарсить PDF/DOCX/PPTX/XLSX; legacy `.xls` пока маркируются как `unsupported`.
4. Сформировать отчет качества парсинга.

## Текущий статус полного локального парсинга

Последний полный локальный прогон после доработки архивов, `.doc`, `.docm`,
legacy `.xls/.xlsx` и image metadata fallback:

- 1453 исходных записи найдено в inventory Яндекс.Диска.
- 1862 parse targets после распаковки архивов и derived-файлов.
- 1862 документа прошли parser pipeline.
- 1857 файлов `ok`, 5 `empty`, 0 `failed`, 0 `unsupported`.
- 89 703 chunks создано.
- 5507 таблиц/table previews извлечено.
- 277 361 545 символов текста извлечено.
- 1862 full-text файла лежат в `data/parsed/full_texts/`.
- 4190 CSV-файлов Excel лежат в `data/parsed/spreadsheets_csv/`.

Excel не разворачивается целиком в `chunks.jsonl`: для RAG пишутся компактные
preview chunks и metadata-ссылки, а полные листы лежат отдельными CSV. Это
сохраняет содержимое workbook-ов без перегруза индекса и оперативной памяти.

Оставшиеся ограничения: 5 пустых PDF требуют OCR, 2 image-like файла
представлены только metadata, 2 FlySheet PDF имеют мало извлекаемого текста.

## Исторический статус до доработки парсера

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
- `DEVELOPMENT_PLAN.md`
- `hackathon_plan/yandex_ai_studio_models.md`
