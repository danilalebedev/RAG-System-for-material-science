# 02. Publication Metadata + RECIPER-Style Summaries

Дата обновления: 2026-07-03.

Статус: активная upstream-задача для графа. Цель - одним воспроизводимым
пайплайном собрать нормализованную библиографическую metadata, краткое summary
каждого источника и RECIPER-style procedure summaries. Graph builder потом
читает эти outputs и строит `Publication` nodes, `described_in` edges и первые
кандидаты `Material`/`Process`/`Experiment`/`Property` без повторного чтения
всего full text.

## Why This Step Exists

Текущий `data/parsed/documents.jsonl` хранит техническую metadata парсинга и
встроенную metadata файлов. Это полезно как baseline, но не равно
библиографии:

- top-level `author/authors/journal/year/doi/abstract` сейчас не заполнены;
- `metadata_json.author` часто означает автора файла или презентации, а не
  автора научной работы;
- `metadata_json.title` часто технический, например `Презентация PowerPoint`;
- год создания файла не всегда равен году публикации.

По фактическому корпусу:

| Категория `source_type` | Кол-во |
|---|---:|
| Материалы конференций | 1327 |
| Журналы | 349 |
| Обзоры | 110 |
| Статьи | 60 |
| Доклады | 16 |

Форматы:

| Extension | Кол-во |
|---|---:|
| `.pdf` | 1308 |
| `.xls` | 405 |
| `.docx` | 117 |
| `.doc` | 18 |
| `.pptx` | 5 |
| `.xlsx` | 5 |
| `.docm` | 3 |
| `.gif` | 1 |

Вывод: типизация должна покрывать не только journal articles, но и conference
materials, обзоры, доклады, технические документы и табличные датасеты.

## RECIPER Format

RECIPER: A Dual-View Retrieval Pipeline for Procedure-Oriented Materials
Question Answering.

- Paper: https://arxiv.org/abs/2604.11229v1
- Code/data: https://github.com/ReaganWu/RECIPER
- Локальный PDF: `Литература/Material Science/2604.11229v1.pdf`

RECIPER строит две проекции документа:

- paragraph-view: обычные paragraph chunks;
- recipe/procedure-view: компактные LLM-extracted procedural summaries.

В их `rag_database.json` paper record содержит:

- `paper_id`
- `title`
- `abstract`
- `metadata`
- `sections[].paragraphs_with_entities[]`
- `recipes[]`

Типовой `recipes[]` record содержит:

- `material_name`
- `synthesis_method`
- `steps[]`
- `steps[].step_number`
- `steps[].description`
- `steps[].parameters`
- `key_points`
- `entities`

В retrieval code recipe превращается в текст вида:

```text
Material: <material_name>
Method: <synthesis_method>
<step descriptions>
Key points: <key_points>
```

Для нашего графа этого мало, поэтому мы сохраняем тот же смысловой формат, но
добавляем provenance и typed hints: `doc_id`, `publication_id`,
`source_span_ids`, `confidence`, `materials`, `processes`, `equipment`,
`properties`, `outputs`, `conditions`, `observed_effects`.

## Inputs

Read-only входы:

- `data/parsed/documents.jsonl`
- `data/parsed/full_texts/*.txt`
- `data/parsed/chunks.jsonl`
- `data/parsed/tables.jsonl`
- `data/parsed/spreadsheets_csv/**/*.csv`

Основной source package для LLM на один документ:

- parser/source metadata из `documents.jsonl`;
- первые 8-12 KB full text для title/authors/header;
- candidate method/experiment snippets из chunks;
- compact table previews из `tables.jsonl`;
- CSV rows только точечно, если table preview указывает на важный workbook.

Нельзя слать весь документ целиком без отбора. Для 1862 документов нужен
cache/resume и лимиты нагрузки.

## Outputs

Пишем в отдельную папку, не смешивая с graph/RAG:

- `data/processed/publications/publications.jsonl`
- `data/processed/publications/publication_authors.jsonl`
- `data/processed/publications/publication_venues.jsonl`
- `data/processed/publications/publication_evidence_spans.jsonl`
- `data/processed/publications/document_summaries.jsonl`
- `data/processed/publications/procedure_summaries.jsonl`
- `data/processed/publications/publication_metadata_report.json`
- `data/processed/publications/publication_metadata_manifest.json`
- `data/processed/publications/publication_quality_report.json` при запуске
  CLI с `--quality-report`

Все `data/processed/*` ignored и не коммитятся.

## Domain Coverage

Текущий extraction layer покрывает требуемые классы данных так:

- научные публикации и отчеты -> `PublicationRecord`;
- экспериментальные данные и протоколы опытов -> `ProcedureSummaryRecord`
  плюс `experimental_protocols`, `process_parameters`, `analysis_results`,
  `numeric_ranges`;
- технологические решения -> `technology_solutions`, `design_features`,
  `equipment_details`, `conditions`, `outputs`;
- материалы и вещества -> `materials`, `material_name`, `input_materials`,
  `reagents`, `outputs`;
- оборудование и установки -> `equipment`, `equipment_details`, затем
  отдельные `Equipment` nodes на graph stage;
- исследовательские команды и эксперты -> `authors`, `organizations`,
  `experts`, `facilities`;
- выводы и рекомендации -> `key_findings`, `observed_effects`,
  `recommendations`, `limitations_or_gaps`, `validation_methods`.

Оборудование не пишется в отдельный JSONL на этом этапе: оно остается в
document/procedure records с evidence. Graph builder должен поднять эти поля в
отдельные `Equipment` nodes и связать их с `Experiment`/`Process` через
официальные отношения и provenance.

## Multilingual Policy

Корпус может быть русским, английским или смешанным. Для этого этапа не нужно
переводить все документы на один язык:

- исходные `title`, `abstract`, `summary`, `evidence_quotes`, названия
  материалов, процессов, оборудования, организаций и географии сохраняем на
  языке источника;
- поле `language` фиксирует `ru`, `en`, `mixed` или `unknown`;
- для будущего RAG достаточно использовать multilingual embedding model, чтобы
  русские и английские chunks попадали в общее семантическое пространство;
- normalization/graph layer должен хранить aliases, например `nickel matte` и
  `никелевый штейн`, а не заменять оригинальный evidence;
- перевод допустим только как вспомогательный слой для query expansion,
  bilingual aliases и финального ответа пользователю;
- финальный GUI/RAG ответ формируется на языке вопроса, но provenance показывает
  оригинальные цитаты.

Это сохраняет проверяемость: любой извлеченный факт можно сопоставить с
оригинальным `source_span_id`, не теряя терминологию из публикации.

## Core Types

### `PublicationRecord`

Одна запись на `doc_id`. Даже если источник не является классической статьей,
он все равно может стать `Publication` node в графе, потому что условие задания
использует `Publication` как тип источника.

Обязательные поля:

- `publication_id`: стабильный id, например `pub_<doc_id>`.
- `doc_id`
- `document_kind`
- `source_type`
- `title`
- `title_confidence`
- `source_path`
- `file_name`
- `extension`
- `extraction_status`: `ok`, `partial`, `no_bibliography`, `needs_review`,
  `failed`.
- `confidence`
- `evidence`

Рекомендуемые поля:

- `subtitle`
- `language`: `ru`, `en`, `mixed`, `unknown`.
- `year`
- `date_published`
- `authors`
- `organizations`
- `venue_name`
- `venue_type`: `journal`, `conference`, `review_series`, `internal_report`,
  `presentation`, `dataset`, `unknown`.
- `publisher`
- `volume`
- `issue`
- `pages`
- `doi`
- `isbn`
- `url`
- `keywords`
- `abstract`
- `topic_tags`
- `embedded_metadata`
- `parser_metadata`
- `missing_fields`
- `review_notes`

### `DocumentKind`

Enum:

- `journal_article`
- `journal_issue`
- `conference_paper`
- `conference_abstract`
- `review_article`
- `technical_report`
- `presentation_report`
- `spreadsheet_dataset`
- `book_or_chapter`
- `thesis`
- `internal_document`
- `unknown`

Mapping baseline:

- `source_type=Журналы` -> `journal_issue` для полных выпусков и
  `journal_article` для отдельных статей; проверять по header/page count.
- `source_type=Материалы конференций` -> `conference_paper` или
  `conference_abstract`; Excel в этой категории -> `spreadsheet_dataset`.
- `source_type=Обзоры` -> `review_article` или `technical_report`.
- `source_type=Статьи` -> `journal_article`/`technical_report`.
- `source_type=Доклады` -> `presentation_report`.

### `AuthorRecord`

Авторы не становятся отдельными graph nodes автоматически. В официальной схеме
есть `Expert`, но нет отношения `authored_by`, поэтому авторов храним как
атрибуты `Publication`. В `Expert` переводим только тех, кто явно нужен как
эксперт/валидатор/исследовательская команда.

Поля:

- `author_id`
- `publication_id`
- `doc_id`
- `raw_name`
- `normalized_name`
- `surname`
- `given_names`
- `initials`
- `affiliations`
- `email`
- `orcid`
- `role`: `author`, `editor`, `speaker`, `expert`, `organization`, `unknown`.
- `order`
- `confidence`
- `evidence`

### `DocumentSummaryRecord`

Одна короткая summary-запись на документ. Это обзор "о чем работа", а не
пошаговый recipe. Нужен для GUI, фильтров, triage и graph candidate selection.

Поля:

- `document_summary_id`
- `publication_id`
- `doc_id`
- `summary`: 3-7 предложений, без выдуманных деталей.
- `main_topic`
- `materials`
- `processes`
- `properties`
- `methods`
- `facilities_or_geography`
- `key_findings`
- `limitations_or_gaps`
- `document_kind`
- `confidence`
- `evidence`

### `ProcedureSummaryRecord`

Одна или несколько RECIPER-style записей на документ. Если в документе описано
несколько независимых процедур/экспериментов, создаем несколько records. Если
процедур нет, для документа может быть 0 procedure records.

Поля:

- `procedure_summary_id`
- `publication_id`
- `doc_id`
- `source_span_ids`
- `material_name`
- `synthesis_or_process_method`
- `procedure_type`: `synthesis`, `processing`, `experiment`,
  `characterization`, `calculation`, `industrial_process`, `unknown`.
- `steps[]`
- `steps[].step_number`
- `steps[].description`
- `steps[].parameters`
- `key_points`
- `materials`
- `processes`
- `equipment`
- `properties`
- `outputs`
- `conditions`
- `process_parameters`
- `observed_effects`
- `numerical_results`
- `analysis_results`
- `equipment_details`
- `technology_solutions`
- `design_features`
- `sample_ids`
- `scale`
- `temporal_scope`
- `graph_hints`
- `confidence`
- `extraction_status`
- `evidence`

`graph_hints` не является графом. Это подсказка для следующего этапа:
какие `Material`, `Process`, `Equipment`, `Property`, `Experiment`,
`Facility` вероятно нужно создать или связать.

### `EvidenceSpan`

Любое извлеченное поле должно иметь traceability:

- `source_span_id`
- `doc_id`
- `publication_id`
- `field_name`
- `source_kind`: `embedded_metadata`, `full_text_header`, `chunk`,
  `filename`, `source_path`, `table`, `csv`
- `start_char`
- `end_char`
- `text`
- `page`
- `confidence`

## JSONL Draft

`publications.jsonl`:

```json
{
  "publication_id": "pub_b94cdbb6a2e6b59b",
  "doc_id": "b94cdbb6a2e6b59b",
  "document_kind": "presentation_report",
  "source_type": "Доклады",
  "title": "Название источника",
  "language": "ru",
  "year": 2025,
  "venue_name": null,
  "venue_type": "presentation",
  "authors": [
    {
      "author_id": "author_...",
      "raw_name": "Иванов И. И.",
      "normalized_name": "Иванов Иван Иванович",
      "role": "speaker",
      "order": 1,
      "confidence": 0.74
    }
  ],
  "organizations": ["Институт Гипроникель"],
  "doi": null,
  "source_path": "/Источники информации/Доклады/...",
  "file_name": "Доклад_...",
  "extension": ".pdf",
  "embedded_metadata": {
    "title": "Презентация PowerPoint",
    "author": "file author",
    "creationDate": "D:20250529073531+03'00'"
  },
  "confidence": 0.68,
  "extraction_status": "partial",
  "missing_fields": ["doi", "venue_name"],
  "evidence": [{"source_span_id": "pubspan_...", "field_name": "title"}]
}
```

`document_summaries.jsonl`:

```json
{
  "document_summary_id": "docsum_b94cdbb6a2e6b59b",
  "publication_id": "pub_b94cdbb6a2e6b59b",
  "doc_id": "b94cdbb6a2e6b59b",
  "summary": "Кратко описывает цель, материал/процесс, метод и ключевой вывод документа.",
  "main_topic": "переработка концентратов",
  "materials": ["концентрат драгоценных металлов"],
  "processes": ["переработка", "оптимизация технологической схемы"],
  "properties": ["извлечение", "экономическая эффективность"],
  "methods": ["технико-экономический расчет"],
  "facilities_or_geography": [],
  "key_findings": ["описан вариант реконфигурации производства"],
  "limitations_or_gaps": ["точные режимы требуют проверки в исходных таблицах"],
  "confidence": 0.72,
  "evidence": [{"source_span_id": "pubspan_..."}]
}
```

`procedure_summaries.jsonl`:

```json
{
  "procedure_summary_id": "proc_b94cdbb6a2e6b59b_0001",
  "publication_id": "pub_b94cdbb6a2e6b59b",
  "doc_id": "b94cdbb6a2e6b59b",
  "material_name": "концентрат драгоценных металлов",
  "synthesis_or_process_method": "технологическая переработка / реконфигурация схемы",
  "procedure_type": "industrial_process",
  "steps": [
    {
      "step_number": 1,
      "description": "Проанализировать текущую технологию производства концентратов.",
      "parameters": {}
    },
    {
      "step_number": 2,
      "description": "Выбрать перспективную схему и подготовить исходные данные для расчета.",
      "parameters": {}
    }
  ],
  "key_points": "Summary сохраняет материал, процесс, условия, выход и эффект, но не заменяет исходный evidence.",
  "materials": ["концентрат драгоценных металлов"],
  "processes": ["переработка", "реконфигурация производства"],
  "equipment": [],
  "properties": ["извлечение", "эффективность"],
  "outputs": ["товарные концентраты"],
  "conditions": [],
  "process_parameters": [],
  "analysis_results": [],
  "equipment_details": [],
  "technology_solutions": [],
  "design_features": [],
  "sample_ids": [],
  "scale": "industrial",
  "observed_effects": [],
  "graph_hints": [
    {
      "relation_type": "uses_material",
      "source_type": "Experiment",
      "target_type": "Material",
      "confidence": 0.68
    }
  ],
  "confidence": 0.7,
  "extraction_status": "partial",
  "evidence": [{"source_span_id": "pubspan_..."}]
}
```

## Extraction Strategy

1. Baseline из `documents.jsonl`: взять `source_type`, `source_path`,
   `file_name`, `extension`, `title`, `metadata_json`, parser stats.
2. Header extraction: читать первые 8-12 KB `full_texts/<doc_id>*.txt`.
3. Candidate snippet selection: выбрать method/experiment/process chunks по
   ключевым словам, числам, единицам, таблицам и headings.
4. Filename/source path extraction: извлечь автора/тип из имен вроде
   `Доклад_Фамилия И.О.pdf`, а также category folder.
5. Regex/rules:
   - DOI: `10.<prefix>/<suffix>`;
   - year: `19xx`/`20xx`, но не брать годы из методологии без контекста;
   - volume/issue/pages: `Т.`, `Vol.`, `No.`, `pp.`, `С.`;
   - authors: строки перед title/abstract или после title, инициалы/фамилии;
   - journal/conference markers: `Журнал`, `Proceedings`, `Материалы`,
     `Conference`, `Сборник`.
6. LLM extraction: отправить bounded source package и получить строгий JSON:
   `PublicationRecord`, `DocumentSummaryRecord`, `ProcedureSummaryRecord[]`.
7. Merge and rank: для каждого поля хранить candidates и выбирать лучший по
   confidence + source priority.
8. Validation:
   - год в разумном диапазоне;
   - DOI соответствует формату;
   - authors не равны creator файла без evidence;
   - title не равен техническому `Презентация PowerPoint` без evidence;
   - procedure summary не содержит материал/режим, которого нет в evidence;
   - `not specified` допустим, если параметр важен, но отсутствует в тексте.
9. Report: coverage по source_type/document_kind, missing fields,
   summary/procedure counts, examples для ручной проверки.

## Source Priority

Для `title`:

1. full text header с явным title;
2. LLM extraction из header;
3. filename cleanup;
4. embedded PDF/DOCX title;
5. parser title fallback.

Для `authors`:

1. full text author block;
2. LLM extraction из header;
3. filename for `Доклад_Фамилия И.О`;
4. embedded metadata author only если совпадает с контекстом;
5. organization/speaker fallback.

Для `year`:

1. publication header/footer;
2. conference/journal issue marker;
3. DOI/venue context if present;
4. filename/source path;
5. file creation date только как low-confidence fallback.

Для `procedure_summaries`:

1. explicit methods/experimental/process sections;
2. table-linked procedure descriptions;
3. abstract/conclusion only as low-confidence fallback;
4. no procedure record if evidence is insufficient.

## Files We Can Change

- `app/extract/*`
- `config/extraction/publication_metadata.json`
- `scripts/extract_publication_metadata.py`
- `tasks/02_publication_metadata/*`

Optional shared helpers после согласования:

- `app/normalization/*` для имен, организаций, журналов, годов.

## Files We Should Not Change

- `app/rag/*`
- `app/index/*`
- `scripts/build_indexes.py`
- `scripts/search_cli.py`
- `data/indexes/*`
- `app/graph/*` кроме чтения готовых publication/summary outputs в graph-task.
- `data/parsed/*` вручную.

## Smoke Command Draft

```powershell
.\.venv\Scripts\python.exe scripts\extract_publication_metadata.py --limit 100 --output-dir data\processed\publications
```

Ускоренный, но безопасный режим для API-bound прогона:

```powershell
.\.venv\Scripts\python.exe scripts\extract_publication_metadata.py --limit 400 --output-dir data\processed\publications --resume --workers 2 --quality-report --summary-audit --summary-audit-sample-size 15
```

`--workers` по умолчанию равен `1` и ограничен сверху `4`. Для локального ПК
рекомендуемый режим `2`: он повышает утилизацию времени ожидания Yandex API, но
не должен заметно грузить RAM/диск. Значения `3-4` использовать только если
нет rate limit/API errors и системная память остается ниже 70-80%.

С quality gate:

```powershell
.\.venv\Scripts\python.exe scripts\extract_publication_metadata.py --output-dir data\processed\publications --aggregate-only --quality-report
```

С sampled summary audit без LLM:

```powershell
.\.venv\Scripts\python.exe scripts\extract_publication_metadata.py --output-dir data\processed\publications --aggregate-only --summary-audit --summary-audit-sample-size 15
```

С sampled LLM-as-judge audit на малом сэмпле:

```powershell
.\.venv\Scripts\python.exe scripts\extract_publication_metadata.py --output-dir data\processed\publications --aggregate-only --summary-audit --summary-audit-llm --summary-audit-sample-size 5
```

Ожидаемые проверки:

- создан `publications.jsonl`;
- созданы `document_summaries.jsonl` и `procedure_summaries.jsonl`;
- при `--quality-report` создан `publication_quality_report.json`;
- при `--summary-audit` создан `summary_quality_report.json`;
- ровно одна publication record на входной `doc_id`;
- одна document summary на входной `doc_id`;
- `procedure_summaries.jsonl` допускает 0..N procedures на документ;
- нет реальных API keys в логах;
- technical titles вроде `Презентация PowerPoint` не считаются high-confidence
  title без evidence из текста;
- report показывает coverage по source_type, missing fields и procedure counts.
- quality report показывает `gate.mass_run_ready`; перед массовым прогоном он
  должен быть `true` или команда должна явно принять listed blockers.
- `refused_triaged` в quality report означает, что LLM отказалась от документа,
  но pipeline сохранил metadata-only baseline как `partial`; такие записи не
  являются hard failure, но не считаются полноценными RECIPER summaries.
- `parse_failed_triaged` означает, что LLM вернула невалидный/оборванный JSON;
  raw response сохранен, а baseline оставлен как `partial` metadata-only
  fallback.

## Acceptance Criteria

MVP готов, если:

- `publications.jsonl` валиден для всех `1862` документов или явно фиксирует
  `extraction_status` для неполных случаев;
- минимум `title`, `document_kind`, `source_type`, `source_path`, `file_name`,
  `confidence`, `evidence` есть у всех records;
- `document_summaries.jsonl` содержит одну запись на каждый документ со
  статусом `ok/partial/no_text`;
- `procedure_summaries.jsonl` содержит только evidence-backed procedures и
  может иметь 0 записей для обзорных/пустых/непроцедурных документов;
- `year` заполнен там, где найден с evidence, и не подменяется blindly датой
  создания файла;
- `authors` извлечены с confidence/evidence, но не превращаются автоматически в
  `Expert` nodes;
- `publication_metadata_report.json` содержит coverage и 20-50 examples для
  ручной проверки;
- graph builder может создать `Publication` nodes из `publications.jsonl` и
  первичные process/material/property candidates из `procedure_summaries.jsonl`
  без повторного чтения full text.
