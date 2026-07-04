from __future__ import annotations

import json
import zipfile
from pathlib import Path

from scripts.build_defense_bundle import build_defense_bundle, collect_bundle_files


def write(path: Path, text: str = "x") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def test_collect_bundle_files_marks_required_docs_and_optional_manifests(tmp_path: Path) -> None:
    write(tmp_path / "reports" / "oreacle_defense_pack.md")
    write(tmp_path / "reports" / "oreacle_pitch_deck.md")
    write(tmp_path / "reports" / "oreacle_routerai_demo_script.md")
    write(tmp_path / "reports" / "oreacle_marketing_demo_plan.md")
    write(tmp_path / "tasks" / "04_query_gui_eval" / "README.md")
    write(tmp_path / "data" / "indexes" / "chunks_routerai_bge_m3" / "manifest.json", "{}")

    files, missing = collect_bundle_files(tmp_path)
    arcnames = {arcname for _path, arcname in files}

    assert "reports/oreacle_defense_pack.md" in arcnames
    assert "reports/oreacle_pitch_deck.md" in arcnames
    assert "tasks/04_query_gui_eval/README.md" in arcnames
    assert "data/indexes/chunks_routerai_bge_m3/manifest.json" in arcnames
    assert "data/indexes/procedure_summaries_routerai_bge_m3/manifest.json" in missing


def test_build_defense_bundle_writes_safe_zip(tmp_path: Path) -> None:
    for rel_path in (
        "reports/oreacle_defense_pack.md",
        "reports/oreacle_pitch_deck.md",
        "reports/oreacle_routerai_demo_script.md",
        "reports/oreacle_marketing_demo_plan.md",
        "tasks/04_query_gui_eval/README.md",
        "config/retrieval/default.json",
    ):
        write(tmp_path / rel_path, "{}" if rel_path.endswith(".json") else rel_path)
    write(
        tmp_path / "data" / "processed" / "demo_preflight" / "preflight_report.json",
        json.dumps(
            {
                "status": "pass",
                "checks": [{"name": "routerai_budget_guard", "status": "pass", "budget_rub": 1500.0}],
            }
        ),
    )
    write(tmp_path / ".env", "ROUTERAI_API_KEY=secret")
    write(tmp_path / "data" / "raw" / "secret.pdf", "raw")

    output = tmp_path / "bundle.zip"
    manifest = build_defense_bundle(tmp_path, output)

    assert output.exists()
    assert manifest["preflight_status"] == "pass"
    assert manifest["routerai_budget_rub"] == 1500.0
    with zipfile.ZipFile(output) as zf:
        names = set(zf.namelist())
        bundle_manifest = json.loads(zf.read("bundle_manifest.json").decode("utf-8"))
        readme = zf.read("README_DEFENSE_BUNDLE.md").decode("utf-8")

    assert "README_DEFENSE_BUNDLE.md" in names
    assert "reports/oreacle_defense_pack.md" in names
    assert "reports/oreacle_pitch_deck.md" in names
    assert "data/processed/demo_preflight/preflight_report.json" in names
    assert ".env" not in names
    assert "data/raw/secret.pdf" not in names
    assert bundle_manifest["preflight_status"] == "pass"
    assert "Local URL: http://127.0.0.1:8501/" in readme
