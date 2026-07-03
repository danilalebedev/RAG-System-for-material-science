# 01. Parsing

Дата обновления: 2026-07-03.

Статус: базовый парсинг корпуса завершен. Эта зона сейчас считается стабильным
read-only входом для graph и RAG.

## Что Уже Сделано

- `1862/1862` локальных файлов обработано.
- `1857 ok`, `5 empty`, `0 failed`, `0 unsupported`.
- `89 703` chunks.
- `5 507` table previews.
- `1 862` full texts.
- `4 190` CSV-файлов с полными Excel-листами.
- Legacy Excel обрабатывается через безопасный bounded pipeline, чтобы не
  перегружать RAM/диск.

Архив для команды:

- Yandex Disk: https://disk.yandex.ru/d/LmU3jske9NQlOA
- Локально у текущего разработчика:
  `C:\Users\user\YandexDisk\Норникель_хакатон\parsed_artifacts\parsed_corpus_full.zip`

## Где Лежит Вход

- `data/parsed/documents.jsonl` - документные metadata, статусы парсинга,
  пути и счетчики.
- `data/parsed/chunks.jsonl` - основной chunk-корпус для downstream задач.
- `data/parsed/tables.jsonl` - previews таблиц и Excel-листов.
- `data/parsed/full_texts/*.txt` - полный извлеченный текст документов.
- `data/parsed/spreadsheets_csv/**/*.csv` - полные CSV-выгрузки Excel-листов.
- `reports/parsing_report.*` - отчеты качества и статистики, если есть локально.

Подробное описание layout: [`../../docs/parsing_data_layout.md`](../../docs/parsing_data_layout.md).

## Как Пользоваться

Для summary/graph:

- читать `chunks.jsonl` потоково;
- при необходимости открывать `full_texts/<doc_id>.txt` для длинного контекста;
- таблицы брать из `tables.jsonl`, а полный Excel открывать через
  `spreadsheets_csv` только по найденному `doc_id`/sheet;
- не изменять parsed-файлы на месте.

Для RAG:

- использовать `chunks.jsonl` как основной dense/lexical corpus;
- metadata из `documents.jsonl` прикладывать к выдаче;
- CSV не индексировать целиком в MVP, а открывать после retrieval по `doc_id`.

## Если Пришли Новые Файлы

Догрузка должна быть воспроизводимой:

```powershell
.\.venv\Scripts\python.exe scripts\update_parsed_corpus.py --dry-run
.\.venv\Scripts\python.exe scripts\update_parsed_corpus.py
.\.venv\Scripts\python.exe scripts\build_parsing_report.py
```

После догрузки нужно проверить:

- счетчики processed/ok/empty/failed/unsupported;
- что новые `doc_id` появились в `documents.jsonl`;
- что для новых документов есть chunks или зафиксирован понятный empty-status;
- что Excel-листы выгружены в CSV при наличии табличных файлов;
- что archive на Yandex Disk обновлен вручную или через отдельный sync-step.

## Что Можно Менять

Только если нужно исправить парсер или догрузить новые файлы:

- `app/parsing/*`
- `app/quality/*`
- `scripts/parse_corpus.py`
- `scripts/update_parsed_corpus.py`
- `scripts/build_parsing_report.py`
- `config/parsing/*`
- `tasks/01_parsing/*`

## Что Не Трогать Из Этой Зоны

- `app/rag/*`, `app/index/*` - зона RAG.
- `app/extract/*`, `app/graph/*` - зона summary/graph.
- `data/parsed/*` в git не добавлять и не редактировать вручную.
