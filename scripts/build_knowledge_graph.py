from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.graph.build_graph import build_graph


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build a lightweight JSONL knowledge graph from publication summaries and parsed artifacts.")
    parser.add_argument("--publications-dir", default="data/processed/publications")
    parser.add_argument("--documents", default="data/parsed/documents.jsonl")
    parser.add_argument("--tables", default="data/parsed/tables.jsonl")
    parser.add_argument("--output-dir", default="data/index")
    return parser.parse_args()


def resolve(root: Path, value: str) -> Path:
    path = Path(value)
    return path if path.is_absolute() else root / path


def main() -> int:
    args = parse_args()
    root = Path(__file__).resolve().parents[1]
    output_dir = resolve(root, args.output_dir)
    manifest = build_graph(
        root=root,
        publications_dir=resolve(root, args.publications_dir),
        documents_path=resolve(root, args.documents),
        tables_path=resolve(root, args.tables),
        output_nodes_path=output_dir / "knowledge_graph_nodes.jsonl",
        output_edges_path=output_dir / "knowledge_graph_edges.jsonl",
        manifest_path=output_dir / "knowledge_graph_manifest.json",
    )
    print(json.dumps(manifest, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

