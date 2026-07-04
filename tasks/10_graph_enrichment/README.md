# 10. Knowledge Graph Enrichment

Date: 2026-07-04

## Goal

Current graph artifacts are useful but still too technical/noisy for demo:
the graph contains many `Publication -> Table` and broad `described_in` links.
The next step is to enrich it into a metallurgy-aware graph focused on:

```text
Material -> Process/Experiment -> Property/Output -> Publication/Evidence
```

The organizer-facing entity types stay:

- `Material`
- `Process`
- `Equipment`
- `Property`
- `Experiment`
- `Publication`
- `Expert`
- `Facility`

Organizer-facing relation types stay:

- `uses_material`
- `operates_at_condition`
- `produces_output`
- `described_in`
- `validated_by`
- `contradicts`

Internal helper relations may be generated only if they are mapped back to the
official relation types for the final API/GUI view.

## Development Zone

Can change:

- `app/graph/*`
- `scripts/build_knowledge_graph.py`
- `scripts/search_graph.py`
- `tasks/10_graph_enrichment/*`
- graph tests under `tests/`

Read-only inputs:

- `data/processed/publications/publications.jsonl`
- `data/processed/publications/document_summaries.jsonl`
- `data/processed/publications/procedure_summaries.jsonl`
- `data/processed/publications/publication_evidence_spans.jsonl`
- `data/parsed/documents.jsonl`
- `data/parsed/tables.jsonl`

Generated outputs:

- `data/index/knowledge_graph_nodes.jsonl`
- `data/index/knowledge_graph_edges.jsonl`
- `data/index/knowledge_graph_manifest.json`
- optional enrichment QA reports under `reports/graph/`

Do not change without coordination:

- `app/index/*`
- `app/rag/*`
- `app/extract/*`
- publication metadata JSONL schema
- parsed corpus files

## Current Baseline

Local graph was rebuilt from publication summaries and parsed artifacts:

- nodes: `42,782`
- edges: `105,628`
- files:
  - `data/index/knowledge_graph_nodes.jsonl`
  - `data/index/knowledge_graph_edges.jsonl`
  - `data/index/knowledge_graph_manifest.json`

Smoke query `никелевая руда` already returns `Material никелевая руда` and
neighbors, including `uses_material` experiment edges and `described_in`
publication edges.

## Enrichment Plan

### Step 1. Edge Audit

Build a small graph QA report:

- node counts by type;
- edge counts by relation;
- top high-degree nodes;
- share of edges with `evidence`;
- share of `Experiment` nodes connected to:
  - Material;
  - Process/condition;
  - Property/output;
  - Publication.

Acceptance:

- report identifies noisy relation families;
- no graph rebuild is considered valid without the report.

### Step 2. Procedure-Centric Extraction

Use `procedure_summaries.jsonl` as the main graph source.

For every procedure card, build an experiment bundle:

```json
{
  "experiment_id": "...",
  "doc_id": "...",
  "publication_id": "...",
  "procedure_summary_id": "...",
  "materials": [],
  "processes": [],
  "equipment": [],
  "conditions": [],
  "outputs": [],
  "properties": [],
  "evidence": []
}
```

Map bundle to official edges:

- `Experiment uses_material Material`
- `Experiment operates_at_condition Process`
- `Experiment operates_at_condition Property` for typed numeric conditions
- `Experiment produces_output Property`
- `Experiment described_in Publication`
- `Experiment validated_by Publication` when evidence/validation method exists

### Step 3. Normalization Pass

Normalize labels before node creation:

- Russian/English aliases for nickel, copper, cobalt, ore, concentrate, matte,
  slag, tailings, solution;
- units and numeric ranges;
- countries/regions/facilities;
- common process names:
  - flotation;
  - leaching;
  - pressure oxidation;
  - pyrometallurgy;
  - hydrometallurgy;
  - electroextraction/electrowinning;
  - gas cleaning.

Acceptance:

- `никелевая руда`, `nickel ore`, `Ni ore` resolve to one preferred Material
  cluster or clearly connected aliases.

### Step 4. Evidence Binding

Every high-value edge should carry at least one evidence pointer when available:

- `source_span_id`
- `procedure_summary_id`
- `doc_id`
- `publication_id`
- confidence

Edges without evidence are allowed only for derived helper links and should have
lower confidence.

### Step 5. Contradiction Candidates

Do not ask LLM to find contradictions across the full corpus. First generate
deterministic candidates:

- same Material + Process + Property;
- conflicting numeric ranges;
- opposite observed effects;
- different geography/time period.

Only then send compact candidate pairs to Yandex/RouterAI for a JSON judgment.

Output edge:

- `SourceA contradicts SourceB`
- metadata: compared field, value_a, value_b, reason, confidence.

### Step 6. Demo Graph Views

Expose graph slices useful for GUI:

- `Material neighborhood`: Material -> Experiment -> Publication.
- `Process comparison`: Process -> Property/output -> Publication.
- `Evidence path`: user query entity -> evidence spans.
- `Gap view`: entities with raw hits but weak graph coverage.

## LLM/API Use

Yandex-first:

- use Yandex for graph enrichment when API is restored;
- use compact procedure/evidence snippets only.

RouterAI fallback:

- use `deepseek/deepseek-chat-v3.1` only for:
  - contradiction judgment;
  - missed relation extraction on selected candidates;
  - QA audit of sampled graph edges.

No LLM should process all raw chunks for graph enrichment.

## Acceptance Criteria

- graph rebuild is reproducible from committed code and local data artifacts;
- `scripts/build_knowledge_graph.py` still works with no network;
- graph contains useful paths for demo queries:
  - `никелевая руда`
  - `автоклавное выщелачивание`
  - `никелевые концентраты`
  - `очистка газов`
  - `техногенный гипс`
- top graph results are not dominated by generic publications/tables;
- high-value edges include evidence references and confidence;
- generated graph artifacts stay out of git.

## Suggested Commands

Baseline rebuild:

```powershell
.\.venv\Scripts\python.exe scripts\build_knowledge_graph.py
```

Smoke search:

```powershell
.\.venv\Scripts\python.exe scripts\search_graph.py "никелевая руда" --top-k 5 --paths --json
```

Future QA command:

```powershell
.\.venv\Scripts\python.exe scripts\audit_knowledge_graph.py `
  --nodes data\index\knowledge_graph_nodes.jsonl `
  --edges data\index\knowledge_graph_edges.jsonl `
  --report reports\graph\graph_quality_report.json
```
