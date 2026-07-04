# Oreacle Pitch Deck

Короткая структура презентации для защиты. Формат: один слайд - один тезис, без технического перегруза.

## Slide 1. Oreacle

Evidence-first R&D assistant для материаловедения, металлургии и горного дела.

Ключевая фраза: не просто чат по PDF, а cockpit, который связывает локальные документы, мировую литературу, методики, свойства, графы и проверяемые отчеты.

## Slide 2. Problem

R&D-вопрос редко закрывается одним документом:

- внутренние PDF/DOCX/PPTX/Excel лежат разрозненно;
- экспериментальные методики и условия спрятаны в procedure sections;
- свойства и численные диапазоны разбросаны по таблицам и статьям;
- внешний контекст нужно сравнивать с локальной базой.

Обычный RAG дает ответ, но плохо продает evidence, confidence и gaps.

## Slide 3. Product

Oreacle превращает инженерный вопрос в evidence workflow:

1. уточняет и переформулирует запрос;
2. ищет локальные raw chunks, summaries, procedures, tables и graph evidence;
3. ищет внешние статьи в scholarly sources;
4. сравнивает local vs web по методикам, условиям и свойствам;
5. формулирует ответ через RouterAI;
6. выгружает PDF/DOCX/ZIP для проверки.

## Slide 4. Three User Modes

`Литературный поиск`: быстрый список релевантных публикаций, confidence, links report, optional Deep Search.

`Поиск методик`: сравнение режимов обработки и экспериментальных условий, graph `Material -> Method -> Source`.

`Поиск свойств`: свойства, ranges, numeric results, graph `Material -> Property -> Value/range -> Source`.

## Slide 5. Architecture

Поток данных:

```text
User query
  -> LLM rewrite
  -> Local RAG: raw + summaries + procedures + tables + graph
  -> Web literature APIs
  -> Optional Deep Search summaries
  -> Local vs web comparison
  -> RouterAI answer
  -> PDF/DOCX/ZIP exports
```

Текущий демо-профиль: `routerai_bge_m3` для raw chunks, document summaries и procedure summaries.

## Slide 6. What The User Sees

Один chat input и семь вкладок результата:

- `Ответ`: итоговый RouterAI answer, budget/usage, query rewrite;
- `Источники`: web/local evidence, confidence и причины релевантности;
- `Сравнение`: confirmed/local-only/web-only/gaps;
- `Evidence`: raw/summary/table rows;
- `Графы`: knowledge graph и mode-aware comparison graph;
- `Графики`: годы публикаций и источники;
- `Отчеты`: PDF/DOCX/JSON/ZIP.

## Slide 7. Confidence And Trust

Каждая публикация получает confidence label и причины:

- keyword/title/abstract hits;
- material/process/property signals;
- DOI/abstract/year/citation metadata;
- journal quartile signal where available;
- source coverage.

Это важно для экспертов: они видят не только score, но и почему источник попал в выдачу.

## Slide 8. Demo Flow

1. Запустить GUI: `scripts/run_demo_app.py --background --address 127.0.0.1`.
2. Выполнить preflight: `scripts/demo_preflight.py`.
3. Открыть `http://127.0.0.1:8501/`.
4. Выбрать `Поиск методик`.
5. Запрос: `Какие никелевые сплавы применяются в судостроении и какие режимы термообработки влияют на твердость?`
6. Показать `Ответ`, `Источники`, `Сравнение`, `Графы`, `Отчеты`.
7. Нажать `Запустить Deep Search по текущей выдаче`.
8. Скачать PDF/DOCX/ZIP.

## Slide 9. Why It Stands Out

- Единый evidence cockpit вместо чат-ответа без источников.
- Local vs world comparison для методик и свойств.
- Визуальные графы для быстрого объяснения результата.
- Deep Search summary по выбранным статьям.
- RouterAI-first inference и бюджетный usage summary.
- Проверяемый handoff: preflight JSON, manifests, reports, ZIP artifacts.

## Slide 10. Business Value

Для R&D и технологов:

- быстрее собрать первичный literature review;
- меньше риск пропустить внешний источник;
- легче сравнить локальные эксперименты с мировой литературой;
- видны gaps и следующие эксперименты;
- результат можно передать как отчет, а не как скриншот чата.

Закрывающая фраза: Oreacle делает инженерный ответ проверяемым, воспроизводимым и удобным для защиты перед экспертами.

