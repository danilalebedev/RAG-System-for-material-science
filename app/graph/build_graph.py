from __future__ import annotations

import hashlib
import json
import re
import unicodedata
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Iterator


ENTITY_FIELDS: dict[str, tuple[str, ...]] = {
    "Material": ("materials", "material_name", "input_materials", "outputs", "reagents"),
    "Process": ("processes", "synthesis_or_process_method", "synthesis_method"),
    "Equipment": ("equipment", "equipment_details", "design_features"),
    "Property": ("properties", "observed_effects", "analysis_results", "numerical_results", "key_findings"),
    "Method": ("methods", "synthesis_or_process_method", "synthesis_method", "technology_solutions", "validation_methods"),
    "Facility": ("facilities", "facilities_or_geography", "geography", "deposits", "organizations"),
    "Expert": ("experts", "authors"),
}


@dataclass
class GraphNode:
    node_id: str
    type: str
    label: str
    aliases: set[str] = field(default_factory=set)
    doc_ids: set[str] = field(default_factory=set)
    publication_ids: set[str] = field(default_factory=set)
    metadata: dict[str, Any] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        return {
            "node_id": self.node_id,
            "type": self.type,
            "label": self.label,
            "aliases": sorted(self.aliases),
            "doc_ids": sorted(self.doc_ids),
            "publication_ids": sorted(self.publication_ids),
            "metadata": self.metadata,
        }


@dataclass(frozen=True)
class GraphEdge:
    edge_id: str
    source_id: str
    target_id: str
    type: str
    doc_id: str = ""
    publication_id: str = ""
    procedure_summary_id: str = ""
    confidence: float | None = None
    evidence: tuple[str, ...] = ()
    metadata: dict[str, Any] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        return {
            "edge_id": self.edge_id,
            "source_id": self.source_id,
            "target_id": self.target_id,
            "type": self.type,
            "doc_id": self.doc_id,
            "publication_id": self.publication_id,
            "procedure_summary_id": self.procedure_summary_id,
            "confidence": self.confidence,
            "evidence": list(self.evidence),
            "metadata": self.metadata,
        }


def stable_hash(value: str, *, size: int = 16) -> str:
    return hashlib.sha1(value.encode("utf-8", errors="ignore")).hexdigest()[:size]


def normalize_label(value: Any) -> str:
    text = unicodedata.normalize("NFKC", str(value or ""))
    text = re.sub(r"\s+", " ", text).strip(" \t\r\n;,.")
    return text


def normalize_key(value: Any) -> str:
    return normalize_label(value).casefold()


def node_id(node_type: str, label: str) -> str:
    return f"{node_type.lower()}_{stable_hash(normalize_key(label))}"


def publication_node_id(publication_id: str, doc_id: str) -> str:
    return f"publication_{stable_hash(publication_id or doc_id)}"


def table_node_id(table_id: str, doc_id: str, label: str) -> str:
    return f"table_{stable_hash(table_id or doc_id + ':' + label)}"


def edge_id(source_id: str, edge_type: str, target_id: str, qualifier: str = "") -> str:
    return f"edge_{stable_hash('|'.join((source_id, edge_type, target_id, qualifier)), size=20)}"


def iter_jsonl(path: Path) -> Iterator[dict[str, Any]]:
    if not path.exists():
        return
    with path.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                yield json.loads(line)


def write_jsonl(path: Path, rows: Iterable[dict[str, Any]]) -> int:
    path.parent.mkdir(parents=True, exist_ok=True)
    count = 0
    with path.open("w", encoding="utf-8", newline="\n") as f:
        for row in rows:
            f.write(json.dumps(row, ensure_ascii=False, default=str) + "\n")
            count += 1
    return count


def add_node(
    nodes: dict[str, GraphNode],
    node_type: str,
    label: Any,
    *,
    doc_id: str = "",
    publication_id: str = "",
    metadata: dict[str, Any] | None = None,
    explicit_id: str | None = None,
) -> str | None:
    label_text = normalize_label(label)
    if not label_text:
        return None
    nid = explicit_id or node_id(node_type, label_text)
    node = nodes.get(nid)
    if node is None:
        node = GraphNode(node_id=nid, type=node_type, label=label_text, metadata=metadata or {})
        nodes[nid] = node
    node.aliases.add(label_text)
    if doc_id:
        node.doc_ids.add(doc_id)
    if publication_id:
        node.publication_ids.add(publication_id)
    if metadata:
        node.metadata.update({key: value for key, value in metadata.items() if value not in (None, "", [], {})})
    return nid


def add_edge(
    edges: dict[str, GraphEdge],
    source_id: str | None,
    edge_type: str,
    target_id: str | None,
    *,
    doc_id: str = "",
    publication_id: str = "",
    procedure_summary_id: str = "",
    confidence: float | None = None,
    evidence: Iterable[Any] = (),
    metadata: dict[str, Any] | None = None,
) -> None:
    if not source_id or not target_id or source_id == target_id:
        return
    evidence_ids = tuple(extract_evidence_ids(evidence))
    eid = edge_id(source_id, edge_type, target_id, procedure_summary_id or doc_id)
    edges[eid] = GraphEdge(
        edge_id=eid,
        source_id=source_id,
        target_id=target_id,
        type=edge_type,
        doc_id=doc_id,
        publication_id=publication_id,
        procedure_summary_id=procedure_summary_id,
        confidence=confidence,
        evidence=evidence_ids,
        metadata=metadata or {},
    )


def extract_evidence_ids(value: Iterable[Any]) -> list[str]:
    ids: list[str] = []
    for item in value or []:
        if isinstance(item, dict):
            source_id = item.get("source_span_id") or item.get("id")
            if source_id:
                ids.append(str(source_id))
        elif item:
            ids.append(str(item))
    return ids


def flatten_values(value: Any) -> Iterator[str]:
    if value in (None, "", [], {}):
        return
    if isinstance(value, str):
        for part in split_entity_string(value):
            yield part
        return
    if isinstance(value, dict):
        preferred = (
            value.get("name")
            or value.get("label")
            or value.get("value")
            or value.get("text")
            or value.get("material")
            or value.get("method")
            or value.get("process")
            or value.get("property")
        )
        if preferred:
            yield from flatten_values(preferred)
        return
    if isinstance(value, list):
        for item in value:
            yield from flatten_values(item)
        return
    yield normalize_label(value)


def split_entity_string(value: str) -> list[str]:
    text = normalize_label(value)
    if not text:
        return []
    if len(text) <= 120 and not any(separator in text for separator in ("\n", ";")):
        return [text]
    parts = re.split(r"[\n;]+", text)
    return [normalize_label(part) for part in parts if 2 <= len(normalize_label(part)) <= 160]


def record_entity_values(record: dict[str, Any], node_type: str) -> list[str]:
    values: list[str] = []
    for field_name in ENTITY_FIELDS.get(node_type, ()):
        values.extend(flatten_values(record.get(field_name)))
    additional = record.get("additional_domain_fields")
    if isinstance(additional, dict):
        for field_name in ENTITY_FIELDS.get(node_type, ()):
            values.extend(flatten_values(additional.get(field_name)))
    return unique(values)


def unique(values: Iterable[str], *, limit: int = 80) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for value in values:
        text = normalize_label(value)
        key = normalize_key(text)
        if len(text) < 2 or key in seen:
            continue
        seen.add(key)
        result.append(text)
        if len(result) >= limit:
            break
    return result


def confidence(record: dict[str, Any]) -> float | None:
    value = record.get("confidence")
    try:
        return float(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def build_publication_nodes(
    nodes: dict[str, GraphNode],
    edges: dict[str, GraphEdge],
    publications_path: Path,
    documents_path: Path,
) -> dict[str, str]:
    doc_to_publication_node: dict[str, str] = {}
    rows = list(iter_jsonl(publications_path)) if publications_path.exists() else []
    if not rows:
        rows = list(iter_jsonl(documents_path))
    for row in rows:
        doc_id = str(row.get("doc_id") or "")
        publication_id = str(row.get("publication_id") or f"pub_{doc_id}")
        label = row.get("title") or row.get("file_name") or row.get("source_path") or doc_id
        pid = publication_node_id(publication_id, doc_id)
        add_node(
            nodes,
            "Publication",
            label,
            doc_id=doc_id,
            publication_id=publication_id,
            explicit_id=pid,
            metadata={
                "year": row.get("year"),
                "document_kind": row.get("document_kind") or row.get("parser"),
                "source_type": row.get("source_type"),
                "source_path": row.get("source_path"),
                "file_name": row.get("file_name"),
                "confidence": row.get("confidence"),
            },
        )
        doc_to_publication_node[doc_id] = pid
        for expert in flatten_values(row.get("authors")):
            expert_id = add_node(nodes, "Expert", expert, doc_id=doc_id, publication_id=publication_id)
            add_edge(edges, expert_id, "authored", pid, doc_id=doc_id, publication_id=publication_id, confidence=confidence(row))
        for facility in flatten_values(row.get("organizations")):
            facility_id = add_node(nodes, "Facility", facility, doc_id=doc_id, publication_id=publication_id)
            add_edge(edges, pid, "validated_by", facility_id, doc_id=doc_id, publication_id=publication_id, confidence=confidence(row))
    return doc_to_publication_node


def build_summary_entities(
    nodes: dict[str, GraphNode],
    edges: dict[str, GraphEdge],
    summaries_path: Path,
    doc_to_publication_node: dict[str, str],
) -> None:
    for row in iter_jsonl(summaries_path):
        doc_id = str(row.get("doc_id") or "")
        publication_id = str(row.get("publication_id") or f"pub_{doc_id}")
        pub_node = doc_to_publication_node.get(doc_id) or publication_node_id(publication_id, doc_id)
        for node_type in ("Material", "Process", "Equipment", "Property", "Method", "Facility", "Expert"):
            for value in record_entity_values(row, node_type):
                nid = add_node(nodes, node_type, value, doc_id=doc_id, publication_id=publication_id)
                add_edge(
                    edges,
                    nid,
                    "described_in",
                    pub_node,
                    doc_id=doc_id,
                    publication_id=publication_id,
                    confidence=confidence(row),
                    evidence=row.get("evidence") or [],
                )


def build_procedure_entities(
    nodes: dict[str, GraphNode],
    edges: dict[str, GraphEdge],
    procedures_path: Path,
    doc_to_publication_node: dict[str, str],
) -> None:
    for row in iter_jsonl(procedures_path):
        doc_id = str(row.get("doc_id") or "")
        publication_id = str(row.get("publication_id") or f"pub_{doc_id}")
        procedure_id = str(row.get("procedure_summary_id") or "")
        pub_node = doc_to_publication_node.get(doc_id) or publication_node_id(publication_id, doc_id)
        label = row.get("synthesis_or_process_method") or row.get("synthesis_method") or row.get("material_name") or procedure_id
        experiment_id = add_node(
            nodes,
            "Experiment",
            label,
            doc_id=doc_id,
            publication_id=publication_id,
            explicit_id=f"experiment_{stable_hash(procedure_id or doc_id + ':' + normalize_label(label))}",
            metadata={
                "procedure_summary_id": procedure_id,
                "procedure_type": row.get("procedure_type"),
                "key_points": row.get("key_points"),
                "confidence": row.get("confidence"),
            },
        )
        add_edge(
            edges,
            experiment_id,
            "described_in",
            pub_node,
            doc_id=doc_id,
            publication_id=publication_id,
            procedure_summary_id=procedure_id,
            confidence=confidence(row),
            evidence=row.get("evidence") or row.get("source_span_ids") or [],
        )
        typed_nodes: dict[str, list[str]] = {}
        for node_type in ("Material", "Process", "Equipment", "Property", "Method", "Facility", "Expert"):
            typed_nodes[node_type] = []
            for value in record_entity_values(row, node_type):
                nid = add_node(nodes, node_type, value, doc_id=doc_id, publication_id=publication_id)
                if nid:
                    typed_nodes[node_type].append(nid)
                    add_edge(
                        edges,
                        nid,
                        "described_in",
                        pub_node,
                        doc_id=doc_id,
                        publication_id=publication_id,
                        procedure_summary_id=procedure_id,
                        confidence=confidence(row),
                        evidence=row.get("evidence") or row.get("source_span_ids") or [],
                    )
        for material_id in typed_nodes["Material"]:
            add_edge(edges, experiment_id, "uses_material", material_id, doc_id=doc_id, publication_id=publication_id, procedure_summary_id=procedure_id, confidence=confidence(row))
        for target_type in ("Process", "Equipment", "Method", "Facility"):
            for target_id in typed_nodes[target_type]:
                add_edge(edges, experiment_id, "operates_at_condition", target_id, doc_id=doc_id, publication_id=publication_id, procedure_summary_id=procedure_id, confidence=confidence(row))
        for property_id in typed_nodes["Property"]:
            add_edge(edges, experiment_id, "produces_output", property_id, doc_id=doc_id, publication_id=publication_id, procedure_summary_id=procedure_id, confidence=confidence(row))


def build_table_nodes(
    nodes: dict[str, GraphNode],
    edges: dict[str, GraphEdge],
    tables_path: Path,
    documents_path: Path,
    doc_to_publication_node: dict[str, str],
    *,
    root: Path,
) -> None:
    for row in iter_jsonl(tables_path):
        doc_id = str(row.get("doc_id") or "")
        pub_node = doc_to_publication_node.get(doc_id)
        label = row.get("page_or_sheet") or row.get("table_id") or f"table {doc_id}"
        tid = table_node_id(str(row.get("table_id") or ""), doc_id, str(label))
        add_node(
            nodes,
            "Table",
            label,
            doc_id=doc_id,
            explicit_id=tid,
            metadata={"row_count": row.get("row_count"), "local_path": row.get("local_path"), "text_preview": str(row.get("text") or "")[:500]},
        )
        add_edge(edges, tid, "described_in", pub_node, doc_id=doc_id)
    for row in iter_jsonl(documents_path):
        doc_id = str(row.get("doc_id") or "")
        metadata = parse_metadata(row.get("metadata_json"))
        for sheet in metadata.get("sheets") or []:
            if not isinstance(sheet, dict):
                continue
            label = sheet.get("sheet_name") or sheet.get("csv_path") or "sheet"
            tid = table_node_id(str(sheet.get("csv_path") or ""), doc_id, str(label))
            add_node(
                nodes,
                "Table",
                label,
                doc_id=doc_id,
                explicit_id=tid,
                metadata={
                    "csv_path": str(resolve_project_path(sheet.get("csv_path"), root=root)),
                    "rows": sheet.get("rows"),
                    "columns": sheet.get("columns"),
                },
            )
            add_edge(edges, tid, "described_in", doc_to_publication_node.get(doc_id), doc_id=doc_id)


def parse_metadata(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    if not value:
        return {}
    try:
        parsed = json.loads(str(value))
    except json.JSONDecodeError:
        return {}
    return parsed if isinstance(parsed, dict) else {}


def resolve_project_path(value: Any, *, root: Path) -> Path:
    path = Path(str(value or ""))
    if path.is_absolute() and path.exists():
        return path
    if path.is_absolute():
        parts = list(path.parts)
        lowered = [part.casefold() for part in parts]
        marker = ["data", "parsed", "spreadsheets_csv"]
        for index in range(0, len(parts) - len(marker) + 1):
            if lowered[index : index + len(marker)] == marker:
                return root.joinpath(*parts[index:])
        return path
    return root / path


def build_graph(
    *,
    root: Path,
    publications_dir: Path,
    documents_path: Path,
    tables_path: Path,
    output_nodes_path: Path,
    output_edges_path: Path,
    manifest_path: Path,
) -> dict[str, Any]:
    nodes: dict[str, GraphNode] = {}
    edges: dict[str, GraphEdge] = {}
    publications_path = publications_dir / "publications.jsonl"
    document_summaries_path = publications_dir / "document_summaries.jsonl"
    procedures_path = publications_dir / "procedure_summaries.jsonl"

    doc_to_publication_node = build_publication_nodes(nodes, edges, publications_path, documents_path)
    build_summary_entities(nodes, edges, document_summaries_path, doc_to_publication_node)
    build_procedure_entities(nodes, edges, procedures_path, doc_to_publication_node)
    build_table_nodes(nodes, edges, tables_path, documents_path, doc_to_publication_node, root=root)

    node_count = write_jsonl(output_nodes_path, (node.as_dict() for node in sorted(nodes.values(), key=lambda item: (item.type, item.label))))
    edge_count = write_jsonl(output_edges_path, (edge.as_dict() for edge in sorted(edges.values(), key=lambda item: item.edge_id)))
    manifest = {
        "built_at": datetime.now(timezone.utc).isoformat(),
        "nodes_path": str(output_nodes_path),
        "edges_path": str(output_edges_path),
        "node_count": node_count,
        "edge_count": edge_count,
        "inputs": {
            "publications": str(publications_path),
            "document_summaries": str(document_summaries_path),
            "procedure_summaries": str(procedures_path),
            "documents": str(documents_path),
            "tables": str(tables_path),
        },
        "warnings": [
            f"missing optional input: {path}"
            for path in (publications_path, document_summaries_path, procedures_path)
            if not path.exists()
        ],
    }
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return manifest

