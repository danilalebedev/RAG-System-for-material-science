from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.graph.search import load_graph, neighbors, paths_to_types, search_entities


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Search the lightweight knowledge graph.")
    parser.add_argument("query", nargs="?", default="")
    parser.add_argument("--nodes", default="data/index/knowledge_graph_nodes.jsonl")
    parser.add_argument("--edges", default="data/index/knowledge_graph_edges.jsonl")
    parser.add_argument("--type", dest="node_type", default=None)
    parser.add_argument("--top-k", type=int, default=10)
    parser.add_argument("--neighbors", default=None, help="Node id to inspect.")
    parser.add_argument("--paths", action="store_true", help="Return paths from best hit or --neighbors node.")
    parser.add_argument("--json", action="store_true")
    return parser.parse_args()


def resolve(root: Path, value: str) -> Path:
    path = Path(value)
    return path if path.is_absolute() else root / path


def main() -> int:
    args = parse_args()
    root = Path(__file__).resolve().parents[1]
    nodes, edges = load_graph(resolve(root, args.nodes), resolve(root, args.edges))
    hits = search_entities(nodes, args.query, node_type=args.node_type, top_k=args.top_k) if args.query else []
    selected_id = args.neighbors or (hits[0].node.get("node_id") if hits else None)
    neighbor_rows = neighbors(nodes, edges, selected_id, limit=50) if selected_id else []
    path_rows = paths_to_types(nodes, edges, selected_id, limit=20) if selected_id and args.paths else []
    payload = {
        "hits": [hit.as_dict() for hit in hits],
        "neighbors": neighbor_rows,
        "paths": path_rows,
    }
    if args.json:
        print(json.dumps(payload, ensure_ascii=False, indent=2, default=str))
        return 0
    for hit in hits:
        node = hit.node
        print(f"{hit.rank}. score={hit.score:.3f} {node.get('type')} {node.get('node_id')} {node.get('label')}")
    if neighbor_rows:
        print("\nNeighbors:")
        for row in neighbor_rows[:20]:
            edge = row["edge"]
            node = row["node"]
            print(f"- {edge.get('type')}: {node.get('type')} {node.get('label')} ({node.get('node_id')})")
    if path_rows:
        print("\nPaths:")
        for path in path_rows[:10]:
            print(" -> ".join(str(step["node"].get("label")) for step in path))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

