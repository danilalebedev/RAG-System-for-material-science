from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

from scripts import demo_preflight


def test_check_manifest_validates_backend_dimension_and_count(tmp_path: Path) -> None:
    manifest = tmp_path / "manifest.json"
    manifest.write_text(
        json.dumps(
            {
                "embedding_backend": "routerai",
                "dimension": 1024,
                "chunk_count": 42,
            }
        ),
        encoding="utf-8",
    )

    result = demo_preflight.check_manifest(
        "test_manifest",
        manifest,
        expected_backend="routerai",
        expected_dimension=1024,
        min_count=10,
    )

    assert result["status"] == "pass"
    assert result["chunk_count"] == 42


def test_check_manifest_reports_mismatch(tmp_path: Path) -> None:
    manifest = tmp_path / "manifest.json"
    manifest.write_text(json.dumps({"embedding_backend": "local-hash", "dimension": 384, "chunk_count": 0}), encoding="utf-8")

    result = demo_preflight.check_manifest(
        "summary_manifest",
        manifest,
        expected_backend="routerai",
        expected_dimension=1024,
        min_count=1,
    )

    assert result["status"] == "fail"
    assert any("backend" in issue for issue in result["issues"])
    assert any("dimension" in issue for issue in result["issues"])
    assert any("chunk_count" in issue for issue in result["issues"])


def test_summarize_requires_all_checks_to_pass() -> None:
    assert demo_preflight.summarize([{"status": "pass"}, {"status": "pass"}]) == "pass"
    assert demo_preflight.summarize([{"status": "pass"}, {"status": "fail"}]) == "fail"


def test_routerai_budget_defaults_and_env_override(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.delenv("ROUTERAI_BUDGET_RUB", raising=False)
    default_budget, source, error = demo_preflight.routerai_budget_rub_from_env(tmp_path)
    assert default_budget == 1500.0
    assert source == "default"
    assert error is None

    monkeypatch.setenv("ROUTERAI_BUDGET_RUB", "900.5")
    env_budget, env_source, env_error = demo_preflight.routerai_budget_rub_from_env(tmp_path)
    assert env_budget == 900.5
    assert env_source == "env"
    assert env_error is None


def test_run_search_smoke_checks_required_streams(monkeypatch, tmp_path: Path) -> None:
    def fake_run(*_: object, **__: object) -> SimpleNamespace:
        streams = {stream: 1 for stream in demo_preflight.REQUIRED_STREAMS}
        return SimpleNamespace(returncode=0, stdout=f"streams={streams}", stderr="")

    monkeypatch.setattr(demo_preflight.subprocess, "run", fake_run)

    result = demo_preflight.run_search_smoke(
        tmp_path,
        profile="routerai_bge_m3",
        query="nickel",
        timeout_seconds=60,
    )

    assert result["status"] == "pass"
    assert result["missing_streams"] == []
