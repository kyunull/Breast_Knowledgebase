from __future__ import annotations

from hashlib import sha256
import json
from pathlib import Path
import shutil
from uuid import uuid4

import pytest
from llama_index.core.embeddings import MockEmbedding

from app.constants import AuthorityLevel, SourceKind, VersionStatus
from app.contracts import RawChunkRecord, VersionRecord
from app.index_store import (
    IndexSnapshotStore,
    NodeBuildContext,
    ProvenanceNodeBuilder,
    SnapshotInfo,
    SnapshotIntegrityError,
)


def _task_dir() -> Path:
    path = Path(__file__).resolve().parents[1] / "data" / "runtime_cache" / "test_task3" / uuid4().hex
    path.mkdir(parents=True)
    return path


def _chunk(chunk_id: str = "nccn_v6_2026_0000", text: str = "HER2-positive treatment evidence") -> RawChunkRecord:
    return RawChunkRecord(
        id=f"source-1:{chunk_id}",
        source_file_id="source-1",
        source_ordinal=7,
        chunk_id=chunk_id,
        text=text,
        content_sha256=sha256(text.encode("utf-8")).hexdigest(),
        locator_json=json.dumps(
            {
                "chunk_id": chunk_id,
                "doc_id": "nccn-v6",
                "doc_title": "NCCN Breast Cancer",
                "section_path": "Systemic therapy",
                "page_code": "BINV-15",
                "page_start": 4,
                "page_end": 4,
                "block_type": "paragraph",
                "text": text,
            }
        ),
    )


def _context() -> NodeBuildContext:
    return NodeBuildContext(
        guideline_id="nccn",
        version_id="nccn-v6",
        language="en",
        authority_level=AuthorityLevel.PRIMARY_GUIDELINE,
        source_sha256="a" * 64,
        source_kind=SourceKind.PDF,
    )


def _version() -> VersionRecord:
    return VersionRecord(
        id="nccn-v6",
        guideline_id="nccn",
        version_label="6.2026",
        status=VersionStatus.DRAFT,
        snapshot_path=None,
        snapshot_manifest_sha256=None,
        published_at="2026-08-01",
        created_at="2026-08-14T00:00:00",
        approved_at=None,
    )


def _store(root: Path) -> IndexSnapshotStore:
    return IndexSnapshotStore(
        root,
        embed_model=MockEmbedding(embed_dim=8),
        model_metadata={"provider": "mock", "model_name": "mock-8", "embed_dim": 8},
    )


def test_node_builder_assigns_stable_id_and_complete_provenance() -> None:
    chunk = _chunk()

    nodes = ProvenanceNodeBuilder().build([chunk], _context())

    assert len(nodes) == 1
    node = nodes[0]
    assert node.node_id == "nccn:nccn-v6:nccn_v6_2026_0000:0"
    assert node.text == chunk.text
    assert node.start_char_idx == 0
    assert node.end_char_idx == len(chunk.text)
    assert node.metadata["raw_chunk_id"] == chunk.id
    assert node.metadata["source_ordinal"] == 7
    assert node.metadata["content_sha256"] == chunk.content_sha256
    assert node.metadata["fragment_ordinal"] == 0
    assert node.metadata["char_start"] == 0
    assert node.metadata["char_end"] == len(chunk.text)


def test_snapshot_build_verify_load_and_retrieve_without_model_download() -> None:
    root = _task_dir() / "indices"
    store = _store(root)
    nodes = ProvenanceNodeBuilder().build([_chunk()], _context())

    snapshot = store.build(_version(), nodes)

    assert snapshot.path == root / "nccn" / "nccn-v6"
    assert snapshot.path.is_dir()
    assert not any("staging" in item.name for item in snapshot.path.parent.iterdir())
    manifest_bytes = (snapshot.path / "manifest.json").read_bytes()
    manifest = json.loads(manifest_bytes)
    assert manifest_bytes == (json.dumps(manifest, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8")
    assert manifest["version_id"] == "nccn-v6"
    assert manifest["index_id"] == "nccn:nccn-v6"
    assert manifest["node_count"] == 1
    assert manifest["node_ids"] == ["nccn:nccn-v6:nccn_v6_2026_0000:0"]
    assert manifest["model"] == {"embed_dim": 8, "model_name": "mock-8", "provider": "mock"}
    assert list(manifest["component_hashes"]) == sorted(manifest["component_hashes"])
    assert snapshot.manifest_sha256 == sha256(manifest_bytes).hexdigest()

    store.verify(snapshot)
    loaded = store.load(snapshot)
    results = loaded.as_retriever(similarity_top_k=1).retrieve("HER2 treatment")
    assert results[0].node.node_id == manifest["node_ids"][0]
    assert results[0].node.metadata["raw_chunk_id"] == "source-1:nccn_v6_2026_0000"


def test_snapshot_verification_detects_component_corruption() -> None:
    store = _store(_task_dir() / "indices")
    nodes = ProvenanceNodeBuilder().build([_chunk()], _context())
    snapshot = store.build(_version(), nodes)
    manifest = json.loads((snapshot.path / "manifest.json").read_text(encoding="utf-8"))
    component = snapshot.path / next(iter(manifest["component_hashes"]))
    component.write_bytes(component.read_bytes() + b"corrupt")

    with pytest.raises(SnapshotIntegrityError, match="hash mismatch"):
        store.verify(snapshot)


def test_snapshot_verification_hashes_nested_file_named_manifest_json() -> None:
    store = _store(_task_dir() / "indices")
    snapshot = store.build(_version(), ProvenanceNodeBuilder().build([_chunk()], _context()))
    nested_manifest = snapshot.path / "nested" / "manifest.json"
    nested_manifest.parent.mkdir()
    nested_manifest.write_text("untracked", encoding="utf-8")

    with pytest.raises(SnapshotIntegrityError, match="component inventory mismatch"):
        store.verify(snapshot)


def test_snapshot_verification_rejects_a_copy_at_noncanonical_version_path() -> None:
    root = _task_dir() / "indices"
    store = _store(root)
    snapshot = store.build(_version(), ProvenanceNodeBuilder().build([_chunk()], _context()))
    copied_path = root / "nccn" / "wrong-location"
    shutil.copytree(snapshot.path, copied_path)
    copied_snapshot = SnapshotInfo(
        guideline_id=snapshot.guideline_id,
        version_id=snapshot.version_id,
        index_id=snapshot.index_id,
        path=copied_path,
        node_count=snapshot.node_count,
        manifest_sha256=snapshot.manifest_sha256,
    )

    with pytest.raises(SnapshotIntegrityError, match="canonical version directory"):
        store.verify(copied_snapshot)


def test_snapshot_build_never_overwrites_a_published_version() -> None:
    store = _store(_task_dir() / "indices")
    nodes = ProvenanceNodeBuilder().build([_chunk()], _context())
    first = store.build(_version(), nodes)
    original_manifest = (first.path / "manifest.json").read_bytes()

    with pytest.raises(FileExistsError, match="already exists"):
        store.build(_version(), nodes)

    assert (first.path / "manifest.json").read_bytes() == original_manifest


@pytest.mark.parametrize(
    "guideline_id,version_id",
    [
        ("..", "nccn-v6"),
        ("nccn", "../escape"),
        ("nccn:alternate", "nccn-v6"),
        ("CON", "nccn-v6"),
    ],
)
def test_snapshot_build_rejects_path_escape_components(guideline_id: str, version_id: str) -> None:
    store = _store(_task_dir() / "indices")
    version = _version()
    unsafe = VersionRecord(
        id=version_id,
        guideline_id=guideline_id,
        version_label=version.version_label,
        status=version.status,
        snapshot_path=None,
        snapshot_manifest_sha256=None,
        published_at=version.published_at,
        created_at=version.created_at,
        approved_at=None,
    )

    with pytest.raises(ValueError, match="safe path component"):
        store.build(unsafe, [])
