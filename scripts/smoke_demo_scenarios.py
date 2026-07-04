from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

from app.query.comparison import compare_methods  # noqa: E402
from app.query.orchestrator import run_query_orchestration  # noqa: E402
from app.query.planner import plan_query  # noqa: E402


DEMO_PROMPTS = [
    (
        "Сравнить методы переработки литий-ионных батарей для извлечения Ni и Co",
        {"summary_rag", "raw_rag", "table_search"},
    ),
    (
        "Найти технологии удаления SO2 в металлургии и сравнить ограничения",
        {"summary_rag", "raw_rag", "table_search"},
    ),
    (
        "Показать связи: никель -> процессы -> свойства -> публикации",
        {"graph_search"},
    ),
    (
        "Найти таблицы с содержанием Ni, Cu, Co и сравнить значения",
        {"table_search", "raw_rag"},
    ),
    (
        "Сравнить внутренние данные с внешними публикациями по кучному выщелачиванию в холодном климате",
        {"internal_rag", "web_search"},
    ),
]


def assert_true(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def main() -> int:
    rows: list[dict[str, object]] = []
    for prompt, expected_routes in DEMO_PROMPTS:
        plan = plan_query(prompt)
        assert_true(bool(plan.original_query), "planner returned empty plan")
        missing_routes = expected_routes.difference(plan.routes)
        assert_true(not missing_routes, f"planner routes for '{prompt}' missed {sorted(missing_routes)}; got {plan.routes}")
        result = run_query_orchestration(prompt, include_web=False)
        payload = result.as_dict()
        assert_true(set(payload["retrieved_context"]) == {"raw", "summaries", "tables", "graph", "web"}, "bad structured context")
        rows.append(
            {
                "query": prompt,
                "intent": plan.intent,
                "routes": plan.routes,
                "fallbacks": len(payload.get("fallbacks") or []),
            }
        )

    comparison = compare_methods(DEMO_PROMPTS[0], top_k=3)
    assert_true(bool(comparison.as_dict().get("comparison_dimensions")), "comparison mode returned no dimensions")

    import app.ui.demo_app as demo_app  # noqa: F401

    print(json.dumps({"status": "ok", "scenarios": rows}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
