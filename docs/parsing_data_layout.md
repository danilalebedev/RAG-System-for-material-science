# Parsing Data Layout

Дата полного локального прогона: 2026-07-03.

Этот документ описывает локальные артефакты parser pipeline. Сырые данные, распарсенные JSONL/full texts и отчеты качества не коммитятся, но структура воспроизводима командами ниже.

## Команды

```powershell
.\.venv\Scripts\python.exe scripts\inventory_yandex_disk.py
.\.venv\Scripts\python.exe scripts\download_dataset.py --all
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
| `reports/parsing/parse_manifest.csv` | CSV для ручной проверки качества | ignored |
| `reports/parsing/parsing_quality_report.md` | агрегированный отчет качества | ignored |

## Последний результат

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

## Известные ограничения

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
7. Для DOCX/XLSX проверить `data/parsed/tables.jsonl`.

Достаточно для перехода к RAG: 87.6% локально доступных файлов уже `ok`, у chunks есть `doc_id` и source path, проблемные форматы перечислены отдельно.
