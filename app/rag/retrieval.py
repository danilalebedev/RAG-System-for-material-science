from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable, Literal

from app.index.chunks import load_chunk_texts
from app.index.lexical import LexicalHit, LexicalIndex
from app.index.summaries import summary_embedding_text, summary_id as build_summary_id
from app.index.vector_store import MANIFEST_FILE, VECTOR_FILE, VectorHit, VectorIndex, load_manifest, load_metadata
from app.rag.query_signals import (
    QuerySignals,
    SignalWeights,
    extract_query_signals,
    field_text,
    merge_reasons,
    rank_component,
    text_signal_score,
)


SearchMode = Literal["hybrid", "dense", "lexical"]


@dataclass
class RetrievalResult:
    rank: int
    score: float
    chunk_id: str
    doc_id: str
    chunk_index: int | None
    source_path: str
    local_path: str
    text: str
    candidate_id: str = ""
    source_type: str = "raw_chunk"
    summary_id: str = ""
    title: str = ""
    components: dict[str, float] = field(default_factory=dict)
    reasons: tuple[str, ...] = ()
    metadata: dict[str, Any] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        components = {key: round(value, 6) for key, value in sorted(self.components.items())}
        return {
            "rank": self.rank,
            "score": round(self.score, 6),
            "candidate_id": self.candidate_id or f"{self.source_type}:{self.chunk_id or self.summary_id or self.doc_id}",
            "source_type": self.source_type,
            "chunk_id": self.chunk_id,
            "summary_id": self.summary_id,
            "doc_id": self.doc_id,
            "chunk_index": self.chunk_index,
            "title": self.title,
            "source_path": self.source_path,
            "local_path": self.local_path,
            "text": self.text,
            "score_components": components,
            "components": components,
            "why": list(self.reasons),
            "metadata": self.metadata,
        }


@dataclass
class RetrievalDiagnostics:
    query: QuerySignals
    mode: SearchMode
    dense_status: str = "not_requested"
    dense_index_backend: str = ""
    dense_model_selection: str = ""
    warnings: list[str] = field(default_factory=list)
    streams: dict[str, int] = field(default_factory=dict)

    def add_warning(self, message: str) -> None:
        if message not in self.warnings:
            self.warnings.append(message)

    def as_dict(self) -> dict[str, Any]:
        return {
            "query": self.query.as_dict(),
            "mode": self.mode,
            "dense_status": self.dense_status,
            "dense_index_backend": self.dense_index_backend,
            "dense_model_selection": self.dense_model_selection,
            "warnings": self.warnings,
            "streams": self.streams,
        }


@dataclass
class CandidateDraft:
    candidate_id: str
    source_type: str
    doc_id: str
    chunk_id: str = ""
    summary_id: str = ""
    chunk_index: int | None = None
    source_path: str = ""
    local_path: str = ""
    title: str = ""
    text: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)
    components: dict[str, float] = field(default_factory=dict)
    reasons: tuple[str, ...] = ()
    text_signals_applied: bool = False

    def add_component(self, name: str, value: float, reason: str = "") -> None:
        if value <= 0:
            return
        self.components[name] = self.components.get(name, 0.0) + float(value)
        if reason:
            self.reasons = merge_reasons(self.reasons, (reason,))

    @property
    def score(self) -> float:
        return float(sum(self.components.values()))


def dense_search(index_dir: Path, query_vector: Iterable[float], *, top_k: int, batch_size: int = 8192) -> list[VectorHit]:
    return VectorIndex(index_dir).search(query_vector, top_k=top_k, batch_size=batch_size)


def lexical_search(index_dir: Path, query: str, *, top_k: int) -> list[LexicalHit]:
    return LexicalIndex(index_dir).search(query, top_k=top_k)


def reciprocal_rank_fusion(
    *,
    dense_hits: list[VectorHit],
    lexical_hits: list[LexicalHit],
    rrf_k: int = 60,
    top_k: int = 10,
) -> list[tuple[int, float, dict[str, float]]]:
    fused: dict[int, float] = {}
    components: dict[int, dict[str, float]] = {}
    for rank, hit in enumerate(dense_hits, start=1):
        fused[hit.row_id] = fused.get(hit.row_id, 0.0) + 1.0 / (rrf_k + rank)
        components.setdefault(hit.row_id, {})["dense"] = hit.score
    for rank, hit in enumerate(lexical_hits, start=1):
        fused[hit.row_id] = fused.get(hit.row_id, 0.0) + 1.0 / (rrf_k + rank)
        components.setdefault(hit.row_id, {})["lexical"] = hit.score
    ranked = sorted(fused.items(), key=lambda item: item[1], reverse=True)[:top_k]
    return [(row_id, score, components.get(row_id, {})) for row_id, score in ranked]


def candidate_id_for_raw(row: dict[str, Any]) -> str:
    return f"raw_chunk:{row.get('chunk_id') or row.get('row_id')}"


def raw_candidate_from_metadata(row: dict[str, Any]) -> CandidateDraft:
    return CandidateDraft(
        candidate_id=candidate_id_for_raw(row),
        source_type="raw_chunk",
        doc_id=str(row.get("doc_id") or ""),
        chunk_id=str(row.get("chunk_id") or ""),
        chunk_index=row.get("chunk_index"),
        source_path=str(row.get("source_path") or ""),
        local_path=str(row.get("local_path") or ""),
        metadata={"row_id": row.get("row_id")},
    )


def get_or_create(candidates: dict[str, CandidateDraft], candidate: CandidateDraft) -> CandidateDraft:
    existing = candidates.get(candidate.candidate_id)
    if existing is not None:
        return existing
    candidates[candidate.candidate_id] = candidate
    return candidate


def add_text_signal_components(
    candidate: CandidateDraft,
    *,
    signals: QuerySignals,
    config: dict[str, Any],
    weights: SignalWeights,
    row: dict[str, Any] | None = None,
) -> None:
    if candidate.text_signals_applied:
        return
    signal_score = text_signal_score(
        signals=signals,
        body_text=candidate.text,
        field_values=(candidate.title, candidate.source_path, candidate.local_path, candidate.doc_id, candidate.chunk_id, candidate.summary_id),
        row={**candidate.metadata, **(row or {})},
        config=config,
        weights=weights,
    )
    for name, value in signal_score.components().items():
        candidate.add_component(name, value)
    candidate.reasons = merge_reasons(candidate.reasons, signal_score.reasons)
    if signal_score.matched_terms:
        candidate.metadata["matched_terms"] = list(signal_score.matched_terms)
    if signal_score.matched_phrases:
        candidate.metadata["matched_phrases"] = list(signal_score.matched_phrases)
    if signal_score.matched_concepts:
        candidate.metadata["matched_concepts"] = list(signal_score.matched_concepts)
    candidate.text_signals_applied = True


def add_raw_dense_candidates(
    candidates: dict[str, CandidateDraft],
    *,
    dense_hits: list[VectorHit],
    metadata_by_row: dict[int, dict[str, Any]],
    rrf_k: int,
    weights: SignalWeights,
) -> None:
    for rank, hit in enumerate(dense_hits, start=1):
        row = metadata_by_row.get(hit.row_id)
        if not row:
            continue
        candidate = get_or_create(candidates, raw_candidate_from_metadata(row))
        candidate.add_component("dense", rank_component(rank, rrf_k=rrf_k, weight=weights.dense), f"dense rank {rank}, similarity {hit.score:.4f}")
        candidate.metadata["dense_similarity"] = round(hit.score, 6)


def add_raw_lexical_candidates(
    candidates: dict[str, CandidateDraft],
    *,
    lexical_hits: list[LexicalHit],
    metadata_by_row: dict[int, dict[str, Any]],
    rrf_k: int,
    weights: SignalWeights,
) -> None:
    for rank, hit in enumerate(lexical_hits, start=1):
        row = metadata_by_row.get(hit.row_id)
        if not row:
            continue
        candidate = get_or_create(candidates, raw_candidate_from_metadata(row))
        candidate.add_component("lexical", rank_component(rank, rrf_k=rrf_k, weight=weights.lexical), f"raw FTS rank {rank}, bm25 score {hit.score:.4f}")
        candidate.metadata["lexical_score"] = round(hit.score, 6)


def materialize_raw_candidates(
    candidates: dict[str, CandidateDraft],
    *,
    chunks_path: Path,
    signals: QuerySignals,
    config: dict[str, Any],
    weights: SignalWeights,
) -> None:
    raw_candidates = [candidate for candidate in candidates.values() if candidate.source_type == "raw_chunk"]
    texts = load_chunk_texts(chunks_path, {candidate.chunk_id for candidate in raw_candidates if candidate.chunk_id})
    for candidate in raw_candidates:
        candidate.text = texts.get(candidate.chunk_id, candidate.text)
        add_text_signal_components(candidate, signals=signals, config=config, weights=weights, row=candidate.metadata)


def iter_jsonl(path: Path) -> Iterable[dict[str, Any]]:
    if not path.exists():
        return
    with path.open("r", encoding="utf-8") as f:
        for line in f:
            if line.strip():
                yield json.loads(line)


def summary_sources(publications_dir: Path | None) -> list[tuple[str, Path]]:
    if publications_dir is None:
        return []
    return [
        ("document_summary", publications_dir / "document_summaries.jsonl"),
        ("procedure_summary", publications_dir / "procedure_summaries.jsonl"),
    ]


def lexical_summary_score(candidate: CandidateDraft, signals: QuerySignals) -> float:
    text = field_text(candidate.title, candidate.source_path, candidate.text).casefold().replace("ё", "е")
    matched_terms = [term for term in signals.tokens if term in text]
    matched_phrases = [phrase for phrase in signals.phrases if phrase and phrase in text]
    matched_concepts = candidate.metadata.get("matched_concepts") or []
    if not matched_terms and not matched_phrases and not matched_concepts:
        return 0.0
    coverage = len(set(matched_terms)) / max(len(signals.tokens), 1)
    return coverage * 10.0 + len(matched_phrases) * 2.0 + len(matched_concepts) * 2.5


def add_summary_lexical_candidates(
    candidates: dict[str, CandidateDraft],
    *,
    signals: QuerySignals,
    publications_dir: Path | None,
    top_k: int,
    rrf_k: int,
    config: dict[str, Any],
    weights: SignalWeights,
) -> int:
    if top_k <= 0:
        return 0
    scored: list[tuple[float, CandidateDraft, dict[str, Any]]] = []
    for kind, path in summary_sources(publications_dir):
        for row in iter_jsonl(path):
            sid = build_summary_id(row, kind)
            text = summary_embedding_text(row)
            candidate = CandidateDraft(
                candidate_id=f"{kind}:{sid}",
                source_type=kind,
                doc_id=str(row.get("doc_id") or ""),
                summary_id=sid,
                source_path=str(row.get("source_path") or row.get("local_path") or ""),
                title=str(row.get("title") or row.get("main_topic") or row.get("material_name") or row.get("doc_id") or ""),
                text=text,
                metadata={"publication_id": row.get("publication_id"), "confidence": row.get("confidence")},
            )
            add_text_signal_components(candidate, signals=signals, config=config, weights=weights, row=row)
            score = lexical_summary_score(candidate, signals)
            if score > 0:
                scored.append((score, candidate, row))
    scored.sort(key=lambda item: item[0], reverse=True)
    for rank, (score, draft, _) in enumerate(scored[:top_k], start=1):
        candidate = get_or_create(candidates, draft)
        candidate.add_component(
            "summary_lexical",
            rank_component(rank, rrf_k=rrf_k, weight=weights.summary_lexical),
            f"{draft.source_type} lexical rank {rank}, score {score:.3f}",
        )
    return min(len(scored), top_k)


def load_summary_texts(source_path: Path, summary_ids: set[str], kind: str) -> dict[str, tuple[str, dict[str, Any]]]:
    if not source_path.exists() or not summary_ids:
        return {}
    rows: dict[str, tuple[str, dict[str, Any]]] = {}
    for row in iter_jsonl(source_path):
        sid = build_summary_id(row, kind)
        if sid in summary_ids:
            rows[sid] = (summary_embedding_text(row), row)
            if len(rows) == len(summary_ids):
                break
    return rows


def add_summary_vector_candidates(
    candidates: dict[str, CandidateDraft],
    *,
    summary_index_dir: Path,
    source_type: str,
    query_vector: Iterable[float] | None,
    top_k: int,
    rrf_k: int,
    batch_size: int,
    signals: QuerySignals,
    config: dict[str, Any],
    weights: SignalWeights,
    diagnostics: RetrievalDiagnostics,
) -> int:
    if top_k <= 0 or query_vector is None:
        return 0
    if not (summary_index_dir / VECTOR_FILE).exists() or not (summary_index_dir / MANIFEST_FILE).exists():
        return 0
    try:
        hits = dense_search(summary_index_dir, query_vector, top_k=top_k, batch_size=batch_size)
    except Exception as exc:  # noqa: BLE001 - dense summary must degrade independently.
        diagnostics.add_warning(f"{source_type} vector search skipped: {exc}")
        return 0
    manifest = load_manifest(summary_index_dir)
    metadata = {int(row["row_id"]): row for row in load_metadata(summary_index_dir)}
    source_path = Path(str(manifest.get("source_summary_path") or ""))
    text_rows = load_summary_texts(source_path, {str(metadata.get(hit.row_id, {}).get("summary_id") or "") for hit in hits}, source_type)
    for rank, hit in enumerate(hits, start=1):
        row = metadata.get(hit.row_id)
        if not row:
            continue
        sid = str(row.get("summary_id") or "")
        text, original_row = text_rows.get(sid, ("", {}))
        draft = CandidateDraft(
            candidate_id=f"{source_type}:{sid}",
            source_type=source_type,
            doc_id=str(row.get("doc_id") or ""),
            summary_id=sid,
            source_path=str(row.get("source_path") or ""),
            title=str(row.get("title") or ""),
            text=text,
            metadata={"publication_id": row.get("publication_id"), "dense_similarity": round(hit.score, 6)},
        )
        candidate = get_or_create(candidates, draft)
        if text and not candidate.text:
            candidate.text = text
        candidate.add_component(
            "summary_vector",
            rank_component(rank, rrf_k=rrf_k, weight=weights.summary_vector),
            f"{source_type} vector rank {rank}, similarity {hit.score:.4f}",
        )
        add_text_signal_components(candidate, signals=signals, config=config, weights=weights, row=original_row)
    return len(hits)


def add_table_candidates(
    candidates: dict[str, CandidateDraft],
    *,
    query: str,
    root: Path,
    table_roots: Iterable[Path],
    documents_path: Path | None,
    tables_path: Path | None,
    top_k: int,
    rrf_k: int,
    signals: QuerySignals,
    config: dict[str, Any],
    weights: SignalWeights,
    diagnostics: RetrievalDiagnostics,
) -> int:
    if top_k <= 0 or not documents_path or not tables_path:
        return 0
    try:
        from app.query.csv_corpus import row_to_text, search_tables

        hits = search_tables(
            query,
            roots=table_roots,
            documents_path=documents_path,
            tables_path=tables_path,
            project_root=root,
            top_k=top_k,
        )
    except Exception as exc:  # noqa: BLE001 - table search is optional for hybrid.
        diagnostics.add_warning(f"table search skipped: {exc}")
        return 0
    for rank, hit in enumerate(hits, start=1):
        summary = hit.summary
        rows_text = "\n".join(row_to_text(row) for row in hit.rows)
        text = field_text(summary.preview, " ".join(summary.columns), rows_text)
        path_key = str(summary.path).replace("\\", "/")
        table_key = summary.table_id or f"{path_key}:{summary.sheet}"
        candidate = get_or_create(
            candidates,
            CandidateDraft(
                candidate_id=f"table:{table_key}",
                source_type="table",
                doc_id=summary.doc_id,
                source_path=summary.source_path or str(summary.path),
                local_path=str(summary.path),
                title=summary.sheet or summary.table_id or summary.path.name,
                text=text,
                metadata={
                    "table_id": summary.table_id,
                    "sheet": summary.sheet,
                    "row_count": summary.row_count,
                    "matched_terms": list(hit.matched_terms),
                },
            ),
        )
        candidate.add_component("table", rank_component(rank, rrf_k=rrf_k, weight=weights.table), f"table rank {rank}, score {hit.score:.3f}")
        add_text_signal_components(candidate, signals=signals, config=config, weights=weights)
    return len(hits)


def add_graph_candidates(
    candidates: dict[str, CandidateDraft],
    *,
    query: str,
    nodes_path: Path | None,
    edges_path: Path | None,
    top_k: int,
    rrf_k: int,
    signals: QuerySignals,
    config: dict[str, Any],
    weights: SignalWeights,
    diagnostics: RetrievalDiagnostics,
) -> int:
    if top_k <= 0 or not nodes_path or not edges_path or not nodes_path.exists() or not edges_path.exists():
        return 0
    try:
        from app.graph.search import load_graph, node_text, search_entities

        nodes, edges = load_graph(nodes_path, edges_path)
        hits = search_entities(nodes, query, top_k=top_k)
    except Exception as exc:  # noqa: BLE001 - graph search is optional for hybrid.
        diagnostics.add_warning(f"graph search skipped: {exc}")
        return 0
    _ = edges
    for rank, hit in enumerate(hits, start=1):
        node = hit.node
        doc_ids = node.get("doc_ids") if isinstance(node.get("doc_ids"), list) else []
        metadata = node.get("metadata") if isinstance(node.get("metadata"), dict) else {}
        candidate = get_or_create(
            candidates,
            CandidateDraft(
                candidate_id=f"graph:{node.get('node_id')}",
                source_type="graph",
                doc_id=str(doc_ids[0]) if doc_ids else str(metadata.get("doc_id") or ""),
                source_path=str(metadata.get("source_path") or ""),
                title=str(node.get("label") or ""),
                text=node_text(node),
                metadata={
                    "node_id": node.get("node_id"),
                    "node_type": node.get("type"),
                    "matched_terms": list(hit.matched_terms),
                },
            ),
        )
        candidate.add_component("graph", rank_component(rank, rrf_k=rrf_k, weight=weights.graph), f"graph rank {rank}, score {hit.score:.3f}")
        add_text_signal_components(candidate, signals=signals, config=config, weights=weights)
    return len(hits)


def resolve_query_model(manifest: dict[str, Any], requested: str) -> str:
    if requested == "auto":
        return "fallback" if manifest.get("model_selection") == "fallback" else "query"
    return requested


def dense_query_vector_for_index(
    *,
    query: str,
    retrieval_config: dict[str, Any],
    index_dir: Path,
    model: str,
    embedding_backend: str | None,
    allow_network: bool,
    api_key: str | None,
    folder_id: str | None,
    diagnostics: RetrievalDiagnostics,
    require_dense: bool,
) -> list[float] | None:
    from app.index.embeddings import build_embedding_client

    manifest = load_manifest(index_dir)
    if not manifest:
        message = f"vector manifest not found in {index_dir}"
        if require_dense:
            raise RuntimeError(message)
        diagnostics.dense_status = "missing_index"
        diagnostics.add_warning(message)
        return None
    backend = str(manifest.get("embedding_backend") or (retrieval_config.get("embedding") or {}).get("backend") or "yandex")
    diagnostics.dense_index_backend = backend
    if embedding_backend and embedding_backend != backend:
        message = f"query backend {embedding_backend} is not compatible with index backend {backend}"
        if require_dense:
            raise RuntimeError(message)
        diagnostics.dense_status = "incompatible_backend"
        diagnostics.add_warning(message)
        return None
    if backend == "yandex" and not allow_network:
        message = "dense search skipped in offline mode for a Yandex embedding index"
        if require_dense:
            raise RuntimeError(message)
        diagnostics.dense_status = "skipped_offline"
        diagnostics.add_warning(message)
        return None

    query_model = resolve_query_model(manifest, model)
    diagnostics.dense_model_selection = query_model
    if backend == "yandex":
        manifest_selection = "fallback" if manifest.get("model_selection") == "fallback" else "query"
        if query_model != manifest_selection:
            message = f"query model {query_model} is not compatible with index model_selection {manifest_selection}"
            if require_dense:
                raise RuntimeError(message)
            diagnostics.dense_status = "incompatible_model"
            diagnostics.add_warning(message)
            return None
    try:
        client = build_embedding_client(
            backend=backend,
            retrieval_config=retrieval_config,
            kind="query",
            fallback_model=query_model == "fallback",
            api_key=api_key,
            folder_id=folder_id,
        )
        vector = client.embed_text(query)
    except Exception as exc:  # noqa: BLE001 - hybrid should degrade to lexical/offline streams.
        message = f"dense query embedding failed: {str(exc)[:500]}"
        if require_dense:
            raise RuntimeError(message) from exc
        diagnostics.dense_status = "embedding_failed"
        diagnostics.add_warning(message)
        return None
    expected_dim = int(manifest.get("dimension") or 0)
    if expected_dim and len(vector) != expected_dim:
        message = f"query embedding dimension {len(vector)} does not match index dimension {expected_dim}"
        if require_dense:
            raise RuntimeError(message)
        diagnostics.dense_status = "incompatible_dimension"
        diagnostics.add_warning(message)
        return None
    diagnostics.dense_status = "ok"
    return vector


def auxiliary_query_vector_for_index(
    *,
    query: str,
    retrieval_config: dict[str, Any],
    index_dir: Path,
    model: str,
    allow_network: bool,
    api_key: str | None,
    folder_id: str | None,
    diagnostics: RetrievalDiagnostics,
    stream_name: str,
) -> list[float] | None:
    previous = (
        diagnostics.dense_status,
        diagnostics.dense_index_backend,
        diagnostics.dense_model_selection,
    )
    before_warning_count = len(diagnostics.warnings)
    try:
        vector = dense_query_vector_for_index(
            query=query,
            retrieval_config=retrieval_config,
            index_dir=index_dir,
            model=model,
            embedding_backend=None,
            allow_network=allow_network,
            api_key=api_key,
            folder_id=folder_id,
            diagnostics=diagnostics,
            require_dense=False,
        )
        aux_status = diagnostics.dense_status
    finally:
        diagnostics.dense_status, diagnostics.dense_index_backend, diagnostics.dense_model_selection = previous
    if len(diagnostics.warnings) > before_warning_count:
        diagnostics.warnings[-1] = f"{stream_name}: {diagnostics.warnings[-1]}"
    diagnostics.streams[f"{stream_name}_query_embedding"] = 1 if aux_status == "ok" else 0
    return vector


def hybrid_search(
    *,
    query: str,
    retrieval_config: dict[str, Any],
    index_dir: Path,
    lexical_dir: Path,
    chunks_path: Path,
    top_k: int = 10,
    mode: SearchMode = "hybrid",
    dense_top_k: int | None = None,
    lexical_top_k: int | None = None,
    summary_top_k: int | None = None,
    table_top_k: int | None = None,
    graph_top_k: int | None = None,
    snippet_chars: int | None = None,
    rrf_k: int | None = None,
    vector_batch_size: int | None = None,
    allow_network: bool = True,
    embedding_backend: str | None = None,
    model: str = "auto",
    api_key: str | None = None,
    folder_id: str | None = None,
    root: Path | None = None,
    publications_dir: Path | None = None,
    document_summary_index_dir: Path | None = None,
    procedure_summary_index_dir: Path | None = None,
    table_roots: Iterable[Path] = (),
    documents_path: Path | None = None,
    tables_path: Path | None = None,
    graph_nodes_path: Path | None = None,
    graph_edges_path: Path | None = None,
    include_summaries: bool = True,
    include_tables: bool = False,
    include_graph: bool = False,
) -> tuple[list[RetrievalResult], RetrievalDiagnostics]:
    search_config = retrieval_config.get("search") or {}
    signals = extract_query_signals(query, retrieval_config)
    diagnostics = RetrievalDiagnostics(query=signals, mode=mode)
    weights = SignalWeights.from_config(retrieval_config)
    dense_top_k = dense_top_k if dense_top_k is not None else int(search_config.get("dense_top_k") or 50)
    lexical_top_k = lexical_top_k if lexical_top_k is not None else int(search_config.get("lexical_top_k") or 50)
    summary_top_k = summary_top_k if summary_top_k is not None else int(search_config.get("summary_top_k") or 30)
    table_top_k = table_top_k if table_top_k is not None else int(search_config.get("table_top_k") or 8)
    graph_top_k = graph_top_k if graph_top_k is not None else int(search_config.get("graph_top_k") or 8)
    snippet_chars = snippet_chars if snippet_chars is not None else int(search_config.get("snippet_chars") or 700)
    rrf_k = rrf_k if rrf_k is not None else int(search_config.get("rrf_k") or 60)
    vector_batch_size = vector_batch_size if vector_batch_size is not None else int(search_config.get("vector_batch_size") or 8192)

    candidates: dict[str, CandidateDraft] = {}
    metadata_by_row = {int(row["row_id"]): row for row in load_metadata(index_dir)}
    query_vector: list[float] | None = None

    if mode in {"hybrid", "dense"}:
        query_vector = dense_query_vector_for_index(
            query=signals.search_query,
            retrieval_config=retrieval_config,
            index_dir=index_dir,
            model=model,
            embedding_backend=embedding_backend,
            allow_network=allow_network,
            api_key=api_key,
            folder_id=folder_id,
            diagnostics=diagnostics,
            require_dense=mode == "dense",
        )
        if query_vector is not None:
            try:
                dense_hits = dense_search(index_dir, query_vector, top_k=dense_top_k if mode == "hybrid" else top_k, batch_size=vector_batch_size)
            except Exception as exc:  # noqa: BLE001
                if mode == "dense":
                    raise
                dense_hits = []
                diagnostics.dense_status = "search_failed"
                diagnostics.add_warning(f"dense vector search failed: {exc}")
            add_raw_dense_candidates(candidates, dense_hits=dense_hits, metadata_by_row=metadata_by_row, rrf_k=rrf_k, weights=weights)
            diagnostics.streams["raw_dense"] = len(dense_hits)

    if mode in {"hybrid", "lexical"}:
        lexical_index = LexicalIndex(lexical_dir)
        if lexical_index.exists():
            lexical_hits = lexical_search(lexical_dir, signals.search_query, top_k=lexical_top_k if mode == "hybrid" else top_k)
            add_raw_lexical_candidates(candidates, lexical_hits=lexical_hits, metadata_by_row=metadata_by_row, rrf_k=rrf_k, weights=weights)
            diagnostics.streams["raw_lexical"] = len(lexical_hits)
        elif mode == "lexical":
            raise RuntimeError(f"lexical index not found in {lexical_dir}; run scripts/build_indexes.py first")

    materialize_raw_candidates(candidates, chunks_path=chunks_path, signals=signals, config=retrieval_config, weights=weights)

    if mode == "hybrid" and include_summaries:
        diagnostics.streams["summary_lexical"] = add_summary_lexical_candidates(
            candidates,
            signals=signals,
            publications_dir=publications_dir,
            top_k=summary_top_k,
            rrf_k=rrf_k,
            config=retrieval_config,
            weights=weights,
        )
        if document_summary_index_dir and (document_summary_index_dir / VECTOR_FILE).exists() and (document_summary_index_dir / MANIFEST_FILE).exists():
            document_query_vector = auxiliary_query_vector_for_index(
                query=signals.search_query,
                retrieval_config=retrieval_config,
                index_dir=document_summary_index_dir,
                model=model,
                allow_network=allow_network,
                api_key=api_key,
                folder_id=folder_id,
                diagnostics=diagnostics,
                stream_name="document_summary_vector",
            )
            diagnostics.streams["document_summary_vector"] = add_summary_vector_candidates(
                candidates,
                summary_index_dir=document_summary_index_dir,
                source_type="document_summary",
                query_vector=document_query_vector,
                top_k=summary_top_k,
                rrf_k=rrf_k,
                batch_size=vector_batch_size,
                signals=signals,
                config=retrieval_config,
                weights=weights,
                diagnostics=diagnostics,
            )
        if procedure_summary_index_dir and (procedure_summary_index_dir / VECTOR_FILE).exists() and (procedure_summary_index_dir / MANIFEST_FILE).exists():
            procedure_query_vector = auxiliary_query_vector_for_index(
                query=signals.search_query,
                retrieval_config=retrieval_config,
                index_dir=procedure_summary_index_dir,
                model=model,
                allow_network=allow_network,
                api_key=api_key,
                folder_id=folder_id,
                diagnostics=diagnostics,
                stream_name="procedure_summary_vector",
            )
            diagnostics.streams["procedure_summary_vector"] = add_summary_vector_candidates(
                candidates,
                summary_index_dir=procedure_summary_index_dir,
                source_type="procedure_summary",
                query_vector=procedure_query_vector,
                top_k=summary_top_k,
                rrf_k=rrf_k,
                batch_size=vector_batch_size,
                signals=signals,
                config=retrieval_config,
                weights=weights,
                diagnostics=diagnostics,
            )

    if mode == "hybrid" and include_tables and root is not None:
        diagnostics.streams["tables"] = add_table_candidates(
            candidates,
            query=signals.search_query,
            root=root,
            table_roots=table_roots,
            documents_path=documents_path,
            tables_path=tables_path,
            top_k=table_top_k,
            rrf_k=rrf_k,
            signals=signals,
            config=retrieval_config,
            weights=weights,
            diagnostics=diagnostics,
        )

    if mode == "hybrid" and include_graph:
        diagnostics.streams["graph"] = add_graph_candidates(
            candidates,
            query=signals.search_query,
            nodes_path=graph_nodes_path,
            edges_path=graph_edges_path,
            top_k=graph_top_k,
            rrf_k=rrf_k,
            signals=signals,
            config=retrieval_config,
            weights=weights,
            diagnostics=diagnostics,
        )

    if mode == "dense" and not candidates:
        raise RuntimeError("dense search returned no candidates")

    ranked = sorted(candidates.values(), key=lambda candidate: (candidate.score, candidate.components.get("domain", 0.0), candidate.components.get("phrase", 0.0)), reverse=True)
    return materialize_candidate_results(ranked[:top_k], snippet_chars=snippet_chars), diagnostics


def materialize_candidate_results(candidates: list[CandidateDraft], *, snippet_chars: int) -> list[RetrievalResult]:
    results: list[RetrievalResult] = []
    for rank, candidate in enumerate(candidates, start=1):
        text = candidate.text
        if snippet_chars > 0 and len(text) > snippet_chars:
            text = text[: snippet_chars - 3].rstrip() + "..."
        results.append(
            RetrievalResult(
                rank=rank,
                score=candidate.score,
                chunk_id=candidate.chunk_id,
                doc_id=candidate.doc_id,
                chunk_index=candidate.chunk_index,
                source_path=candidate.source_path,
                local_path=candidate.local_path,
                text=text,
                candidate_id=candidate.candidate_id,
                source_type=candidate.source_type,
                summary_id=candidate.summary_id,
                title=candidate.title,
                components=candidate.components,
                reasons=candidate.reasons,
                metadata=candidate.metadata,
            )
        )
    return results


def materialize_results(
    *,
    ranked_rows: list[tuple[int, float, dict[str, float]]],
    index_dir: Path,
    chunks_path: Path,
    snippet_chars: int,
) -> list[RetrievalResult]:
    metadata = {int(row["row_id"]): row for row in load_metadata(index_dir)}
    chunk_ids = {str(metadata[row_id].get("chunk_id") or "") for row_id, _, _ in ranked_rows if row_id in metadata}
    texts = load_chunk_texts(chunks_path, chunk_ids)
    results: list[RetrievalResult] = []
    for rank, (row_id, score, components) in enumerate(ranked_rows, start=1):
        row = metadata.get(row_id)
        if not row:
            continue
        chunk_id = str(row.get("chunk_id") or "")
        text = texts.get(chunk_id, "")
        if snippet_chars > 0 and len(text) > snippet_chars:
            text = text[: snippet_chars - 3].rstrip() + "..."
        results.append(
            RetrievalResult(
                rank=rank,
                score=score,
                chunk_id=chunk_id,
                doc_id=str(row.get("doc_id") or ""),
                chunk_index=row.get("chunk_index"),
                source_path=str(row.get("source_path") or ""),
                local_path=str(row.get("local_path") or ""),
                text=text,
                candidate_id=f"raw_chunk:{chunk_id}",
                source_type="raw_chunk",
                components=components,
            )
        )
    return results
