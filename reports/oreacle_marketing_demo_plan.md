# Oreacle marketing demo plan

Дата: 2026-07-04

## 1. Positioning

**Название:** Oreacle.

**Формула:** metallurgy-aware R&D Knowledge Cockpit.

**Короткая подача:**

Oreacle - это не "поиск по PDF" и не generic chatbot. Это ИИ-оракул для металлургического R&D: он связывает внутренние документы, таблицы, граф знаний, эксперименты, рыночные данные и evidence в проверяемый инженерный brief.

**Главный тезис:**

Oreacle превращает разрозненные PDF, Excel, обзоры, патенты, отчеты и market data в evidence-first инженерные выводы: какие процессы применимы, при каких условиях, с какими эффектами, рисками, источниками и следующими проверками.

**Чем отличается от обычного RAG:**

| Generic RAG | Oreacle |
|---|---|
| Ищет похожие фрагменты текста | Разводит вопрос по маршрутам: raw chunks, summaries, tables, graph, compare, business context |
| Отвечает текстом | Собирает evidence matrix, numeric ranges, graph path и краткий engineering brief |
| Работает как чат | Работает как R&D cockpit с проверкой источников |
| Не понимает металлургическую структуру | Видит материал, процесс, оборудование, условия, свойства, продукт, качество, риски |
| Может спрятать неопределенность | Явно показывает confidence, missing evidence, fallbacks и provider status |

**One-slide pitch:**

Oreacle is a metallurgy-aware R&D Knowledge Cockpit. It connects internal reports, Excel tables, knowledge graphs, official production statistics, company reports, open-access literature and domain-specific model endpoints. Unlike generic RAG, Oreacle understands metallurgical objects: ore, concentrate, matte, slag, recovery, grade, reagents, impurities and production constraints. The result is a verified engineering brief with evidence, numbers, risks and next experiments - not just search results.

## 2. Demo story

### Opening pain

R&D knowledge in metallurgy is scattered across:

- scanned PDFs and journal issues;
- Excel tables and product specifications;
- conference proceedings;
- internal reports and reviews;
- patents and market reports;
- external public statistics.

For an engineer, the hard part is not "find a document". The hard part is to connect process, conditions, recovery, product quality, source reliability and business impact.

### Hero query

Use this as the primary demo query:

```text
Никелевая руда: какие методы переработки, условия, эффекты и источники?
```

The demo should immediately show five routes:

1. **Raw RAG** - source passages from the parsed corpus.
2. **Summary RAG** - document/procedure summaries from extracted publication metadata.
3. **Tables** - matched rows/cells from tables and spreadsheets.
4. **Knowledge Graph** - a curated path, not the full graph.
5. **Comparison Mode** - method-by-method matrix with missing evidence.

### Concrete evidence anchors already found locally

Local lexical RAG found strong evidence for:

- nickel ore flotation and reagent practice in `Handbook of Flotation Reagents_ Chemistry, Theory and Practice.pdf`;
- autoclave oxidative leaching of nickel/cobalt sulfide concentrates in ALTA Ni-Co proceedings and `Цветные металлы/2014/CM_09_14.pdf`;
- SO2/offgas treatment and sulfur capture in extractive metallurgy/copper conference sources;
- technogenic gypsum/synthetic anhydrite from sulfur-containing gases in Russian review documents;
- nickel product composition tables with Ni, Co, Fe, C, S, Cu and other impurities.

The current graph also returns `Material: никелевая руда` with related experiments such as enrichment/processing, flotation and ferronickel production, plus publication links.

### Business close

End the demo with the business layer:

```text
technology evidence -> process risk -> product quality -> production/market context -> next experiments
```

Suggested business framing:

- production stability: which processing route protects recovery and product quality;
- import substitution: where reagent replacement can damage selectivity, Ni/Cu recovery or impurity profile;
- environmental constraint: SO2 capture and sulfur-containing gas utilization;
- product quality: whether route changes threaten nickel grade and impurity limits;
- market context: where production, supply or regulatory pressure makes a technical topic urgent.

## 3. Presentation structure

### Slide 1. Problem

Title: `R&D data is everywhere. Engineering evidence is nowhere.`

Show the pain visually as fragmented sources: PDF, Excel, patents, reports, market statistics, lab notes.

Speaker line:

```text
In metallurgy, the question is rarely "find me a PDF". The real question is "what process can we trust, under which conditions, with what recovery, what product quality and which evidence?"
```

### Slide 2. Product definition

Title: `Oreacle: metallurgy-aware R&D Knowledge Cockpit`

Show the formula:

```text
Documents + Tables + Knowledge Graph + Experiments + Market Context + Evidence
```

Speaker line:

```text
Oreacle is an evidence-first cockpit around metallurgical R&D knowledge. It can use LLMs, but it is not defined by the model. It is defined by the evidence workflow.
```

### Slide 3. Architecture

Show a compact architecture:

```text
User Question
  -> Query Intelligence
  -> Multi-route Retrieval
     -> Raw RAG
     -> Summary RAG
     -> Tables
     -> Knowledge Graph
     -> Web / Market data
  -> Metallurgy Reasoning Layer
  -> Evidence Matrix
  -> Engineering Brief
```

Keep this slide functional, not decorative.

### Slide 4. Live query

Show the cockpit first screen with:

- query input;
- scenario buttons;
- compact QueryPlan;
- provider status;
- visible tabs: Evidence, Raw, Summary, Tables, Graph, Compare, Business.

Use the nickel ore query.

### Slide 5. Evidence matrix

Show one matrix:

| Claim | Route | Source | Evidence | Confidence | Gap |
|---|---|---|---|---|---|
| Flotation is a key route for copper-nickel ores | Raw/Summary | Handbook / journal source | fragment | high | verify local ore type |
| Autoclave leaching has operating windows | Raw/Tables | ALTA / Цветные металлы | temperature, oxygen pressure, time | medium-high | normalize units |
| Product purity is table-backed | Tables | nickel product tables | Ni, Co, Fe, S, Cu rows | high | map to product spec |

### Slide 6. Graph path

Do not show the whole graph. Show one path:

```text
никелевая руда
  -> флотация / выщелачивание / плавка
  -> извлечение Ni/Cu/Co, концентрат, продукт
  -> publication / table / evidence span
```

Speaker line:

```text
The graph is useful because it gives a path from material to process to result to source, not because it draws thousands of nodes.
```

### Slide 7. Comparison mode

Compare 3-4 methods:

- flotation;
- autoclave sulfuric-acid leaching;
- pyrometallurgical route;
- heap/bioleaching if evidence is available for the chosen corpus slice.

Rows should show conditions, benefits, risks, product quality impact, source count and missing evidence.

### Slide 8. Business layer

Show a mock but structured `Business` tab:

- production radar;
- market context;
- source confidence;
- import substitution relevance;
- environmental / SO2 risk;
- recommended next checks.

Speaker line:

```text
Oreacle closes the loop from R&D evidence to production risk and business decision context.
```

### Slide 9. Final thesis

Title:

```text
Verified engineering brief, not just search.
```

Final line:

```text
Oreacle turns metallurgical knowledge into traceable decisions: evidence, numbers, graph paths, comparisons, risks and next experiments.
```

## 4. 90-second video script

### 0-10 sec: problem

Visual: fast montage of PDFs, Excel tables, scanned journal pages, patents and reports.

Voice:

```text
Metallurgical R&D data is fragmented across PDFs, Excel files, reviews, patents and reports. Engineers do not need another list of files. They need verified answers with conditions, effects and sources.
```

### 10-25 sec: Oreacle cockpit and query

Visual: first screen is the cockpit, not a landing page. User clicks scenario `Никелевая руда`.

Voice:

```text
Oreacle is a metallurgy-aware R&D Knowledge Cockpit. We ask: nickel ore - which processing methods, operating conditions, effects and sources are available?
```

On screen:

- QueryPlan chips: intent, entities, routes, provider;
- provider status: Offline / Yandex / RouterAI;
- tabs: Evidence, Raw, Summary, Tables, Graph, Compare, Business.

### 25-45 sec: evidence matrix, sources, graph path

Visual: Evidence cards and a graph path.

Voice:

```text
Oreacle does not hide behind one generated answer. It opens the evidence matrix: raw passages, extracted summaries, matched tables and a graph path from material to process to publication.
```

Show:

- source, doc_id, year, confidence;
- nickel ore -> flotation/leaching -> recovery/product quality -> source.

### 45-65 sec: comparison mode

Visual: method comparison table.

Voice:

```text
Then Comparison Mode turns sources into an engineering table: flotation, autoclave leaching and pyrometallurgical routes are compared by conditions, effects, risks and missing evidence.
```

Show:

- operating conditions;
- recovery/grade/product fields where present;
- missing evidence/fallbacks.

### 65-80 sec: business/production radar mock

Visual: Business tab with production radar mock.

Voice:

```text
The business layer connects R&D evidence to production questions: product quality, SO2 constraints, reagent substitution, import risk and market context.
```

Show:

- production radar;
- market context;
- source confidence;
- next checks.

### 80-90 sec: final thesis

Visual: executive engineering brief export.

Voice:

```text
Oreacle is not just search. It creates a verified engineering brief - evidence, numbers, graph paths, comparisons, risks and next experiments.
```

On screen:

```text
Oreacle. Verified engineering brief, not just search.
```

## 5. Frontend requirements for demo-ready polish

### P0: first screen must be the cockpit

The first viewport should be the working cockpit, not a landing page or hero. The user should immediately see:

- query input;
- demo scenario buttons;
- provider status;
- compact QueryPlan;
- main tabs.

Current GUI already has a Streamlit cockpit, mode cards and scenario selector. For the demo, move the operational cockpit above any descriptive blocks.

### P0: main tabs must match the story

Use these visible tabs:

```text
Evidence | Raw | Summary | Tables | Graph | Compare | Business
```

Current GUI has mixed modes and result tabs such as `Cockpit`, `Публикации`, `Deep Search`, `Evidence`, `Local Knowledge`, `Knowledge Graph`, `Графики`, plus route tabs `Evidence`, `Raw`, `Summaries`, `Tables`, `Graph`, `Web`, `Fallbacks`. For the presentation, normalize the main demo path to the seven tabs above.

### P0: demo scenarios as buttons

Add buttons:

- `Никелевая руда`;
- `Автоклавное выщелачивание`;
- `Техногенный гипс`;
- `Очистка газов`;
- `Импортозамещение реагентов`.

The current sidebar scenarios are useful but not aligned enough with the story. Keep them, but make the five presentation scenarios first-class buttons near the query box.

### P0: QueryPlan must be compact and honest

Show chips:

- intent;
- entities;
- routes;
- provider.

Important current gap: the query

```text
никелевая руда: какие методы переработки, условия, эффекты и источники?
```

currently plans only `raw_rag` and extracts entity `руда`, not `никелевая руда`. For demo readiness, either:

- improve planner entity/routing rules for this scenario; or
- force the scenario preset to run `raw_rag`, `summary_rag`, `table_search`, `graph_search` and comparison.

### P0: evidence cards must expose provenance

Each evidence card should show:

- source;
- doc_id;
- chunk_id or summary_id when available;
- confidence;
- date/year;
- route;
- short evidence preview;
- "open source" / local path if available.

The current evidence cards already show confidence, year and source in places, but `doc_id` should be consistently visible because hackathon evaluators will check traceability.

### P0: provider status

Show a small status strip:

```text
Provider: Offline | Yandex | RouterAI
Embeddings: lexical | yandex-vector | local-hash
Fallback: none | permission_denied | local_draft
```

Do not imply MetalGPT is running locally. Say `MetalGPT-ready endpoint` only if it is a placeholder.

### P1: Graph view must show a path, not the whole graph

Default graph view should be:

```text
Material -> Experiment/Process -> Property/Output -> Publication/Evidence
```

Use the full graph only behind an expander or debug control. Current graph artifacts are large: 42,782 nodes and 105,628 edges. The demo should show curated paths.

### P1: Tables view must highlight matched cells/columns

Tables should visibly highlight:

- matched column names;
- matched rows;
- numeric cells;
- units;
- source doc_id.

Good current table demo:

```text
nickel composition grade recovery Ni Cu Co
```

It returns nickel product composition tables with Ni, Co, Fe, C, S, Cu and product names. This is excellent for showing that Oreacle can inspect tables rather than summarize prose only.

### P1: Summary tab should use extracted summaries honestly

The data exists:

- `document_summaries.jsonl`: 1,862 rows;
- `procedure_summaries.jsonl`: 879 rows;
- procedure summaries without evidence: 0.

But dense summary vector indexes are not currently present. Therefore the tab can be called `Summary` and use available summary search/fallback, but the pitch should not claim that dense summary vector RAG is already active unless those indexes are built.

### P1: Compare tab should make missing evidence visible

Comparison Mode should include:

- method;
- material/input;
- conditions;
- observed effects;
- numeric results;
- source count;
- confidence;
- missing evidence.

This is already aligned with `app/query/comparison.py`. The demo should avoid pretending all rows are equally proven.

### P1: Business tab can be mock + structure

Business tab should not fake external production data. For the demo, show a structured mock:

- production radar;
- market context;
- import substitution relevance;
- environmental risk;
- source confidence;
- next data connectors.

Label it clearly as `mock / structure` until official production connectors are implemented.

### P2: hide technical logs

Keep raw JSON, full structured payloads and route debug inside expanders. The demo surface should prioritize:

- question;
- evidence matrix;
- comparison;
- graph path;
- business implication.

## 6. Publication-backed use cases

### Use case 1. Nickel ore processing cockpit

**Demo query:**

```text
Никелевая руда: какие методы переработки, условия, эффекты и источники?
```

**Why it works:**

- graph search already finds `Material: никелевая руда`;
- local raw RAG finds flotation and nickel/copper ore evidence;
- tables can show nickel product quality;
- comparison can contrast flotation, leaching and pyrometallurgical processing.

**What to show:**

- Raw: flotation passages and source paths;
- Summary: document/procedure cards;
- Tables: product composition and process rows;
- Graph: `никелевая руда -> флотация/выщелачивание/плавка -> results -> publication`;
- Compare: routes by conditions, recovery, grade, risks;
- Business: production and product quality impact.

**Best role in presentation:** main hero story.

### Use case 2. Autoclave leaching of Ni/Co sulfide concentrates

**Demo query:**

```text
Сравни автоклавное выщелачивание никель-кобальтовых сульфидных концентратов: условия, извлечение, риски, источники.
```

**Local evidence found:**

- ALTA Ni-Co proceedings;
- `Цветные металлы/2014/CM_09_14.pdf`;
- passages mention autoclave oxidative leaching, sulfide concentrates, nickel, cobalt, temperature/pressure/time ranges.

**What to show:**

- conditions such as temperature, oxygen pressure, sulfuric acid/sulfate additives where evidence exists;
- risks: sulfur shielding, refractory minerals, PGM losses to tails, unit normalization;
- graph path from concentrate to autoclave leaching to solution/product/evidence.

**Best role in presentation:** technical credibility scene.

### Use case 3. Reagent substitution for copper-nickel flotation

**Demo query:**

```text
Подбери варианты импортозамещения реагентов для флотации медно-никелевой сульфидной руды. Покажи риски для извлечения Ni и качества концентрата.
```

**Local evidence found:**

- `Handbook of Flotation Reagents` contains copper-nickel flotation reagent practice;
- evidence mentions xanthates, dithiophosphates/mercaptans, depressants, soda ash, talc depression, grade/recovery relationships.

**What to show:**

- reagent class;
- role;
- substitute class;
- controlled metric;
- risk;
- lab check.

**Best role in presentation:** business relevance for import substitution.

### Use case 4. SO2 gas cleaning and sulfur capture

**Demo query:**

```text
Какие методы очистки металлургических газов от SO2 применимы, какие ограничения и источники?
```

**Local evidence found:**

- extractive metallurgy/copper sources describe offgases from smelting/converting and sulfuric acid plants;
- Copper 2010 and Copper 2013 sources include SO2 reduction, gas management, acid plant optimization and sulfur capture;
- ALTA 2012 mentions WSA technology for SO2-containing off-gases.

**What to show:**

- process options;
- SO2 concentration / gas flow if available;
- acid plant / WSA / gas handling;
- environmental and production risk.

**Best role in presentation:** production risk and ESG scene.

### Use case 5. Technogenic gypsum / synthetic anhydrite

**Demo query:**

```text
Техногенный гипс и синтетический ангидрит из серосодержащих газов: применение, риски, источники.
```

**Local evidence found:**

- Russian review documents on synthetic anhydrite;
- references to utilization of technogenic anhydrite from sulfur-containing gases;
- phosphogypsum processing sources, including rare-earth recovery context.

**What to show:**

- source material;
- utilization route;
- environmental/business impact;
- evidence confidence and gaps.

**Best role in presentation:** broadens Oreacle beyond nickel into waste utilization and circular economy.

### Use case 6. Product quality checker for nickel products

**Demo query:**

```text
Проверь показатели качества никелевой продукции: Ni, Co, Fe, C, S, Cu и источники таблиц.
```

**Local evidence found:**

- table search returns nickel product composition rows for Vale, Nikkelverk, Severonickel/Kola GMK and others;
- columns include Ni, Co, Fe, C, S, Cu, Zn, Pb, As and product names.

**What to show:**

- matched cells/columns;
- product names and plants;
- impurity limits;
- source doc_id;
- confidence.

**Best role in presentation:** tables proof point.

## 7. What not to do

- Do not sell Oreacle as a generic chatbot.
- Do not make a landing page instead of the cockpit.
- Do not overload the screen with raw logs, JSON dumps or API stack traces.
- Do not claim local MetalGPT is running if only endpoint compatibility exists.
- Do not show Sci-Hub or paywalled scraping flows.
- Do not hide missing evidence; missing evidence is part of trust.
- Do not present Business tab mock as live production data.
- Do not use decorative frontend features that do not help prove evidence, graph, tables, comparison or business relevance.

## 8. Agent task formulation

```text
Проанализируй oreacle_metallurgy_models_sources_features.md, текущие tasks/* и GUI. Подготовь marketing narrative, структуру презентации, 90-секундный video script и список frontend-доработок для demo-ready Oreacle.

Фокус: Oreacle как metallurgy-aware R&D Knowledge Cockpit, evidence-first, graph + RAG + tables + business context.

Обязательно:
- показать, что это не generic chatbot и не поиск по PDF;
- начать демо с боли R&D-данных;
- использовать запрос про никелевую руду как главный demo story;
- показать 5 потоков: Raw RAG, Summary RAG, Tables, Knowledge Graph, Comparison Mode;
- завершить business layer: production, risks, import substitution, reagent substitution;
- предложить только frontend-доработки, которые помогают демо и проверке решения;
- не обещать локальный MetalGPT, Sci-Hub/paywall flow или неподтвержденные production data.

Выдать:
- positioning;
- presentation structure;
- 90-second video script;
- frontend demo polish requirements;
- publication-backed use cases with evidence anchors.
```

## 9. Local facts used

Inspected:

- `C:\Users\user\Downloads\oreacle_metallurgy_models_sources_features.md`;
- `tasks/*`;
- `app/ui/demo_app.py`;
- `app/query/cockpit.py`;
- `data/processed/publications/*`;
- `data/index/knowledge_graph_manifest.json`;
- `data/indexes/chunks/manifest.json`.

Relevant local status:

- publication records: 1,862;
- document summaries: 1,862;
- procedure summaries: 879;
- evidence spans: 21,328;
- raw chunks index: 89,703 chunks;
- knowledge graph: 42,782 nodes and 105,628 edges;
- lexical RAG works offline;
- dense/hybrid Yandex query embeddings are currently blocked by `403 Permission denied`;
- summary JSONL files exist, but summary vector index manifests were not present during this analysis.

Commands used for evidence checks:

```powershell
.\.venv\Scripts\python.exe scripts\search_cli.py "nickel ore flotation recovery" --mode lexical --top-k 5 --json
.\.venv\Scripts\python.exe scripts\search_cli.py "autoclave leaching nickel cobalt sulfide concentrate" --mode lexical --top-k 5 --json
.\.venv\Scripts\python.exe scripts\search_cli.py "gas cleaning sulfur dioxide SO2 metallurgy" --mode lexical --top-k 5 --json
.\.venv\Scripts\python.exe scripts\search_cli.py "reagent substitution flotation collector depressant nickel" --mode lexical --top-k 5 --json
.\.venv\Scripts\python.exe scripts\search_cli.py "technogenic gypsum phosphogypsum metallurgical waste" --mode lexical --top-k 5 --json
.\.venv\Scripts\python.exe scripts\run_csv_query.py "nickel composition grade recovery Ni Cu Co" --top-k 5 --top-rows 3 --max-rows-per-table 20
.\.venv\Scripts\python.exe scripts\search_graph.py "никелевая руда" --top-k 8 --paths
.\.venv\Scripts\python.exe scripts\plan_query.py "никелевая руда: какие методы переработки, условия, эффекты и источники?" --json
```
