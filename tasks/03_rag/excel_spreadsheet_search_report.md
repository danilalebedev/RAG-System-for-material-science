# Отчет по Excel Spreadsheet Search

Дата: 2026-07-03.

Статус: реализовано и подготовлено к использованию в RAG/answer layer.

## Краткий итог

Excel-файлы теперь обрабатываются как отдельный retrieval слой поверх уже
созданных CSV-выгрузок. Мы не эмбеддим все ячейки и не перегружаем основной
RAG-index: chunks/table previews находят релевантный workbook или sheet, а
`search_spreadsheets.py` точечно читает полный CSV и возвращает строки для
ответа.

## Задача

Текстовый RAG уже работает по `data/parsed/chunks.jsonl`, но Excel-файлы нельзя
разворачивать целиком в embeddings: в корпусе есть тысячи CSV-выгрузок листов, и
полный dense index по ячейкам будет тяжелым и шумным. Нужно дать answer layer
способ точечно доставать строки из Excel после того, как retrieval нашел
релевантный workbook или sheet preview.

## Реализация

Добавлен отдельный слой `app/index/spreadsheet_store.py` поверх существующих
parsed artifacts:

- читает `data/parsed/documents.jsonl`;
- извлекает из `metadata_json.sheets[]` список Excel-листов;
- разрешает absolute и portable `csv_path`;
- возвращает листы workbook-а по `doc_id`;
- читает preview первых строк CSV;
- потоково ищет строки в CSV по query terms.

Добавлен CLI:

```powershell
.\.venv\Scripts\python.exe scripts\search_spreadsheets.py "Nickel 2012" --doc-id 486b2a745dcf8685 --top-k 3
```

Ключевые файлы:

- `app/index/spreadsheet_store.py` - API для листов, preview и поиска строк;
- `scripts/search_spreadsheets.py` - CLI для ручного и программного запуска;
- `tests/test_spreadsheet_store.py` - focused tests контракта;
- `tasks/03_rag/README.md` - место интеграции в RAG-документации.

## Как использовать в RAG

Основной маршрут:

1. Запустить обычный retrieval по chunks/table previews:

   ```powershell
   .\.venv\Scripts\python.exe scripts\search_cli.py "Nickel 2012" --top-k 5
   ```

2. Взять из результата `doc_id` Excel workbook-а или sheet preview.
3. Запустить точечный поиск по CSV этого workbook-а:

   ```powershell
   .\.venv\Scripts\python.exe scripts\search_spreadsheets.py "Nickel 2012" --doc-id <doc_id> --top-k 5
   ```

4. В answer layer передавать только найденные строки, `sheet_name`, `row_number`,
   `csv_path`, `file_name`, `source_path`, а не весь CSV.

## Основные команды

Поиск строк в конкретном workbook-е:

```powershell
.\.venv\Scripts\python.exe scripts\search_spreadsheets.py "Nickel 2012" --doc-id 486b2a745dcf8685 --top-k 3
```

Поиск только релевантных листов, без чтения строк CSV:

```powershell
.\.venv\Scripts\python.exe scripts\search_spreadsheets.py "ICSG production usage 2009" --sheets-only --top-k 5
```

Показать preview первых строк найденных листов:

```powershell
.\.venv\Scripts\python.exe scripts\search_spreadsheets.py "ICSG production usage 2009" --sheets-only --preview-rows 5 --top-k 3
```

JSON-вывод для GUI/answer layer:

```powershell
.\.venv\Scripts\python.exe scripts\search_spreadsheets.py "Nickel 2012" --doc-id 486b2a745dcf8685 --top-k 3 --json
```

Ограничить листы и строки при отладке:

```powershell
.\.venv\Scripts\python.exe scripts\search_spreadsheets.py "Nickel 2012" --max-sheets 20 --max-rows-per-sheet 200 --top-k 5
```

## Важные нюансы

- `sheet preview` - это компактное представление листа для RAG, а не полный
  Excel. Сейчас preview создается парсером из первых строк и ограниченного числа
  колонок.
- Полный источник истины для Excel - CSV-файлы в
  `data/parsed/spreadsheets_csv/**/*.csv`.
- Глобальный поиск без `--doc-id` сканирует все CSV-выгрузки. Он работает как
  fallback, но на полном локальном корпусе может занимать около минуты.
- Для интерактива предпочтителен двухшаговый поиск: RAG -> `doc_id` -> CSV row
  search по одному workbook-у.
- Модуль не требует новых зависимостей и не пересобирает embeddings.
- Поиск сейчас lexical substring-based. Он хорошо подходит для имен металлов,
  годов, стран, компаний и названий листов, но не является SQL/аналитическим
  движком по числовым условиям.
- Для будущих числовых фильтров лучше добавить отдельный parser query layer:
  распознавать колонки/единицы измерения и применять typed comparisons после
  выбора листа.

## Рекомендованный контракт для GUI/answer layer

Использовать JSON-вывод CLI или напрямую `SpreadsheetStore.search_rows()`.
Минимальный полезный payload для ответа:

- `doc_id`;
- `file_name`;
- `source_path`;
- `sheet_name`;
- `row_number`;
- `row_text` или массив `row`;
- `csv_path`;
- `matched_terms`;
- `score`.

Не передавать в LLM весь CSV. Если нужно больше контекста, расширять окно вокруг
найденной строки отдельным helper-ом, а не подмешивать весь workbook.

## Проверка

Запускались:

```powershell
.\.venv\Scripts\python.exe -m compileall app scripts
.\.venv\Scripts\python.exe -m pytest tests\test_spreadsheet_store.py -q
.\.venv\Scripts\python.exe -m pytest -q
.\.venv\Scripts\python.exe scripts\search_spreadsheets.py "Nickel 2012" --doc-id 486b2a745dcf8685 --top-k 3
```

Результат:

- compileall прошел;
- focused tests: 4 passed;
- весь pytest suite: 26 passed, 2 deprecation warnings из `bs4/lxml`;
- smoke CLI на реальных Excel CSV вернул строки из `CopperMonitor2012DecData.xlsx`.

## Публикация

Рабочая ветка: `codex/rag-excel-search`.
