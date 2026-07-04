from __future__ import annotations

import json
import sys
from pathlib import Path
from types import SimpleNamespace

from scripts import run_demo_app


def test_streamlit_command_uses_current_python_and_headless() -> None:
    command = run_demo_app.streamlit_command(
        Path("app/ui/demo_app.py"),
        port=8507,
        address="127.0.0.1",
        headless=True,
    )

    assert command[:4] == [sys.executable, "-m", "streamlit", "run"]
    assert "--server.port" in command
    assert "8507" in command
    assert "--server.address" in command
    assert "127.0.0.1" in command
    assert command[-2:] == ["--server.headless", "true"]


def test_verify_demo_import_current_checkout() -> None:
    ok, detail = run_demo_app.verify_demo_import(Path(__file__).resolve().parents[1])

    assert ok is True
    assert detail == "ok"


def test_find_existing_demo_processes_filters_streamlit_port(monkeypatch) -> None:
    rows = [
        {"ProcessId": 11, "CommandLine": "python -m streamlit run app\\ui\\demo_app.py --server.port 8501"},
        {"ProcessId": 12, "CommandLine": "python -m streamlit run app\\ui\\demo_app.py --server.port 8502"},
        {"ProcessId": 13, "CommandLine": "python other.py 8501"},
    ]

    def fake_run(*_: object, **__: object) -> SimpleNamespace:
        return SimpleNamespace(returncode=0, stdout=json.dumps(rows), stderr="")

    monkeypatch.setattr(run_demo_app.os, "name", "nt")
    monkeypatch.setattr(run_demo_app.subprocess, "run", fake_run)

    processes = run_demo_app.find_existing_demo_processes(port=8501)

    assert processes == [
        {"pid": 11, "commandline": "python -m streamlit run app\\ui\\demo_app.py --server.port 8501"}
    ]

