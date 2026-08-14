from __future__ import annotations

import json
from pathlib import Path

import pytest
from llama_index.core.embeddings import MockEmbedding

from app.constants import AuthorityLevel, SourceKind
from app.contracts import (
    GuidelineInput,
    SearchRequest,
    SourceFileRecord,
    VersionInput,
)
from app.ingestion import ManagedSourceInput
from app.lifecycle import GuidelineIngestRequest
from app.registry import Registry
from app.service import GuidelineService
from app.settings import PathOutsideProjectError, Settings


def _settings(project_root: Path) -> Settings:
    data_dir = project_root / "data"
    return Settings(
        project_root=project_root,
        data_dir=data_dir,
        registry_db_path=data_dir / "registry" / "knowledge.sqlite3",
        managed_sources_dir=data_dir / "managed_sources",
        index_root=data_dir / "llama_indices",
        model_cache_dir=data_dir / "model_cache",
        runtime_cache_dir=data_dir / "runtime_cache",
        model_name="BAAI/bge-m3",
        model_revision="5617a9f61b028005a4858fdac845db406aefb181",
        model_device="cpu",
        model_max_seq_length=512,
        embedding_batch_size=4,
        model_local_files_only=True,
        bm25_enabled=True,
    )


def _legacy_registry(
    settings: Settings,
    *,
    version_id: str = "nccn-v1",
    create_snapshot: bool = True,
    create_managed_source: bool = True,
) -> tuple[Registry, str, str]:
    registry = Registry(settings.registry_db_path)
    registry.initialize()
    registry.create_guideline(
        GuidelineInput(
            id="nccn",
            title="NCCN Breast Cancer",
            language="en",
            authority_level=AuthorityLevel.PRIMARY_GUIDELINE,
        ),
        actor="fixture",
    )
    registry.create_draft_version(
        VersionInput(id=version_id, guideline_id="nccn", version_label="6.2026"),
        actor="fixture",
    )

    old_snapshot = rf"D:\coding\knowledgebase\data\llama_indices\nccn\{version_id}"
    old_managed = rf"D:\coding\knowledgebase\data\managed_sources\{version_id}\source-guide.pdf"
    registry.set_draft_snapshot(
        version_id,
        snapshot_path=old_snapshot,
        snapshot_manifest_sha256="a" * 64,
        actor="fixture",
    )
    registry.add_source_file(
        SourceFileRecord(
            id="source",
            version_id=version_id,
            source_kind=SourceKind.PDF,
            original_path=r"E:\incoming\guide.pdf",
            managed_path=old_managed,
            sha256="b" * 64,
            byte_size=1,
        ),
        actor="fixture",
    )

    if create_snapshot:
        (settings.index_root / "nccn" / version_id).mkdir(parents=True)
    if create_managed_source:
        target = settings.managed_sources_dir / version_id / "source-guide.pdf"
        target.parent.mkdir(parents=True)
        target.write_bytes(b"x")
    return registry, old_snapshot, old_managed


def _managed_path(registry: Registry) -> str:
    with registry.connect() as connection:
        row = connection.execute(
            "SELECT managed_path FROM source_file WHERE id = 'source'"
        ).fetchone()
    return str(row["managed_path"])


def test_settings_resolves_only_paths_inside_the_current_project(
    tmp_path: Path,
) -> None:
    root = (tmp_path / "portable-project").resolve()
    root.mkdir()
    settings = _settings(root)
    inside = root / "data" / "managed_sources" / "guide.pdf"

    assert settings.resolve_project_path("data/managed_sources/guide.pdf") == inside
    assert settings.resolve_project_path(inside) == inside
    with pytest.raises(PathOutsideProjectError, match="project root"):
        settings.resolve_project_path(tmp_path / "outside.pdf")


def test_rebases_legacy_runtime_paths_once_and_records_count_only_audit(
    tmp_path: Path,
) -> None:
    settings = _settings((tmp_path / "relocated-project").resolve())
    registry, _, _ = _legacy_registry(settings)

    changed = registry.rebase_runtime_paths(
        project_root=settings.project_root,
        managed_sources_dir=settings.managed_sources_dir,
        index_root=settings.index_root,
        actor="system",
    )

    assert changed == 2
    assert registry.get_version("nccn-v1").snapshot_path == (
        "data/llama_indices/nccn/nccn-v1"
    )
    assert _managed_path(registry) == (
        "data/managed_sources/nccn-v1/source-guide.pdf"
    )
    events = [event for event in registry.list_audit() if event.action == "project_paths_rebased"]
    assert len(events) == 1
    assert json.loads(events[0].payload_json) == {"path_count": 2}

    assert registry.rebase_runtime_paths(
        project_root=settings.project_root,
        managed_sources_dir=settings.managed_sources_dir,
        index_root=settings.index_root,
        actor="system",
    ) == 0
    assert len(
        [event for event in registry.list_audit() if event.action == "project_paths_rebased"]
    ) == 1


def test_rebase_rolls_back_every_path_and_audit_when_a_target_is_missing(
    tmp_path: Path,
) -> None:
    settings = _settings((tmp_path / "relocated-project").resolve())
    registry, old_snapshot, old_managed = _legacy_registry(
        settings, create_managed_source=False
    )

    with pytest.raises(FileNotFoundError, match="source"):
        registry.rebase_runtime_paths(
            project_root=settings.project_root,
            managed_sources_dir=settings.managed_sources_dir,
            index_root=settings.index_root,
            actor="system",
        )

    assert registry.get_version("nccn-v1").snapshot_path == old_snapshot
    assert _managed_path(registry) == old_managed
    assert not any(
        event.action == "project_paths_rebased" for event in registry.list_audit()
    )


def test_new_ingest_persists_relative_paths_and_resolves_them_for_use(
    tmp_path: Path,
) -> None:
    settings = _settings((tmp_path / "portable-project").resolve())
    source_root = tmp_path / "external-sources"
    source_root.mkdir()
    pdf_path = source_root / "guide.pdf"
    jsonl_path = source_root / "chunks.jsonl"
    pdf_path.write_bytes(b"%PDF-1.4\nfixture\n")
    jsonl_path.write_text(
        json.dumps(
            {
                "chunk_id": "her2-1",
                "doc_id": "nccn",
                "doc_title": "NCCN Breast Cancer",
                "section_path": "HER2-positive disease",
                "page_code": "BINV-1",
                "page_start": 0,
                "page_end": 0,
                "block_type": "paragraph",
                "text": "Trastuzumab is recommended for HER2-positive disease.",
            }
        )
        + "\n",
        encoding="utf-8",
    )
    service = GuidelineService(settings, embed_model=MockEmbedding(embed_dim=8))
    request = GuidelineIngestRequest(
        version=VersionInput(
            id="nccn-v1", guideline_id="nccn", version_label="6.2026"
        ),
        language="en",
        authority_level=AuthorityLevel.PRIMARY_GUIDELINE,
        sources=(
            ManagedSourceInput(
                id="guide",
                path=pdf_path,
                source_kind=SourceKind.PDF,
                provenance={},
            ),
            ManagedSourceInput(
                id="chunks",
                path=jsonl_path,
                source_kind=SourceKind.JSONL,
                provenance={},
            ),
        ),
        jsonl_source_id="chunks",
        citation_source_id="guide",
    )

    version = service.ingest(
        request,
        actor="importer",
        guideline=GuidelineInput(
            id="nccn",
            title="NCCN Breast Cancer",
            language="en",
            authority_level=AuthorityLevel.PRIMARY_GUIDELINE,
        ),
    )

    assert version.snapshot_path == "data/llama_indices/nccn/nccn-v1"
    with service.registry.connect() as connection:
        managed_paths = [
            row["managed_path"]
            for row in connection.execute(
                "SELECT managed_path FROM source_file ORDER BY id"
            ).fetchall()
        ]
    assert managed_paths == [
        "data/managed_sources/nccn-v1/chunks-chunks.jsonl",
        "data/managed_sources/nccn-v1/guide-guide.pdf",
    ]
    assert all(not Path(value).is_absolute() for value in managed_paths)

    snapshot = service.snapshot_info(version.id)
    assert snapshot.path == settings.index_root / "nccn" / "nccn-v1"
    service.index_store.verify(snapshot)
    service.approve(version.id, reviewer="reviewer")
    response = service.search(SearchRequest(query="trastuzumab", top_k=1))
    assert response.evidence[0].raw_chunk_id == "chunks:her2-1"
