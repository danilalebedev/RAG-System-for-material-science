from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import app.query.literature as literature_module  # noqa: E402
from app.query.orchestrator import run_query_orchestration  # noqa: E402
from app.query.planner import plan_query  # noqa: E402
from app.web_search.schemas import LiteratureSearchRequest, LiteratureSearchResult  # noqa: E402
from app.ui.demo_app import REQUEST_TYPES  # noqa: E402


SCENARIOS = [
    {
        "mode": "Литературный поиск",
        "query": "Найди зарубежные публикации по флотации никелевых руд и влиянию реагентов на извлечение Ni",
    },
    {
        "mode": "Анализ методик и свойств",
        "query": "Какие никелевые сплавы применяются в судостроении и какие режимы термообработки влияют на твердость?",
    },
    {
        "mode": "Бизнес-аналитика",
        "query": "Сравни производство стали в России, Китае, Индии и Турции и покажи рыночные доли.",
    },
]


class OfflineLiteratureClient:
    def search(
        self,
        query: str,
        *,
        keywords: list[str],
        sources: list[str],
        top_k: int,
        query_variants: list[str],
        materials_only: bool,
        relevance_terms: list[str],
    ) -> tuple[list[LiteratureSearchResult], list[str]]:
        del sources, query_variants, materials_only, relevance_terms
        result = LiteratureSearchResult(
            result_id="smoke_crossref_001",
            source="crossref",
            title="Nickel ore flotation reagent effects on Ni recovery",
            authors=["Demo Expert"],
            year=2024,
            venue="Materials Processing Demo Journal",
            doi="10.0000/demo-smoke",
            url="https://example.org/demo-smoke",
            abstract="Materials science study of nickel ore flotation and reagent effects on Ni recovery.",
            score=2.5,
            keyword_hits=keywords[:8],
            raw={"smoke": True},
        )
        return [result][:top_k], []


def assert_true(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def context_counts(payload: dict[str, Any]) -> dict[str, int]:
    context = payload.get("retrieved_context") or {}
    return {key: len(context.get(key) or []) for key in ("raw", "summaries", "tables", "graph", "web")}


def run_literature_smoke(query: str, *, output_root: Path) -> dict[str, Any]:
    original_enrich = literature_module.enrich_open_access
    literature_module.enrich_open_access = lambda _results, _warnings, limit=10: None
    try:
        run = literature_module.run_literature_search(
            LiteratureSearchRequest(
                query=query,
                top_k=3,
                sources=["crossref"],
                deep_search="none",
                include_local_search=True,
                use_query_rewrite=True,
                use_llm_query_rewrite=False,
                include_recommended_resource_links=False,
                fetch_excerpts=False,
                generate_pdf_report=False,
                run_id="smoke_literature",
            ),
            project_root=ROOT,
            client=OfflineLiteratureClient(),
            output_root=output_root,
        )
    finally:
        literature_module.enrich_open_access = original_enrich

    assert_true(bool(run.keywords), "literature mode produced no keywords")
    assert_true(bool(run.results), "literature mode produced no web metadata results")
    assert_true(run.links_report_docx_path is not None and run.links_report_docx_path.exists(), "links DOCX report missing")
    assert_true(run.full_run_json_path is not None and run.full_run_json_path.exists(), "full_run.json missing")
    return {
        "mode": "Литературный поиск",
        "intent": run.query_plan.get("intent"),
        "keywords": run.keywords[:12],
        "web_results": len(run.results),
        "local_matches": len(run.local_matches),
        "reports": {
            "links_docx": str(run.links_report_docx_path),
            "full_run_json": str(run.full_run_json_path),
        },
    }


def run_orchestration_smoke(mode: str, query: str) -> dict[str, Any]:
    required_routes = REQUEST_TYPES[mode]
    plan = plan_query(query)
    result = run_query_orchestration(
        query,
        include_web=False,
        required_routes=required_routes,
        use_query_rewrite=True,
        use_llm_query_rewrite=False,
        generate_pdf_report=False,
    )
    payload = result.as_dict()
    counts = context_counts(payload)
    assert_true(set(payload["retrieved_context"]) == {"raw", "summaries", "tables", "graph", "web"}, f"{mode}: bad context shape")
    assert_true(set(required_routes).issubset(set(payload["plan"]["routes"])), f"{mode}: required routes missing")
    assert_true(bool(payload["answer_draft"]), f"{mode}: empty answer draft")
    return {
        "mode": mode,
        "intent": plan.intent,
        "routes": payload["plan"]["routes"],
        "required_routes": required_routes,
        "context_counts": counts,
        "fallbacks": len(payload.get("fallbacks") or []),
    }


def run_smoke(*, output_root: Path) -> dict[str, Any]:
    rows: list[dict[str, Any]] = []
    for scenario in SCENARIOS:
        mode = scenario["mode"]
        query = scenario["query"]
        if mode == "Литературный поиск":
            rows.append(run_literature_smoke(query, output_root=output_root))
        else:
            rows.append(run_orchestration_smoke(mode, query))
    return {"status": "ok", "created_at": datetime.now(timezone.utc).isoformat(timespec="seconds"), "scenarios": rows}


def write_smoke_report(path: Path, payload: dict[str, Any]) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    return path


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Smoke-check the three current Oreacle demo modes without paid LLM/web calls.")
    parser.add_argument("--output-root", type=Path, default=ROOT / "data" / "processed" / "demo_smoke")
    parser.add_argument("--output", type=Path, default=None, help="JSON report path. Defaults to <output-root>/smoke_report.json.")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    payload = run_smoke(output_root=args.output_root)
    output_path = args.output or args.output_root / "smoke_report.json"
    write_smoke_report(output_path, payload)
    payload = {**payload, "output": str(output_path)}
    print(json.dumps(payload, ensure_ascii=False, indent=2, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
