from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any

from app.constants import AuthorityLevel, ChangeType, SourceKind, VersionStatus
from app.citation import Citation


@dataclass(frozen=True, slots=True)
class GuidelineInput:
    id: str
    title: str
    language: str
    authority_level: AuthorityLevel
    title_zh: str | None = None
    publisher: str | None = None


@dataclass(frozen=True, slots=True)
class GuidelineRecord:
    id: str
    title: str
    language: str
    authority_level: AuthorityLevel
    title_zh: str | None = None
    publisher: str | None = None


@dataclass(frozen=True, slots=True)
class VersionInput:
    id: str
    guideline_id: str
    version_label: str
    published_at: str | None = None
    snapshot_path: str | None = None


@dataclass(frozen=True, slots=True)
class VersionRecord:
    id: str
    guideline_id: str
    version_label: str
    status: VersionStatus
    snapshot_path: str | None
    snapshot_manifest_sha256: str | None
    published_at: str | None
    created_at: str
    approved_at: str | None


@dataclass(frozen=True, slots=True)
class SourceFileRecord:
    id: str
    version_id: str
    source_kind: SourceKind
    original_path: str
    managed_path: str
    sha256: str
    byte_size: int
    provenance_json: str = "{}"


@dataclass(frozen=True, slots=True)
class RawChunkRecord:
    id: str
    source_file_id: str
    source_ordinal: int
    chunk_id: str
    text: str
    content_sha256: str
    locator_json: str


@dataclass(frozen=True, slots=True)
class NodeManifestRecord:
    node_id: str
    version_id: str
    raw_chunk_id: str
    fragment_ordinal: int
    source_ordinal: int
    content_sha256: str
    char_start: int
    char_end: int
    metadata_json: str


@dataclass(frozen=True, slots=True)
class AuditEvent:
    id: int
    actor: str
    action: str
    entity_type: str
    entity_id: str
    payload_json: str
    created_at: str


@dataclass(frozen=True, slots=True)
class VersionDiffRecord:
    id: str
    prior_version_id: str
    current_version_id: str
    chunk_id: str
    change_type: ChangeType
    prior_raw_chunk_id: str | None
    current_raw_chunk_id: str | None
    prior_normalized_sha256: str | None
    current_normalized_sha256: str | None


@dataclass(frozen=True, slots=True)
class SearchRequest:
    query: str
    guideline_ids: tuple[str, ...] = ()
    version_ids: tuple[str, ...] = ()
    language: str | None = None
    top_k: int = 5
    use_bm25: bool = False


@dataclass(frozen=True, slots=True)
class Evidence:
    node_id: str
    raw_chunk_id: str
    text: str
    score: float
    guideline_id: str
    version_id: str
    language: str
    authority_level: str
    citation: Citation


@dataclass(frozen=True, slots=True)
class SearchResponse:
    evidence: tuple[Evidence, ...]
    resolved_version_ids: tuple[str, ...]
    retrieval_modes: tuple[str, ...]
