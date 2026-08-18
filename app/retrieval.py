from __future__ import annotations

from collections import defaultdict
import math
from pathlib import Path
import re
from typing import Callable, Iterable, Sequence

from llama_index.core.schema import BaseNode, NodeWithScore
from llama_index.core.indices.vector_store.retrievers import VectorIndexRetriever

from app.citation import format_citation
from app.constants import VersionStatus
from app.contracts import Evidence, SearchRequest, SearchResponse, VersionRecord
from app.index_store import IndexSnapshotStore, SnapshotInfo
from app.registry import Registry
from app.terminology import expand_query, tokenize_query

try:
    from llama_index.retrievers.bm25 import BM25Retriever
except ImportError:  # Vector retrieval remains an explicit, observable baseline.
    BM25Retriever = None

try:
    import bm25s
except ImportError:  # pragma: no cover - covered by the BM25 availability test.
    bm25s = None


class EvidenceRetriever:
    """Retrieve version-scoped source evidence without response synthesis or an LLM."""

    def __init__(
        self,
        *,
        registry: Registry,
        index_store: IndexSnapshotStore,
        resolve_project_path: Callable[[str | Path], Path] | None = None,
        glossary_terms: dict[str, tuple[str, ...]] | None = None,
    ) -> None:
        self._registry = registry
        self._index_store = index_store
        self._resolve_project_path = resolve_project_path or Path
        self._glossary_terms = glossary_terms or {}

    def search(self, request: SearchRequest) -> SearchResponse:
        versions = self._resolve_versions(request)
        modes = (
            ("vector", "bm25")
            if request.use_bm25 and BM25Retriever is not None and bm25s is not None
            else ("vector",)
        )
        ranked: list[NodeWithScore] = []
        query = expand_query(request.query, self._glossary_terms)

        for version in versions:
            index = self._index_store.load(self._snapshot(version))
            all_nodes = _docstore_nodes(index.docstore.docs.values())
            indexable_nodes = [node for node in all_nodes if is_indexable_node(node)]
            indexable_ids = [node.node_id for node in indexable_nodes]
            vector = (
                VectorIndexRetriever(
                    index=index,
                    similarity_top_k=min(request.top_k, len(indexable_ids)),
                    node_ids=indexable_ids,
                    callback_manager=index._callback_manager,
                    object_map=index._object_map,
                ).retrieve(query)
                if indexable_ids
                else []
            )
            if len(modes) == 2:
                bm25 = retrieve_bm25(indexable_nodes, query, request.top_k)
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
    bm25 = filter_positive_bm25(bm25)
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


def bm25_tokenizer(text: str) -> list[str]:
    """Return BM25 tokens with Chinese character n-grams and bilingual terms."""
    return list(tokenize_query(text))


def filter_positive_bm25(items: Sequence[NodeWithScore]) -> list[NodeWithScore]:
    """Drop BM25 candidates whose raw score cannot support a lexical match."""
    return [
        item
        for item in items
        if item.score is not None
        and math.isfinite(float(item.score))
        and float(item.score) > 0.0
    ]


def retrieve_bm25(
    nodes: Sequence[BaseNode], query: str, top_k: int
) -> list[NodeWithScore]:
    """Retrieve positive BM25 matches using a deterministic custom tokenizer."""
    if bm25s is None or top_k <= 0 or not nodes:
        return []
    tokenized_nodes = [
        (node, bm25_tokenizer(node.get_content(metadata_mode="none")))
        for node in nodes
    ]
    tokenized_nodes = [(node, tokens) for node, tokens in tokenized_nodes if tokens]
    query_tokens = bm25_tokenizer(query)
    if not tokenized_nodes or not query_tokens:
        return []

    engine = bm25s.BM25()
    engine.index([tokens for _, tokens in tokenized_nodes], show_progress=False)
    limit = min(top_k, len(tokenized_nodes))
    indexes, scores = engine.retrieve(
        [query_tokens],
        k=limit,
        show_progress=False,
    )
    items = [
        NodeWithScore(
            node=tokenized_nodes[int(indexes[0][position])][0],
            score=float(scores[0][position]),
        )
        for position in range(len(indexes[0]))
    ]
    return filter_positive_bm25(items)


def is_indexable_node(node: BaseNode) -> bool:
    """Decide whether an existing node should participate in semantic search."""
    metadata = node.metadata
    explicit = metadata.get("indexable")
    if explicit is not None:
        if isinstance(explicit, str):
            return explicit.strip().casefold() not in {"false", "0", "no"}
        return bool(explicit)

    text = node.get_content(metadata_mode="none").strip()
    if not text:
        return False
    if re.fullmatch(r"[\d\s./:;,_-]+", text):
        return False

    block_type = str(metadata.get("block_type", "")).casefold()
    if block_type in {"table", "table_row", "algorithm"}:
        return True

    page_start = _page_number(metadata.get("page_start"))
    section = str(metadata.get("section_path", "")).casefold()
    if any(
        marker in section
        for marker in (
            "图书在版",
            "指南工作委员会",
            "table of contents",
            "copyright",
            "front matter",
            "front-matter",
            "目录",
            "cip",
        )
    ):
        return False

    role = str(metadata.get("retrieval_role", "")).casefold()
    if role in {"cover", "toc", "credits", "copyright", "legal", "metadata"}:
        return False
    if role == "front_matter" and not _has_clinical_content(text):
        return False

    # The first NCCN/CSCO records are title and publishing metadata. They are
    # retained in raw JSONL but should not compete with clinical evidence.
    if page_start is not None and page_start <= 1 and len(text) < 350:
        if _looks_like_guideline_identity(text):
            return False
    if page_start is not None and page_start <= 5 and len(text) < 700:
        if any(marker in text.casefold() for marker in ("isbn", "出版社", "定价", "publisher")):
            return False
    return True


def _page_number(value: object) -> int | None:
    try:
        return int(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def _looks_like_guideline_identity(text: str) -> bool:
    lowered = text.casefold()
    markers = ("guideline", "指南", "nccn", "csco", "caca", "breast cancer", "乳腺癌")
    return any(marker in lowered for marker in markers)


def _has_clinical_content(text: str) -> bool:
    lowered = text.casefold()
    markers = (
        "治疗",
        "诊断",
        "筛查",
        "乳腺癌",
        "therapy",
        "treatment",
        "recurrent",
        "metastatic",
        "breast cancer",
    )
    return any(marker in lowered for marker in markers) and len(text) >= 350


def _docstore_nodes(values: Iterable[BaseNode]) -> list[BaseNode]:
    return sorted(values, key=lambda node: node.node_id)
