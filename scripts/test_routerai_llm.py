from __future__ import annotations

import sys
from pathlib import Path

from dotenv import load_dotenv

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
for stream in (sys.stdout, sys.stderr):
    if hasattr(stream, "reconfigure"):
        stream.reconfigure(encoding="utf-8", errors="replace")

from app.llm.routerai_client import RouterAILLMClient, RouterAILLMConfig


def main() -> None:
    root = Path(__file__).resolve().parents[1]
    load_dotenv(root / ".env")
    client = RouterAILLMClient(RouterAILLMConfig.from_env(load_dotenv_file=False))
    response = client.generate(
        [{"role": "user", "content": "Ответь ровно одним словом: ГОТОВО"}],
        max_tokens=300,
        temperature=0.2,
    )
    print(response.text)
    print(
        "provider_status="
        f"provider={response.provider}; "
        f"model={response.model}; "
        f"status={response.status}; "
        f"used_evidence={str(response.used_evidence).lower()}"
    )


if __name__ == "__main__":
    main()
