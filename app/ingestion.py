from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
import json
from pathlib import Path
import shutil
from typing import Iterable, Mapping

from app.constants import AuthorityLevel, SourceKind
from app.contracts import RawChunkRecord, SourceFileRecord
from app.registry import Registry


REQUIRED_CHUNK_FIELDS = (
    "chunk_id",
    "doc_id",
    "doc_title",
    "section_path",
    "page_code",
    "page_start",
    "page_end",
    "block_type",
    "text",
)
OPTIONAL_CHUNK_FIELDS = ("part", "part_count", "parent_h1", "heading_level")


class JsonlIngestionError(ValueError):
    """A JSONL record violates the source-contract needed for provenance."""


@dataclass(frozen=True, slots=True)
class ManagedSourceInput:
    id: str
    path: Path
    source_kind: SourceKind
    provenance: Mapping[str, object]


def read_jsonl(path: Path, *, source_file_id: str | None = None) -> list[RawChunkRecord]:
    """Read UTF-8 JSONL records without normalizing their text content."""
    source_path = Path(path)
    record_source_id = source_file_id or f"unregistered:{source_path.name}"
    seen_chunk_ids: set[str] = set()
    records: list[RawChunkRecord] = []

    with source_path.open("r", encoding="utf-8", newline="") as handle:
        for line_number, line in enumerate(handle, start=1):
            if line.strip("\r\n") == "":
                raise JsonlIngestionError(f"line {line_number}: empty JSONL record")
            try:
                payload = json.loads(line)
            except json.JSONDecodeError as error:
                raise JsonlIngestionError(f"line {line_number}: invalid JSON: {error.msg}") from error
            if not isinstance(payload, dict):
                raise JsonlIngestionError(f"line {line_number}: JSONL record must be an object")
            _validate_chunk_payload(payload, line_number)

            chunk_id = payload["chunk_id"]
            if chunk_id in seen_chunk_ids:
                raise JsonlIngestionError(f"line {line_number}: duplicate chunk_id: {chunk_id}")
            seen_chunk_ids.add(chunk_id)

            text = payload["text"]
            locator = {
                field: payload[field]
                for field in (*REQUIRED_CHUNK_FIELDS, *OPTIONAL_CHUNK_FIELDS)
                if field in payload
            }
            records.append(
                RawChunkRecord(
                    id=f"{record_source_id}:{chunk_id}",
                    source_file_id=record_source_id,
                    source_ordinal=line_number,
                    chunk_id=chunk_id,
                    text=text,
                    content_sha256=sha256(text.encode("utf-8")).hexdigest(),
                    locator_json=json.dumps(locator, ensure_ascii=False, sort_keys=True, separators=(",", ":")),
                )
            )
    return records


def copy_and_register_sources(
    *,
    registry: Registry,
    version_id: str,
    project_root: Path,
    managed_sources_dir: Path,
    sources: Iterable[ManagedSourceInput],
    actor: str,
) -> list[SourceFileRecord]:
    """Create immutable managed copies and register their byte-level provenance."""
    _require_safe_path_component(version_id, "version_id")
    root = Path(project_root).resolve()
    managed_root = Path(managed_sources_dir).resolve()
    if not managed_root.is_relative_to(root):
        raise ValueError("managed source root must remain below the project root")
    destination_root = (managed_root / version_id).resolve()
    if not destination_root.is_relative_to(managed_root):
        raise ValueError("managed source destination must remain below the managed source root")
    destination_root.mkdir(parents=True, exist_ok=True)
    records: list[SourceFileRecord] = []
    for source in sources:
        _require_safe_path_component(source.id, "source id")
        original_path = Path(source.path).resolve()
        if not original_path.is_file():
            raise FileNotFoundError(original_path)
        destination = (destination_root / f"{source.id}-{original_path.name}").resolve()
        if not destination.is_relative_to(managed_root):
            raise ValueError("managed source destination must remain below the managed source root")
        if destination == original_path:
            raise ValueError("managed source destination must not be the original source file")
        if destination.exists():
            raise FileExistsError(f"managed source already exists: {destination}")
        shutil.copyfile(original_path, destination)
        source_bytes = original_path.read_bytes()
        if destination.read_bytes() != source_bytes:
            raise RuntimeError(f"managed copy is not byte-identical: {destination}")
        record = SourceFileRecord(
            id=source.id,
            version_id=version_id,
            source_kind=source.source_kind,
            original_path=str(original_path),
            managed_path=destination.relative_to(root).as_posix(),
            sha256=sha256(source_bytes).hexdigest(),
            byte_size=len(source_bytes),
            provenance_json=json.dumps(dict(source.provenance), ensure_ascii=False, sort_keys=True),
        )
        registry.add_source_file(record, actor=actor)
        records.append(record)
    return records


def make_node_metadata(
    raw_chunk: RawChunkRecord,
    *,
    guideline_id: str,
    version_id: str,
    language: str,
    authority_level: AuthorityLevel | str,
    source_sha256: str,
    source_kind: SourceKind | str,
) -> dict[str, object]:
    """Make the explicit provenance metadata carried by every LlamaIndex node."""
    locator = json.loads(raw_chunk.locator_json)
    authority = authority_level.value if isinstance(authority_level, AuthorityLevel) else authority_level
    kind = source_kind.value if isinstance(source_kind, SourceKind) else source_kind
    metadata: dict[str, object] = {
        "guideline_id": guideline_id,
        "version_id": version_id,
        "language": language,
        "authority_level": authority,
        "source_kind": kind,
        "source_sha256": source_sha256,
        "source_file_id": raw_chunk.source_file_id,
        "raw_chunk_id": raw_chunk.id,
        "chunk_id": raw_chunk.chunk_id,
        "source_ordinal": raw_chunk.source_ordinal,
        "content_sha256": raw_chunk.content_sha256,
    }
    for field in (*REQUIRED_CHUNK_FIELDS, *OPTIONAL_CHUNK_FIELDS):
        if field in locator:
            metadata[field] = locator[field]
    return metadata


def _validate_chunk_payload(payload: Mapping[str, object], line_number: int) -> None:
    for field in REQUIRED_CHUNK_FIELDS:
        if field not in payload:
            raise JsonlIngestionError(f"line {line_number}: missing required field: {field}")
    if not isinstance(payload["chunk_id"], str) or not payload["chunk_id"]:
        raise JsonlIngestionError(f"line {line_number}: chunk_id must be a non-empty string")
    if not isinstance(payload["text"], str):
        raise JsonlIngestionError(f"line {line_number}: text must be a string")


def _require_safe_path_component(value: str, label: str) -> None:
    candidate = Path(value)
    if not value or candidate.is_absolute() or value in {".", ".."} or len(candidate.parts) != 1:
        raise ValueError(f"{label} must be a safe path component")
