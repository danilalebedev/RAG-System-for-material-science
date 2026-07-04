# Market Radar / Рыночная разведка

## Что реализовано

- Добавлен независимый модуль `app.market` для production/market intelligence по публичным металлургическим источникам.
- Pipeline работает без LLM для числовых фактов:
  1. определяет commodity/company/country/period из запроса;
  2. выбирает релевантные официальные источники;
  3. загружает small demo fixtures, если live source недоступен;
  4. нормализует единицы (`t`, `kt`, `Mt`, `koz`) и предупреждает о смешанных units;
  5. возвращает structured rows, summary, source status, missing data, chart payloads и internal knowledge terms.
- Добавлена CLI-команда `scripts/run_market_radar.py`.
- Добавлен `scripts/update_market_sources.py` для маленького JSON cache в `data/processed/market_cache/` (директория уже gitignored через `data/processed/`).
- В Streamlit GUI добавлен режим `Market Radar / Рыночная разведка`:
  - demo prompts;
  - executive summary;
  - KPI cards;
  - production table;
  - time-series chart;
  - comparison chart;
  - source status;
  - caveats/missing data;
  - links to internal knowledge terms for Ni/Cu/PGM.

## Поддерживаемые источники v1

- Nornickel production reports
- RUSAL operating results
- World Steel Association data
- International Aluminium Institute statistics
- USGS Mineral Commodity Summaries
- Rosstat / Fedstat / EMISS
- Severstal, NLMK, MMK, Metalloinvest reports

В текущей demo-safe версии live downloads отключены: модуль использует маленькие встроенные fixtures и явно помечает их как `fallback`.

## Команды

```powershell
.\.venv\Scripts\python.exe scripts\run_market_radar.py "Сколько никеля, меди, палладия и платины произвёл Норникель в последнем доступном периоде?"
.\.venv\Scripts\python.exe scripts\run_market_radar.py "Сравни производство стали в России, Китае, Индии и Турции." --json
.\.venv\Scripts\python.exe scripts\update_market_sources.py
.\.venv\Scripts\python.exe scripts\run_demo_app.py
```

## Demo prompts

- Сколько никеля, меди, палладия и платины произвёл Норникель в последнем доступном периоде?
- Покажи динамику производства Ni/Cu/Pd/Pt Норникеля по годам.
- Сравни производство стали в России, Китае, Индии и Турции.
- Покажи мировое производство алюминия по регионам.
- Покажи топ стран по добыче никеля и роль России.
- Свяжи рыночные данные по никелю с внутренними документами по никелевой руде и сульфидным концентратам.

## Known blockers / caveats

- Live загрузка официальных источников не включена в demo-safe режиме, чтобы не зависеть от сети и форматов сайтов во время демо.
- Fixtures предназначены для стабильной демонстрации структуры продукта; перед production-показом последние значения нужно перепроверить по официальным отчетам.
- Yandex API 403 не лечится в этом модуле и не влияет на Market Radar, потому что numeric facts не синтезируются LLM.

## Проверки

- `.\.venv\Scripts\python.exe -m compileall app scripts`
- `.\.venv\Scripts\python.exe -m pytest -q`
- `.\.venv\Scripts\python.exe scripts\run_market_radar.py "Сколько никеля, меди, палладия и платины произвёл Норникель в последнем доступном периоде?"`

## Git

- Push не выполнялся.
