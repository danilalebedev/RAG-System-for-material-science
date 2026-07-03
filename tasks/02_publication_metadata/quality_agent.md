# QA-субагент Publication Metadata

## Назначение

QA-субагент проверяет готовые outputs этапа Publication Metadata + RECIPER-style summaries перед массовым прогоном. Он не вызывает LLM/API, не запускает extraction и не меняет `data/processed/publications`: входом является уже собранная папка output, обычно `data/processed/publications`.

Основной entrypoint:

```python
from pathlib import Path
from app.extract.publication_quality import build_quality_report

report = build_quality_report(Path("data/processed/publications"))
```

CLI-вариант через основной extraction script:

```powershell
.\.venv\Scripts\python.exe scripts\extract_publication_metadata.py --output-dir data\processed\publications --aggregate-only --quality-report
```

Если нужен локальный JSON-артефакт, использовать helper:

```python
from pathlib import Path
from app.extract.publication_quality import build_and_write_quality_report

build_and_write_quality_report(Path("data/processed/publications"))
```

## Что проверяется

- Наличие обязательных полей в `publications.jsonl`, `document_summaries.jsonl` и `procedure_summaries.jsonl`.
- Coverage по `title`, `year`, `authors`, `doi`, `document_summary`, `procedure_summary`, `evidence`.
- Ссылочная целостность `evidence[].source_span_id` и `source_span_ids` относительно `publication_evidence_spans.jsonl`.
- Generic/bad titles: технические названия вроде `Презентация PowerPoint`, `Тема доклада:`, слишком короткие title, одиночные слова, должности или организации вместо названия публикации.
- Suspicious authors: автор совпадает с embedded file creator, но не имеет evidence или надежной confidence.
- RECIPER-style procedure summaries: наличие material/process/method/key_points и evidence-backed provenance.
- Top unknown keys по каждому output type относительно документированной схемы. Это помогает увидеть малополезные или случайно протекшие поля.
- Language distribution: declared и inferred `ru/en/mixed/unknown`, invalid labels, готовность к mixed-language RAG.
- Per-doc `records/*.json`: `publication.extraction_status`, `llm.status`, partial/failed/refusal-like статистика и samples.

## Как читать отчет

`report["issues"]["by_severity"]`:

- `error` - блокирующая проблема качества или целостности. Для массового прогона сначала исправить.
- `warning` - риск качества, который требует triage или настройки extractor/prompt, но может быть принят для пилота.
- `info` - диагностическая информация без прямого блокера.

`report["sample_issues"]` содержит короткие строки для ручной проверки:

- `doc_id`
- `publication_id`
- `title`
- `file`
- `field`
- `message`

`report["coverage"]` показывает count/total/ratio по главным полям. Низкий DOI coverage сам по себе не блокер для этого корпуса, но низкий coverage по title/document_summary/evidence блокирует downstream graph/RAG.

`report["unknown_keys"]` не означает ошибку автоматически. Это список полей, которых нет в документированной схеме. Поля с большим count нужно либо добавить в схему явно, либо удалить из extractor output.

`report["records"]` нужен для оценки надежности прогона. `failed_llm_records`, `partial_records`, `refusal_like_records` и `triaged_refusal_records` показывают, можно ли масштабировать extraction без накопления ручного долга.

`refused_triaged` означает, что модель отказалась обрабатывать документ, но
пайплайн сохранил metadata-only baseline и пометил запись как `partial`. Это
не считается hard failure, но такие документы нужно учитывать в ручном triage и
не использовать как полноценные RECIPER-style summaries.

## Gate criteria для массового прогона

Минимальный gate:

- `report["gate"]["mass_run_ready"] == true`;
- `error == 0`;
- broken evidence refs == 0 для всех output файлов;
- `document_summary.ratio >= 0.98`;
- `evidence.ratio >= 0.98`;
- `title.ratio >= 0.98`;
- `declared_invalid_count == 0`;
- `declared_unknown_ratio <= 0.20`.
- `failed_llm_records == 0`;
- `refusal_like_records == 0`.
- `triaged_refusal_records` явно просмотрены на sample и приняты как
  metadata-only fallback для safety-sensitive документов.

Recommended gate:

- `warning` issues просмотрены и либо исправлены, либо явно приняты;
- `procedure_without_evidence` отсутствует;
- bad titles не являются массовым классом ошибок;
- suspicious embedded creator authors проверены на sample и не попадают в graph как `Expert`;
- unknown keys либо документированы, либо удалены;
- failed/refusal-like records не растут на seed-прогоне после retry/repair.

Если gate не проходит, QA-субагент должен вернуть blocker summary: сколько ошибок, какие коды лидируют, 10-20 representative samples и рекомендуемый следующий фикс в extractor/prompt.
