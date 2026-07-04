from __future__ import annotations

import argparse
import importlib
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts import demo_preflight  # noqa: E402


ROUTERAI_MANIFESTS = (
    ("raw_vector", "data/indexes/chunks_routerai_bge_m3/manifest.json", "routerai", 1024, 100),
    ("raw_lexical", "data/indexes/lexical_routerai_bge_m3/manifest.json", None, None, 100),
    ("document_summary_vector", "data/indexes/document_summaries_routerai_bge_m3/manifest.json", "routerai", 1024, 1),
    ("procedure_summary_vector", "data/indexes/procedure_summaries_routerai_bge_m3/manifest.json", "routerai", 1024, 1),
)
PITCH_FILES = (
    "reports/oreacle_defense_pack.md",
    "reports/oreacle_pitch_deck.md",
    "reports/oreacle_routerai_demo_script.md",
    "reports/oreacle_demo_video_storyboard.md",
)
EXPORT_SYMBOLS = (
    "build_pdf_report",
    "build_docx_report",
    "build_section_exports",
    "build_answer_exports",
    "build_run_archive",
    "build_orchestration_exports",
    "build_orchestration_archive",
)


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def project_path(root: Path, rel_path: str) -> Path:
    path = Path(rel_path)
    return path if path.is_absolute() else root / path


def read_json(path: Path) -> dict[str, Any] | None:
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return None


def status_from_issues(issues: list[str], *, missing_is_warn: bool = False) -> str:
    if not issues:
        return "pass"
    if missing_is_warn and all("missing" in issue for issue in issues):
        return "warn"
    return "fail"


def manifest_check(
    root: Path,
    *,
    label: str,
    rel_path: str,
    expected_backend: str | None,
    expected_dimension: int | None,
    min_count: int,
) -> dict[str, Any]:
    path = project_path(root, rel_path)
    manifest = read_json(path)
    if manifest is None:
        return {"label": label, "status": "fail", "path": rel_path, "issues": ["manifest_missing_or_invalid_json"]}
    issues: list[str] = []
    backend = manifest.get("embedding_backend") or manifest.get("backend")
    dimension = manifest.get("dimension")
    count = manifest.get("chunk_count")
    if expected_backend and backend != expected_backend:
        issues.append(f"backend={backend!r}, expected={expected_backend!r}")
    if expected_dimension is not None and dimension != expected_dimension:
        issues.append(f"dimension={dimension!r}, expected={expected_dimension!r}")
    if not isinstance(count, int) or count < min_count:
        issues.append(f"chunk_count={count!r}, expected>={min_count}")
    return {
        "label": label,
        "status": "fail" if issues else "pass",
        "path": rel_path,
        "backend": backend,
        "dimension": dimension,
        "chunk_count": count,
        "issues": issues,
    }


def symbol_check(module_name: str, symbols: tuple[str, ...]) -> dict[str, Any]:
    try:
        module = importlib.import_module(module_name)
    except Exception as exc:  # noqa: BLE001 - readiness audit must report import failures.
        return {"module": module_name, "status": "fail", "missing": list(symbols), "error": f"{type(exc).__name__}: {exc}"}
    missing = [symbol for symbol in symbols if not callable(getattr(module, symbol, None))]
    return {"module": module_name, "status": "fail" if missing else "pass", "missing": missing}


def file_group_check(root: Path, rel_paths: tuple[str, ...]) -> dict[str, Any]:
    rows = [{"path": rel_path, "exists": project_path(root, rel_path).exists()} for rel_path in rel_paths]
    missing = [row["path"] for row in rows if not row["exists"]]
    return {"status": "fail" if missing else "pass", "files": rows, "missing": missing}


def routerai_key_configured(root: Path) -> bool:
    load_dotenv(root / ".env", override=False, encoding="utf-8-sig")
    value = os.getenv("ROUTERAI_API_KEY", "").strip()
    return bool(value and "YOUR_" not in value.upper())


def build_capability_matrix(root: Path) -> dict[str, Any]:
    manifest_checks = [
        manifest_check(
            root,
            label=label,
            rel_path=rel_path,
            expected_backend=expected_backend,
            expected_dimension=expected_dimension,
            min_count=min_count,
        )
        for label, rel_path, expected_backend, expected_dimension, min_count in ROUTERAI_MANIFESTS
    ]
    preflight = read_json(root / "data" / "processed" / "demo_preflight" / "preflight_report.json") or {}
    smoke = read_json(root / "data" / "processed" / "demo_smoke" / "smoke_report.json") or {}
    gui_contract = demo_preflight.check_demo_ui_contract(root)
    web_schema = importlib.import_module("app.web_search.schemas")
    search_sources = list(getattr(web_schema, "ALL_SEARCH_SOURCES", []) or [])
    export_symbols = symbol_check("app.query.reports", EXPORT_SYMBOLS)
    deep_symbols = symbol_check("app.query.literature", ("run_deep_search_for_existing_run", "run_literature_search"))
    pitch_files = file_group_check(root, PITCH_FILES)

    capabilities = [
        {
            "id": "routerai_unified_rag",
            "title": "RouterAI BGE-M3 indexes for raw + summary RAG",
            "status": "pass" if all(row["status"] == "pass" for row in manifest_checks) else "fail",
            "evidence": manifest_checks,
            "user_value": "Единое embedding-пространство для raw chunks, document summaries и procedure summaries.",
        },
        {
            "id": "routerai_final_answer",
            "title": "RouterAI final answer and query refinement path",
            "status": "pass" if routerai_key_configured(root) else "warn",
            "evidence": {"routerai_api_key_configured": routerai_key_configured(root), "secret_printed": False},
            "user_value": "Финальный ответ формулируется через provider router без печати секретов.",
        },
        {
            "id": "gui_three_modes",
            "title": "GUI with one query and three user task modes",
            "status": gui_contract.get("status"),
            "evidence": gui_contract,
            "user_value": "Литературный поиск, поиск методик и поиск свойств без Demo scenario / Query Decomposer.",
        },
        {
            "id": "web_literature_search",
            "title": "Web literature metadata search across scholarly APIs",
            "status": "pass" if len(search_sources) >= 5 else "fail",
            "evidence": {"source_count": len(search_sources), "sources": search_sources},
            "user_value": "Больше охват публикаций за счет нескольких metadata API без generic crawler.",
        },
        {
            "id": "deep_search",
            "title": "Optional Deep Search summaries for top-N web records",
            "status": deep_symbols["status"],
            "evidence": deep_symbols,
            "user_value": "Пользователь может сначала получить metadata-only список, затем summary extraction по top-N.",
        },
        {
            "id": "reports_exports",
            "title": "PDF/DOCX/ZIP exports for answer, links, sections, and artifacts",
            "status": export_symbols["status"],
            "evidence": export_symbols,
            "user_value": "Результат можно передать как проверяемый отчет и ZIP, а не как скриншот чата.",
        },
        {
            "id": "preflight_and_smoke",
            "title": "Demo preflight and three-mode product smoke",
            "status": "pass" if preflight.get("status") == "pass" and smoke.get("status") == "ok" else "warn",
            "evidence": {
                "preflight_status": preflight.get("status"),
                "demo_smoke_status": smoke.get("status"),
                "scenario_count": len(smoke.get("scenarios") or []),
            },
            "user_value": "Перед показом можно проверить готовность без платных LLM/web вызовов.",
        },
        {
            "id": "pitch_and_video_handoff",
            "title": "Pitch deck, defense runbook, demo script, and video storyboard",
            "status": pitch_files["status"],
            "evidence": pitch_files,
            "user_value": "Команда может быстро объяснить бизнес-ценность и снять демовидео.",
        },
    ]
    statuses = [row["status"] for row in capabilities]
    overall_status = "fail" if "fail" in statuses else "warn" if "warn" in statuses else "pass"
    return {"status": overall_status, "created_at": utc_now(), "capabilities": capabilities}


def build_markdown_report(matrix: dict[str, Any]) -> str:
    lines = [
        "# Oreacle Capability Matrix",
        "",
        f"- Created at: {matrix.get('created_at')}",
        f"- Overall status: {matrix.get('status')}",
        "",
        "| Capability | Status | User value | Evidence |",
        "|---|---|---|---|",
    ]
    for item in matrix.get("capabilities", []):
        evidence = item.get("evidence")
        if isinstance(evidence, dict):
            evidence_text = "; ".join(f"{key}={value}" for key, value in evidence.items() if key not in {"files"})
        else:
            evidence_text = f"{len(evidence or [])} checks"
        lines.append(
            "| {title} | {status} | {value} | {evidence} |".format(
                title=str(item.get("title", "")).replace("|", "/"),
                status=item.get("status"),
                value=str(item.get("user_value", "")).replace("|", "/"),
                evidence=str(evidence_text).replace("|", "/")[:500],
            )
        )
    lines.extend(
        [
            "",
            "## Notes",
            "",
            "- Audit does not call external APIs and does not print API keys.",
            "- `warn` usually means an optional runtime artifact is missing or the RouterAI key is not configured in the current environment.",
            "- Use this together with `scripts/demo_preflight.py` and `scripts/smoke_demo_scenarios.py` before live-demo.",
        ]
    )
    return "\n".join(lines) + "\n"


def write_outputs(matrix: dict[str, Any], *, output_json: Path, output_md: Path) -> None:
    output_json.parent.mkdir(parents=True, exist_ok=True)
    output_json.write_text(json.dumps(matrix, ensure_ascii=False, indent=2, default=str) + "\n", encoding="utf-8")
    output_md.parent.mkdir(parents=True, exist_ok=True)
    output_md.write_text(build_markdown_report(matrix), encoding="utf-8")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build a no-network demo capability matrix for Oreacle.")
    parser.add_argument("--output-json", type=Path, default=ROOT / "data" / "processed" / "demo_preflight" / "capability_matrix.json")
    parser.add_argument("--output-md", type=Path, default=ROOT / "data" / "processed" / "demo_preflight" / "capability_matrix.md")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    matrix = build_capability_matrix(ROOT)
    write_outputs(matrix, output_json=args.output_json, output_md=args.output_md)
    print(json.dumps({"status": matrix["status"], "output_json": str(args.output_json), "output_md": str(args.output_md)}, ensure_ascii=False, indent=2))
    return 0 if matrix["status"] != "fail" else 1


if __name__ == "__main__":
    raise SystemExit(main())
