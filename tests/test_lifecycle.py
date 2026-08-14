from __future__ import annotations

import json
from pathlib import Path
from uuid import uuid4

import pytest
from llama_index.core.embeddings import MockEmbedding

from app.constants import AuthorityLevel, SourceKind, VersionStatus
from app.contracts import GuidelineInput, VersionInput
from app.index_store import IndexSnapshotStore, SnapshotIntegrityError
from app.ingestion import ManagedSourceInput
from app.lifecycle import GuidelineIngestRequest, GuidelineLifecycle
from app.registry import Registry


PROJECT_ROOT = Path(r"D:\coding\knowledgebase")


def _task_dir() -> Path:
    path = PROJECT_ROOT / "data" / "runtime_cache" / "test_task4_lifecycle" / uuid4().hex
    path.mkdir(parents=True)
    return path


def _write_inputs(root: Path, version_id: str, text: str) -> tuple[Path, Path]:
    source = root / f"{version_id}.pdf"
    source.write_bytes(b"%PDF-1.4\nfixture only\n")
    chunks = root / f"{version_id}.jsonl"
    payload = {
        "chunk_id": "shared-treatment-chunk",
        "doc_id": "nccn",
        "doc_title": "NCCN Breast Cancer",
        "section_path": "HER2-positive disease",
        "page_code": "BINV-1",
        "page_start": 0,
        "page_end": 0,
        "block_type": "paragraph",
        "text": text,
    }
    chunks.write_text(json.dumps(payload, ensure_ascii=False) + "\n", encoding="utf-8")
    return source, chunks


def _request(root: Path, version_id: str, label: str, text: str) -> GuidelineIngestRequest:
    source, chunks = _write_inputs(root, version_id, text)
    return GuidelineIngestRequest(
        version=VersionInput(id=version_id, guideline_id="nccn", version_label=label),
        language="en",
        authority_level=AuthorityLevel.PRIMARY_GUIDELINE,
        sources=(
            ManagedSourceInput(
                id=f"{version_id}-document",
                path=source,
                source_kind=SourceKind.PDF,
                provenance={"role": "citation_source"},
            ),
            ManagedSourceInput(
                id=f"{version_id}-chunks",
                path=chunks,
                source_kind=SourceKind.JSONL,
                provenance={"role": "chunk_input"},
            ),
        ),
        jsonl_source_id=f"{version_id}-chunks",
        citation_source_id=f"{version_id}-document",
    )


def _lifecycle(root: Path) -> tuple[Registry, GuidelineLifecycle]:
    registry = Registry(root / "registry" / "knowledge.sqlite3")
    registry.initialize()
    registry.create_guideline(
        GuidelineInput(
            id="nccn",
            title="NCCN Breast Cancer",
            language="en",
            authority_level=AuthorityLevel.PRIMARY_GUIDELINE,
        ),
        actor="operator",
    )
    store = IndexSnapshotStore(
        root / "indices",
        embed_model=MockEmbedding(embed_dim=8),
        model_metadata={"provider": "mock", "model_name": "mock-8", "embed_dim": 8},
    )
    lifecycle = GuidelineLifecycle(
        registry=registry,
        managed_sources_dir=root / "managed",
        index_store=store,
        project_root=PROJECT_ROOT,
    )
    return registry, lifecycle


def test_ingest_keeps_draft_unsearchable_and_approval_supersedes_atomically() -> None:
    root = _task_dir()
    registry, lifecycle = _lifecycle(root)

    first = lifecycle.ingest(_request(root, "nccn-v1", "1.2026", "First evidence"), actor="importer")

    assert first.status is VersionStatus.DRAFT
    assert first.snapshot_path == str(root / "indices" / "nccn" / "nccn-v1")
    assert first.snapshot_manifest_sha256 is not None
    assert registry.list_searchable_versions() == []
    assert registry.count_rows("raw_chunk") == 1
    assert registry.count_rows("node_manifest") == 1

    approved_first = lifecycle.approve(first.id, actor="reviewer-a")
    assert approved_first.status is VersionStatus.ACTIVE

    second = lifecycle.ingest(_request(root, "nccn-v2", "2.2026", "Second evidence"), actor="importer")
    automatic_diff = registry.list_version_diffs(first.id, second.id)
    assert len(automatic_diff) == 1
    assert automatic_diff[0].change_type.value == "modified"
    approved_second = lifecycle.approve(second.id, actor="reviewer-b")

    assert approved_second.status is VersionStatus.ACTIVE
    assert registry.get_version(first.id).status is VersionStatus.SUPERSEDED
    assert [item.id for item in registry.list_searchable_versions()] == ["nccn-v2"]
    assert [event.action for event in registry.list_audit()].count("ingest_succeeded") == 2


def test_approval_reverifies_snapshot_before_preserving_prior_active() -> None:
    root = _task_dir()
    registry, lifecycle = _lifecycle(root)
    first = lifecycle.ingest(_request(root, "nccn-v1", "1.2026", "First evidence"), actor="importer")
    lifecycle.approve(first.id, actor="reviewer-a")
    second = lifecycle.ingest(_request(root, "nccn-v2", "2.2026", "Second evidence"), actor="importer")
    manifest = json.loads((Path(second.snapshot_path) / "manifest.json").read_text(encoding="utf-8"))
    component_path = Path(second.snapshot_path) / next(iter(manifest["component_hashes"]))
    component_path.write_bytes(component_path.read_bytes() + b"tampered")

    with pytest.raises(SnapshotIntegrityError, match="hash mismatch"):
        lifecycle.approve(second.id, actor="reviewer-b")

    assert registry.get_version(first.id).status is VersionStatus.ACTIVE
    assert registry.get_version(second.id).status is VersionStatus.DRAFT
    failed = [
        event
        for event in registry.list_audit()
        if event.entity_id == second.id and event.action == "approval_failed"
    ]
    assert len(failed) == 1
    payload = json.loads(failed[0].payload_json)
    assert payload["error_type"] == "SnapshotIntegrityError"
    assert len(payload["message"]) <= 200


def test_approval_must_reload_the_index_before_changing_active_version() -> None:
    class LoadRejectingStore(IndexSnapshotStore):
        def load(self, snapshot):
            self.verify(snapshot)
            raise SnapshotIntegrityError("index cannot be reloaded")

    root = _task_dir()
    registry, lifecycle = _lifecycle(root)
    first = lifecycle.ingest(_request(root, "nccn-v1", "1.2026", "First evidence"), actor="importer")
    lifecycle.approve(first.id, actor="reviewer-a")
    second = lifecycle.ingest(_request(root, "nccn-v2", "2.2026", "Second evidence"), actor="importer")
    rejecting_store = LoadRejectingStore(
        root / "indices",
        embed_model=MockEmbedding(embed_dim=8),
        model_metadata={"provider": "mock", "model_name": "mock-8", "embed_dim": 8},
    )
    guarded = GuidelineLifecycle(
        registry=registry,
        managed_sources_dir=root / "managed",
        index_store=rejecting_store,
        project_root=PROJECT_ROOT,
    )

    with pytest.raises(SnapshotIntegrityError, match="cannot be reloaded"):
        guarded.approve(second.id, actor="reviewer-b")

    assert registry.get_version(first.id).status is VersionStatus.ACTIVE
    assert registry.get_version(second.id).status is VersionStatus.DRAFT


def test_ingest_failure_remains_draft_and_records_failure_without_changing_active() -> None:
    class BuildRejectingStore(IndexSnapshotStore):
        def build(self, version, nodes):
            raise RuntimeError("simulated snapshot failure")

    root = _task_dir()
    registry, lifecycle = _lifecycle(root)
    first = lifecycle.ingest(_request(root, "nccn-v1", "1.2026", "First evidence"), actor="importer")
    lifecycle.approve(first.id, actor="reviewer-a")
    rejecting_store = BuildRejectingStore(
        root / "indices",
        embed_model=MockEmbedding(embed_dim=8),
        model_metadata={"provider": "mock", "model_name": "mock-8", "embed_dim": 8},
    )
    guarded = GuidelineLifecycle(
        registry=registry,
        managed_sources_dir=root / "managed",
        index_store=rejecting_store,
        project_root=PROJECT_ROOT,
    )

    with pytest.raises(RuntimeError, match="simulated snapshot failure"):
        guarded.ingest(_request(root, "nccn-v2", "2.2026", "Second evidence"), actor="importer")

    assert registry.get_version(first.id).status is VersionStatus.ACTIVE
    assert registry.get_version("nccn-v2").status is VersionStatus.DRAFT
    assert registry.get_version("nccn-v2").snapshot_path is None
    actions = [event.action for event in registry.list_audit() if event.entity_id == "nccn-v2"]
    assert "ingest_failed" in actions
    assert "ingest_succeeded" not in actions


def test_diff_failure_does_not_record_ingest_success() -> None:
    class RejectingDiffer:
        def compare(self, prior_version_id, current_version_id, *, actor):
            raise RuntimeError("simulated diff failure")

    root = _task_dir()
    registry, lifecycle = _lifecycle(root)
    first = lifecycle.ingest(_request(root, "nccn-v1", "1.2026", "First evidence"), actor="importer")
    lifecycle.approve(first.id, actor="reviewer-a")
    lifecycle._differ = RejectingDiffer()

    with pytest.raises(RuntimeError, match="simulated diff failure"):
        lifecycle.ingest(_request(root, "nccn-v2", "2.2026", "Second evidence"), actor="importer")

    actions = [event.action for event in registry.list_audit() if event.entity_id == "nccn-v2"]
    assert "ingest_failed" in actions
    assert "ingest_succeeded" not in actions


@pytest.mark.parametrize(
    "managed_root,index_root",
    [
        (Path(r"C:\kb-managed"), PROJECT_ROOT / "data" / "runtime_cache" / "safe-indices"),
        (PROJECT_ROOT / "data" / "runtime_cache" / "safe-managed", Path(r"C:\kb-indices")),
    ],
)
def test_lifecycle_rejects_writable_roots_outside_d_project_before_ingest(
    managed_root: Path, index_root: Path
) -> None:
    root = _task_dir()
    registry = Registry(root / "registry.sqlite3")
    registry.initialize()
    store = IndexSnapshotStore(
        index_root,
        embed_model=MockEmbedding(embed_dim=8),
        model_metadata={"provider": "mock"},
    )

    with pytest.raises(ValueError, match="project root"):
        GuidelineLifecycle(
            registry=registry,
            managed_sources_dir=managed_root,
            index_store=store,
            project_root=PROJECT_ROOT,
        )

    assert not Path(r"C:\kb-managed").exists()
    assert not Path(r"C:\kb-indices").exists()


def test_lifecycle_rejects_a_c_drive_project_root_without_creating_it() -> None:
    c_root = Path(r"C:\codex-task4-must-not-exist")
    registry = Registry(c_root / "registry.sqlite3")
    store = IndexSnapshotStore(
        c_root / "indices",
        embed_model=MockEmbedding(embed_dim=8),
        model_metadata={"provider": "mock"},
    )

    with pytest.raises(ValueError, match="D drive"):
        GuidelineLifecycle(
            registry=registry,
            managed_sources_dir=c_root / "managed",
            index_store=store,
            project_root=c_root,
        )

    assert not c_root.exists()


def test_ingest_rejects_wrong_or_ambiguous_source_roles_before_creating_draft() -> None:
    root = _task_dir()
    registry, lifecycle = _lifecycle(root)
    request = _request(root, "nccn-v1", "1.2026", "Evidence")
    wrong_jsonl = GuidelineIngestRequest(
        version=request.version,
        language=request.language,
        authority_level=request.authority_level,
        sources=request.sources,
        jsonl_source_id=request.citation_source_id,
        citation_source_id=request.jsonl_source_id,
    )

    with pytest.raises(ValueError, match="jsonl_source_id must reference a JSONL source"):
        lifecycle.ingest(wrong_jsonl, actor="importer")
    with pytest.raises(KeyError):
        registry.get_version("nccn-v1")

    ambiguous = GuidelineIngestRequest(
        version=request.version,
        language=request.language,
        authority_level=request.authority_level,
        sources=request.sources,
        jsonl_source_id=request.jsonl_source_id,
        citation_source_id=request.jsonl_source_id,
    )
    with pytest.raises(ValueError, match="must identify different sources"):
        lifecycle.ingest(ambiguous, actor="importer")


@pytest.mark.parametrize(
    "language, authority_level, expected_error",
    [
        ("zh", AuthorityLevel.PRIMARY_GUIDELINE, "language must match"),
        ("en", AuthorityLevel.SECONDARY_SUMMARY, "authority_level must match"),
    ],
)
def test_ingest_rejects_metadata_that_conflicts_with_registered_guideline_before_creating_draft(
    language: str, authority_level: AuthorityLevel, expected_error: str
) -> None:
    root = _task_dir()
    registry, lifecycle = _lifecycle(root)
    request = _request(root, "nccn-v1", "1.2026", "Evidence")
    mismatched = GuidelineIngestRequest(
        version=request.version,
        language=language,
        authority_level=authority_level,
        sources=request.sources,
        jsonl_source_id=request.jsonl_source_id,
        citation_source_id=request.citation_source_id,
    )

    with pytest.raises(ValueError, match=expected_error):
        lifecycle.ingest(mismatched, actor="importer")

    with pytest.raises(KeyError):
        registry.get_version("nccn-v1")
