from __future__ import annotations

from collections import defaultdict
from pathlib import Path
from typing import Callable, Iterable, Sequence

from llama_index.core.schema import BaseNode, NodeWithScore

from app.citation import format_citation
from app.constants import VersionStatus
from app.contracts import Evidence, SearchRequest, SearchResponse, VersionRecord
from app.index_store import IndexSnapshotStore, SnapshotInfo
from app.registry import Registry

try:
    from llama_index.retrievers.bm25 import BM25Retriever
except ImportError:  # Vector retrieval remains an explicit, observable baseline.
    BM25Retriever = None


class EvidenceRetriever:
    """Retrieve version-scoped source evidence without response synthesis or an LLM."""

    def __init__(
        self,
        *,
        registry: Registry,
        index_store: IndexSnapshotStore,
        resolve_project_path: Callable[[str | Path], Path] | None = None,
    ) -> None:
        self._registry = registry
        self._index_store = index_store
        self._resolve_project_path = resolve_project_path or Path

    def search(self, request: SearchRequest) -> SearchResponse:
        versions = self._resolve_versions(request)
        modes = ("vector", "bm25") if request.use_bm25 and BM25Retriever is not None else ("vector",)
        ranked: list[NodeWithScore] = []

        for version in versions:
            index = self._index_store.load(self._snapshot(version))
            vector = index.as_retriever(similarity_top_k=request.top_k).retrieve(request.query)
            if len(modes) == 2:
                nodes = _docstore_nodes(index.docstore.docs.values())
                bm25 = BM25Retriever.from_defaults(
                    nodes=nodes,
                    similarity_top_k=request.top_k,
                ).retrieve(request.query)
                version_ranked = rrf_merge(vector, bm25, k=60)
            else:
                version_ranked = list(vector)
            ranked.extend(version_ranked)

        ranked.sort(key=lambda item: (-float(item.score or 0.0), item.node.node_id))
        evidence = tuple(self._to_evidence(item) for item in ranked[: request.top_k])
        return SearchResponse(
            evidence=evidence,
            resolved_version_ids=tuple(version.id for version in versions),
            retrieval_modes=modes,
        )

    def _resolve_versions(self, request: SearchRequest) -> list[VersionRecord]:
        query = request.query.strip()
        if not query:
            raise ValueError("query must not be empty")
        if not 1 <= request.top_k <= 100:
            raise ValueError("top_k must be between 1 and 100")
        guideline_filter = set(request.guideline_ids)
        if len(guideline_filter) != len(request.guideline_ids):
            raise ValueError("guideline_ids must not contain duplicates")
        if len(set(request.version_ids)) != len(request.version_ids):
            raise ValueError("version_ids must not contain duplicates")

        if request.version_ids:
            versions = [self._registry.get_version(version_id) for version_id in request.version_ids]
            for version in versions:
                if version.status is VersionStatus.DRAFT:
                    raise ValueError(f"draft version is not searchable: {version.id}")
                if guideline_filter and version.guideline_id not in guideline_filter:
                    raise ValueError(
                        f"version {version.id} does not belong to requested guideline_ids"
                    )
        else:
            versions = self._registry.list_searchable_versions()
            if guideline_filter:
                versions = [item for item in versions if item.guideline_id in guideline_filter]

        if request.language:
            versions = [
                item
                for item in versions
                if self._registry.get_guideline(item.guideline_id).language == request.language
            ]
        return sorted(versions, key=lambda item: item.id)

    def _snapshot(self, version: VersionRecord) -> SnapshotInfo:
        if not version.snapshot_path or not version.snapshot_manifest_sha256:
            raise ValueError(f"version has no registered snapshot: {version.id}")
        return SnapshotInfo(
            guideline_id=version.guideline_id,
            version_id=version.id,
            index_id=f"{version.guideline_id}:{version.id}",
            path=self._resolve_project_path(version.snapshot_path),
            node_count=self._registry.count_nodes_for_version(version.id),
            manifest_sha256=version.snapshot_manifest_sha256,
        )

    @staticmethod
    def _to_evidence(item: NodeWithScore) -> Evidence:
        metadata = item.node.metadata
        return Evidence(
            node_id=item.node.node_id,
            raw_chunk_id=str(metadata["raw_chunk_id"]),
            text=item.node.get_content(metadata_mode="none"),
            score=float(item.score or 0.0),
            guideline_id=str(metadata["guideline_id"]),
            version_id=str(metadata["version_id"]),
            language=str(metadata["language"]),
            authority_level=str(metadata["authority_level"]),
            citation=format_citation(metadata),
        )


def rrf_merge(
    vector: Sequence[NodeWithScore],
    bm25: Sequence[NodeWithScore],
    k: int = 60,
) -> list[NodeWithScore]:
    """Merge two rankings by reciprocal rank fusion, deduplicated by node ID."""
    if k <= 0:
        raise ValueError("RRF k must be positive")
    scores: dict[str, float] = defaultdict(float)
    nodes: dict[str, BaseNode] = {}
    for ranking in (vector, bm25):
        seen: set[str] = set()
        for rank, item in enumerate(ranking, start=1):
            node_id = item.node.node_id
            if node_id in seen:
                continue
            seen.add(node_id)
            nodes[node_id] = item.node
            scores[node_id] += 1.0 / (k + rank)
    return [
        NodeWithScore(node=nodes[node_id], score=scores[node_id])
        for node_id in sorted(scores, key=lambda value: (-scores[value], value))
    ]


def _docstore_nodes(values: Iterable[BaseNode]) -> list[BaseNode]:
    return sorted(values, key=lambda node: node.node_id)
