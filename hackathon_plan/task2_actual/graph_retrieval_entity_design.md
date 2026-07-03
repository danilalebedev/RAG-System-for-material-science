# Graph, Metadata Extraction and Vector Retrieval Design

## 1. Каноническая предметная модель

Для MVP и защиты берем ровно типы из условия как **канонические узлы графа**:

- `Material`
- `Process`
- `Equipment`
- `Property`
- `Experiment`
- `Publication`
- `Expert`
- `Facility`

Канонические отношения из условия:

- `uses_material`
- `operates_at_condition`
- `produces_output`
- `described_in`
- `validated_by`
- `contradicts`

Расширенные сущности из раннего плана (`Location`, `Measurement`, `Claim`, `Version`, `KPI`, `Chunk`) не нужно делать отдельными graph node в MVP. Они полезны, но лучше хранить их как:

- атрибуты узлов/ребер;
- typed metadata tables;
- provenance tables;
- helper objects внутри JSON extraction.

Так граф остается совместимым с условием и проще объясняется жюри.

## 2. Как выглядит extraction JSON

LLM/extractor должен возвращать именно эти сущности и отношения, плюс информацию об источнике.

```json
{
  "source": {
    "publication_id": "pub_001",
    "title": "string",
    "file_path": "string",
    "page": 12,
    "chunk_id": "chunk_001",
    "source_type": "article|report|conference|journal|review|presentation",
    "evidence_text": "short exact quote"
  },
  "entities": {
    "materials": [
      {
        "id": "mat_001",
        "name": "Ni-Cu concentrate",
        "aliases": ["nickel-copper concentrate"],
        "composition": [{"component": "Ni", "value": 12.5, "unit": "wt%"}]
      }
    ],
    "processes": [
      {
        "id": "proc_001",
        "name": "flotation",
        "conditions": [
          {"name": "pH", "value": 9.5, "unit": ""},
          {"name": "temperature", "value": 25, "unit": "C"}
        ],
        "parameters_text": "pH 9.5 at 25 C"
      }
    ],
    "equipment": [
      {"id": "eq_001", "name": "flotation cell", "type": "lab equipment"}
    ],
    "properties": [
      {"id": "prop_001", "name": "recovery", "value": 92.0, "unit": "%", "direction": "increase"}
    ],
    "experiments": [
      {
        "id": "exp_001",
        "name": "flotation test",
        "date": null,
        "version": "source_date_or_doc_version",
        "confidence": 0.78
      }
    ],
    "publications": [
      {"id": "pub_001", "title": "string", "year": 2024}
    ],
    "experts": [
      {"id": "expert_001", "name": "Иванов И.И.", "role": "author"}
    ],
    "facilities": [
      {"id": "fac_001", "name": "Норильская обогатительная фабрика", "location": "Норильск"}
    ]
  },
  "relations": [
    {
      "source_id": "exp_001",
      "type": "uses_material",
      "target_id": "mat_001",
      "confidence": 0.86,
      "evidence_text": "short exact quote"
    },
    {
      "source_id": "exp_001",
      "type": "operates_at_condition",
      "target_id": "proc_001",
      "condition": {"name": "pH", "value": 9.5, "unit": ""},
      "confidence": 0.82,
      "evidence_text": "short exact quote"
    },
    {
      "source_id": "exp_001",
      "type": "produces_output",
      "target_id": "prop_001",
      "confidence": 0.8,
      "evidence_text": "short exact quote"
    },
    {
      "source_id": "exp_001",
      "type": "described_in",
      "target_id": "pub_001",
      "confidence": 1.0,
      "evidence_text": "source metadata"
    }
  ]
}
```

## 3. Где хранить метаданные

Нужно различать **graph ontology** и **search metadata**.

Графовые узлы: только 8 типов из условия.

Typed metadata tables:

- `entity_aliases(entity_id, alias, language, source)`
- `numeric_conditions(relation_id, parameter, value_min, value_max, unit, raw_text)`
- `source_spans(source_span_id, doc_id, chunk_id, page, char_start, char_end, text)`
- `entity_mentions(entity_id, chunk_id, mention_text, confidence)`
- `versions(entity_id_or_relation_id, source_date, extracted_at, extraction_model, version_label)`
- `locations(entity_id, raw_location, normalized_location, country, region, coordinates_optional)`

Так мы сохраняем числовой и географический поиск, но не раздуваем граф.

## 4. Как векторизуем чанки

### Что векторизуем

Создаем несколько embedding spaces, но физически это могут быть отдельные FAISS/Qdrant collections:

1. `chunk_text_vectors`
   - обычные текстовые чанки 600-1000 tokens;
   - нужны для semantic search по документам.

2. `entity_context_vectors`
   - краткий текст на сущность: `type + name + aliases + source snippets`;
   - нужен для entity linking и поиска сущностей по запросу.

3. `procedure_summary_vectors`
   - RECIPER-style summaries для процессов/экспериментов;
   - нужен для вопросов про режимы, условия, эффект.

4. `publication_title_abstract_vectors`
   - заголовки, аннотации, оглавления;
   - нужен для быстрой навигации по источникам.

### Модель embeddings

Практичный выбор:

- локально: `BAAI/bge-m3` или `intfloat/multilingual-e5-large`;
- через RouterAI: `baai/bge-m3` или `intfloat/multilingual-e5-large`.

Почему не DeepSeek для embeddings: `deepseek/deepseek-v4-pro` — chat/text generation model, ее стоит использовать для extraction/answer, а не для массового embedding index. Для embeddings нужна специализированная embedding-модель.

### Алгоритм поиска похожих векторов

Offline:

1. Parse document.
2. Split into chunks.
3. Normalize text.
4. Compute embedding vector for each chunk.
5. Store vector in FAISS/Qdrant with payload:
   - `chunk_id`
   - `doc_id`
   - `page`
   - `source_type`
   - detected entity ids
   - numeric ranges
   - language

Online:

1. Query parser выделяет slots: entity names, numeric constraints, source type, task intent.
2. Query text превращается в embedding той же embedding-моделью.
3. ANN search ищет top-k nearest neighbors:
   - cosine similarity или inner product после normalization;
   - FAISS HNSW/IVF или Qdrant HNSW.
4. Кандидаты фильтруются metadata filters:
   - source type;
   - numeric ranges;
   - entity ids;
   - date/version.
5. Потом объединяются с BM25 и graph candidates.

Формула финального rerank score:

```text
score =
  0.40 * vector_similarity +
  0.25 * bm25_score +
  0.20 * typed_constraint_match +
  0.10 * graph_proximity +
  0.05 * source_reliability
```

Вес можно быстро подобрать на 20-50 контрольных вопросах.

## 5. Будет ли отдельное metadata vector space

Да, но не вместо графа.

`entity_context_vectors` нужен для задач:

- пользователь пишет "Норильская фабрика", а в документах "НОФ";
- пользователь пишет "извлечение меди", а в документах "Cu recovery";
- нужно найти похожие материалы/процессы по описанию.

Но числовые условия нельзя искать только в embedding space. Температура `900-1100 C`, pH, давление, концентрация должны идти через typed metadata filter.

Итог:

- semantic similarity -> vector index;
- точные названия/числа -> BM25 + typed metadata;
- связи и цепочки -> graph;
- финальный ответ -> evidence-grounded LLM.

## 6. Как строим граф

### Шаг 1. Extract mentions

Для каждого chunk/table/slide:

- rule-based detector находит кандидатов материалов, процессов, свойств, чисел, оборудования;
- LLM extractor возвращает JSON по официальной онтологии;
- каждая сущность и связь получает `evidence_text` и `source_span`.

### Шаг 2. Entity resolution

Сущности схлопываются по правилам:

1. exact normalized name;
2. alias table;
3. fuzzy match только как candidate;
4. embedding similarity по `entity_context_vectors`;
5. ручное подтверждение для спорных сущностей.

### Шаг 3. Build canonical nodes

Создаем/обновляем узлы:

```text
(:Material {id, name, aliases, attrs})
(:Process {id, name, attrs})
(:Equipment {id, name, attrs})
(:Property {id, name, value, unit, attrs})
(:Experiment {id, name, date, confidence, attrs})
(:Publication {id, title, year, source_path})
(:Expert {id, name, role})
(:Facility {id, name, location})
```

### Шаг 4. Build official edges

```text
(Experiment)-[:uses_material]->(Material)
(Experiment)-[:operates_at_condition {parameter, value, unit}]->(Process)
(Experiment)-[:produces_output]->(Property)
(Experiment)-[:described_in]->(Publication)
(Experiment)-[:validated_by]->(Expert)
(Experiment)-[:validated_by]->(Facility)
(Publication)-[:contradicts]->(Publication)
(Experiment)-[:contradicts]->(Experiment)
```

`contradicts` строится не сразу LLM-ом по всему корпусу, а осторожно:

1. одинаковый Material/Process/Property;
2. разные outputs/effects;
3. похожие условия;
4. LLM или rule-based verifier проверяет evidence пары.

### Шаг 5. Graph retrieval

Когда пользователь задает вопрос:

1. Link query to entities через aliases + entity vectors.
2. Найти стартовые nodes.
3. Выполнить traversal 1-2 hops:
   - Material -> Experiment -> Process/Property/Publication;
   - Process -> Experiment -> Material/Property;
   - Property -> Experiment -> Material/Process.
4. Получить связанные source spans.
5. Передать в reranker вместе с vector/BM25 candidates.

## 7. Почему это лучше раздутой модели

Официальная онтология проще:

- легче защищать перед жюри;
- проще валидировать extraction JSON;
- меньше шума в графе;
- быстрее graph queries;
- легче сделать UI-фильтры;
- проще экспортировать в GraphML/JSON.

Расширенные вещи не теряются: они уходят в атрибуты и typed metadata, где им и место.
