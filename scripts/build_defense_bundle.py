from __future__ import annotations

import argparse
import json
import subprocess
import sys
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


DOC_FILES = (
    "reports/oreacle_defense_pack.md",
    "reports/oreacle_pitch_deck.md",
    "reports/oreacle_routerai_demo_script.md",
    "reports/oreacle_marketing_demo_plan.md",
    "tasks/04_query_gui_eval/README.md",
)
INDEX_MANIFESTS = (
    "data/indexes/chunks_routerai_bge_m3/manifest.json",
    "data/indexes/lexical_routerai_bge_m3/manifest.json",
    "data/indexes/document_summaries_routerai_bge_m3/manifest.json",
    "data/indexes/procedure_summaries_routerai_bge_m3/manifest.json",
)
OPTIONAL_FILES = (
    "data/processed/demo_preflight/preflight_report.json",
    "config/retrieval/default.json",
)


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def safe_stamp() -> str:
    return datetime.now().strftime("%Y%m%d_%H%M%S")


def project_root() -> Path:
    return Path(__file__).resolve().parents[1]


def read_json_if_exists(path: Path) -> dict[str, Any] | None:
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return None


def git_commit(root: Path) -> str | None:
    completed = subprocess.run(
        ["git", "rev-parse", "--short", "HEAD"],
        cwd=root,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )
    value = (completed.stdout or "").strip()
    return value or None


def collect_bundle_files(root: Path) -> tuple[list[tuple[Path, str]], list[str]]:
    files: list[tuple[Path, str]] = []
    missing: list[str] = []
    for rel_path in DOC_FILES:
        path = root / rel_path
        if path.exists():
            files.append((path, rel_path.replace("\\", "/")))
        else:
            missing.append(rel_path)
    for rel_path in (*INDEX_MANIFESTS, *OPTIONAL_FILES):
        path = root / rel_path
        if path.exists():
            files.append((path, rel_path.replace("\\", "/")))
        else:
            missing.append(rel_path)
    return files, missing


def run_preflight(root: Path, *, timeout_seconds: int) -> dict[str, Any]:
    command = [
        sys.executable,
        str(root / "scripts" / "demo_preflight.py"),
        "--skip-search",
        "--timeout-seconds",
        str(timeout_seconds),
    ]
    completed = subprocess.run(
        command,
        cwd=root,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=max(timeout_seconds + 10, 20),
        check=False,
    )
    return {
        "command": command,
        "returncode": completed.returncode,
        "stdout_preview": (completed.stdout or "")[:2000],
        "stderr_preview": (completed.stderr or "")[:2000],
    }


def build_bundle_readme(manifest: dict[str, Any]) -> str:
    return (
        "# Oreacle Defense Bundle\n\n"
        "This archive is a lightweight handoff for judges and demo operators. It does not contain raw corpus files, "
        "full web texts, API keys, or `.env` content.\n\n"
        "## Open Demo\n\n"
        "```powershell\n"
        ".\\.venv\\Scripts\\python.exe scripts\\run_demo_app.py --background --address 127.0.0.1\n"
        ".\\.venv\\Scripts\\python.exe scripts\\demo_preflight.py\n"
        "```\n\n"
        "Local URL: http://127.0.0.1:8501/\n\n"
        "## Included\n\n"
        "- Defense runbook, pitch deck, and pitch notes from `reports/`.\n"
        "- Demo UX / technical task notes from `tasks/04_query_gui_eval/README.md`.\n"
        "- RouterAI BGE-M3 index manifests when present.\n"
        "- Latest demo preflight report when present.\n"
        "- `bundle_manifest.json` with commit, paths, and readiness metadata.\n\n"
        "## Current Bundle Status\n\n"
        f"- Created at: {manifest.get('created_at')}\n"
        f"- Git commit: {manifest.get('git_commit') or 'n/a'}\n"
        f"- Preflight status: {manifest.get('preflight_status') or 'not included'}\n"
        f"- RouterAI budget: {manifest.get('routerai_budget_rub') or 1500} RUB\n"
    )


def build_defense_bundle(
    root: Path,
    output_path: Path,
    *,
    run_preflight_first: bool = False,
    preflight_timeout_seconds: int = 20,
) -> dict[str, Any]:
    preflight_run = run_preflight(root, timeout_seconds=preflight_timeout_seconds) if run_preflight_first else None
    files, missing = collect_bundle_files(root)
    preflight_path = root / "data" / "processed" / "demo_preflight" / "preflight_report.json"
    preflight = read_json_if_exists(preflight_path) or {}
    budget_check = next((row for row in preflight.get("checks", []) if row.get("name") == "routerai_budget_guard"), {})
    manifest = {
        "created_at": utc_now(),
        "git_commit": git_commit(root),
        "preflight_status": preflight.get("status"),
        "preflight_run": preflight_run,
        "routerai_budget_rub": budget_check.get("budget_rub", 1500),
        "included_files": [arcname for _path, arcname in files],
        "missing_files": missing,
        "notes": [
            "Raw corpus files, full web texts, API keys, and .env files are intentionally not included.",
            "Use run_artifacts.zip from a specific GUI run for query-level evidence packages.",
        ],
    }
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(output_path, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=6) as zf:
        zf.writestr("README_DEFENSE_BUNDLE.md", build_bundle_readme(manifest))
        zf.writestr("bundle_manifest.json", json.dumps(manifest, ensure_ascii=False, indent=2, default=str))
        for path, arcname in files:
            zf.write(path, arcname)
    manifest["output_path"] = str(output_path)
    manifest["output_size_bytes"] = output_path.stat().st_size
    return manifest


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build a lightweight Oreacle defense/demo bundle.")
    parser.add_argument("--output", type=Path, default=None)
    parser.add_argument("--run-preflight", action="store_true", help="Refresh demo_preflight report before packaging.")
    parser.add_argument("--preflight-timeout-seconds", type=int, default=20)
    return parser.parse_args()


def main() -> int:
    root = project_root()
    args = parse_args()
    output = args.output or root / "data" / "processed" / "defense_bundle" / f"oreacle_defense_bundle_{safe_stamp()}.zip"
    manifest = build_defense_bundle(
        root,
        output,
        run_preflight_first=args.run_preflight,
        preflight_timeout_seconds=args.preflight_timeout_seconds,
    )
    print(json.dumps({"status": "pass", "output": manifest["output_path"], "size_bytes": manifest["output_size_bytes"]}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
