# 04. Query + GUI + Evaluation

Дата обновления: 2026-07-04.

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
- Для пользователя raw score преобразуется в `relevance confidence`: `Высокая` /
  `Средняя` / `Низкая`, процент и короткие причины релевантности. Этот блок выводится
  в GUI, Markdown reports, `links.csv`, `web_links_manifest.json` и RouterAI answer report.
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

Поверх literature-search и local RAG слоев добавлен упрощенный demo cockpit, рассчитанный на проверку решения через GUI:

- первый экран - это чат с единым пользовательским запросом; введенный запрос остается в истории сообщений;
- sidebar оставляет только рабочие настройки: тип запроса, RAG profile, local/web search, LLM rewrite, Deep Search,
  top-k, источники поиска, RouterAI answer и выгрузки;
- есть три пользовательских режима: `Литературный поиск`, `Поиск методик`, `Поиск свойств`;
- `LLM rewrite запроса` теперь общий первый шаг для web-search и local RAG: для режимов методик/свойств
  `app/query/orchestrator.py` принимает `rewrite_client`, сохраняет `query_rewrite` и подставляет corrected/search
  variants в `raw_rag`, `summary_rag`, `graph`, `tables` и `web`;
- вкладка `Ответ` показывает итоговый ответ, confidence score, ключевые слова и переформулировки запроса;
- вкладка `Сравнение` показывает confirmed/local-only/web-only методики и property/numeric rows;
- вкладка `Evidence` разделяет Raw RAG, Summary RAG, Tables и fallbacks;
- вкладка `Графы` показывает local knowledge graph и local-vs-web method graph;
- вкладка `Графики` показывает распределение публикаций по годам и базам данных;
- вкладка `Отчеты` дает PDF/DOCX/JSON/ZIP выгрузки для web/literature run и отдельно для local RAG orchestration;
- отдельные вкладки могут выгружаться как секционные PDF/DOCX: web/literature report и local RAG report идут отдельными
  кнопками, чтобы не смешивать metadata search и внутренний RAG evidence.

## Technical Implementation Notes

Этот блок фиксирует, что уже реализовано и как слой примерно устроен, чтобы следующая разработка могла
быстро продолжить работу без обратного разбора кода.

### Основной сценарий выполнения

1. Пользователь вводит R&D-вопрос в Streamlit GUI или CLI.
2. Запрос проходит через query rewrite:
   - `app/query/rewrite.py` делает детерминированную нормализацию, извлекает materials/processes/properties
     и генерирует RU/EN search queries;
   - если включен LLM rewrite, GUI передает RouterAI-backed completion client в literature layer или local
     `run_query_orchestration`; при недоступности LLM система продолжает работать детерминированно.
3. Для `Литературный поиск` `app/query/literature.py::run_literature_search` собирает единый run:
   - читает локальные publication artifacts, если они уже существуют;
   - выполняет web metadata search по выбранным API-источникам;
   - дедуплицирует и ранжирует результаты;
   - опционально запускает Deep Search по top-N найденным публикациям;
   - строит comparison local vs web;
   - сохраняет JSONL/JSON/Markdown/PDF/DOCX артефакты в `data/processed/web_search/<run_id>/`.
4. Для `Поиск методик` и `Поиск свойств` `app/query/orchestrator.py::run_query_orchestration` строит local
   RAG план, применяет rewrite variants к retrieval routes, подключает optional web-search/deep-search и передает
   retrieved context в RouterAI final answer.
5. `app/ui/demo_app.py` отображает результат как cockpit: ответ, источники, сравнение, evidence, графы,
   графики и отчеты.

LLM path for the demo is RouterAI-first: query rewrite / Deep Search extraction / final answer helpers call
`ProviderRouter.from_env(..., primary_provider="routerai")`. If RouterAI is unavailable, the existing provider
router fallback behavior is preserved so the GUI degrades to Yandex/local deterministic responses instead of
failing the run.

### Ключевые файлы

- `app/web_search/schemas.py` - Pydantic-контракты для web literature layer:
  `LiteratureSearchRequest`, `LiteratureSearchResult`, `DeepSearchResult`, `MethodComparison`,
  `LiteratureSearchRun`.
- `app/web_search/keywords.py` - deterministic keyword extraction для RU/EN запросов, domain hints
  материаловедения, quoted phrases и material/process/property tokens.
- `app/web_search/clients.py` - API-клиенты Crossref, Semantic Scholar, OpenAlex, Europe PMC, DataCite
  и optional arXiv. Semantic Scholar использует `SEMANTIC_SCHOLAR_API_KEY`, если ключ есть в `.env`.
- `app/web_search/ranking.py` - score, dedupe и domain filtering. Ранжирование учитывает совпадения
  keywords в title/abstract/venue, наличие DOI/abstract, citation/year signals, materials-science domain
  signals и journal quartile boost.
- `config/web_search/journal_quartiles.json` - seed mapping журналов в Q1/Q2/Q3/Q4. Сейчас это
  небольшой локальный справочник; его можно заменить выгрузкой Scimago/Scopus/WoS.
- `app/web_search/deep_search.py` - безопасная загрузка коротких excerpts, extraction summaries и
  fallback summaries без LLM.
- `app/web_search/comparison.py` - сравнение local procedure summaries с web procedure summaries.
- `app/query/literature.py` - orchestration layer для local evidence + web search + deep search +
  comparison + report payload.
- `app/query/cockpit.py` - deterministic UI/analytics helpers: query decomposition, Local vs World
  Dashboard, Knowledge Gap Radar, method matrix, heatmap, evidence cards, numeric intervals, mini graph,
  executive brief.
- `app/query/reports.py` - генерация Markdown/PDF/DOCX отчетов, links-only report, Deep Search report,
  executive brief и `full_run.json`.
- `app/ui/demo_app.py` - основной Streamlit cockpit.
- `scripts/search_web_literature.py` - CLI smoke/automation entrypoint.
- `scripts/run_demo_app.py` - локальный запуск Streamlit на `0.0.0.0` с выводом local/LAN URL.
  Для защиты удобен режим `--background`: launcher проверяет импорт текущего `app.ui.demo_app`, останавливает
  stale demo-процессы на выбранном порту, стартует clean Streamlit server session и пишет логи в `logs/streamlit_demo/`.
  Streamlit на Windows может держать parent/child Python-пару; актуальный listener проверяется healthcheck по URL.
- `scripts/demo_preflight.py` - быстрый readiness check перед защитой: RouterAI key configured flag,
  `demo_app_import`, `routerai_bge_m3` manifests, Streamlit import/URL и offline search smoke по raw + summary streams.
- `scripts/smoke_demo_scenarios.py` - product smoke для трех текущих режимов GUI: `Литературный поиск`,
  `Поиск методик`, `Поиск свойств`; использует fake web metadata client, не делает платных LLM/web вызовов
  и сохраняет `data/processed/demo_smoke/smoke_report.json`.
- `scripts/build_defense_bundle.py` - сборка lightweight ZIP для организаторов: pitch/runbook/storyboard docs, preflight JSON,
  demo smoke JSON, RouterAI BGE-M3 manifests и README с командами запуска без `.env`, raw corpus и full web text.

### Поиск, источники и ранжирование

Автоматический поиск сейчас реально выполняется только по API-источникам, которые есть в `Search resources`
GUI/CLI: Crossref, Semantic Scholar, OpenAlex, Europe PMC, DataCite и optional arXiv. Ранее обсуждавшиеся
ResearchGate, eLIBRARY, Springer, MDPI, Wiley, ScienceDirect, Sci-Hub и похожие сайты не скрейпятся generic
crawler'ом: это сделано намеренно из-за ограничений доступа, ToS, капч, paywall и безопасности. Для расширения
охвата выбран более устойчивый MVP-формат: scholarly metadata APIs + DOI/URL ссылки на оригинальные страницы.

Deduplication:

- сначала склеивание по нормализованному DOI;
- затем fallback по URL;
- затем title similarity/normalization, чтобы убрать одинаковые записи из разных API.

Ranking:

- базовый score растет за совпадение query keywords в title, abstract и venue;
- есть бонусы за наличие abstract, DOI, source URL, citation count и свежий год;
- materials-only режим добавляет фильтр/буст по терминам материаловедения, металлургии, сплавов,
  термообработки, покрытий, коррозии, прочности, hardness и т.д.;
- journal quartile boost добавляет приоритет Q1/Q2 журналам, но не выбрасывает Q3/Q4, чтобы не терять
  отраслевые источники;
- результат score нужно считать эвристикой для demo/ranking, а не библиометрической метрикой.

### Deep Search

Deep Search является opt-in режимом, потому что он медленнее и может тратить LLM-квоту.

Что происходит технически:

- берется top-N уже deduped/ranked публикаций, лимит в GUI сейчас до 20;
- для каждой публикации используется metadata: title, abstract, DOI, venue, year, authors, URL;
- если есть безопасный HTTPS URL, система пробует скачать только ограниченный excerpt с timeout и size cap;
- `http`, `file`, localhost/private IP и redirect в private network блокируются;
- полный copyrighted full text не сохраняется;
- при наличии YandexGPT выполняется extraction prompt, совместимый по смыслу с текущими
  `document_summaries.jsonl` и `procedure_summaries.jsonl`;
- без ключей создается fallback summary из metadata/abstract, чтобы demo не падало;
- после extraction строятся `web_document_summaries.jsonl`, `web_procedure_summaries.jsonl`,
  `comparison_report.json`, `deep_search_report.*` и общий Russian overall summary по найденным статьям.

### Локальная база и сравнение local vs web

Локальный слой сейчас read-only и терпимо относится к частично готовым extraction artifacts. Если файлов нет,
GUI и CLI не падают, а показывают, что локальное покрытие пока пустое.

Читаемые файлы:

- `data/processed/publications/publications.jsonl`;
- `data/processed/publications/document_summaries.jsonl`;
- `data/processed/publications/procedure_summaries.jsonl`.

Сравнение строится по extracted procedure summaries:

- method/procedure;
- material;
- conditions;
- equipment;
- outputs/properties;
- observed effects;
- numeric results;
- evidence/source ссылкам.

Основные секции comparison:

- что подтверждается и локально, и внешней литературой;
- что найдено только в локальной базе;
- что найдено только во внешней литературе;
- где условия/диапазоны отличаются;
- gaps, где данных мало или нужна ручная проверка.

### GUI: что показывается пользователю

GUI разгружен до одного chat input и трех режимов задачи: `Литературный поиск`, `Поиск методик`,
`Поиск свойств`. Отдельные старые Demo scenario / Query Decomposer элементы не используются в основном
Streamlit-приложении.

Основные зоны:

- Sidebar: на первом уровне оставлены только тип запроса, Local search, Web literature search, Deep Search,
  Deep Search limit и top-k. Технические параметры `RAG profile`, LLM rewrite, source selection,
  RouterAI answer, PDF/DOCX/report options и safe excerpt fetching перенесены в `Advanced`.
- Верхний блок: единый chat input. Query rewrite показывается после запуска во вкладке `Ответ` как corrected
  query и route-specific variants. Это общий первый шаг для web-search и local RAG search.
- `Ответ`: финальный RouterAI answer, прямые PDF/DOCX/JSON выгрузки ответа, provider metadata,
  RouterAI budget/usage summary для демо-лимита 1500 RUB,
  keywords и query rewrites.
- `Источники`: ranked web metadata с relevance confidence/reasons, links и локальные совпадения.
- `Сравнение`: confirmed/local-only/web-only методики, различающиеся условия и property/numeric rows.
  Для property/numeric rows есть отдельная секционная выгрузка `properties_report.md/.pdf/.docx`.
- `Evidence`: Raw RAG, Summary RAG, Tables и fallbacks.
- `Графы`: local knowledge graph и mode-aware comparison graph. Для `Поиск методик` показывается
  local-vs-web graph методик/режимов обработки, для `Поиск свойств` - graph свойств и численных диапазонов.
  Если local graph route не вернул rows или открыт чистый literature run, GUI использует fallback mini graph
  из web/local/deep/comparison evidence, чтобы вкладка не была пустой.
- `Графики`: распределение публикаций по годам и базам данных.
- `Отчеты`: выгрузка RouterAI answer report, full report, links-only report, Deep Search report,
  executive brief, DOCX/PDF/JSON и ZIP artifacts.

Актуальный pitch/demo материал лежит в `reports/oreacle_defense_pack.md`,
`reports/oreacle_pitch_deck.md`, `reports/oreacle_routerai_demo_script.md`
и `reports/oreacle_demo_video_storyboard.md`.

### Артефакты одного run

Все generated outputs пишутся в ignored директорию:

`data/processed/web_search/<run_id>/`

Типовые файлы:

- `request.json` - параметры запуска;
- `query_plan.json` - rewrite/decomposition/search queries;
- `keywords.json` - extracted keywords/domain hints;
- `metadata_results.jsonl` - ranked web metadata;
- `local_matches.jsonl` - найденные локальные публикации/summaries;
- `resource_links.jsonl` - ссылки на внешние страницы;
- `web_document_summaries.jsonl` - Deep Search document summaries;
- `web_procedure_summaries.jsonl` - Deep Search procedure summaries;
- `comparison_report.json` - structured comparison;
- `literature_report.md/.pdf/.docx` - полный отчет;
- `literature_links_report.md/.pdf/.docx` - обычный отчет только со ссылками;
- `deep_search_report.md/.pdf/.docx` - отчет со ссылками и summaries;
- `executive_brief.md/.pdf/.docx` - короткий управленческий отчет;
- `full_run.json` - полный payload для GUI/отладки, включая charts/cockpit payload;
- `answer_report/routerai_answer.md/.pdf/.docx/.json` - финальный RouterAI ответ, metadata провайдера,
  RouterAI token usage/budget summary,
  релевантные web-ссылки и, если есть, Deep Search summaries / local RAG evidence;
- `web_links_manifest.json` - нормализованный manifest web-ссылок без сохранения full text,
  включая `relevance_confidence`;
- `local_publication_files_manifest.json` - manifest локальных файлов, которые удалось найти и включить в архив;
- `section_reports/<section>_report.md/.pdf/.docx` - выгрузки отдельных GUI-вкладок `sources`, `comparison`, `evidence`,
  `properties`, `graphs`, `charts`, `deep`;
- `run_artifacts.zip` - единый архив run-а: JSON/JSONL/Markdown/PDF/DOCX, manifests, секционные отчеты и до 20 найденных
  локальных публикационных файлов из проекта.

ZIP intentionally не архивирует полный web full text: для внешней литературы сохраняются только metadata, ссылки,
короткие excerpts/summaries и derived reports. Локальные файлы добавляются только если путь найден внутри project root;
лимиты архива: 20 файлов и 250 MB.

Для режимов `Поиск методик` и `Поиск свойств` дополнительно создаются local RAG artifacts в:

`data/processed/rag_runs/<run_id>/`

Типовые файлы:

- `orchestration_payload.json` - полный `QueryOrchestrationResult` + metadata финального RouterAI answer;
- `orchestration_web_links_manifest.json` - web links из orchestration context, если web-search был включен;
- `orchestration_local_files_manifest.json` - найденные локальные файлы из raw/summary/table/graph evidence;
- `section_reports/full_report.md/.pdf/.docx` - полный local RAG отчет;
- `section_reports/answer_report.md/.pdf/.docx`, `sources_report`, `comparison_report`, `evidence_report`,
  `properties_report`, `graphs_report`, `charts_report` - секционные выгрузки для GUI tabs;
- `orchestration_artifacts.zip` - единый архив local RAG run-а с JSON/Markdown/PDF/DOCX/manifests и найденными
  локальными файлами.

### Точки расширения

- Новый metadata source: добавить enum/label источника, client/parser в `app/web_search/clients.py`,
  нормализацию в `LiteratureSearchResult`, подключение в orchestrator и unit tests на mocked JSON.
- Новый сайт без API: сначала проверить наличие официального API/RSS/OAI-PMH/export endpoint. Generic crawler
  не добавлять без отдельного security review.
- Улучшение RAG: будущий локальный RAG лучше подключить в `app/query/literature.py` вместо текущего
  lightweight local search, сохранив выходной формат `local_matches` для GUI/report compatibility.
- Настоящий graph backend: заменить/дополнить `mini_graph_edges` данными из `data/processed/graph/*`,
  оставив текущий DOT/табличный fallback.
- Более сильные отчеты: расширять `app/query/reports.py`, но держать PDF-таблицы узкими. Для PDF уже
  специально оставлены только `#`, `Title`, `Link`, чтобы не ломать верстку длинными DOI/source полями.
- Более точные квартильные бусты: обновить `config/web_search/journal_quartiles.json` внешней выгрузкой и
  добавить тесты на нормализацию названий журналов.

### Ограничения и риски

- Geography/year filters в MVP в основном усиливают query и отображаются в query plan; это еще не строгие
  API-фильтры для всех источников.
- Semantic Scholar без API key может быстро rate-limit'ить запросы.
- Deep Search quality зависит от наличия abstract/excerpt и LLM keys.
- Heatmap/method comparison содержательны только после Deep Search или при наличии локальных
  `procedure_summaries.jsonl`.
- Expert nodes в mini knowledge map сейчас приближены через authors; после готовности graph layer нужно
  заменить на реальные expert/person/entity связи.

### Проверки

Текущая рекомендуемая проверка после изменений в этом слое:

```powershell
.\.venv\Scripts\python.exe -m compileall app scripts
.\.venv\Scripts\python.exe -m pytest tests\test_web_search.py -q
.\.venv\Scripts\python.exe scripts\search_web_literature.py "никелевые сплавы термообработка твердость" --top-k 5 --deep-search none
.\.venv\Scripts\python.exe scripts\run_demo_app.py
```

Ожидаемый GUI URL для локальной demo-сессии: `http://127.0.0.1:8501/`.

Для устойчивого запуска перед показом:

```powershell
.\.venv\Scripts\python.exe scripts\run_demo_app.py --background --address 127.0.0.1
```

Для сборки handoff-архива:

```powershell
.\.venv\Scripts\python.exe scripts\build_defense_bundle.py --run-preflight --run-smoke
```

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
