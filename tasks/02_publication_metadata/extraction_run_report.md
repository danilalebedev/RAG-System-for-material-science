# Publication Metadata Extraction Run Report

Дата отчета: 2026-07-04.

Этот отчет фиксирует, что было сделано по задаче `Publication Metadata +
RECIPER-style summaries`, какие артефакты получены и какие проверки пройдены.

## Objective

Нужно было собрать по корпусу:

- bibliographic publication metadata;
- document-level summaries;
- RECIPER-style procedure summaries;
- максимум полезных domain fields для будущего graph/RAG;
- evidence/provenance для проверки фактов;
- quality reports, чтобы downstream не строился на невалидных данных.

Использован Yandex AI Studio generation API через модель:

```text
gpt://<folder_id>/yandexgpt-5.1/latest
```

Секреты не выводились в логи и не сохранялись в docs.

## Timeline Summary

1. Реализован extraction pipeline:
   - `app/extract/publication_metadata.py`;
   - `app/extract/publication_quality.py`;
   - `app/extract/summary_quality.py`;
   - `scripts/extract_publication_metadata.py`;
   - `config/extraction/publication_metadata.json`.
2. Добавлен QA gate:
   - required fields;
   - JSONL validity;
   - evidence refs;
   - title/year/author sanity;
   - procedure summaries with evidence;
   - sampled summary quality audit.
3. Добавлен bounded worker mode:
   - `--workers`;
   - default `1`;
   - cap `4`;
   - финальный устойчивый режим `workers=4`.
4. Выполнен полный прогон корпуса:
   - `1862` selected documents;
   - `failed_this_run = 0`;
   - final `mass_run_ready = true`.
5. После полного прогона обнаружено, что первые `1-250` документов были
   собраны старой версией prompt/schema.
6. Выполнен targeted rebuild первых `250` документов новой схемой:
   - `processed_this_run = 250`;
   - `failed_this_run = 0`;
   - outputs переагрегированы по всем `1862` documents;
   - quality gates остались зелеными.

## Final Commands

Полный corpus resume, которым добирались последние документы:

```powershell
.\.venv\Scripts\python.exe scripts\extract_publication_metadata.py --limit 1862 --output-dir data\processed\publications --resume --workers 4 --quality-report --summary-audit --summary-audit-sample-size 15
```

Targeted rebuild первых 250:

```powershell
.\.venv\Scripts\python.exe scripts\extract_publication_metadata.py --limit 250 --output-dir data\processed\publications --rebuild --workers 4 --quality-report --summary-audit --summary-audit-sample-size 15
```

Дополнительная LLM-as-judge sample проверка выполнялась после полного прогона:

```powershell
.\.venv\Scripts\python.exe scripts\extract_publication_metadata.py --output-dir data\processed\publications --aggregate-only --summary-audit --summary-audit-llm --summary-audit-sample-size 5 --summary-audit-path data\processed\publications\summary_quality_llm_sample_report.json
```

## Final Artifact Counts

После rebuild первых 250:

| Artifact | Count |
|---|---:|
| `records/*.json` | 1862 |
| `publications.jsonl` | 1862 |
| `document_summaries.jsonl` | 1862 |
| `procedure_summaries.jsonl` | 879 |
| `publication_authors.jsonl` | 948 |
| `publication_venues.jsonl` | 294 |
| `publication_evidence_spans.jsonl` | 21328 |

JSONL integrity:

| File | Rows | Bad JSON |
|---|---:|---:|
| `publications.jsonl` | 1862 | 0 |
| `document_summaries.jsonl` | 1862 | 0 |
| `procedure_summaries.jsonl` | 879 | 0 |
| `publication_evidence_spans.jsonl` | 21328 | 0 |

## Quality Gates

Current `publication_quality_report.json`:

| Gate field | Value |
|---|---|
| `mass_run_ready` | `true` |
| `blocking_error_count` | `0` |
| `warning_count` | `416` |
| `reasons` | `[]` |

Current `summary_quality_report.json`:

| Gate field | Value |
|---|---|
| `summary_audit_ready` | `true` |
| `blocking_error_count` | `0` |
| `warning_count` | `1` |
| `reasons` | `[]` |

Important invariant:

```text
procedures_without_evidence = 0
```

## Coverage

Core coverage after rebuild:

| Field | Count / Total | Ratio |
|---|---:|---:|
| title | 1862 / 1862 | 1.0000 |
| year | 1806 / 1862 | 0.9699 |
| authors | 763 / 1862 | 0.4098 |
| doi | 7 / 1862 | 0.0038 |
| document_summary | 1862 / 1862 | 1.0000 |
| procedure_summary | 463 / 1862 | 0.2487 |
| evidence | 1862 / 1862 | 1.0000 |

Low DOI coverage is expected for this corpus: many sources are journal issues,
conference materials, internal reports, Excel tables, reviews or scanned PDFs.
It is not a blocking QA condition.

Procedure coverage is intentionally lower than document summary coverage:
not every document contains an evidence-backed experiment/procedure/process.
The extractor now filters procedure cards without evidence.

## Rebuild 1-250 Result

Reason for rebuild:

Early records `1-250` were generated before prompt/schema included the full
set of domain fields:

- `equipment_details`;
- `experimental_protocols`;
- `technology_solutions`;
- `process_parameters`;
- `analysis_results`;
- extended equipment/process/condition fields.

Before rebuild, the first bucket had zero coverage for several new fields:

| Bucket 1-250 before | Count |
|---|---:|
| document `equipment_details` | 0 |
| document `technology_solutions` | 0 |
| document `experimental_protocols` | 0 |
| procedure `process_parameters` | 0 |
| procedure `analysis_results` | 0 |
| procedure `equipment_details` | 0 |

After rebuild:

| Bucket 1-250 after | Count |
|---|---:|
| document `equipment_details` | 143 |
| document `technology_solutions` | 177 |
| document `experimental_protocols` | 50 |
| procedure `process_parameters` | 271 |
| procedure `analysis_results` | 168 |
| procedure `equipment_details` | 182 |
| procedure `without_evidence` | 0 |

This confirms the rebuild fixed the schema gap.

## Domain Data Extracted

The extraction layer now provides candidates for the required hackathon
knowledge model:

| Required concept | Where it lives now |
|---|---|
| `Material` | `materials`, `material_name`, `input_materials`, `reagents`, `outputs`, `entities[]`. |
| `Process` | `processes`, `synthesis_or_process_method`, `procedure_type`, `steps[]`. |
| `Equipment` | `equipment`, `equipment_details`, `design_features`. |
| `Property` | `properties`, `numerical_results`, `analysis_results`, `observed_effects`. |
| `Experiment` | `procedure_summaries`, `experimental_protocols`, `steps`, `sample_ids`, `validation_methods`. |
| `Publication` | `publications.jsonl`. |
| `Expert` | `authors`, `experts`, `organizations`, role metadata. |
| `Facility` | `facilities`, `facilities_or_geography`, `geography`, `deposits`. |

Additional useful fields:

- numeric conditions and ranges;
- units;
- geography/domestic/foreign practice;
- economic indicators;
- environmental/safety notes;
- software/models;
- data gaps;
- contradiction candidates;
- recommendations;
- source actualization date;
- evidence quotes.

## What Changed In Data Semantics

Procedure count changed from `918` to `879` after first-bucket rebuild. This is
acceptable and expected:

- old extraction could keep weak/noisy procedure candidates;
- newer extraction is stricter and filters rows without evidence;
- QA confirms `procedures_without_evidence = 0`.

For downstream graph/RAG, fewer evidence-backed procedure records are better
than more unsupported pseudo-procedures.

## Files For Teammates

Read these before building graph/RAG over publication outputs:

- `tasks/02_publication_metadata/data_contract.md` - data structure and joins.
- `tasks/02_publication_metadata/quality_agent.md` - QA interpretation.
- `tasks/02_publication_metadata/summary_quality_audit.md` - sampled summary audit.
- `tasks/02_summary_graph/README.md` - graph builder plan.
- `tasks/03_rag/README.md` - RAG index plan.

Primary local data files:

- `data/processed/publications/publications.jsonl`;
- `data/processed/publications/document_summaries.jsonl`;
- `data/processed/publications/procedure_summaries.jsonl`;
- `data/processed/publications/publication_evidence_spans.jsonl`;
- `data/processed/publications/publication_quality_report.json`;
- `data/processed/publications/summary_quality_report.json`.

## Known Limitations

- Authors coverage is partial. Many corpus files are full journal issues,
  proceedings, spreadsheets or reports, not single clean articles.
- DOI coverage is very low for the same reason and should not be used as a
  required key.
- Procedure summaries exist only where evidence supports a procedure/process.
- Some `parse_failed_triaged` and `refused_triaged` records remain as
  metadata/document-summary baseline. They are not blocking, but graph builder
  should prefer records with procedure/evidence.
- Extracted fields are candidates, not normalized ontology. Normalization of
  aliases, units, geography and entity merges belongs to graph/normalization
  workstreams.

## Recommended Next Steps

1. Graph builder should load `publications.jsonl`,
   `document_summaries.jsonl`, `procedure_summaries.jsonl` and
   `publication_evidence_spans.jsonl`.
2. Build `Publication` nodes first, then `Experiment`/`Process` candidates from
   procedure cards.
3. Normalize units/geography/material aliases outside these source files.
4. Build a separate procedure-summary retrieval stream for RAG.
5. Keep raw chunk RAG for citations and exact context.
6. Any future schema/prompt change should run targeted rebuild for affected
   ranges and compare bucket coverage before/after.
