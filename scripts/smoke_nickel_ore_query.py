from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

from app.query.local_orchestrator import default_config, run_local_knowledge  # noqa: E402
from app.query.planner import plan_query  # noqa: E402


QUERY = "никелевая руда"


def text_has_nickel(value: Any) -> bool:
    text = json.dumps(value, ensure_ascii=False, default=str).casefold()
    return any(term in text for term in ("nickel", " ni", "ni/", "никел"))


def text_has_gold_without_nickel(value: Any) -> bool:
    text = json.dumps(value, ensure_ascii=False, default=str).casefold()
    gold = any(term in text for term in ("gold", " au", "au/", "золот"))
    return gold and not text_has_nickel(value)


def assert_true(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def main() -> int:
    plan = plan_query(QUERY)
    assert_true("никелевая руда" in plan.entities.materials, "material phrase was not extracted")
    assert_true({"raw_rag", "table_search", "graph_search"}.issubset(set(plan.routes)), "forced material routes are missing")
    actual_queries = " ".join([*plan.internal_search_queries, *plan.web_search_queries])
    assert_true("Материал:" not in actual_queries, "service slot label leaked into search query")
    assert_true("nickel ore" in actual_queries and "никелевая руда" in actual_queries, "nickel ore aliases are missing")

    config = default_config(ROOT)
    bundle = run_local_knowledge(QUERY, config=config)
    if bundle.raw_chunks:
        assert_true(text_has_nickel(bundle.raw_chunks[0].text), "top raw hit does not mention nickel/Ni")
    if bundle.table_hits:
        assert_true(text_has_nickel(bundle.table_hits[0].as_dict()), "top table hit does not mention nickel/Ni")
        assert_true(not text_has_gold_without_nickel(bundle.table_hits[0].as_dict()), "top table hit prefers Au/gold without Ni")
    graph_artifacts_exist = bool(config.graph_nodes_path and config.graph_nodes_path.exists() and config.graph_edges_path and config.graph_edges_path.exists())
    if graph_artifacts_exist:
        assert_true(len(bundle.graph_hits) > 0, "graph artifacts exist but graph_hits is empty")

    print(
        json.dumps(
            {
                "status": "ok",
                "material": plan.entities.materials,
                "routes": plan.routes,
                "internal_search_queries": plan.internal_search_queries,
                "web_search_queries": plan.web_search_queries,
                "raw_hits": len(bundle.raw_chunks),
                "table_hits": len(bundle.table_hits),
                "graph_hits": len(bundle.graph_hits),
                "warnings": bundle.warnings,
            },
            ensure_ascii=False,
            indent=2,
            default=str,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
