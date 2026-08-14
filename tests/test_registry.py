from __future__ import annotations

from pathlib import Path
import sqlite3

import pytest

from app.constants import AuthorityLevel, SourceKind, VersionStatus
from app.contracts import (
    GuidelineInput,
    NodeManifestRecord,
    RawChunkRecord,
    SourceFileRecord,
    VersionInput,
)
from app.registry import Registry


@pytest.fixture
def registry(tmp_path):
    value = Registry(tmp_path / "registry.sqlite3")
    value.initialize()
    return value


def _create_guideline(registry: Registry) -> None:
    registry.create_guideline(
        GuidelineInput(
            id="nccn",
            title="NCCN Breast Cancer",
            language="en",
            authority_level=AuthorityLevel.PRIMARY_GUIDELINE,
        ),
        actor="operator",
    )


def test_approval_atomically_supersedes_prior_active(registry: Registry) -> None:
    _create_guideline(registry)
    first = registry.create_draft_version(
        VersionInput(id="nccn-v1", guideline_id="nccn", version_label="6.2026"),
        actor="operator",
    )
    second = registry.create_draft_version(
        VersionInput(id="nccn-v2", guideline_id="nccn", version_label="7.2026"),
        actor="operator",
    )

    registry.approve_version(first.id, actor="reviewer-a", snapshot_manifest_sha256="a" * 64)
    registry.approve_version(second.id, actor="reviewer-b", snapshot_manifest_sha256="b" * 64)

    assert registry.get_version(first.id).status is VersionStatus.SUPERSEDED
    assert registry.get_version(second.id).status is VersionStatus.ACTIVE
    assert [item.id for item in registry.list_searchable_versions()] == ["nccn-v2"]


def test_audit_rows_cannot_be_updated_or_deleted(registry: Registry) -> None:
    event_id = registry.record_audit("operator", "import_started", "version", "nccn-v1", {})

    with pytest.raises(sqlite3.DatabaseError, match="append-only"):
        registry.execute_for_test("UPDATE audit_event SET action = 'changed' WHERE id = ?", (event_id,))
    with pytest.raises(sqlite3.DatabaseError, match="append-only"):
        registry.execute_for_test("DELETE FROM audit_event WHERE id = ?", (event_id,))


def test_source_raw_chunks_and_node_manifest_are_persisted(registry: Registry) -> None:
    _create_guideline(registry)
    version = registry.create_draft_version(
        VersionInput(id="nccn-v1", guideline_id="nccn", version_label="6.2026"),
        actor="operator",
    )
    registry.add_source_file(
        SourceFileRecord(
            id="source-1",
            version_id=version.id,
            source_kind=SourceKind.PDF,
            original_path=r"D:\document\nccn.pdf",
            managed_path="data/managed_sources/nccn.pdf",
            sha256="1" * 64,
            byte_size=123,
        ),
        actor="operator",
    )
    registry.add_raw_chunks(
        [
            RawChunkRecord(
                id="chunk-1",
                source_file_id="source-1",
                source_ordinal=1,
                chunk_id="nccn_v6_2026_0000",
                text="HER2 positive evidence",
                content_sha256="2" * 64,
                locator_json='{"page_start": 0}',
            )
        ],
        actor="operator",
    )
    registry.add_node_manifest(
        [
            NodeManifestRecord(
                node_id="nccn:nccn-v1:nccn_v6_2026_0000:0",
                version_id=version.id,
                raw_chunk_id="chunk-1",
                fragment_ordinal=0,
                source_ordinal=1,
                content_sha256="2" * 64,
                char_start=0,
                char_end=22,
                metadata_json='{"language": "en"}',
            )
        ],
        actor="operator",
    )

    assert registry.count_rows("source_file") == 1
    assert registry.count_rows("raw_chunk") == 1
    assert registry.count_rows("node_manifest") == 1


def test_approval_rejects_missing_manifest_hash(registry: Registry) -> None:
    _create_guideline(registry)
    version = registry.create_draft_version(
        VersionInput(id="nccn-v1", guideline_id="nccn", version_label="6.2026"),
        actor="operator",
    )

    with pytest.raises(ValueError, match="SHA-256"):
        registry.approve_version(version.id, actor="reviewer", snapshot_manifest_sha256="")


def test_approval_rejects_non_hex_manifest_hash(registry: Registry) -> None:
    _create_guideline(registry)
    version = registry.create_draft_version(
        VersionInput(id="nccn-v1", guideline_id="nccn", version_label="6.2026"),
        actor="operator",
    )

    with pytest.raises(ValueError, match="SHA-256"):
        registry.approve_version(version.id, actor="reviewer", snapshot_manifest_sha256="z" * 64)


def test_database_rejects_non_hex_snapshot_hash_when_written_directly(registry: Registry) -> None:
    _create_guideline(registry)
    version = registry.create_draft_version(
        VersionInput(id="nccn-v1", guideline_id="nccn", version_label="6.2026"),
        actor="operator",
    )

    with pytest.raises(sqlite3.IntegrityError):
        registry.execute_for_test(
            "UPDATE document_version SET snapshot_manifest_sha256 = ? WHERE id = ?",
            ("z" * 64, version.id),
        )


def test_archiving_a_superseded_version_preserves_the_active_version(registry: Registry) -> None:
    _create_guideline(registry)
    first = registry.create_draft_version(
        VersionInput(id="nccn-v1", guideline_id="nccn", version_label="6.2026"),
        actor="operator",
    )
    second = registry.create_draft_version(
        VersionInput(id="nccn-v2", guideline_id="nccn", version_label="7.2026"),
        actor="operator",
    )
    registry.approve_version(first.id, actor="reviewer-a", snapshot_manifest_sha256="a" * 64)
    registry.approve_version(second.id, actor="reviewer-b", snapshot_manifest_sha256="b" * 64)

    archived = registry.archive_version(first.id, actor="records-manager")

    assert archived.status is VersionStatus.ARCHIVED
    assert [item.id for item in registry.list_searchable_versions()] == ["nccn-v2"]
    assert registry.list_audit()[-1].action == "version_archived"


def test_archiving_a_draft_version_is_rejected(registry: Registry) -> None:
    _create_guideline(registry)
    draft = registry.create_draft_version(
        VersionInput(id="nccn-v1", guideline_id="nccn", version_label="6.2026"),
        actor="operator",
    )

    with pytest.raises(ValueError, match="superseded"):
        registry.archive_version(draft.id, actor="records-manager")

    assert registry.get_version(draft.id).status is VersionStatus.DRAFT


def test_source_file_rejects_non_hex_sha256(registry: Registry) -> None:
    _create_guideline(registry)
    version = registry.create_draft_version(
        VersionInput(id="nccn-v1", guideline_id="nccn", version_label="6.2026"),
        actor="operator",
    )

    with pytest.raises(ValueError, match="SHA-256"):
        registry.add_source_file(
            SourceFileRecord(
                id="source-invalid-hash",
                version_id=version.id,
                source_kind=SourceKind.PDF,
                original_path=r"D:\document\nccn.pdf",
                managed_path="data/managed_sources/nccn.pdf",
                sha256="z" * 64,
                byte_size=123,
            ),
            actor="operator",
        )


def test_legacy_custom_vector_database_module_is_not_shipped() -> None:
    project_root = Path(__file__).resolve().parents[1]

    assert not (project_root / "app" / "database.py").exists()
