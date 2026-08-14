from __future__ import annotations

from hashlib import sha256
import json
from pathlib import Path
from uuid import uuid4

import pytest

from app.constants import AuthorityLevel, ChangeType, SourceKind
from app.contracts import GuidelineInput, RawChunkRecord, SourceFileRecord, VersionInput
from app.diffing import VersionDiffer, normalize_text, normalized_text_sha256
from app.registry import Registry


PROJECT_ROOT = Path(r"D:\coding\knowledgebase")


def _registry() -> Registry:
    root = PROJECT_ROOT / "data" / "runtime_cache" / "test_task4_diffing" / uuid4().hex
    root.mkdir(parents=True)
    registry = Registry(root / "registry.sqlite3")
    registry.initialize()
    return registry


def _create_guideline(registry: Registry, guideline_id: str) -> None:
    registry.create_guideline(
        GuidelineInput(
            id=guideline_id,
            title=guideline_id,
            language="en",
            authority_level=AuthorityLevel.PRIMARY_GUIDELINE,
        ),
        actor="operator",
    )


def _add_version(
    registry: Registry, guideline_id: str, version_id: str, chunks: dict[str, str]
) -> None:
    registry.create_draft_version(
        VersionInput(id=version_id, guideline_id=guideline_id, version_label=version_id),
        actor="operator",
    )
    source_id = f"{version_id}-chunks"
    registry.add_source_file(
        SourceFileRecord(
            id=source_id,
            version_id=version_id,
            source_kind=SourceKind.JSONL,
            original_path=str(PROJECT_ROOT / "fixtures" / f"{version_id}.jsonl"),
            managed_path=str(PROJECT_ROOT / "data" / "managed_sources" / f"{version_id}.jsonl"),
            sha256="a" * 64,
            byte_size=1,
        ),
        actor="operator",
    )
    registry.add_raw_chunks(
        [
            RawChunkRecord(
                id=f"{source_id}:{chunk_id}",
                source_file_id=source_id,
                source_ordinal=ordinal,
                chunk_id=chunk_id,
                text=text,
                content_sha256=sha256(text.encode("utf-8")).hexdigest(),
                locator_json=json.dumps({"chunk_id": chunk_id}),
            )
            for ordinal, (chunk_id, text) in enumerate(chunks.items(), start=1)
        ],
        actor="operator",
    )


def test_normalization_is_nfkc_whitespace_only_and_preserves_case_and_punctuation() -> None:
    assert normalize_text("  ＨＥＲ２\r\n  positive\t disease  ") == "HER2 positive disease"
    assert normalized_text_sha256("A, B") != normalized_text_sha256("a B")


def test_diff_persists_added_removed_modified_and_unchanged_by_original_chunk_id() -> None:
    registry = _registry()
    _create_guideline(registry, "nccn")
    _add_version(
        registry,
        "nccn",
        "nccn-v1",
        {
            "same": "Trastuzumab\r\n plus   pertuzumab",
            "changed": "Dose 1 mg",
            "removed": "Historical recommendation",
        },
    )
    _add_version(
        registry,
        "nccn",
        "nccn-v2",
        {
            "same": "Trastuzumab plus pertuzumab",
            "changed": "Dose 2 mg",
            "added": "New recommendation",
        },
    )

    records = VersionDiffer(registry).compare("nccn-v1", "nccn-v2", actor="auditor")
    by_chunk = {record.chunk_id: record for record in records}

    assert {key: value.change_type for key, value in by_chunk.items()} == {
        "added": ChangeType.ADDED,
        "changed": ChangeType.MODIFIED,
        "removed": ChangeType.REMOVED,
        "same": ChangeType.UNCHANGED,
    }
    assert by_chunk["added"].prior_raw_chunk_id is None
    assert by_chunk["added"].current_raw_chunk_id == "nccn-v2-chunks:added"
    assert by_chunk["removed"].prior_raw_chunk_id == "nccn-v1-chunks:removed"
    assert by_chunk["removed"].current_raw_chunk_id is None
    assert by_chunk["changed"].prior_normalized_sha256 != by_chunk["changed"].current_normalized_sha256
    assert by_chunk["same"].prior_normalized_sha256 == by_chunk["same"].current_normalized_sha256
    assert registry.list_version_diffs("nccn-v1", "nccn-v2") == records

    repeated = VersionDiffer(registry).compare("nccn-v1", "nccn-v2", actor="auditor")
    assert repeated == records


def test_diff_rejects_versions_from_different_guidelines_without_persisting() -> None:
    registry = _registry()
    _create_guideline(registry, "nccn")
    _create_guideline(registry, "caca")
    _add_version(registry, "nccn", "nccn-v1", {"same": "NCCN text"})
    _add_version(registry, "caca", "caca-v1", {"same": "CACA text"})

    with pytest.raises(ValueError, match="same guideline"):
        VersionDiffer(registry).compare("nccn-v1", "caca-v1", actor="auditor")

    assert registry.list_version_diffs("nccn-v1", "caca-v1") == []
