from __future__ import annotations

import hashlib
import json
from pathlib import Path
from uuid import uuid4

import pytest

from app.constants import AuthorityLevel, SourceKind
from app.contracts import GuidelineInput, VersionInput
from app.ingestion import (
    JsonlIngestionError,
    ManagedSourceInput,
    copy_and_register_sources,
    make_node_metadata,
    read_jsonl,
)
from app.registry import Registry


FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture
def task_dir() -> Path:
    value = Path(r"D:\coding\knowledgebase\data\runtime_cache\test_task2") / uuid4().hex
    value.mkdir(parents=True)
    return value


@pytest.fixture
def registry(task_dir: Path) -> Registry:
    value = Registry(task_dir / "registry.sqlite3")
    value.initialize()
    value.create_guideline(
        GuidelineInput(
            id="nccn",
            title="NCCN Breast Cancer",
            language="en",
            authority_level=AuthorityLevel.PRIMARY_GUIDELINE,
        ),
        actor="tester",
    )
    value.create_draft_version(
        VersionInput(id="nccn-v6", guideline_id="nccn", version_label="6.2026"),
        actor="tester",
    )
    return value


def test_read_jsonl_preserves_text_and_uses_one_based_line_numbers() -> None:
    chunks = read_jsonl(FIXTURES / "caca.jsonl")

    assert len(chunks) == 1
    assert chunks[0].source_ordinal == 1
    assert chunks[0].chunk_id == "caca_2026_0001"
    assert chunks[0].text == "原文  保留\n换行"
    assert json.loads(chunks[0].locator_json)["part_count"] == 2
    assert chunks[0].content_sha256 == hashlib.sha256("原文  保留\n换行".encode("utf-8")).hexdigest()


@pytest.mark.parametrize("fixture_name", ["gradishar.jsonl", "nccn.jsonl", "oncotoolkit.jsonl"])
def test_read_jsonl_accepts_all_remaining_source_shapes(fixture_name: str) -> None:
    chunks = read_jsonl(FIXTURES / fixture_name)

    assert len(chunks) == 1
    assert chunks[0].source_ordinal == 1
    assert chunks[0].text


def test_read_jsonl_rejects_duplicate_chunk_id_with_line_number(task_dir: Path) -> None:
    source = task_dir / "duplicate.jsonl"
    record = json.loads((FIXTURES / "nccn.jsonl").read_text(encoding="utf-8"))
    source.write_text("\n".join((json.dumps(record), json.dumps(record))), encoding="utf-8")

    with pytest.raises(JsonlIngestionError, match=r"line 2.*duplicate chunk_id"):
        read_jsonl(source)


def test_read_jsonl_rejects_missing_common_field_with_line_number(task_dir: Path) -> None:
    source = task_dir / "missing.jsonl"
    record = json.loads((FIXTURES / "nccn.jsonl").read_text(encoding="utf-8"))
    del record["section_path"]
    source.write_text(json.dumps(record), encoding="utf-8")

    with pytest.raises(JsonlIngestionError, match=r"line 1.*missing required field: section_path"):
        read_jsonl(source)


def test_copy_and_register_sources_is_byte_identical_and_keeps_original_unchanged(
    registry: Registry, task_dir: Path
) -> None:
    original = task_dir / "original.jsonl"
    original_bytes = b'{"chunk_id":"fixture"}\r\n'
    original.write_bytes(original_bytes)

    records = copy_and_register_sources(
        registry=registry,
        version_id="nccn-v6",
        managed_sources_dir=task_dir / "managed",
        sources=(
            ManagedSourceInput(
                id="nccn-jsonl",
                path=original,
                source_kind=SourceKind.JSONL,
                provenance={"role": "chunk_input"},
            ),
        ),
        actor="importer",
    )

    assert original.read_bytes() == original_bytes
    assert records[0].managed_path != str(original)
    assert Path(records[0].managed_path).read_bytes() == original_bytes
    assert records[0].sha256 == hashlib.sha256(original_bytes).hexdigest()
    assert registry.count_rows("source_file") == 1


@pytest.mark.parametrize("version_id, source_id", [("..", "source"), ("nccn-v6", "..")])
def test_copy_and_register_sources_rejects_path_components_that_escape_managed_root(
    registry: Registry, task_dir: Path, version_id: str, source_id: str
) -> None:
    original = task_dir / "original.jsonl"
    original.write_bytes(b'{"chunk_id":"fixture"}\n')
    managed_root = task_dir / "managed"

    with pytest.raises(ValueError, match="safe path component"):
        copy_and_register_sources(
            registry=registry,
            version_id=version_id,
            managed_sources_dir=managed_root,
            sources=(
                ManagedSourceInput(
                    id=source_id,
                    path=original,
                    source_kind=SourceKind.JSONL,
                    provenance={"role": "chunk_input"},
                ),
            ),
            actor="importer",
        )

    assert not (task_dir / "source-original.jsonl").exists()


def test_make_node_metadata_keeps_provenance_and_optional_fields() -> None:
    chunk = read_jsonl(FIXTURES / "oncotoolkit.jsonl", source_file_id="html-source")[0]
    metadata = make_node_metadata(
        chunk,
        guideline_id="oncotoolkit",
        version_id="oncotoolkit-2026",
        language="en",
        authority_level=AuthorityLevel.SECONDARY_SUMMARY,
        source_sha256="a" * 64,
        source_kind=SourceKind.HTML,
    )

    assert metadata["raw_chunk_id"] == chunk.id
    assert metadata["chunk_id"] == "oncotoolkit_her2_0001"
    assert metadata["text"] == "Treatment sequence overview."
    assert metadata["source_ordinal"] == 1
    assert metadata["parent_h1"] == "HER2+ Breast Cancer"
    assert metadata["heading_level"] == 2
    assert metadata["version_id"] == "oncotoolkit-2026"
    assert metadata["authority_level"] == "secondary_summary"
    assert metadata["source_sha256"] == "a" * 64
