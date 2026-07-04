# RouterAI: как использовать в решении

## Что это дает

RouterAI можно использовать как разрешенный API-слой для LLM/embeddings/rerank, если команда подтвердит, что выбранная модель и провайдер соответствуют правилам хакатона. Для финального решения все равно нужен локальный fallback, потому что организаторы ценят экономию ресурсов и могут ограничить внешние вызовы.

Официальная документация говорит:

- единый API для разных AI-моделей;
- совместимость с OpenAI SDK;
- API base URL: `https://routerai.ru/api/v1`;
- chat endpoint: `https://routerai.ru/api/v1/chat/completions`;
- API-ключ передается как `Authorization: Bearer YOUR_API_KEY`;
- можно указать `provider.country: "ru"` и `allow_fallbacks: false`;
- PDF можно отправлять в `/api/v1/chat/completions` как URL или base64 через content type `file`;
- для PDF parser есть engines: `cloudflare-ai`, `mistral-ocr`, `native`.

## Обязательная настройка для хакатона

В `.env` или переменных окружения:

```powershell
$env:ROUTERAI_API_KEY = "<ключ из личного кабинета RouterAI>"
$env:ROUTERAI_BASE_URL = "https://routerai.ru/api/v1"
```

Для запросов, где важна обработка на территории РФ:

```json
"provider": {
  "country": "ru",
  "allow_fallbacks": false
}
```

Это снижает риск, что RouterAI сделает fallback к нежелательному провайдеру. Но это не заменяет юридическую проверку лицензии и доступности конкретной модели.

## Минимальный chat completion

```python
import os
from openai import OpenAI

client = OpenAI(
    api_key=os.environ["ROUTERAI_API_KEY"],
    base_url=os.getenv("ROUTERAI_BASE_URL", "https://routerai.ru/api/v1"),
)

resp = client.chat.completions.create(
    model="deepseek/deepseek-chat-v3.1",
    messages=[
        {"role": "system", "content": "Отвечай строго по источникам."},
        {"role": "user", "content": "Кратко объясни, что такое GraphRAG."},
    ],
    temperature=0,
    extra_body={"provider": {"country": "ru", "allow_fallbacks": False}},
)

print(resp.choices[0].message.content)
```

## JSON extraction

Для извлечения метаданных лучше использовать низкую температуру и JSON mode/structured outputs. После ответа обязательно валидировать JSON локальной схемой.

```python
schema_prompt = """
Извлеки эксперименты из текста. Верни только JSON:
{
  "experiments": [
    {
      "material": {"raw_name": "...", "composition": []},
      "processing": [],
      "measurements": [],
      "claims": []
    }
  ]
}
"""

resp = client.chat.completions.create(
    model="deepseek/deepseek-chat-v3.1",
    messages=[
        {"role": "system", "content": "Ты extractor научных фактов. Не добавляй факты без evidence."},
        {"role": "user", "content": schema_prompt + "\n\nTEXT:\n" + chunk_text},
    ],
    temperature=0,
    response_format={"type": "json_object"},
    extra_body={"provider": {"country": "ru", "allow_fallbacks": False}},
)
```

## Embeddings

Публичный `/api/v1/models` показывает embedding-модели, полезные для проекта:

| Model id | Назначение | Context |
|---|---|---:|
| `baai/bge-m3` | мультиязычные embeddings, хороший кандидат для RU/EN корпуса | 8192 |
| `intfloat/multilingual-e5-large` | мультиязычный semantic search | 8192 |
| `qwen/qwen3-embedding-4b` | крупнее, длиннее контекст | 32768 |
| `qwen/qwen3-embedding-8b` | крупнее, дороже/тяжелее | 32000 |

Пример:

```python
emb = client.embeddings.create(
    model="baai/bge-m3",
    input=["сплав Ni-Cr после отжига 900 C", "annealing improves hardness"],
)
vectors = [item.embedding for item in emb.data]
```

## Rerank

Каталог моделей RouterAI также показывает rerank-модели `cohere/rerank-*`. Если endpoint rerank доступен в аккаунте, их можно использовать после BM25+dense retrieval. Если нет, fallback: локальный cross-encoder или простая формула `dense_score + lexical_overlap + graph_score`.

## PDF через RouterAI

RouterAI позволяет отправлять PDF прямо в chat completions. Это удобно для быстрых smoke tests, но для production/MVP лучше сохранять локальный parsing pipeline и использовать RouterAI как fallback для плохих PDF.

Рекомендуемая политика:

- текстовый PDF: локально `pypdf`/PyMuPDF, затем extraction;
- сканированный PDF: RouterAI `file-parser` с `mistral-ocr` или локальный OCR, если доступен;
- приватные документы: отправлять base64 только если правила хакатона разрешают внешний API;
- все извлеченные факты сохранять с evidence spans.

Пример конфигурации plugin из документации:

```json
{
  "plugins": [
    {
      "id": "file-parser",
      "pdf": {
        "engine": "cloudflare-ai"
      }
    }
  ]
}
```

## Рекомендуемые роли RouterAI в проекте

| Задача | Использовать RouterAI? | Модель/тип |
|---|---|---|
| Быстрый extractor JSON | Да, если разрешено | Qwen/DeepSeek с `temperature=0` |
| Procedure summaries | Да | компактная instruct-модель |
| Финальный ответ | Опционально | Qwen/DeepSeek, строгий evidence prompt |
| Embeddings | Можно | `baai/bge-m3` или `multilingual-e5-large` |
| Rerank | Можно | `cohere/rerank-4-fast`, если endpoint доступен |
| Постоянный ingestion всего корпуса | Осторожно | лучше локально из-за стоимости/скорости |

## Риски

- Модель может быть доступна через RouterAI, но не подходить под ограничения хакатона по лицензии/географии.
- Fallback provider может нарушить ожидания, если не указать `allow_fallbacks: false`.
- PDF/upload внутренних документов через внешний API может быть запрещен правилами данных.
- JSON mode не гарантирует истинность фактов; нужна проверка evidence span.
- Стоимость и latency нужно логировать как отдельные benchmark metrics.

## DeepSeek Chat V3.1

Runtime fallback uses `deepseek/deepseek-chat-v3.1` because it returned non-empty chat content in the RouterAI smoke check:

- output modality: text;
- context length: 1,048,576;
- подходит для extraction, procedure summaries и финального ответа по evidence pack;
- не является embedding-моделью, поэтому для векторного индекса лучше использовать `baai/bge-m3`, `intfloat/multilingual-e5-large` или `qwen/qwen3-embedding-*`.
