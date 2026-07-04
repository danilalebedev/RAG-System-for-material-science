# Oreacle Demo Video Storyboard

Цель: короткий монтажный лист для 90-секундного видео и live-demo. Он дополняет pitch deck: здесь не тезисы для слайдов, а что именно показывать на экране, что говорить и какой fallback использовать, если внешний API или Deep Search тормозит.

## Перед записью

Команды готовности:

```powershell
.\.venv\Scripts\python.exe scripts\run_demo_app.py --background --address 127.0.0.1
.\.venv\Scripts\python.exe scripts\demo_preflight.py --timeout-seconds 10
.\.venv\Scripts\python.exe scripts\smoke_demo_scenarios.py
```

Открыть:

```text
http://127.0.0.1:8501/
```

Рекомендуемые настройки:

- тип запроса: `Поиск методик`;
- `Local search`: on;
- `Web literature search`: on;
- `Deep Search`: off на первом проходе, затем запуск отдельной кнопкой;
- `RAG profile`: `routerai_bge_m3`;
- `Ответ через RouterAI`: on;
- `Генерировать PDF`: on.

Основной запрос:

```text
Какие никелевые сплавы применяются в судостроении и какие режимы термообработки влияют на твердость?
```

## 90 секунд

| Тайминг | Экран | Что сказать | Что должно быть видно |
| --- | --- | --- | --- |
| 0-8 | Открытый Oreacle cockpit | "Инженерный вопрос редко закрывается одним PDF: нужны локальные отчеты, статьи, методики, свойства и ссылки." | Один chat input, три режима, без технических demo/decomposer панелей. |
| 8-18 | Sidebar + ввод запроса | "Выбираем сценарий: методики, свойства или литература. Запрос остается обычным инженерным текстом." | Тип `Поиск методик`, включены local/web, запрос вставлен в чат. |
| 18-32 | Вкладка `Ответ` | "RouterAI уточняет формулировку, обращается к RAG и формулирует ответ только по retrieved evidence." | Итоговый ответ, confidence, блок `Как система искала`. |
| 32-45 | Вкладка `Источники` | "Публикации ранжируются с объяснением уверенности: keyword/title/abstract hits, DOI, год, квартиль, источник." | Таблица web-источников с `confidence`, `score`, `quartile`, `why`, `link`. |
| 45-58 | Вкладка `Evidence` | "Локальный слой не прячется: видны raw chunks, summaries, tables и fallback rows." | Raw RAG, Summary RAG, Tables. |
| 58-70 | Вкладка `Сравнение` | "Система разделяет подтвержденные методики, локальные уникальные данные, внешние находки и численные свойства." | Confirmed / local-only / web-only / свойства. |
| 70-80 | Вкладка `Графы` | "Граф показывает, как материал связан с методикой, источником и найденными свойствами." | Knowledge graph и mode-aware comparison graph. |
| 80-90 | Вкладка `Отчеты` | "Результат можно отдать организатору как PDF, DOCX или ZIP с manifests, ссылками и локальными файлами." | Кнопки PDF/DOCX/ZIP, затем скачанный artifact. |

## Deep Search вставка

Если остается еще 20-30 секунд, после первого быстрого ответа нажать:

```text
Запустить Deep Search по текущей выдаче
```

Показать:

- `Deep Search summaries` в метриках;
- общий summary на русском;
- отдельный Deep Search PDF/DOCX;
- обновленный ZIP, где есть `web_document_summaries.jsonl`, `web_procedure_summaries.jsonl`, `comparison_report.json`.

Фраза:

```text
Deep Search не заменяет легальный доступ к full text: мы сохраняем metadata, ссылки, короткие excerpts и LLM-summary, чтобы не тащить copyrighted full text в продукт.
```

## Backup, если сеть тормозит

Если web API или Deep Search медленные:

1. Оставить `Web literature search` включенным, но не включать Deep Search на первом проходе.
2. Показать уже сохраненный `data/processed/demo_smoke/smoke_report.json`.
3. Перейти к вкладкам `Evidence`, `Графы`, `Отчеты`: они демонстрируют локальный RAG и упаковку артефактов без внешних вызовов.
4. В конце сказать: "Внешний слой асинхронный: metadata-only быстро дает список источников, Deep Search запускается по top-N и может занимать минуты."

## Кадры для слайдов или постера

1. `Ответ`: RouterAI answer + `Как система искала`.
2. `Источники`: таблица релевантных публикаций с confidence.
3. `Сравнение`: confirmed/local-only/web-only.
4. `Графы`: knowledge graph + method/property graph.
5. `Отчеты`: PDF/DOCX/ZIP export buttons.

## Что не говорить

- Не обещать массовый scraping ResearchGate/Sci-Hub/paywalled full text.
- Не утверждать, что quartile score является production-grade библиометрией: это ranking signal.
- Не говорить, что graph уже является финальной промышленной онтологией.
- Не говорить, что LLM знает ответ сама: ответ строится по retrieved evidence.
