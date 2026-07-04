from __future__ import annotations

import json
import zipfile
from pathlib import Path

from scripts import build_defense_bundle as defense_bundle_module
from scripts.build_defense_bundle import build_defense_bundle, collect_bundle_files


def write(path: Path, text: str = "x") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def test_collect_bundle_files_marks_required_docs_and_optional_manifests(tmp_path: Path) -> None:
    write(tmp_path / "reports" / "oreacle_defense_pack.md")
    write(tmp_path / "reports" / "oreacle_pitch_deck.md")
    write(tmp_path / "reports" / "oreacle_routerai_demo_script.md")
    write(tmp_path / "reports" / "oreacle_demo_video_storyboard.md")
    write(tmp_path / "reports" / "oreacle_marketing_demo_plan.md")
    write(tmp_path / "tasks" / "04_query_gui_eval" / "README.md")
    write(tmp_path / "data" / "indexes" / "chunks_routerai_bge_m3" / "manifest.json", "{}")

    files, missing = collect_bundle_files(tmp_path)
    arcnames = {arcname for _path, arcname in files}

    assert "reports/oreacle_defense_pack.md" in arcnames
    assert "reports/oreacle_pitch_deck.md" in arcnames
    assert "reports/oreacle_demo_video_storyboard.md" in arcnames
    assert "tasks/04_query_gui_eval/README.md" in arcnames
    assert "data/indexes/chunks_routerai_bge_m3/manifest.json" in arcnames
    assert "data/indexes/procedure_summaries_routerai_bge_m3/manifest.json" in missing


def test_build_defense_bundle_writes_safe_zip(tmp_path: Path) -> None:
    for rel_path in (
        "reports/oreacle_defense_pack.md",
        "reports/oreacle_pitch_deck.md",
        "reports/oreacle_routerai_demo_script.md",
        "reports/oreacle_demo_video_storyboard.md",
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
    write(
        tmp_path / "data" / "processed" / "demo_smoke" / "smoke_report.json",
        json.dumps({"status": "ok", "scenarios": [{"mode": "Литературный поиск"}]}),
    )
    write(tmp_path / ".env", "ROUTERAI_API_KEY=secret")
    write(tmp_path / "data" / "raw" / "secret.pdf", "raw")

    output = tmp_path / "bundle.zip"
    manifest = build_defense_bundle(tmp_path, output)

    assert output.exists()
    assert manifest["preflight_status"] == "pass"
    assert manifest["demo_smoke_status"] == "ok"
    assert manifest["routerai_budget_rub"] == 1500.0
    with zipfile.ZipFile(output) as zf:
        names = set(zf.namelist())
        bundle_manifest = json.loads(zf.read("bundle_manifest.json").decode("utf-8"))
        readme = zf.read("README_DEFENSE_BUNDLE.md").decode("utf-8")

    assert "README_DEFENSE_BUNDLE.md" in names
    assert "reports/oreacle_defense_pack.md" in names
    assert "reports/oreacle_pitch_deck.md" in names
    assert "reports/oreacle_demo_video_storyboard.md" in names
    assert "data/processed/demo_preflight/preflight_report.json" in names
    assert "data/processed/demo_smoke/smoke_report.json" in names
    assert ".env" not in names
    assert "data/raw/secret.pdf" not in names
    assert bundle_manifest["preflight_status"] == "pass"
    assert bundle_manifest["demo_smoke_status"] == "ok"
    assert "Local URL: http://127.0.0.1:8501/" in readme
    assert "Demo smoke status: ok" in readme


def test_build_defense_bundle_can_refresh_demo_smoke(tmp_path: Path, monkeypatch) -> None:
    for rel_path in (
        "reports/oreacle_defense_pack.md",
        "reports/oreacle_pitch_deck.md",
        "reports/oreacle_routerai_demo_script.md",
        "reports/oreacle_demo_video_storyboard.md",
        "reports/oreacle_marketing_demo_plan.md",
        "tasks/04_query_gui_eval/README.md",
    ):
        write(tmp_path / rel_path, rel_path)

    def fake_run_demo_smoke(root: Path, *, timeout_seconds: int) -> dict:
        assert timeout_seconds == 7
        write(
            root / "data" / "processed" / "demo_smoke" / "smoke_report.json",
            json.dumps({"status": "ok", "scenarios": [{"mode": "methods"}]}),
        )
        return {"returncode": 0, "stdout_preview": "smoke ok", "stderr_preview": ""}

    monkeypatch.setattr(defense_bundle_module, "run_demo_smoke", fake_run_demo_smoke)

    output = tmp_path / "bundle.zip"
    manifest = build_defense_bundle(tmp_path, output, run_smoke_first=True, smoke_timeout_seconds=7)

    assert manifest["demo_smoke_status"] == "ok"
    assert manifest["demo_smoke_run"]["returncode"] == 0
    with zipfile.ZipFile(output) as zf:
        names = set(zf.namelist())
        bundle_manifest = json.loads(zf.read("bundle_manifest.json").decode("utf-8"))

    assert "data/processed/demo_smoke/smoke_report.json" in names
    assert bundle_manifest["demo_smoke_status"] == "ok"
    assert bundle_manifest["demo_smoke_run"]["stdout_preview"] == "smoke ok"


def test_build_defense_bundle_can_refresh_capability_audit(tmp_path: Path, monkeypatch) -> None:
    for rel_path in (
        "reports/oreacle_defense_pack.md",
        "reports/oreacle_pitch_deck.md",
        "reports/oreacle_routerai_demo_script.md",
        "reports/oreacle_demo_video_storyboard.md",
        "reports/oreacle_marketing_demo_plan.md",
        "tasks/04_query_gui_eval/README.md",
    ):
        write(tmp_path / rel_path, rel_path)

    def fake_run_capability_audit(root: Path, *, timeout_seconds: int) -> dict:
        assert timeout_seconds == 11
        write(
            root / "data" / "processed" / "demo_preflight" / "capability_matrix.json",
            json.dumps({"status": "pass", "capabilities": [{"id": "gui_three_modes"}]}),
        )
        write(
            root / "data" / "processed" / "demo_preflight" / "capability_matrix.md",
            "# Oreacle Capability Matrix\n",
        )
        return {"returncode": 0, "stdout_preview": "audit pass", "stderr_preview": ""}

    monkeypatch.setattr(defense_bundle_module, "run_capability_audit", fake_run_capability_audit)

    output = tmp_path / "bundle.zip"
    manifest = build_defense_bundle(
        tmp_path,
        output,
        run_capability_audit_first=True,
        capability_audit_timeout_seconds=11,
    )

    assert manifest["capability_matrix_status"] == "pass"
    assert manifest["capability_audit_run"]["returncode"] == 0
    with zipfile.ZipFile(output) as zf:
        names = set(zf.namelist())
        bundle_manifest = json.loads(zf.read("bundle_manifest.json").decode("utf-8"))
        readme = zf.read("README_DEFENSE_BUNDLE.md").decode("utf-8")

    assert "data/processed/demo_preflight/capability_matrix.json" in names
    assert "data/processed/demo_preflight/capability_matrix.md" in names
    assert bundle_manifest["capability_matrix_status"] == "pass"
    assert "Capability matrix status: pass" in readme
