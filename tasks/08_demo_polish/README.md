# Oreacle Demo Polish

## What changed

- Renamed the product UI to **Oreacle**.
- Updated browser/page title and hero:
  - `Oreacle`
  - `R&D Knowledge Cockpit for Metals & Mining`
  - `От разрозненных отчётов, таблиц и публикаций — к проверяемым инженерным решениям.`
- Added clickable Demo scenarios for comparison, SO2 removal, graph exploration, table search, and internal-vs-external analysis.
- Added `Safe demo mode` copy: unavailable APIs/indexes are shown as unavailable sources instead of crashing the demo.
- Improved QueryPlan card:
  - intent
  - answer format
  - highlighted entities
  - used search sources
  - entity aliases
  - local search queries
  - web search queries
- Replaced technical labels in route output with manager-friendly copy:
  - raw chunks -> фрагменты внутренних документов
  - retrieved_context -> найденные источники
  - fallbacks -> недоступные источники / резервный режим
  - routes -> использованные источники поиска
- Added local-search diagnostics when local matches are empty.
- Added legal full-text access cards for web results.

## How to run GUI

```powershell
.\.venv\Scripts\python.exe scripts\run_demo_app.py
```

## Demo prompts

- Сравнить методы переработки литий-ионных батарей для извлечения Ni и Co
- Найти технологии удаления SO2 в металлургии и сравнить ограничения
- Показать связи: никель -> процессы -> свойства -> публикации
- Найти таблицы с содержанием Ni, Cu, Co и сравнить значения
- Сравнить внутренние данные с внешними публикациями по кучному выщелачиванию в холодном климате

## Known blockers

- Yandex API may return external `403 Permission denied`; GUI keeps deterministic fallback behavior.
- Some summary artifacts may be absent in this checkout, so summary route can show unavailable-source diagnostics.

## Checked

- `compileall app scripts`
- `pytest -q`
- `scripts\smoke_demo_scenarios.py`
- `scripts\smoke_nickel_ore_query.py`
- `scripts\run_local_knowledge.py "никелевая руда" --json`
- `scripts\resolve_open_access.py --doi "10.48550/arXiv.2604.11229"`

No `git push` was performed.
