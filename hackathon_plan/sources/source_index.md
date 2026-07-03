# Source Index

## Локальные материалы

1. `Литература/Repositories.docx`
   - Содержит ссылку на репозиторий NirDiamant/RAG_Techniques.
2. `Литература/Material Science/rag_materials_science_report.md`
   - Уже собранный обзор работ по RAG, GraphRAG, Knowledge Graph и materials science.
3. `Литература/Material Science/2604.11229v1.pdf`
   - RECIPER: A Dual-View Retrieval Pipeline for Procedure-Oriented Materials Question Answering.
   - Вывод для проекта: procedural summaries полезны как дополнительный retrieval-view, но не должны заменять обычные paragraph chunks.

## Ключевые внешние источники

- Сайт хакатона: https://nornickel-ai-hackathon.ru/
- Habr-обзор RAG: https://habr.com/ru/articles/871226/
- NirDiamant/RAG_Techniques: https://github.com/NirDiamant/RAG_Techniques
  - Важно: репозиторий указывает custom non-commercial license. Использовать как учебный референс; код копировать в сдаваемое решение только после проверки лицензии.
- GraphRAG notebook: https://colab.research.google.com/github/NirDiamant/RAG_Techniques/blob/main/all_rag_techniques/graph_rag.ipynb
- RECIPER paper: https://arxiv.org/abs/2604.11229v1
- RECIPER code/data: https://github.com/ReaganWu/RECIPER
- From Local to Global: A Graph RAG Approach to Query-Focused Summarization: https://arxiv.org/abs/2404.16130
- LightRAG: Simple and Fast Retrieval-Augmented Generation: https://arxiv.org/abs/2410.05779
- RAPTOR: Recursive Abstractive Processing for Tree-Organized Retrieval: https://arxiv.org/abs/2401.18059
- Self-RAG: Learning to Retrieve, Generate, and Critique through Self-Reflection: https://arxiv.org/abs/2310.11511
- RAGAS: Automated Evaluation of Retrieval Augmented Generation: https://arxiv.org/abs/2309.15217
- ARES: An Automated Evaluation Framework for Retrieval-Augmented Generation Systems: https://arxiv.org/abs/2311.09476
- LLaMP: Large Language Model Made Powerful for High-fidelity Materials Knowledge Retrieval and Distillation: https://arxiv.org/abs/2401.17244
- ChatExtract: Extracting Accurate Materials Data from Research Papers with Conversational Language Models and Prompt Engineering: https://arxiv.org/abs/2303.05352
- MatSciBERT: A Materials Domain Language Model for Text Mining and Information Extraction: https://arxiv.org/abs/2109.15290
- MatSci-NLP: https://arxiv.org/abs/2305.08264
- MatKG: https://arxiv.org/abs/2210.17340
- MatKB: https://arxiv.org/abs/2302.05597

## RouterAI

- RouterAI docs overview: https://routerai.ru/docs/guides
  - Base URL: `https://routerai.ru/api/v1`
  - Chat endpoint: `https://routerai.ru/api/v1/chat/completions`
  - OpenAI SDK compatible API.
- Authentication: https://routerai.ru/docs/guides/overview/authentication
  - API key is passed as `Authorization: Bearer YOUR_API_KEY`.
- Provider selection: https://routerai.ru/docs/guides/overview/provider-selection
  - For geopolitical/provider control use `provider.country`, `provider.only`, `provider.ignore`, `provider.allow_fallbacks`.
  - For hackathon use prefer `provider: {"country": "ru", "allow_fallbacks": false}` when API calls are allowed.
- Parameters: https://routerai.ru/docs/guides/overview/parameters
  - Useful for extraction: `temperature`, `top_p`, `top_k`, `response_format`, `structured_outputs`, `tools`.
- PDF documents: https://routerai.ru/docs/guides/overview/multimodal/pdfs
  - PDF can be sent to chat completions as URL or base64 `file` content.
  - File parser engines include `cloudflare-ai`, `mistral-ocr`, `native`.
- Public models API checked: https://routerai.ru/api/v1/models
  - Visible candidates for this project include `baai/bge-m3`, `intfloat/multilingual-e5-large`, `qwen/qwen3-embedding-4b`, `qwen/qwen3-embedding-8b`, `qwen/qwen3-30b-a3b-instruct-2507`, `qwen/qwen3-14b`, `deepseek/deepseek-chat-v3.1`, `cohere/rerank-4-fast`.

## Actual Task 2

- Official detailed task page: https://nornickel-ai-hackathon.ru/task-2
  - Новые требования: 3-5 секунд на сложные запросы при масштабе до 1 млн сущностей, числовые диапазоны, география, версии фактов, RBAC/аудит, экспорт.
- Dataset link from task page: https://disk.yandex.ru/d/npigiuw4Rbe9Pg
  - Проверено через публичный API Яндекс.Диска.
  - Структура: `Источники информации` -> `Доклады`, `Журналы`, `Материалы конференций`, `Обзоры`, `Статьи`.
  - Инвентаризация: 1453 файла, примерно 4.98 GB; 1163 PDF, 115 DOCX, 79 ZIP, 46 XLS, 18 DOC, 16 RAR, 5 PPTX, 3 DOCM, 3 XLSX.

## Проверенные тезисы из локального PDF RECIPER

- Индексируются две проекции документа: paragraph-view и recipe/procedure-view.
- Procedure summaries генерируются LLM и описывают материалы, операции и условия.
- В публичном `rag_database.json` procedure-view хранится как `recipes[]` с
  полями `material_name`, `synthesis_method`, `steps[].description`,
  `steps[].parameters`, `key_points`, `entities`.
- Retrieval code строит recipe text из `Material: ...`, `Method: ...`,
  descriptions of steps и `Key points: ...`.
- Recipe-only retrieval слабее paragraph retrieval, но объединение двух потоков улучшает ранние метрики.
- На BGE-large-en-v1.5 RECIPER достиг Recall@1 86.82%, Recall@5 97.07%, Recall@10 97.85%.
- В среднем по четырем dense backbones прирост к paragraph-only: +3.73 Recall@1, +2.85 nDCG@10, +3.13 MRR.
