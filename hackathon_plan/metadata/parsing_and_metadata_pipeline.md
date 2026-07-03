# Парсинг и сбор метаданных

## Что нужно извлекать

Для кейса "Научный клубок" недостаточно сохранить текстовые чанки. Нужно извлечь структуру экспериментов:

- документ: название, тип, источник, дата, автор/команда, теги;
- материал: название, нормализованное название, состав, класс материала;
- режим: операция, температура, время, давление, атмосфера, скорость нагрева/охлаждения;
- оборудование: установка, модель, лаборатория, параметры;
- свойство: название, метод измерения, значение, единица, направление изменения;
- вывод: claim/conclusion, уверенность, поддерживающий фрагмент;
- пробел: что не измерено, где нет режима, где нет контрольного сравнения.

## Пайплайн ingestion

| Шаг | Вход | Выход | Проверка |
|---|---|---|---|
| File registry | DOCX/PDF/HTML/XLSX/CSV | `documents` | hash, размер, тип, дата |
| Raw parsing | файл/URL | сырой текст + таблицы | не пустой текст, число страниц |
| Section detection | сырой текст | секции: abstract, methods, results | заголовки и offsets |
| Chunking | секции | `chunks` | chunk_id, overlap, page/section |
| Table extraction | таблицы | `tables`, `table_cells` | строки/колонки, caption |
| Procedure detection | chunks/tables | candidate procedure spans | наличие операций/температур/времени |
| LLM/regex extraction | spans | JSON facts | JSON schema validation |
| Normalization | JSON facts | normalized entities | единицы, синонимы, справочники |
| Graph build | entities/relations | nodes/edges | every edge has evidence |
| Index build | chunks/procedures/entities | BM25 + vector + graph index | top-k smoke tests |

## Хранилища

Минимально достаточно SQLite или DuckDB. Граф можно хранить как таблицы `nodes`/`edges`, а визуализировать через NetworkX/PyVis.

```sql
documents(doc_id, source_path, source_url, title, doc_type, hash, created_at)
chunks(chunk_id, doc_id, section, page, text, token_count, char_start, char_end)
tables(table_id, doc_id, page, caption, html_or_json)
entities(entity_id, entity_type, name, normalized_name, attrs_json)
experiments(experiment_id, doc_id, material_id, procedure_summary, attrs_json)
measurements(measurement_id, experiment_id, property_id, value, unit, direction, method, evidence_chunk_id)
relations(src_entity_id, relation_type, dst_entity_id, experiment_id, evidence_chunk_id, confidence)
procedure_summaries(summary_id, doc_id, experiment_id, text, extraction_model, confidence)
feedback_log(feedback_id, query, answer_id, rating, comment, created_at)
```

## JSON-схема extraction

Extractor должен возвращать только валидный JSON. Для RouterAI/LLM-вызова лучше использовать `response_format` / `structured_outputs`, а после ответа валидировать Pydantic-схемой.

```json
{
  "document_id": "string",
  "experiments": [
    {
      "material": {
        "raw_name": "string",
        "normalized_name": "string|null",
        "composition": [{"element": "Ni", "amount": 72.0, "unit": "wt%"}]
      },
      "processing": [
        {
          "operation": "annealing",
          "temperature": {"value": 900, "unit": "C"},
          "time": {"value": 2, "unit": "h"},
          "atmosphere": "argon|null",
          "equipment": "furnace|null"
        }
      ],
      "measurements": [
        {
          "property": "hardness",
          "value": 320,
          "unit": "HV",
          "direction": "increase|decrease|no_change|unknown",
          "method": "Vickers|null"
        }
      ],
      "claims": [
        {
          "text": "string",
          "evidence_quote": "short exact fragment",
          "evidence_chunk_id": "string",
          "confidence": 0.0
        }
      ]
    }
  ]
}
```

## Правила нормализации

- Температуру хранить в Celsius и Kelvin, исходную запись сохранять в `attrs_json`.
- Время хранить в секундах и человекочитаемой единице.
- Состав хранить отдельно для atomic %, wt %, mol %, если неясно - `unit_unknown`.
- Свойства маппить в справочник: hardness, yield_strength, tensile_strength, elongation, corrosion_rate, conductivity.
- Марки сплавов не схлопывать только по похожести строки: нужна таблица алиасов.
- Любой факт без evidence span не добавлять в graph как надежный; можно хранить как `candidate_fact`.

## Извлечение процедур

Procedure view нужен отдельно от обычных чанков. Для каждого документа/секции:

1. Найти candidate spans по словам: prepared, synthesized, annealed, aged, quenched, rolled, heated, cooled, выдержка, отжиг, закалка, прокатка.
2. Добавить соседние таблицы и подписи к рисункам.
3. Сжать в procedure summary: material -> operations -> conditions -> measurement -> effect.
4. Индексировать summary как отдельный retrieval stream.
5. При ответе всегда подтягивать исходные chunks, чтобы summary не стало единственным доказательством.

## Контроль качества

| Ошибка | Как ловить |
|---|---|
| LLM придумала значение | проверка evidence_quote есть в chunk |
| Перепутаны единицы | unit parser + диапазоны допустимых значений |
| Смешаны два эксперимента | experiment_id строить вокруг одного procedure span |
| Дубли материалов | alias table + fuzzy match только как candidate |
| Граф без источников | запрет edge без `evidence_chunk_id` |
| PDF плохо распарсен | fallback OCR / RouterAI file-parser / ручной smoke check |
