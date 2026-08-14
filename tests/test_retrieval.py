from __future__ import annotations

from dataclasses import fields
from hashlib import sha256
import json
from pathlib import Path
from uuid import uuid4

import pytest
from llama_index.core.base.embeddings.base import BaseEmbedding
from llama_index.core.schema import NodeWithScore, TextNode

from app.constants import AuthorityLevel, SourceKind, VersionStatus
from app.contracts import (
    GuidelineInput,
    NodeManifestRecord,
    RawChunkRecord,
    SearchRequest,
    SearchResponse,
    SourceFileRecord,
    VersionInput,
)
from app.index_store import IndexSnapshotStore, NodeBuildContext, ProvenanceNodeBuilder, SnapshotIntegrityError
from app.registry import Registry
from app.retrieval import EvidenceRetriever, rrf_merge
import app.retrieval as retrieval_module


PROJECT_ROOT = Path(__file__).resolve().parents[1]


class TerminologyEmbedding(BaseEmbedding):
    """Offline embedding that maps a bilingual oncology term to one concept."""

    model_name: str = "test-bilingual-terminology"

    @staticmethod
    def _vector(text: str) -> list[float]:
        lowered = text.casefold()
        if "trastuzumab" in lowered or "曲妥珠单抗" in text:
            return [1.0, 0.0, 0.0]
        if "surgery" in lowered or "手术" in text:
            return [0.0, 1.0, 0.0]
        return [0.0, 0.0, 1.0]

    def _get_query_embedding(self, query: str) -> list[float]:
        return self._vector(query)

    async def _aget_query_embedding(self, query: str) -> list[float]:
        return self._vector(query)

    def _get_text_embedding(self, text: str) -> list[float]:
        return self._vector(text)


def _task_dir() -> Path:
    path = PROJECT_ROOT / "data" / "runtime_cache" / "test_task5_retrieval" / uuid4().hex
    path.mkdir(parents=True)
    return path


def _chunk(source_id: str, chunk_id: str, text: str, *, language: str) -> RawChunkRecord:
    payload = {
        "chunk_id": chunk_id,
        "doc_id": source_id,
        "doc_title": f"{source_id} breast cancer",
        "section_path": "HER2-positive disease",
        "page_code": "BINV-1" if language == "en" else "乳腺癌-1",
        "page_start": 0,
        "page_end": 0,
        "block_type": "paragraph",
        "text": text,
    }
    return RawChunkRecord(
        id=f"{source_id}:{chunk_id}",
        source_file_id=source_id,
        source_ordinal=1,
        chunk_id=chunk_id,
        text=text,
        content_sha256=sha256(text.encode("utf-8")).hexdigest(),
        locator_json=json.dumps(payload, ensure_ascii=False),
    )


def _add_version(
    registry: Registry,
    store: IndexSnapshotStore,
    *,
    guideline_id: str,
    version_id: str,
    language: str,
    text: str,
    approve: bool,
) -> None:
    version = registry.create_draft_version(
        VersionInput(id=version_id, guideline_id=guideline_id, version_label=version_id),
        actor="fixture",
    )
    chunk = _chunk(f"{version_id}-source", f"{version_id}-chunk", text, language=language)
    node = ProvenanceNodeBuilder().build(
        [chunk],
        NodeBuildContext(
            guideline_id=guideline_id,
            version_id=version_id,
            language=language,
            authority_level=AuthorityLevel.PRIMARY_GUIDELINE,
            source_sha256="a" * 64,
            source_kind=SourceKind.PDF,
        ),
    )[0]
    registry.add_source_file(
        SourceFileRecord(
            id=chunk.source_file_id,
            version_id=version_id,
            source_kind=SourceKind.PDF,
            original_path=f"D:/fixture/{version_id}.pdf",
            managed_path=f"D:/managed/{version_id}.pdf",
            sha256="a" * 64,
            byte_size=1,
        ),
        actor="fixture",
    )
    registry.add_raw_chunks([chunk], actor="fixture")
    registry.add_node_manifest(
        [
            NodeManifestRecord(
                node_id=node.node_id,
                version_id=version_id,
                raw_chunk_id=chunk.id,
                fragment_ordinal=0,
                source_ordinal=chunk.source_ordinal,
                content_sha256=chunk.content_sha256,
                char_start=0,
                char_end=len(chunk.text),
                metadata_json=json.dumps(node.metadata, ensure_ascii=False),
            )
        ],
        actor="fixture",
    )
    snapshot = store.build(version, [node])
    registry.set_draft_snapshot(
        version_id,
        snapshot_path=str(snapshot.path),
        snapshot_manifest_sha256=snapshot.manifest_sha256,
        actor="fixture",
    )
    if approve:
        registry.approve_version(
            version_id,
            actor="reviewer",
            snapshot_manifest_sha256=snapshot.manifest_sha256,
        )


def _system() -> tuple[Registry, IndexSnapshotStore, EvidenceRetriever]:
    root = _task_dir()
    registry = Registry(root / "registry.sqlite3")
    registry.initialize()
    for guideline_id, language in (("nccn", "en"), ("caca", "zh")):
        registry.create_guideline(
            GuidelineInput(
                id=guideline_id,
                title=guideline_id.upper(),
                language=language,
                authority_level=AuthorityLevel.PRIMARY_GUIDELINE,
            ),
            actor="fixture",
        )
    embed = TerminologyEmbedding()
    store = IndexSnapshotStore(
        root / "indices",
        embed_model=embed,
        model_metadata={"provider": "test", "model_name": embed.model_name, "embed_dim": 3},
    )
    _add_version(
        registry,
        store,
        guideline_id="nccn",
        version_id="nccn-old",
        language="en",
        text="Earlier trastuzumab evidence.",
        approve=True,
    )
    _add_version(
        registry,
        store,
        guideline_id="nccn",
        version_id="nccn-active",
        language="en",
        text="Current trastuzumab recommendation.",
        approve=True,
    )
    _add_version(
        registry,
        store,
        guideline_id="caca",
        version_id="caca-active",
        language="zh",
        text="当前推荐曲妥珠单抗治疗。",
        approve=True,
    )
    _add_version(
        registry,
        store,
        guideline_id="caca",
        version_id="caca-draft",
        language="zh",
        text="草案中的曲妥珠单抗内容。",
        approve=False,
    )
    return registry, store, EvidenceRetriever(registry=registry, index_store=store)


def test_search_response_contract_contains_evidence_only_and_defaults_to_active_versions() -> None:
    _, _, retriever = _system()

    response = retriever.search(SearchRequest(query="曲妥珠单抗", top_k=10))

    assert {item.name for item in fields(SearchResponse)} == {
        "evidence",
        "resolved_version_ids",
        "retrieval_modes",
    }
    assert response.resolved_version_ids == ("caca-active", "nccn-active")
    assert {item.version_id for item in response.evidence} == {"caca-active", "nccn-active"}
    assert all(item.text and item.citation.raw_chunk_id == item.raw_chunk_id for item in response.evidence)
    assert all(item.authority_level == "primary_guideline" for item in response.evidence)
    assert response.retrieval_modes[0] == "vector"


def test_explicit_superseded_version_is_searchable_but_draft_is_rejected() -> None:
    _, _, retriever = _system()

    historical = retriever.search(
        SearchRequest(query="trastuzumab", version_ids=("nccn-old",), top_k=2)
    )
    assert historical.resolved_version_ids == ("nccn-old",)
    assert [item.version_id for item in historical.evidence] == ["nccn-old"]

    with pytest.raises(ValueError, match="draft version is not searchable"):
        retriever.search(
            SearchRequest(query="曲妥珠单抗", version_ids=("caca-draft",))
        )


def test_filters_and_bilingual_vector_retrieval_work_in_both_directions() -> None:
    _, _, retriever = _system()

    chinese_to_english = retriever.search(
        SearchRequest(query="曲妥珠单抗", language="en", top_k=1)
    )
    english_to_chinese = retriever.search(
        SearchRequest(query="trastuzumab", guideline_ids=("caca",), top_k=1)
    )

    assert chinese_to_english.evidence[0].language == "en"
    assert "trastuzumab" in chinese_to_english.evidence[0].text
    assert english_to_chinese.evidence[0].language == "zh"
    assert "曲妥珠单抗" in english_to_chinese.evidence[0].text


def test_missing_or_corrupt_explicit_history_raises_without_falling_back_to_active() -> None:
    registry, _, retriever = _system()
    old = registry.get_version("nccn-old")
    manifest = Path(old.snapshot_path) / "manifest.json"
    manifest.write_bytes(manifest.read_bytes() + b"corrupt")

    with pytest.raises(SnapshotIntegrityError):
        retriever.search(
            SearchRequest(query="trastuzumab", version_ids=("nccn-old",))
        )


def test_rrf_is_deterministic_and_deduplicates_by_node_id() -> None:
    a = TextNode(id_="a", text="A")
    b = TextNode(id_="b", text="B")
    vector = [NodeWithScore(node=a, score=0.9), NodeWithScore(node=b, score=0.8)]
    bm25 = [NodeWithScore(node=b, score=12.0), NodeWithScore(node=a, score=3.0)]

    merged = rrf_merge(vector, bm25, k=60)

    assert [item.node.node_id for item in merged] == ["a", "b"]
    assert len(merged) == 2
    assert merged[0].score == merged[1].score


def test_bm25_is_explicitly_reported_when_available() -> None:
    _, _, retriever = _system()

    response = retriever.search(
        SearchRequest(query="trastuzumab", language="en", top_k=2, use_bm25=True)
    )

    assert response.retrieval_modes == ("vector", "bm25")
    assert response.evidence


def test_bm25_import_unavailability_is_exposed_as_vector_only(monkeypatch) -> None:
    _, _, retriever = _system()
    monkeypatch.setattr(retrieval_module, "BM25Retriever", None)

    response = retriever.search(
        SearchRequest(query="trastuzumab", language="en", top_k=1, use_bm25=True)
    )

    assert response.retrieval_modes == ("vector",)


def test_invalid_request_is_rejected_before_any_snapshot_load() -> None:
    registry, store, _ = _system()

    class LoadCountingStore:
        def __init__(self) -> None:
            self.index_root = store.index_root
            self.loads = 0

        def load(self, snapshot):
            self.loads += 1
            return store.load(snapshot)

    counting = LoadCountingStore()
    retriever = EvidenceRetriever(registry=registry, index_store=counting)

    with pytest.raises(ValueError, match="top_k"):
        retriever.search(SearchRequest(query="trastuzumab", top_k=0))
    with pytest.raises(ValueError, match="does not belong"):
        retriever.search(
            SearchRequest(
                query="trastuzumab",
                guideline_ids=("caca",),
                version_ids=("nccn-old",),
            )
        )
    assert counting.loads == 0
