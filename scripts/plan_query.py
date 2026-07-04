from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.query.planner import plan_query


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Plan an R&D RAG query before retrieval.")
    parser.add_argument("query_parts", nargs="*", help="Query text. Alternative: --query.")
    parser.add_argument("--query", help="Query text.")
    parser.add_argument("--json", action="store_true", help="Print machine-readable JSON.")
    return parser.parse_args()


def resolve_query(args: argparse.Namespace) -> str:
    query = args.query or " ".join(args.query_parts)
    query = query.strip()
    if not query:
        raise SystemExit("Query is required. Pass it as an argument or with --query.")
    return query


def main() -> int:
    plan = plan_query(resolve_query(parse_args()))
    print(json.dumps(plan.model_dump(mode="json"), ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
