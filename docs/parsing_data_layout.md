# Parsing Data Layout

Дата полного локального прогона: 2026-07-03.

Этот документ описывает локальные артефакты parser pipeline. Сырые данные, распарсенные JSONL/full texts и отчеты качества не коммитятся, но структура воспроизводима командами ниже.

## Команды

Основной воспроизводимый сценарий для догрузки новых файлов:

```powershell
.\.venv\Scripts\python.exe scripts\update_parsed_corpus.py --mode incremental --batch-size 10 --max-cpu-percent 70 --max-memory-percent 70 --max-disk-active-percent 70
```

Полная пересборка из уже скачанных исходников:

```powershell
.\.venv\Scripts\python.exe scripts\update_parsed_corpus.py --mode fresh --skip-inventory --skip-download --batch-size 10 --max-cpu-percent 70 --max-memory-percent 70 --max-disk-active-percent 70
```

Проверить, какие команды выполнит pipeline, без изменения данных:

```powershell
.\.venv\Scripts\python.exe scripts\update_parsed_corpus.py --dry-run --mode incremental --batch-size 10 --max-batches 1 --package
```

Ручной эквивалент:

```powershell
.\.venv\Scripts\python.exe scripts\inventory_yandex_disk.py
.\.venv\Scripts\python.exe scripts\download_dataset.py --all
.\.venv\Scripts\python.exe scripts\prepare_derived_files.py
.\.venv\Scripts\python.exe scripts\parse_corpus.py
.\.venv\Scripts\python.exe scripts\build_parsing_report.py
```

Для передачи результата другому разработчику:

```powershell
.\.venv\Scripts\python.exe scripts\package_parsed_artifacts.py
```

См. `docs/data_sharing.md`.

Для smoke test:

```powershell
.\.venv\Scripts\python.exe scripts\download_dataset.py --max-files 30
.\.venv\Scripts\python.exe scripts\parse_corpus.py --limit 30
.\.venv\Scripts\python.exe scripts\build_parsing_report.py
```

## Локальные данные

| Путь | Что хранится | Git |
|---|---|---|
| `data/raw/yandex_task2/` | исходные файлы с Яндекс.Диска, структура папок сохранена | ignored |
| `data/interim/yandex_inventory.jsonl` | полный inventory датасета | ignored |
| `data/interim/download_manifest.jsonl` | статус скачивания каждого файла | ignored |
| `data/parsed/documents.jsonl` | один JSON на файл: parser/status/source metadata/text preview/full_text_path | ignored |
| `data/parsed/chunks.jsonl` | один JSON на chunk: `chunk_id`, `doc_id`, `chunk_index`, `text`, source path | ignored |
| `data/parsed/tables.jsonl` | извлеченные таблицы из DOCX/XLSX | ignored |
| `data/parsed/full_texts/*.txt` | полный извлеченный текст, один файл на документ | ignored |
| `data/parsed/spreadsheets_csv/**/*.csv` | полные листы `.xls/.xlsx`, выгруженные в CSV | ignored |
| `reports/parsing/parse_manifest.csv` | CSV для ручной проверки качества | ignored |
| `reports/parsing/parsing_quality_report.md` | агрегированный отчет качества | ignored |

## Последний результат

Актуальный полный локальный прогон после доработки архивов, `.doc`, `.docm`,
legacy `.xls/.xlsx` и image metadata fallback:

- Inventory: 1453 исходных записи, примерно 4.98 GB.
- Parse targets после распаковки архивов и derived-файлов: 1862 файлов.
- Parser pipeline обработал: 1862 файла.
- `ok`: 1857 файлов.
- `empty`: 5 PDF.
- `failed`: 0.
- `unsupported`: 0.
- Quality labels: 1853 `ok`, 5 `empty`, 2 `low_text`, 2 `low_text_pdf`.
- Chunks: 89 703.
- Tables/table previews: 5507.
- Total extracted text: 277 361 545 символов.
- Full texts: 1862 `.txt` в `data/parsed/full_texts/`.
- Spreadsheet CSV exports: 4190 `.csv` в `data/parsed/spreadsheets_csv/`.

Полные Excel-листы не кладутся целиком в `chunks.jsonl`. Парсер сохраняет
компактные preview/table rows для поиска и metadata-ссылки `csv_path` /
`csv_export_dir`, а точные ячейки остаются в CSV:

```text
data/parsed/spreadsheets_csv/<doc_id>__<workbook_stem>/<sheet_name>.csv
```

Downstream-логика должна эмбеддить preview chunks, а CSV открывать только когда
нужны точные значения ячеек или отдельная metadata extraction по workbook.

## Исторический результат до доработки парсера

- Inventory: 1453 файла, примерно 4.98 GB.
- Локально доступно: 1343 файла.
- Не докачалось: 110 файлов из-за `429 Too Many Requests` при обновлении ссылок Яндекс.Диска.
- Parser pipeline обработал: 1343 файла.
- `ok`: 1177 файлов.
- `empty`: 5 PDF.
- `failed`: 3 DOCM.
- `unsupported`: 158 файлов.
- Chunks: 73 293.
- Tables: 1390.
- Total extracted text: 227 577 988 символов.
- Full texts: 1343 `.txt` в `data/parsed/full_texts/`.

## Актуальные ограничения

- 5 `empty` PDF, вероятно, требуют OCR; OCR пока не включен, чтобы не
  перегружать машину.
- 2 image-like файла представлены metadata-only, без OCR.
- 2 low-text PDF FlySheet/control files содержат мало полезного текста.
- `data/raw/`, `data/parsed/`, `reports/` и `artifacts/` не коммитятся, потому
  что содержат корпус и generated artifacts.

## Исторические ограничения до доработки парсера

- Legacy `.xls` отключены как `unsupported`: один файл зависал в `pandas/xlrd`; для MVP нужен отдельный sandboxed extractor или конвертация в `.xlsx`.
- Legacy `.doc` пока не читаются; нужен LibreOffice/Word automation/antiword fallback.
- `.zip/.rar/.001/.002` не распаковываются автоматически.
- `empty` PDF требуют OCR или внешнего PDF parser fallback.
- DOCM failures связаны с macro-enabled Word content type; нужен отдельный extractor/fallback.

## Как проверять качество вручную

1. Открыть `reports/parsing/parse_manifest.csv`.
2. Отфильтровать `quality_label != ok`.
3. Для нескольких `ok` файлов открыть исходник из `data/raw/yandex_task2/`.
4. Найти соответствующий `doc_id` в `data/parsed/documents.jsonl`.
5. Открыть `full_text_path` из `documents.jsonl`.
6. Сравнить полный текст и несколько chunks из `data/parsed/chunks.jsonl`.
7. Для DOCX/XLSX/XLS проверить `data/parsed/tables.jsonl` и, если нужен полный
   workbook, `data/parsed/spreadsheets_csv/`.

Достаточно для перехода к RAG: 100% parse targets имеют `doc_id`, source path,
full-text artifact и parser status без `failed`/`unsupported`. Для Excel
полные данные доступны через CSV-ссылки.
