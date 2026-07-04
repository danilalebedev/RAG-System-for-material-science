from __future__ import annotations

import argparse
import importlib
import importlib.util
import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from urllib.error import URLError
from urllib.request import urlopen

from dotenv import load_dotenv

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.index.embeddings import apply_retrieval_profile, load_retrieval_config  # noqa: E402
from scripts.run_demo_app import verify_demo_import  # noqa: E402


REQUIRED_STREAMS = (
    "raw_dense",
    "raw_lexical",
    "summary_lexical",
    "document_summary_vector",
    "procedure_summary_vector",
)
DEFAULT_ROUTERAI_BUDGET_RUB = 1500.0
EXPECTED_DEMO_REQUEST_TYPES = ("Литературный поиск", "Поиск методик", "Поиск свойств")
BANNED_DEMO_UI_LABELS = ("Demo scenario", "Query Decomposer", "Advanced API metadata sources")


def configure_stdio() -> None:
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Fast readiness check for the Streamlit demo stand.")
    parser.add_argument("--config", default="config/retrieval/default.json")
    parser.add_argument("--profile", default="routerai_bge_m3")
    parser.add_argument("--query", default="никелевые концентраты обжиг выщелачивание")
    parser.add_argument("--streamlit-url", default="http://127.0.0.1:8501/")
    parser.add_argument("--skip-url", action="store_true", default=False)
    parser.add_argument("--skip-search", action="store_true", default=False)
    parser.add_argument("--timeout-seconds", type=int, default=30)
    parser.add_argument("--output", default="data/processed/demo_preflight/preflight_report.json")
    return parser.parse_args()


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def project_path(root: Path, value: str | os.PathLike[str] | None) -> Path:
    path = Path(str(value or ""))
    return path if path.is_absolute() else root / path


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def check_routerai_key(root: Path) -> dict[str, Any]:
    load_dotenv(root / ".env", override=False, encoding="utf-8-sig")
    value = os.getenv("ROUTERAI_API_KEY", "").strip()
    configured = bool(value and "YOUR_" not in value.upper())
    return {"name": "routerai_api_key", "status": "pass" if configured else "fail", "configured": configured}


def routerai_budget_rub_from_env(root: Path) -> tuple[float, str, str | None]:
    load_dotenv(root / ".env", override=False, encoding="utf-8-sig")
    raw = os.getenv("ROUTERAI_BUDGET_RUB", "").strip()
    if not raw:
        return DEFAULT_ROUTERAI_BUDGET_RUB, "default", None
    try:
        value = float(raw.replace(",", "."))
    except ValueError:
        return DEFAULT_ROUTERAI_BUDGET_RUB, "invalid_env_defaulted", "ROUTERAI_BUDGET_RUB is not a number"
    if value <= 0:
        return DEFAULT_ROUTERAI_BUDGET_RUB, "invalid_env_defaulted", "ROUTERAI_BUDGET_RUB must be positive"
    return value, "env", None


def check_routerai_budget(root: Path) -> dict[str, Any]:
    budget_rub, source, error = routerai_budget_rub_from_env(root)
    return {
        "name": "routerai_budget_guard",
        "status": "pass" if error is None else "fail",
        "budget_rub": budget_rub,
        "source": source,
        "error": error,
        "note": "Reports show token usage and compare cost only if RouterAI API returns cost_rub metadata.",
    }


def check_streamlit_import() -> dict[str, Any]:
    installed = importlib.util.find_spec("streamlit") is not None
    return {"name": "streamlit_import", "status": "pass" if installed else "fail", "installed": installed}


def check_demo_app_import(root: Path) -> dict[str, Any]:
    ok, detail = verify_demo_import(root)
    return {
        "name": "demo_app_import",
        "status": "pass" if ok else "fail",
        "detail": detail,
    }


def demo_ui_contract_issues(root: Path, demo_app_module: Any) -> list[str]:
    issues: list[str] = []
    request_types = list(getattr(demo_app_module, "REQUEST_TYPES", {}).keys())
    if request_types != list(EXPECTED_DEMO_REQUEST_TYPES):
        issues.append(f"request_types={request_types!r}, expected={list(EXPECTED_DEMO_REQUEST_TYPES)!r}")

    source_path = root / "app" / "ui" / "demo_app.py"
    if source_path.exists():
        source_text = source_path.read_text(encoding="utf-8")
        for label in BANNED_DEMO_UI_LABELS:
            if label.casefold() in source_text.casefold():
                issues.append(f"banned_label_present={label!r}")

    search_context_rows = getattr(demo_app_module, "search_context_rows", None)
    if not callable(search_context_rows):
        issues.append("search_context_rows_missing")
        return issues
    probe_run = SimpleNamespace(
        request=SimpleNamespace(query="никелевые сплавы"),
        keywords=["никелевые сплавы", "твердость"],
        query_plan={
            "original_query": "никелевые сплавы",
            "llm_rewrite": {
                "corrected_query": "nickel alloys hardness",
                "search_queries": ["nickel alloys hardness"],
                "rewrite_used_llm": True,
            },
        },
    )
    rows = search_context_rows(probe_run, None)
    if not rows or not all({"Что используется", "Значение"}.issubset(set(row)) for row in rows):
        issues.append("search_context_rows_not_user_facing")
    if any({"stage", "query", "llm"} & set(row) for row in rows):
        issues.append("legacy_decomposer_columns_present")

    workflow_summary_rows = getattr(demo_app_module, "workflow_summary_rows", None)
    if not callable(workflow_summary_rows):
        issues.append("workflow_summary_rows_missing")
        return issues
    probe_orchestration = SimpleNamespace(
        plan=SimpleNamespace(routes=["summary_rag", "raw_rag", "table_search", "graph_search"]),
        retrieved_context=SimpleNamespace(
            as_dict=lambda: {
                "raw": [{"id": "raw:1"}],
                "summaries": [{"id": "summary:1"}],
                "tables": [{"id": "table:1"}],
                "graph": [{"id": "graph:1"}],
                "web": [],
            }
        ),
        fallbacks=[],
    )
    workflow_rows = workflow_summary_rows(
        {
            "request_type": "Поиск методик",
            "literature_run": probe_run,
            "orchestration": probe_orchestration,
            "answer": None,
        }
    )
    if not workflow_rows or not all({"Шаг", "Что сделано", "Объем"}.issubset(set(row)) for row in workflow_rows):
        issues.append("workflow_summary_rows_not_user_facing")
    if any({"retrieved_context", "plan", "query_rewrite"} & set(row) for row in workflow_rows):
        issues.append("workflow_summary_uses_internal_json_keys")
    return issues


def check_demo_ui_contract(root: Path) -> dict[str, Any]:
    try:
        demo_app_module = importlib.import_module("app.ui.demo_app")
    except Exception as exc:  # noqa: BLE001 - preflight should report import errors, not crash.
        return {"name": "demo_ui_contract", "status": "fail", "error": f"{type(exc).__name__}: {exc}"}
    issues = demo_ui_contract_issues(root, demo_app_module)
    return {
        "name": "demo_ui_contract",
        "status": "fail" if issues else "pass",
        "request_types": list(getattr(demo_app_module, "REQUEST_TYPES", {}).keys()),
        "banned_labels": list(BANNED_DEMO_UI_LABELS),
        "issues": issues,
    }


def check_streamlit_url(url: str, *, timeout_seconds: int) -> dict[str, Any]:
    try:
        with urlopen(url, timeout=timeout_seconds) as response:  # noqa: S310 - local demo readiness check.
            status_code = int(getattr(response, "status", 0) or response.getcode())
    except (OSError, URLError) as exc:
        return {"name": "streamlit_url", "status": "fail", "url": url, "error": str(exc)[:300]}
    return {"name": "streamlit_url", "status": "pass" if 200 <= status_code < 500 else "fail", "url": url, "status_code": status_code}


def check_manifest(
    name: str,
    path: Path,
    *,
    expected_backend: str | None = None,
    expected_dimension: int | None = None,
    min_count: int = 1,
) -> dict[str, Any]:
    if not path.exists():
        return {"name": name, "status": "fail", "path": str(path), "error": "manifest_missing"}
    try:
        manifest = read_json(path)
    except json.JSONDecodeError as exc:
        return {"name": name, "status": "fail", "path": str(path), "error": f"invalid_json: {exc}"}
    issues: list[str] = []
    backend = manifest.get("embedding_backend") or manifest.get("backend")
    if expected_backend and backend != expected_backend:
        issues.append(f"backend={backend!r}, expected={expected_backend!r}")
    dimension = manifest.get("dimension")
    if expected_dimension is not None and dimension != expected_dimension:
        issues.append(f"dimension={dimension!r}, expected={expected_dimension!r}")
    count = manifest.get("chunk_count")
    if isinstance(count, int) and count < min_count:
        issues.append(f"chunk_count={count}, expected>={min_count}")
    elif count is None:
        issues.append("chunk_count_missing")
    return {
        "name": name,
        "status": "fail" if issues else "pass",
        "path": str(path),
        "backend": backend,
        "dimension": dimension,
        "chunk_count": count,
        "issues": issues,
    }


def profile_manifest_checks(root: Path, config_path: Path, profile: str) -> list[dict[str, Any]]:
    config = apply_retrieval_profile(load_retrieval_config(config_path), profile)
    return [
        check_manifest(
            "raw_vector_manifest",
            project_path(root, config.get("chunk_index_dir")) / "manifest.json",
            expected_backend="routerai" if profile == "routerai_bge_m3" else None,
            expected_dimension=1024 if profile == "routerai_bge_m3" else None,
            min_count=100,
        ),
        check_manifest(
            "lexical_manifest",
            project_path(root, config.get("lexical_index_dir")) / "manifest.json",
            min_count=100,
        ),
        check_manifest(
            "document_summary_manifest",
            project_path(root, config.get("document_summary_index_dir")) / "manifest.json",
            expected_backend="routerai" if profile == "routerai_bge_m3" else None,
            expected_dimension=1024 if profile == "routerai_bge_m3" else None,
            min_count=1,
        ),
        check_manifest(
            "procedure_summary_manifest",
            project_path(root, config.get("procedure_summary_index_dir")) / "manifest.json",
            expected_backend="routerai" if profile == "routerai_bge_m3" else None,
            expected_dimension=1024 if profile == "routerai_bge_m3" else None,
            min_count=1,
        ),
    ]


def run_search_smoke(root: Path, *, profile: str, query: str, timeout_seconds: int) -> dict[str, Any]:
    command = [
        sys.executable,
        str(root / "scripts" / "search_cli.py"),
        query,
        "--profile",
        profile,
        "--top-k",
        "5",
        "--offline",
    ]
    completed = subprocess.run(
        command,
        cwd=root,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=timeout_seconds,
        check=False,
    )
    stdout = completed.stdout or ""
    missing_streams = [stream for stream in REQUIRED_STREAMS if stream not in stdout]
    return {
        "name": "routerai_profile_search_smoke",
        "status": "pass" if completed.returncode == 0 and not missing_streams else "fail",
        "returncode": completed.returncode,
        "required_streams": list(REQUIRED_STREAMS),
        "missing_streams": missing_streams,
        "stdout_preview": stdout[:1200],
        "stderr_preview": (completed.stderr or "")[:1200],
    }


def summarize(checks: list[dict[str, Any]]) -> str:
    return "pass" if all(check.get("status") == "pass" for check in checks) else "fail"


def write_report(path: Path, report: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(report, ensure_ascii=False, indent=2, default=str), encoding="utf-8")


def main() -> int:
    configure_stdio()
    args = parse_args()
    root = Path(__file__).resolve().parents[1]
    config_path = project_path(root, args.config)
    checks: list[dict[str, Any]] = [
        check_routerai_key(root),
        check_routerai_budget(root),
        check_streamlit_import(),
        check_demo_app_import(root),
        check_demo_ui_contract(root),
        *profile_manifest_checks(root, config_path, args.profile),
    ]
    if not args.skip_url:
        checks.append(check_streamlit_url(args.streamlit_url, timeout_seconds=args.timeout_seconds))
    if not args.skip_search:
        checks.append(run_search_smoke(root, profile=args.profile, query=args.query, timeout_seconds=max(args.timeout_seconds, 60)))
    report = {
        "status": summarize(checks),
        "created_at": utc_now(),
        "profile": args.profile,
        "query": args.query,
        "checks": checks,
    }
    output_path = project_path(root, args.output)
    write_report(output_path, report)
    print(json.dumps({"status": report["status"], "output": str(output_path), "failed": [check["name"] for check in checks if check.get("status") != "pass"]}, ensure_ascii=False, indent=2))
    return 0 if report["status"] == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())
