# 09. Inference Provider Fallback

Date: 2026-07-04

## Goal

Inference should be Yandex-first, with RouterAI as a controlled fallback.

Default:

1. use Yandex AI Studio for answer synthesis when `YANDEX_API_KEY` and
   `YANDEX_FOLDER_ID` work;
2. on Yandex `403`, timeout, or model-access failure, fall back to RouterAI
   `deepseek/deepseek-chat-v3.1`;
3. keep deterministic local answer drafts when both remote providers are
   unavailable.

This is for generation/inference only. Embedding primary path is tracked in
`tasks/08_yandex_summary_vectorization/`.

## Development Zone

Can change:

- `app/llm/*`
- `scripts/run_llm_query.py`
- `scripts/test_yandex_llm.py`
- optional `scripts/test_routerai_llm.py`
- `.env.example`
- `tasks/09_inference_provider_fallback/*`

Read-only or coordinate first:

- `app/index/*` except shared provider config decisions
- `app/extract/*`
- `app/graph/*`
- `data/*`

## Required Behavior

Provider router:

```text
Yandex AI Studio
  -> if success: use response
  -> if permission/rate/timeout/model error: record warning, try RouterAI
RouterAI
  -> if success: use response and mark provider=routerai
  -> if failure: return deterministic local brief
```

Output metadata must include:

- selected provider;
- model name;
- fallback reason, if any;
- whether answer used retrieved evidence;
- no API keys or secret fragments.

## Environment Variables

Already present in `.env.example`:

```text
YANDEX_API_KEY=...
YANDEX_FOLDER_ID=...
YANDEX_MODEL=yandexgpt/latest
YANDEX_BASE_URL=https://ai.api.cloud.yandex.net/v1

ROUTERAI_API_KEY=...
ROUTERAI_BASE_URL=https://routerai.ru/api/v1
ROUTERAI_CHAT_MODEL=deepseek/deepseek-chat-v3.1
```

## Acceptance Criteria

- Yandex remains the default provider.
- RouterAI is used only after explicit Yandex failure.
- CLI and GUI show provider/fallback status.
- deterministic fallback still works without network.
- no direct OpenAI/Anthropic API dependency is added.

## Cost Policy

Use LLM calls only after retrieval has produced a compact evidence pack.
Do not send full raw corpus, full CSV files, or full `chunks.jsonl` to a
generative model.

## Implementation Notes

Status: implemented in `app/llm/*` and wired into the CLI smoke scripts.

Key files:

- `app/llm/types.py` - shared `LLMResponse`, provider metadata, safe errors;
- `app/llm/yandex_client.py` - Yandex OpenAI-compatible REST client via
  `requests`, no OpenAI SDK call path;
- `app/llm/routerai_client.py` - RouterAI chat-completions REST client;
- `app/llm/provider_router.py` - Yandex-first routing, controlled RouterAI
  fallback, deterministic local brief when remote providers are unavailable;
- `scripts/run_llm_query.py` - prints and emits provider metadata;
- `scripts/test_yandex_llm.py` - Yandex-first smoke through router;
- `scripts/test_routerai_llm.py` - optional direct RouterAI smoke;
- `tests/test_llm_provider_router.py` - no-network fallback tests.

CLI JSON now includes:

```json
{
  "llm": {
    "provider": "yandex|routerai|local",
    "model": "model-name",
    "status": "primary|fallback|local",
    "fallback_reason": "permission_denied|timeout|model_error|null",
    "used_evidence": true,
    "warnings": []
  }
}
```

Plain text mode prints a `LLM provider:` status block after the answer.

## Usage

Yandex-first RAG/direct CLI:

```powershell
.\.venv\Scripts\python.exe scripts\run_llm_query.py --no-corpus --question "Ответь коротко: API работает?"
```

Yandex-first smoke with RouterAI/local fallback:

```powershell
.\.venv\Scripts\python.exe scripts\test_yandex_llm.py
```

Optional RouterAI-only smoke:

```powershell
.\.venv\Scripts\python.exe scripts\test_routerai_llm.py
```

## Security Notes

- Secrets are read only from environment variables / local `.env`.
- API keys are not included in provider metadata or warnings.
- Provider errors are compacted before surfacing to CLI/JSON output.
- The router does not add direct OpenAI or Anthropic API usage.
- RouterAI is called only after a Yandex failure classified as fallback-safe:
  permission/auth error, timeout/network error, rate/transient error, or
  model-access/model-name error.
