from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.llm.yandex_client import YandexLLMClient


def main() -> None:
    client = YandexLLMClient()
    answer = client.ask(
        "Ответь коротко: API работает?",
        max_tokens=100,
        temperature=0.2,
    )
    print(answer)


if __name__ == "__main__":
    main()
