# Oreacle defense pack

Дата: 2026-07-04

Цель документа: короткий материал для защиты, демовидео и финального питча. Он описывает текущий Streamlit GUI и не использует старые Demo scenario / Query Decomposer элементы.

## 1. One-liner

Oreacle - evidence-first R&D ассистент для материаловедения и металлургии: он уточняет инженерный запрос, ищет локальные и внешние источники, сравнивает методики/свойства и выгружает проверяемые PDF/DOCX/ZIP отчеты.

## 2. Что продаем

Проблема: инженерные знания лежат в PDF, Excel, отчетах, статьях и графах. Обычный чат быстро отвечает, но плохо показывает, откуда взялись методики, условия, диапазоны свойств и насколько релевантны источники.

Решение: Oreacle превращает вопрос в маршрутизированный evidence workflow:

1. LLM rewrite приводит запрос к поисковому виду и RU/EN вариантам.
2. Local RAG ищет raw chunks, document summaries, procedure summaries, tables и graph evidence.
3. Web literature search ищет публикации в scholarly API и ранжирует их по domain/keyword/quartile signals.
4. Deep Search извлекает краткие summaries по выбранным статьям.
5. RouterAI/OpenRouterAI формулирует финальный ответ только по retrieved evidence.
6. GUI показывает ответ, источники, сравнение, графы, графики и отчеты.

## 3. Три пользовательских режима

1. `Литературный поиск`
   - Быстрый список внешних источников по теме.
   - Confidence по каждой публикации.
   - PDF/DOCX links report.
   - Опциональный Deep Search по top-N источникам.

2. `Поиск методик`
   - Сравнение локальных procedure summaries и внешних методик.
   - Граф `Material -> Method -> Source`.
   - Таблицы confirmed / local-only / web-only / differing conditions.

3. `Поиск свойств`
   - Поиск численных результатов, ranges, outputs, conditions.
   - Сравнение локальных evidence и web summaries.
   - Выгрузка таблиц и отчета для ручной проверки.

## 4. Live-demo runbook

URL:

```text
http://127.0.0.1:8501/
```

Устойчивый запуск перед показом:

```powershell
.\.venv\Scripts\python.exe scripts\run_demo_app.py --background --address 127.0.0.1
```

Launcher проверяет импорт текущего GUI, останавливает stale Streamlit demo-процессы на порту 8501,
стартует clean server session, пишет логи в `logs/streamlit_demo/` и делает healthcheck `http://127.0.0.1:8501/`.
На Windows Streamlit может держать parent/child Python-пару; это нормально, если healthcheck проходит.

Настройки перед показом:

- `RAG profile`: `routerai_bge_m3`, если indexes построены; иначе `yandex` или `default`.
- `Local search`: on.
- `Web literature search`: on.
- `LLM rewrite запроса`: on.
- `Ответ через RouterAI`: on.
- `Deep Search`: off для первого быстрого ответа; затем нажать кнопку `Запустить Deep Search по текущей выдаче`.

Перед live-demo можно выполнить preflight:

```powershell
.\.venv\Scripts\python.exe scripts\demo_preflight.py
```

Он проверяет RouterAI key readiness без печати секрета, импорт текущего `app.ui.demo_app`, наличие
`routerai_bge_m3` manifests, Streamlit import, доступность `http://127.0.0.1:8501/` и smoke-поиск
по raw/summary streams. JSON-отчет сохраняется в
`data/processed/demo_preflight/preflight_report.json`.

Для handoff организаторам можно собрать lightweight ZIP без секретов и raw/full-text данных:

```powershell
.\.venv\Scripts\python.exe scripts\build_defense_bundle.py --run-preflight
```

Демо-запрос для режима `Поиск методик`:

```text
Какие никелевые сплавы применяются в судостроении и какие режимы термообработки влияют на твердость?
```

Демо-запрос для режима `Поиск свойств`:

```text
Сравни прочность, твердость и коррозионную стойкость никелевых сплавов после отжига и старения
```

Демо-запрос для режима `Литературный поиск`:

```text
Найди зарубежные публикации по флотации никелевых руд и влиянию реагентов на извлечение Ni
```

Что показывать в GUI:

1. `Ответ`: RouterAI answer, provider metadata, RouterAI token usage/budget summary, query rewrite и keywords.
2. `Источники`: web results с confidence, reasons, quartile и links.
3. `Сравнение`: что подтверждается локально и внешне, что найдено только с одной стороны.
4. `Evidence`: raw/summary/table evidence и fallbacks.
5. `Графы`: local knowledge graph и local-vs-web method graph.
6. `Графики`: распределение публикаций по годам и базам.
7. `Отчеты`: скачать RouterAI answer report, links report, full report и ZIP artifacts.

RouterAI budget guard: preflight и answer reports фиксируют демо-лимит 1500 RUB и фактический token usage из API metadata. Стоимость в рублях сравнивается с лимитом только если RouterAI явно вернул `cost_rub`; иначе система не показывает искусственную оценку цены.

## 5. 90-секундный сценарий видео

0-10 секунд: показать проблему.

```text
В R&D металлургии ответ редко лежит в одном документе: нужны статьи, внутренние отчеты, таблицы, методики, условия и свойства.
```

10-25 секунд: показать единый запрос.

```text
Вводим инженерный вопрос про никелевые сплавы, термообработку и твердость. Oreacle сначала уточняет запрос и строит поисковые формулировки.
```

25-45 секунд: показать ответ.

```text
Финальный ответ формулируется через RouterAI только по найденному evidence: локальные документы, summary RAG, таблицы и внешняя литература.
```

45-60 секунд: показать источники и confidence.

```text
Каждая публикация имеет confidence: высокий, средний или низкий, а также причины - keyword hits, совпадения в заголовке, abstract, domain signals, квартиль журнала.
```

60-75 секунд: показать сравнение и графы.

```text
Для методик система показывает, что подтверждается локально и внешне, где есть только web evidence, где локальная база уникальна и какие условия отличаются.
```

75-90 секунд: показать выгрузку.

```text
В конце можно скачать PDF/DOCX/ZIP: ответ, ссылки, summaries, comparison report, manifests и локальные публикации. Это делает результат проверяемым без чтения кода.
```

## 6. Структура презентации

1. `Problem`: R&D evidence fragmented across internal documents and world literature.
2. `Product`: Oreacle as evidence-first metallurgy R&D assistant.
3. `Workflow`: query rewrite -> local RAG -> web search -> Deep Search -> comparison -> RouterAI answer -> reports.
4. `GUI`: one query, three task modes, seven result sections.
5. `Evidence`: confidence scoring and source traceability.
6. `Comparison`: local vs web method/property analysis.
7. `Exports`: PDF/DOCX/ZIP reports for judges.
8. `Scalability`: independent metadata APIs, RouterAI BGE-M3 profile, fallback Yandex/default RAG, read-only local artifacts.
9. `Business value`: faster engineering review, fewer missed sources, explicit gaps and next experiments.
10. `Close`: Oreacle is not a PDF chatbot; it is an engineering evidence cockpit.

## 7. Что не обещать

- Не обещать массовое скачивание full text с paywalled сайтов.
- Не обещать production-grade библиометрию квартилей: текущий quartile/confidence слой является ranking heuristic.
- Не говорить, что LLM сама знает факты: ответ строится по retrieved evidence.
- Не обещать, что graph полностью готов как промышленная онтология: GUI уже показывает полезный graph layer, который можно заменить/обогатить финальным graph backend.

## 8. Финальная формулировка для защиты

```text
Oreacle помогает R&D-инженеру не просто найти публикации, а получить проверяемый инженерный brief: какие методики и свойства подтверждены локальной базой, что известно во внешней литературе, какие условия и диапазоны отличаются, где есть пробелы, и какие источники можно открыть или выгрузить в отчет.
```
