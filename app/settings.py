from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[1]
CONFIG_PATH = PROJECT_ROOT / "config" / "task2_sources.json"


@dataclass(frozen=True)
class ProjectPaths:
    root: Path = PROJECT_ROOT
    raw_dir: Path = PROJECT_ROOT / "data" / "raw" / "yandex_task2"
    interim_dir: Path = PROJECT_ROOT / "data" / "interim"
    parsed_dir: Path = PROJECT_ROOT / "data" / "parsed"
    full_texts_dir: Path = PROJECT_ROOT / "data" / "parsed" / "full_texts"
    parsing_report_dir: Path = PROJECT_ROOT / "reports" / "parsing"

    def ensure(self) -> None:
        for path in (self.raw_dir, self.interim_dir, self.parsed_dir, self.full_texts_dir, self.parsing_report_dir):
            path.mkdir(parents=True, exist_ok=True)


def load_config() -> dict[str, Any]:
    with CONFIG_PATH.open("r", encoding="utf-8") as f:
        return json.load(f)


def paths() -> ProjectPaths:
    p = ProjectPaths()
    p.ensure()
    return p
