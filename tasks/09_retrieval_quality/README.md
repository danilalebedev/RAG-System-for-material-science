# Retrieval Quality Polish

## What changed

- Planner now extracts material phrases, not only single tokens.
  - Query `никелевая руда` returns material `никелевая руда`.
- QueryPlan now exposes clean retrieval fields:
  - `internal_search_queries`
  - `web_search_queries`
  - `entity_aliases`
  - `slots`
- Existing `rewritten_queries` remains for backward compatibility.
- Added nickel ore aliases:
  - никелевая руда
  - никелевые руды
  - nickel ore
  - nickel ores
  - латеритная никелевая руда
  - сульфидная никелевая руда
  - laterite nickel ore
  - sulfide nickel ore
  - Ni ore
  - сульфидные никелевые концентраты
  - limonite saprolite nickel ore
- Short material/topic queries now force:
  - `raw_rag`
  - `summary_rag`
  - `table_search`
  - `graph_search`
- Web route is appended by orchestrator when `include_web=True`.
- Local retrieval uses clean `internal_search_queries`; web retrieval uses clean `web_search_queries`.
- GUI no longer sends slot-labelled strings like `Материал:` to retrieval.
- Table scoring now boosts Ni/nickel + ore matches and penalizes gold-only matches for nickel ore queries.
- Graph search expands nickel ore query terms.
- Graph builder adds lightweight Material/Process/Property nodes from publication titles and table previews where possible.
- CLI scripts now configure UTF-8 stdout for Windows consoles.

## Diagnostics

When local matches are empty, GUI shows:

- `chunks.jsonl` found/missing
- `documents.jsonl` found/missing
- `tables.jsonl` found/missing
- graph files found/missing
- actual local query
- called search sources

## Checked behavior for `никелевая руда`

- Planner extracts `никелевая руда`.
- Routes include `raw_rag`, `summary_rag`, `table_search`, `graph_search`.
- Search queries do not contain `Материал:`.
- Web queries contain `nickel ore` aliases.
- Local retriever does not crash.
- Top raw/table hits mention nickel/Ni in the current local data.
- Graph hits are returned when graph artifacts exist.

## Commands

```powershell
.\.venv\Scripts\python.exe scripts\smoke_nickel_ore_query.py
.\.venv\Scripts\python.exe scripts\run_local_knowledge.py "никелевая руда" --json
```

## Known blockers

- `data/processed/publications` summary files are missing in this checkout, so `summary_rag` reports an unavailable source.
- Existing graph artifacts may have been built before the lightweight graph extraction change; rebuild graph to get improved Material -> Process -> Property -> Publication links.

No `git push` was performed.
