from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path

from app.constants import AuthorityLevel, SourceKind
from app.contracts import NodeManifestRecord, VersionDiffRecord, VersionInput, VersionRecord
from app.diffing import VersionDiffer
from app.index_store import (
    IndexSnapshotStore,
    NodeBuildContext,
    ProvenanceNodeBuilder,
    SnapshotInfo,
)
from app.ingestion import ManagedSourceInput, copy_and_register_sources, read_jsonl
from app.registry import Registry


@dataclass(frozen=True, slots=True)
class GuidelineIngestRequest:
    version: VersionInput
    language: str
    authority_level: AuthorityLevel
    sources: tuple[ManagedSourceInput, ...]
    jsonl_source_id: str
    citation_source_id: str


class GuidelineLifecycle:
    """Coordinate provenance ingestion, immutable snapshots, approval, and diffing."""

    def __init__(
        self,
        *,
        registry: Registry,
        managed_sources_dir: Path,
        index_store: IndexSnapshotStore,
        project_root: Path,
    ) -> None:
        self._project_root = Path(project_root).resolve()
        if self._project_root.drive.upper() != "D:":
            raise ValueError("project root must be on the D drive")
        self._registry = registry
        self._managed_sources_dir = self._require_project_path(managed_sources_dir)
        self._require_project_path(registry.path)
        self._require_project_path(index_store.index_root)
        self._index_store = index_store
        self._node_builder = ProvenanceNodeBuilder()
        self._differ = VersionDiffer(registry)

    def ingest(self, request: GuidelineIngestRequest, actor: str) -> VersionRecord:
        guideline = self._registry.get_guideline(request.version.guideline_id)
        self._validate_request(request, guideline.language, guideline.authority_level)
        prior_active = next(
            (
                item
                for item in self._registry.list_searchable_versions()
                if item.guideline_id == request.version.guideline_id
            ),
            None,
        )
        version = self._registry.create_draft_version(request.version, actor=actor)
        try:
            source_records = copy_and_register_sources(
                registry=self._registry,
                version_id=version.id,
                managed_sources_dir=self._managed_sources_dir,
                sources=request.sources,
                actor=actor,
            )
            records_by_id = {record.id: record for record in source_records}
            jsonl_source = records_by_id[request.jsonl_source_id]
            citation_source = records_by_id[request.citation_source_id]
            raw_chunks = read_jsonl(
                Path(jsonl_source.managed_path), source_file_id=jsonl_source.id
            )
            self._registry.add_raw_chunks(raw_chunks, actor=actor)
            nodes = self._node_builder.build(
                raw_chunks,
                NodeBuildContext(
                    guideline_id=version.guideline_id,
                    version_id=version.id,
                    language=guideline.language,
                    authority_level=guideline.authority_level,
                    source_sha256=citation_source.sha256,
                    source_kind=citation_source.source_kind,
                ),
            )
            self._registry.add_node_manifest(
                [
                    NodeManifestRecord(
                        node_id=node.node_id,
                        version_id=version.id,
                        raw_chunk_id=str(node.metadata["raw_chunk_id"]),
                        fragment_ordinal=int(node.metadata["fragment_ordinal"]),
                        source_ordinal=int(node.metadata["source_ordinal"]),
                        content_sha256=str(node.metadata["content_sha256"]),
                        char_start=int(node.metadata["char_start"]),
                        char_end=int(node.metadata["char_end"]),
                        metadata_json=json.dumps(
                            node.metadata,
                            ensure_ascii=False,
                            sort_keys=True,
                            separators=(",", ":"),
                        ),
                    )
                    for node in nodes
                ],
                actor=actor,
            )
            snapshot = self._index_store.build(version, nodes)
            self._index_store.verify(snapshot)
            version = self._registry.set_draft_snapshot(
                version.id,
                snapshot_path=str(snapshot.path),
                snapshot_manifest_sha256=snapshot.manifest_sha256,
                actor=actor,
            )
            if prior_active is not None:
                self.diff(prior_active.id, version.id, actor=actor)
            self._registry.record_audit(
                actor,
                "ingest_succeeded",
                "document_version",
                version.id,
                {"node_count": len(nodes)},
            )
            return version
        except Exception as error:
            self._registry.record_audit(
                actor,
                "ingest_failed",
                "document_version",
                version.id,
                {"error_type": type(error).__name__, "message": str(error)},
            )
            raise

    def approve(self, version_id: str, actor: str) -> VersionRecord:
        try:
            version = self._registry.get_version(version_id)
            if not version.snapshot_path or not version.snapshot_manifest_sha256:
                raise ValueError("draft version has no verified snapshot")
            snapshot = SnapshotInfo(
                guideline_id=version.guideline_id,
                version_id=version.id,
                index_id=f"{version.guideline_id}:{version.id}",
                path=Path(version.snapshot_path),
                node_count=self._registry.count_nodes_for_version(version.id),
                manifest_sha256=version.snapshot_manifest_sha256,
            )
            self._index_store.load(snapshot)
            return self._registry.approve_version(
                version.id,
                actor=actor,
                snapshot_manifest_sha256=snapshot.manifest_sha256,
            )
        except Exception as error:
            self._registry.record_audit(
                actor,
                "approval_failed",
                "document_version",
                version_id,
                {
                    "error_type": type(error).__name__[:100],
                    "message": str(error)[:200],
                },
            )
            raise

    def diff(
        self, prior_version_id: str, current_version_id: str, *, actor: str
    ) -> list[VersionDiffRecord]:
        return self._differ.compare(prior_version_id, current_version_id, actor=actor)

    def _require_project_path(self, path: Path) -> Path:
        resolved = Path(path).resolve()
        if not resolved.is_relative_to(self._project_root):
            raise ValueError(f"writable path must remain below project root: {self._project_root}")
        return resolved

    @staticmethod
    def _validate_request(
        request: GuidelineIngestRequest,
        guideline_language: str,
        guideline_authority_level: AuthorityLevel,
    ) -> None:
        if request.language != guideline_language:
            raise ValueError("request language must match the registered guideline language")
        if request.authority_level is not guideline_authority_level:
            raise ValueError("request authority_level must match the registered guideline authority_level")
        sources_by_id = {source.id: source for source in request.sources}
        if len(sources_by_id) != len(request.sources):
            raise ValueError("source IDs must be unique")
        if request.jsonl_source_id not in sources_by_id:
            raise ValueError("jsonl_source_id must identify an input source")
        if request.citation_source_id not in sources_by_id:
            raise ValueError("citation_source_id must identify an input source")
        if request.jsonl_source_id == request.citation_source_id:
            raise ValueError("jsonl_source_id and citation_source_id must identify different sources")
        if sources_by_id[request.jsonl_source_id].source_kind is not SourceKind.JSONL:
            raise ValueError("jsonl_source_id must reference a JSONL source")
        if sources_by_id[request.citation_source_id].source_kind not in {
            SourceKind.PDF,
            SourceKind.HTML,
        }:
            raise ValueError("citation_source_id must reference a PDF or HTML source")
