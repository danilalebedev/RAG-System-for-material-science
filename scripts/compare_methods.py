from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.query.comparison import compare_methods  # noqa: E402


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run deterministic Comparison Mode for R&D RAG.")
    parser.add_argument("query", help="Comparison query, for example: compare battery recycling methods.")
    parser.add_argument("--top-k", type=int, default=5, help="Maximum rows/results to keep in the comparison table.")
    parser.add_argument("--include-web", action="store_true", help="Enable web route when the query plan supports it.")
    parser.add_argument("--json", action="store_true", help="Print full structured JSON.")
    return parser.parse_args()


def _text(value: Any) -> str:
    if isinstance(value, (list, dict)):
        return json.dumps(value, ensure_ascii=False, default=str)
    return str(value or "")


def print_markdown(payload: dict[str, Any]) -> None:
    print("# Comparison Mode")
    print()
    print(payload["answer_summary"])
    print()
    print("## Query Plan")
    plan = payload.get("plan") or {}
    print(f"- intent: {plan.get('intent')}")
    print(f"- routes: {', '.join(plan.get('routes') or [])}")
    print(f"- answer_format: {plan.get('answer_format')}")
    print()
    print("## Comparison Table")
    rows = payload.get("rows") or []
    if not rows:
        print("No comparison rows were produced.")
    for index, row in enumerate(rows, start=1):
        print(f"{index}. {row.get('item')}")
        print(f"   description: {_text(row.get('description'))}")
        print(f"   materials: {_text(row.get('materials'))}")
        print(f"   processes: {_text(row.get('processes'))}")
        print(f"   numeric_values: {_text(row.get('numeric_values'))}")
        print(f"   evidence: {_text([item.get('citation') for item in row.get('evidence') or []])}")
    print()
    print("## Missing Evidence / Fallbacks")
    missing = payload.get("missing_evidence") or []
    if not missing:
        print("No missing evidence detected.")
    for item in missing:
        print(f"- {item.get('route')}: {item.get('reason')}")


def main() -> int:
    args = parse_args()
    result = compare_methods(args.query, include_web=args.include_web, top_k=args.top_k)
    payload = result.as_dict()
    if args.json:
        print(json.dumps(payload, ensure_ascii=False, indent=2, default=str))
    else:
        print_markdown(payload)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
