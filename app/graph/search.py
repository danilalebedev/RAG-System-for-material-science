from __future__ import annotations

import json
import re
import unicodedata
from collections import deque
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Iterator


TOKEN_RE = re.compile(r"[\w.+#%-]+", re.UNICODE)


@dataclass(frozen=True)
class EntityHit:
    rank: int
    score: float
    node: dict[str, Any]
    matched_terms: tuple[str, ...]

    def as_dict(self) -> dict[str, Any]:
        return {
            "rank": self.rank,
            "score": round(self.score, 6),
            "matched_terms": list(self.matched_terms),
            "node": self.node,
        }


def iter_jsonl(path: Path) -> Iterator[dict[str, Any]]:
    if not path.exists():
        return
    with path.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                yield json.loads(line)


def load_graph(nodes_path: Path, edges_path: Path) -> tuple[dict[str, dict[str, Any]], list[dict[str, Any]]]:
    nodes = {str(row.get("node_id")): row for row in iter_jsonl(nodes_path)}
    edges = list(iter_jsonl(edges_path))
    return nodes, edges


def normalize_text(value: Any) -> str:
    text = unicodedata.normalize("NFKC", str(value or "")).casefold()
    return re.sub(r"\s+", " ", text).strip()


def query_terms(query: str) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for token in TOKEN_RE.findall(normalize_text(query)):
        token = token.strip(".+#%-_")
        if len(token) < 2 or token in seen:
            continue
        seen.add(token)
        result.append(token)
    return result


def expanded_query_terms(query: str) -> list[str]:
    terms = query_terms(query)
    normalized = normalize_text(query)
    nickel = any(term in normalized for term in ("nickel", "ni", "никел"))
    ore = any(term in normalized for term in ("ore", "ores", "руда", "руды", "руд"))
    if nickel and ore:
        terms.extend(["никелевая", "никелевые", "никель", "nickel", "ni", "ore", "ores", "руда"])
    return list(dict.fromkeys(terms))


def node_text(node: dict[str, Any]) -> str:
    metadata = node.get("metadata") or {}
    aliases = node.get("aliases") or []
    return " ".join(
        [
            str(node.get("type") or ""),
            str(node.get("label") or ""),
            " ".join(str(alias) for alias in aliases),
            str(metadata.get("source_path") or ""),
            str(metadata.get("file_name") or ""),
            str(metadata.get("year") or ""),
        ]
    )


def score_text(text: str, terms: Iterable[str]) -> tuple[float, tuple[str, ...]]:
    terms_tuple = tuple(terms)
    normalized = normalize_text(text)
    matched = tuple(term for term in terms_tuple if term in normalized)
    if not matched:
        return 0.0, ()
    return len(matched) / max(len(terms_tuple), 1), matched


def search_entities(
    nodes: dict[str, dict[str, Any]],
    query: str,
    *,
    node_type: str | None = None,
    top_k: int = 20,
) -> list[EntityHit]:
    terms = expanded_query_terms(query)
    hits: list[EntityHit] = []
    for node in nodes.values():
        if node_type and node.get("type") != node_type:
            continue
        score, matched = score_text(node_text(node), terms)
        if score <= 0:
            continue
        if normalize_text(query) == normalize_text(node.get("label")):
            score += 1.0
        hits.append(EntityHit(rank=0, score=score, node=node, matched_terms=matched))
    hits.sort(key=lambda hit: hit.score, reverse=True)
    return [EntityHit(rank=rank, score=hit.score, node=hit.node, matched_terms=hit.matched_terms) for rank, hit in enumerate(hits[:top_k], start=1)]


def neighbor_edges(edges: list[dict[str, Any]], node_id: str, *, limit: int = 50) -> list[dict[str, Any]]:
    rows = [edge for edge in edges if edge.get("source_id") == node_id or edge.get("target_id") == node_id]
    return rows[:limit]


def neighbors(
    nodes: dict[str, dict[str, Any]],
    edges: list[dict[str, Any]],
    node_id: str,
    *,
    limit: int = 50,
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for edge in neighbor_edges(edges, node_id, limit=limit):
        other_id = edge.get("target_id") if edge.get("source_id") == node_id else edge.get("source_id")
        rows.append({"edge": edge, "node": nodes.get(str(other_id), {"node_id": other_id})})
    return rows


def build_adjacency(edges: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    adjacency: dict[str, list[dict[str, Any]]] = {}
    for edge in edges:
        adjacency.setdefault(str(edge.get("source_id")), []).append(edge)
        reverse = {**edge, "source_id": edge.get("target_id"), "target_id": edge.get("source_id"), "type": f"reverse:{edge.get('type')}"}
        adjacency.setdefault(str(edge.get("target_id")), []).append(reverse)
    return adjacency


def paths_to_types(
    nodes: dict[str, dict[str, Any]],
    edges: list[dict[str, Any]],
    start_node_id: str,
    *,
    target_types: set[str] | None = None,
    max_depth: int = 3,
    limit: int = 20,
) -> list[list[dict[str, Any]]]:
    targets = target_types or {"Publication", "Process", "Property"}
    adjacency = build_adjacency(edges)
    found: list[list[dict[str, Any]]] = []
    queue: deque[tuple[str, list[dict[str, Any]], set[str]]] = deque([(start_node_id, [], {start_node_id})])
    while queue and len(found) < limit:
        node_id, path, seen = queue.popleft()
        if len(path) >= max_depth:
            continue
        for edge in adjacency.get(node_id, []):
            next_id = str(edge.get("target_id"))
            if next_id in seen:
                continue
            next_node = nodes.get(next_id)
            if not next_node:
                continue
            next_path = path + [{"edge": edge, "node": next_node}]
            if next_node.get("type") in targets:
                found.append(next_path)
                if len(found) >= limit:
                    break
            queue.append((next_id, next_path, seen | {next_id}))
    return found
