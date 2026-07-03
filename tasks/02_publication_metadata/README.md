# 02. Publication Metadata

Дата обновления: 2026-07-03.

Статус: новая отдельная upstream-задача. Цель - извлечь нормализованную
библиографическую metadata по источникам корпуса, чтобы graph builder мог
создавать `Publication` nodes и связывать эксперименты/процессы/материалы с
источником через `described_in`.

## Почему Это Отдельный Шаг

Текущий `data/parsed/documents.jsonl` хранит техническую metadata парсинга и
встроенную metadata файлов. Это полезно как baseline, но не равно
библиографии:

- top-level `author/authors/journal/year/doi/abstract` сейчас не заполнены;
- `metadata_json.author` часто означает автора файла или презентации, а не
  автора научной работы;
- `metadata_json.title` часто технический: например, `Презентация PowerPoint`;
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

## Inputs

Read-only входы:

- `data/parsed/documents.jsonl`
- `data/parsed/full_texts/*.txt`
- `data/parsed/chunks.jsonl` только если нужно найти title/author в первых
  chunks;
- `data/parsed/tables.jsonl` и `data/parsed/spreadsheets_csv/**/*.csv` только
  для Excel/DOCX cases, где metadata находится в таблице.

## Outputs

Пишем в отдельную папку, не смешивая с graph/RAG:

- `data/processed/publications/publications.jsonl`
- `data/processed/publications/publication_authors.jsonl`
- `data/processed/publications/publication_venues.jsonl`
- `data/processed/publications/publication_evidence_spans.jsonl`
- `data/processed/publications/publication_metadata_report.json`
- `data/processed/publications/publication_metadata_manifest.json`

Все `data/processed/*` ignored и не коммитятся.

## Core Types

### `PublicationRecord`

Одна запись на `doc_id`. Даже если источник не является классической статьей,
он все равно может стать `Publication` node в графе, потому что условие задания
использует `Publication` как тип источника.

Обязательные поля:

- `publication_id`: стабильный id, например `pub_<doc_id>` или hash canonical
  title/year/source.
- `doc_id`: id из `documents.jsonl`.
- `document_kind`: нормализованный тип документа.
- `source_type`: исходная категория из Яндекс.Диска.
- `title`: лучший извлеченный заголовок.
- `title_confidence`: confidence для заголовка.
- `source_path`, `file_name`, `extension`: provenance из parser metadata.
- `extraction_status`: `ok`, `partial`, `no_bibliography`, `needs_review`,
  `failed`.
- `confidence`: общий confidence записи.
- `evidence`: список evidence spans.

Рекомендуемые поля:

- `subtitle`
- `language`: `ru`, `en`, `mixed`, `unknown`.
- `year`: нормализованный год публикации.
- `date_published`: если удалось извлечь точную дату.
- `authors`: массив author refs или inline author objects.
- `organizations`: организации/лаборатории/аффилиации.
- `venue_name`: журнал, сборник, конференция, мероприятие или серия.
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
- `topic_tags`: tags из источника или LLM/rule extraction.
- `embedded_metadata`: исходные PDF/DOCX поля без нормализации.
- `parser_metadata`: page count, text chars, parser, quality label.
- `missing_fields`: список важных отсутствующих полей.
- `review_notes`: почему запись требует ручной проверки.

### `DocumentKind`

Enum:

- `journal_article`
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

- `source_type=Журналы` -> чаще `journal_article`, но проверять по title/header.
- `source_type=Материалы конференций` -> `conference_paper` или
  `conference_abstract`; Excel в этой категории -> `spreadsheet_dataset`.
- `source_type=Обзоры` -> `review_article` или `technical_report`.
- `source_type=Статьи` -> `journal_article`/`technical_report`, зависит от
  header.
- `source_type=Доклады` -> `presentation_report`.

### `AuthorRecord`

Авторы не становятся отдельными graph nodes автоматически. В официальной схеме
есть `Expert`, но нет отношения `authored_by`, поэтому авторов храним как
атрибуты `Publication`. В `Expert` переводим только тех, кто явно нужен как
эксперт/валидатор/исследовательская команда.

Поля:

- `author_id`: стабильный hash normalized name + optional affiliation.
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

### `VenueRecord`

Venue не становится graph node в MVP. Это атрибут `Publication`, но отдельный
JSONL нужен для нормализации названий журналов/конференций.

Поля:

- `venue_id`
- `raw_name`
- `normalized_name`
- `venue_type`
- `issn`
- `publisher`
- `country`
- `city`
- `aliases`
- `confidence`
- `evidence`

### `EvidenceSpan`

Любое извлеченное библиографическое поле должно иметь traceability:

- `source_span_id`
- `doc_id`
- `publication_id`
- `field_name`
- `source_kind`: `embedded_metadata`, `full_text_header`, `chunk`, `filename`,
  `source_path`, `table`
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
  "date_published": null,
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
  "keywords": [],
  "abstract": null,
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
  "evidence": [
    {
      "source_span_id": "pubspan_...",
      "field_name": "title",
      "source_kind": "full_text_header",
      "text": "..."
    }
  ]
}
```

`publication_authors.jsonl`:

```json
{
  "author_id": "author_...",
  "publication_id": "pub_...",
  "doc_id": "doc_...",
  "raw_name": "Петров П. П.",
  "normalized_name": "Петров Петр Петрович",
  "affiliations": ["..."],
  "role": "author",
  "order": 2,
  "confidence": 0.81,
  "evidence": [{"source_span_id": "pubspan_..."}]
}
```

`publication_venues.jsonl`:

```json
{
  "venue_id": "venue_...",
  "raw_name": "Журнал ...",
  "normalized_name": "Журнал ...",
  "venue_type": "journal",
  "publisher": null,
  "country": "RU",
  "aliases": [],
  "confidence": 0.77,
  "evidence": [{"source_span_id": "pubspan_..."}]
}
```

## Extraction Strategy

1. Baseline из `documents.jsonl`: взять `source_type`, `source_path`,
   `file_name`, `extension`, `title`, `metadata_json`, parser stats.
2. Header extraction: читать первые 8-12 KB `full_texts/<doc_id>*.txt`.
   Для PDF это обычно первые страницы; для DOCX/DOC - начало документа.
3. Filename/source path extraction: извлекать автора/тип из имен вроде
   `Доклад_Фамилия И.О.pdf`, а также category folder.
4. Regex/rules:
   - DOI: `10.<prefix>/<suffix>`;
   - year: `19xx`/`20xx`, но не брать годы из методологии без контекста;
   - volume/issue/pages: `Т.`, `Vol.`, `No.`, `pp.`, `С.`;
   - authors: строки перед title/abstract или после title, инициалы/фамилии;
   - journal/conference markers: `Журнал`, `Proceedings`, `Материалы`,
     `Conference`, `Сборник`.
5. LLM fallback: только head snippets, filename и embedded metadata, не весь
   документ. Модель возвращает строгий JSON по schema.
6. Merge and rank: для каждого поля хранить candidates и выбирать лучший по
   confidence + source priority.
7. Validation: год в разумном диапазоне, DOI format, authors не равны creator
   файла, title не равен техническому `Презентация PowerPoint` без evidence.
8. Report: coverage по source_type/document_kind, missing fields, examples для
   ручной проверки.

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
- `app/graph/*` кроме чтения готового `publications.jsonl` в graph-task.
- `data/parsed/*` вручную.

## Smoke Command Draft

```powershell
.\.venv\Scripts\python.exe scripts\extract_publication_metadata.py --limit 100 --output-dir data\processed\publications
```

Ожидаемые проверки:

- создан `publications.jsonl`;
- ровно одна publication record на входной `doc_id`;
- нет реальных API keys в логах;
- technical titles вроде `Презентация PowerPoint` не считаются high-confidence
  title без evidence из текста;
- report показывает coverage по source_type и missing fields.

## Acceptance Criteria

MVP готов, если:

- `publications.jsonl` валиден для всех `1862` документов или явно фиксирует
  `extraction_status` для неполных случаев;
- минимум `title`, `document_kind`, `source_type`, `source_path`, `file_name`,
  `confidence`, `evidence` есть у всех records;
- `year` заполнен там, где найден с evidence, и не подменяется blindly датой
  создания файла;
- `authors` извлечены с confidence/evidence, но не превращаются автоматически в
  `Expert` nodes;
- `publication_metadata_report.json` содержит coverage и 20-50 examples для
  ручной проверки;
- graph builder может создать `Publication` nodes из `publications.jsonl`
  без повторного чтения full text.
