# 04. Query + GUI + Evaluation

Дата обновления: 2026-07-03.

Статус: будущая интеграционная зона. Сейчас не активна: сначала должны появиться
минимальные outputs из `02_summary_graph` и `03_rag`.

## Цель

Собрать пользовательский слой поверх RAG и graph:

- уточнение пользовательского вопроса;
- typed filters по материалам, процессам, свойствам, регионам, датам;
- evidence pack из документов, summaries и graph;
- GUI для поиска, просмотра источников, мини-графа и экспорта;
- evaluation loop для проверки качества ответов.

## Dependencies

От `02_summary_graph`:

- `data/processed/extraction/numeric_conditions.jsonl`
- `data/processed/graph/nodes.jsonl`
- `data/processed/graph/edges.jsonl`
- `data/processed/graph/graph_stats.json`

От `02_publication_metadata`:

- `data/processed/publications/publications.jsonl`
- `data/processed/publications/publication_authors.jsonl`
- `data/processed/publications/document_summaries.jsonl`
- `data/processed/publications/procedure_summaries.jsonl`
- `data/processed/publications/publication_metadata_report.json`

От `03_rag`:

- `data/indexes/chunks/*`
- retrieval CLI/API
- top-k hits с `doc_id`, `chunk_id`, `score`, `source_path`, text preview

От parsing:

- `data/parsed/documents.jsonl`
- `data/parsed/chunks.jsonl`
- `data/parsed/full_texts/*`
- `data/parsed/spreadsheets_csv/*`

## Future Files

Можно менять в этой зоне после старта интеграции:

- `app/query/*`
- `app/ui/*`
- `app/eval/*`
- `config/eval/*`
- `scripts/run_demo_app.py`
- `scripts/evaluate_retrieval.py`
- `tasks/04_query_gui_eval/*`

Нельзя менять без согласования:

- `app/index/*`, `app/rag/*` - зона RAG.
- `app/extract/*`, `app/graph/*` - зона summary/graph.
- `data/processed/*` и `data/indexes/*` вручную.

## GUI Requirements Draft

Минимальный demo-screen:

- строка запроса;
- панель уточненных slots: material, process, property, geography, time,
  conditions;
- список evidence documents/chunks;
- вкладка graph с найденными сущностями и 1-2 hop neighbors;
- вкладка tables/source viewer;
- экспорт evidence в JSON/CSV.

GUI не должен модифицировать offline artifacts. Он только читает indexes,
graph outputs и parsed sources.

## Web Literature Search MVP

Добавлен независимый внешний literature layer, который можно использовать до
полной готовности graph/RAG:

- CLI: `scripts/search_web_literature.py "query" --top-k 20 --deep-search none|top5`.
- GUI: `scripts/run_demo_app.py` запускает Streamlit chatbot/cockpit. По
  умолчанию сервер слушает `0.0.0.0` и печатает local/LAN URLs для demo.
- Автоматические источники metadata/ranking: Crossref, Semantic Scholar, OpenAlex,
  Europe PMC, DataCite и опционально arXiv. По умолчанию включены 5 более
  стабильных источников; arXiv доступен в advanced/CLI, но может отвечать медленно.
  Semantic Scholar key опционален через `.env` как `SEMANTIC_SCHOLAR_API_KEY`;
  остальные источники в MVP работают без ключей.
- Первый шаг сценария - universal query rewrite:
  `app/query/rewrite.py` исправляет запрос, выделяет materials/processes/
  properties и генерирует несколько RU/EN search queries. Этот слой должен
  использоваться и web search, и будущим RAG search.
- Поиск внешних публикаций по умолчанию ограничен materials science /
  metallurgy / mineral processing domain signals.
- Default mode: metadata-only search с dedupe/ranking.
- Ranking учитывает keyword match в title/abstract/venue, abstract/DOI/citation/year
  сигналы, domain-сигналы материаловедения и квартиль журнала, если он известен.
  Seed mapping квартилей лежит в `config/web_search/journal_quartiles.json` и может
  быть заменен на выгрузку Scimago/Scopus/WoS.
- Opt-in mode: `deep_search=top5`, где top-5 внешних источников приводятся к
  формату document/procedure summaries и сравниваются с локальными
  `data/processed/publications/*`.
- Каждый run сохраняет `literature_report.md` и `literature_report.pdf` с
  релевантными ссылками; после deep search туда добавляются краткие summary по
  статьям и общий summary по запросу.
- В GUI основной выбор ресурсов называется `Search resources`: там оставлены только
  реальные автоматические API-базы поиска и ранжирования. Кликабельные ссылки на
  ResearchGate/eLIBRARY/Springer/MDPI/etc. убраны из demo UI, чтобы не создавать
  впечатление, что они автоматически скрейпятся.
- Deep Search имеет настраиваемый лимит статей; общий summary по всем найденным
  summary показывается во вкладке `Deep Search` и попадает в markdown/PDF отчет.
- Лимит Deep Search в GUI увеличен до 20 статей. Deep Search можно запускать сразу
  вместе с основным запросом или отдельной кнопкой после metadata-only web-search
  по уже найденному ranked list.
- Отчеты разделены на full report, links-only report и Deep Search report.
  Каждый run сохраняет markdown, PDF и DOCX варианты, а также `full_run.json`
  с web/local/deep/comparison данными и chart data по годам и источникам.
- PDF-таблица релевантных источников намеренно оставляет только `#`, `Title`,
  `Link`, чтобы длинные DOI/source/year поля не ломали верстку.
- В GUI есть опция генерации детерминированных выводов по сравнению локального
  поиска и web-search: тренды по годам/источникам, пересечения методик,
  local-only/web-only методики и отличающиеся условия.
- Generated artifacts пишутся в `data/processed/web_search/<run_id>/`.

## Demo Cockpit Additions

Поверх literature-search слоя добавлен демонстрационный cockpit, рассчитанный на проверку решения через GUI:

- первый экран показывает пользовательский запрос, переформулированный поисковый запрос, ключевые слова и editable slots:
  материал, процесс, условия, числовые ограничения, география, период, свойства, оборудование и варианты
  поисковых запросов;
- sidebar содержит готовые demo scenarios, session presets и structured filters по географии/периоду;
- вкладка `Cockpit` показывает Local vs World Dashboard, coverage signals, Knowledge Gap Radar, evidence cards
  и краткий управленческий вывод;
- вкладка `Сравнение` показывает Contradiction & Consensus Panel, method comparison matrix и heatmap
  `материал x методика` после Deep Search;
- вкладка `Evidence` показывает evidence cards и кандидаты числовых диапазонов; вкладка `Графики` строит mini graph
  `Material -> Process -> Equipment -> Output`;
- `full_run.json` теперь включает cockpit payload: query decomposition, dashboard metrics, method matrix, heatmap,
  consensus panel, evidence cards, numeric intervals, mini graph edges, gap radar и executive brief markdown;
- executive brief структурирован как `5 ключевых выводов`, `3 риска`, `3 пробела`, `top-5 источников`
  и рекомендуемые следующие эксперименты/литературные направления;
- каждый run сохраняет отдельный `executive_brief.md`, `executive_brief.docx` и, если включена PDF-генерация,
  `executive_brief.pdf`.

Security constraints:

- нет generic crawler;
- excerpt fetching разрешен только для HTTPS URL с блокировкой private/localhost
  адресов и size cap;
- API keys не логируются;
- полный copyrighted текст не сохраняется, только metadata, short excerpts,
  summaries и ссылки.

## Evaluation Draft

Минимальные проверки:

- 5-10 demo queries от команды;
- наличие цитат и `doc_id`/`chunk_id` в ответе;
- retrieval recall вручную по известным документам;
- graph query success для материалов/процессов/свойств;
- latency на warm local artifacts;
- feedback log: полезно/неверно/не хватает источников.
