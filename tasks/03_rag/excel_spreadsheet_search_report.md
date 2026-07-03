# Excel Spreadsheet Search Report

Дата: 2026-07-03.

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
- весь pytest suite: 24 passed, 2 deprecation warnings из `bs4/lxml`;
- smoke CLI на реальных Excel CSV вернул строки из `CopperMonitor2012DecData.xlsx`.
