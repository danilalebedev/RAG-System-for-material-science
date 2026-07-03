# Summary quality audit

`app/extract/summary_quality.py` is an optional sampled audit for
`document_summaries.jsonl` and, when enabled, `procedure_summaries.jsonl`.
It is optional and runs only when requested through Python helpers or explicit
CLI flags, so normal metadata collection does not slow down.

## What it checks

Deterministic checks run without any LLM client:

- summary length: flags very short or oversized document summaries;
- generic summaries: flags summaries that look like placeholders and have no
  materials/processes/properties signal;
- missing evidence: flags summary rows without evidence refs;
- broken evidence refs: verifies refs against
  `publication_evidence_spans.jsonl`;
- summary/evidence overlap: compares summary tokens with resolved evidence
  text;
- entity coverage: checks that `materials`, `processes`, and `properties`
  values are supported by summary or evidence text.

If a `YandexCompletionClient` is passed, the audit also runs an LLM-as-judge
on the sampled documents. The prompt includes the publication title,
document summary, procedure summaries for the same `doc_id`, and resolved
evidence texts. The judge returns strict JSON:

```json
{
  "score": 1,
  "verdict": "pass",
  "issues": [{"code": "string", "severity": "info|warning|error", "message": "string"}],
  "missing_critical_fields": ["string"],
  "hallucination_risk": "low|medium|high"
}
```

The judge is not asked to rewrite summaries. If the model returns fenced JSON,
prefix/suffix text, or malformed output, the audit records a warning issue for
that sampled document and continues.

## Run without API

Use this for a fast smoke check or CI-style local validation:

```powershell
.\.venv\Scripts\python.exe -c "from pathlib import Path; from app.extract.summary_quality import audit_summary_quality; report = audit_summary_quality(Path('data/processed/publications'), sample_size=15, seed=1729); print(report['gate'])"
```

Or through the extraction CLI, without slowing the default extraction path:

```powershell
.\.venv\Scripts\python.exe scripts\extract_publication_metadata.py --output-dir data\processed\publications --aggregate-only --summary-audit --summary-audit-sample-size 15
```

This writes:

```text
data/processed/publications/summary_quality_report.json
```

## Run with Yandex judge

Create the same `YandexCompletionClient` used by
`scripts/extract_publication_metadata.py`, then pass it explicitly:

```python
from pathlib import Path

from app.extract.publication_metadata import ExtractionConfig, YandexCompletionClient
from app.extract.summary_quality import audit_summary_quality

config = ExtractionConfig.from_file(Path("config/extraction/publication_metadata.json"))
client = YandexCompletionClient(
    api_key="<YANDEX_API_KEY>",
    folder_id="<YANDEX_FOLDER_ID>",
    config=config,
)

report = audit_summary_quality(
    Path("data/processed/publications"),
    client=client,
    sample_size=15,
    seed=1729,
    include_procedures=True,
)
print(report["gate"])
```

The same audit can be run through the CLI:

```powershell
.\.venv\Scripts\python.exe scripts\extract_publication_metadata.py --output-dir data\processed\publications --aggregate-only --summary-audit --summary-audit-llm --summary-audit-sample-size 5
```

Recommended `sample_size`: 10-25 documents per batch. This is enough to catch
common summary failures without turning the audit into another full extraction
pass.

## Interpreting the report

Top-level fields:

- `sampled_doc_ids`: deterministic sample selected by `seed`;
- `deterministic_checks`: per-document metrics and deterministic issues;
- `llm_judge`: judge results when `client` was provided, otherwise
  `used=false`;
- `issue_counts`: combined deterministic and judge issue counts;
- `gate.summary_audit_ready`: false when blocking deterministic errors exist,
  the sample is empty, or the judge finds fail/high hallucination risk;
- `gate.reasons`: concrete blockers to inspect before a larger run.

Warnings do not always block the gate. They mark summaries that are usable but
need spot review, for example weak lexical overlap or unsupported entity text.

## Why it does not slow extraction

The module has no API calls at import time. The deterministic path reads only
the existing JSONL outputs and checks a bounded sample. LLM judging runs only
when a caller passes a client explicitly or uses `--summary-audit-llm`, and only
for the sampled `doc_id` values.
