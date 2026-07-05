from __future__ import annotations

import json
from pathlib import Path

from scripts import demo_capability_matrix


def write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")


def test_manifest_check_validates_routerai_backend_dimension_and_count(tmp_path: Path) -> None:
    write_json(
        tmp_path / "data/indexes/chunks_routerai_bge_m3/manifest.json",
        {"embedding_backend": "routerai", "dimension": 1024, "chunk_count": 120},
    )

    result = demo_capability_matrix.manifest_check(
        tmp_path,
        label="raw_vector",
        rel_path="data/indexes/chunks_routerai_bge_m3/manifest.json",
        expected_backend="routerai",
        expected_dimension=1024,
        min_count=100,
    )

    assert result["status"] == "pass"
    assert result["backend"] == "routerai"
    assert result["dimension"] == 1024
    assert result["chunk_count"] == 120


def test_manifest_check_reports_missing_or_mismatched_manifest(tmp_path: Path) -> None:
    missing = demo_capability_matrix.manifest_check(
        tmp_path,
        label="document_summary_vector",
        rel_path="data/indexes/document_summaries_routerai_bge_m3/manifest.json",
        expected_backend="routerai",
        expected_dimension=1024,
        min_count=1,
    )
    assert missing["status"] == "fail"
    assert missing["issues"] == ["manifest_missing_or_invalid_json"]

    write_json(
        tmp_path / "manifest.json",
        {"embedding_backend": "local-hash", "dimension": 64, "chunk_count": 0},
    )
    mismatch = demo_capability_matrix.manifest_check(
        tmp_path,
        label="bad",
        rel_path="manifest.json",
        expected_backend="routerai",
        expected_dimension=1024,
        min_count=1,
    )

    assert mismatch["status"] == "fail"
    assert any("backend" in issue for issue in mismatch["issues"])
    assert any("dimension" in issue for issue in mismatch["issues"])
    assert any("chunk_count" in issue for issue in mismatch["issues"])


def test_markdown_report_contains_capability_rows() -> None:
    matrix = {
        "status": "pass",
        "created_at": "2026-07-04T00:00:00+00:00",
        "capabilities": [
            {
                "title": "GUI with one query and three user task modes",
                "status": "pass",
                "user_value": "Литературный поиск, методики, свойства.",
                "evidence": {"request_types": ["Литературный поиск", "Анализ методик и свойств", "Бизнес-аналитика"]},
            }
        ],
    }

    markdown = demo_capability_matrix.build_markdown_report(matrix)

    assert "# Oreacle Capability Matrix" in markdown
    assert "GUI with one query" in markdown
    assert "Overall status: pass" in markdown
    assert "Литературный поиск" in markdown


def test_write_outputs_writes_json_and_markdown(tmp_path: Path) -> None:
    matrix = {"status": "warn", "created_at": "now", "capabilities": []}

    demo_capability_matrix.write_outputs(
        matrix,
        output_json=tmp_path / "capability_matrix.json",
        output_md=tmp_path / "capability_matrix.md",
    )

    assert json.loads((tmp_path / "capability_matrix.json").read_text(encoding="utf-8"))["status"] == "warn"
    assert "Overall status: warn" in (tmp_path / "capability_matrix.md").read_text(encoding="utf-8")
