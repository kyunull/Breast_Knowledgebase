from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
import json
import os
from pathlib import Path
import re
import shutil
from typing import Iterable, Mapping, Sequence
from uuid import uuid4

from llama_index.core import StorageContext, VectorStoreIndex, load_index_from_storage
from llama_index.core.base.embeddings.base import BaseEmbedding
from llama_index.core.schema import TextNode

from app.constants import AuthorityLevel, SourceKind
from app.contracts import RawChunkRecord, VersionRecord
from app.ingestion import make_node_metadata


class SnapshotIntegrityError(RuntimeError):
    """A persisted LlamaIndex snapshot does not match its signed inventory."""


_MODEL_PROFILE_FIELDS = {"provider", "model_name", "dimension", "normalize"}
_PINNED_LOCAL_MODEL = "BAAI/bge-m3"
_PINNED_LOCAL_REVISION = "5617a9f61b028005a4858fdac845db406aefb181"
_PINNED_LOCAL_DIMENSION = 1024


@dataclass(frozen=True, slots=True)
class NodeBuildContext:
    guideline_id: str
    version_id: str
    language: str
    authority_level: AuthorityLevel | str
    source_sha256: str
    source_kind: SourceKind | str


@dataclass(frozen=True, slots=True)
class SnapshotInfo:
    guideline_id: str
    version_id: str
    index_id: str
    path: Path
    node_count: int
    manifest_sha256: str


class ProvenanceNodeBuilder:
    """Build LlamaIndex nodes without changing the registered raw chunks."""

    def build(
        self, raw_chunks: Iterable[RawChunkRecord], context: NodeBuildContext
    ) -> list[TextNode]:
        nodes: list[TextNode] = []
        for raw_chunk in raw_chunks:
            fragment_ordinal = 0
            char_start = 0
            char_end = len(raw_chunk.text)
            metadata = make_node_metadata(
                raw_chunk,
                guideline_id=context.guideline_id,
                version_id=context.version_id,
                language=context.language,
                authority_level=context.authority_level,
                source_sha256=context.source_sha256,
                source_kind=context.source_kind,
            )
            metadata.update(
                {
                    "fragment_ordinal": fragment_ordinal,
                    "char_start": char_start,
                    "char_end": char_end,
                }
            )
            nodes.append(
                TextNode(
                    id_=f"{context.guideline_id}:{context.version_id}:{raw_chunk.chunk_id}:{fragment_ordinal}",
                    text=raw_chunk.text,
                    metadata=metadata,
                    start_char_idx=char_start,
                    end_char_idx=char_end,
                )
            )
        return nodes


class IndexSnapshotStore:
    """Persist, verify, and load immutable version-scoped LlamaIndex snapshots."""

    _MANIFEST_NAME = "manifest.json"
    _SHA256_PATTERN = re.compile(r"[0-9a-f]{64}")

    def __init__(
        self,
        index_root: Path,
        *,
        embed_model: BaseEmbedding,
        model_metadata: Mapping[str, object],
    ) -> None:
        self._index_root = Path(index_root).resolve()
        self._embed_model = embed_model
        self._model_metadata = _normalize_configured_model_metadata(
            model_metadata, embed_model
        )

    @property
    def index_root(self) -> Path:
        return self._index_root

    def build(self, version: VersionRecord, nodes: Sequence[TextNode]) -> SnapshotInfo:
        _require_safe_path_component(version.guideline_id, "guideline_id")
        _require_safe_path_component(version.id, "version_id")
        guideline_root = self._contained_path(self._index_root / version.guideline_id)
        destination = self._contained_path(guideline_root / version.id)
        if destination.exists():
            raise FileExistsError(f"published snapshot already exists: {destination}")

        guideline_root.mkdir(parents=True, exist_ok=True)
        staging = self._contained_path(
            guideline_root / f".{version.id}.staging-{uuid4().hex}"
        )
        index_id = f"{version.guideline_id}:{version.id}"
        try:
            storage_context = StorageContext.from_defaults()
            index = VectorStoreIndex(
                nodes=list(nodes),
                storage_context=storage_context,
                embed_model=self._embed_model,
                show_progress=False,
            )
            index.set_index_id(index_id)
            index.storage_context.persist(persist_dir=str(staging))

            component_hashes = self._component_hashes(staging)
            manifest = {
                "component_hashes": component_hashes,
                "guideline_id": version.guideline_id,
                "index_id": index_id,
                "model": self._model_metadata,
                "node_count": len(nodes),
                "node_ids": sorted(node.node_id for node in nodes),
                "version_id": version.id,
            }
            manifest_bytes = _canonical_json_bytes(manifest)
            (staging / self._MANIFEST_NAME).write_bytes(manifest_bytes)
            staging_info = SnapshotInfo(
                guideline_id=version.guideline_id,
                version_id=version.id,
                index_id=index_id,
                path=staging,
                node_count=len(nodes),
                manifest_sha256=sha256(manifest_bytes).hexdigest(),
            )
            self._verify_at_path(staging_info, staging)

            if destination.exists():
                raise FileExistsError(f"published snapshot already exists: {destination}")
            try:
                os.rename(staging, destination)
            except OSError as error:
                if destination.exists():
                    raise FileExistsError(
                        f"published snapshot already exists: {destination}"
                    ) from error
                raise
            return SnapshotInfo(
                guideline_id=version.guideline_id,
                version_id=version.id,
                index_id=index_id,
                path=destination,
                node_count=len(nodes),
                manifest_sha256=staging_info.manifest_sha256,
            )
        except Exception:
            if staging.exists():
                shutil.rmtree(staging)
            raise

    def verify(self, snapshot: SnapshotInfo) -> None:
        snapshot_path = self._canonical_snapshot_path(snapshot)
        self._verify_at_path(snapshot, snapshot_path)

    def _verify_at_path(self, snapshot: SnapshotInfo, snapshot_path: Path) -> None:
        manifest_path = snapshot_path / self._MANIFEST_NAME
        if not manifest_path.is_file():
            raise SnapshotIntegrityError(f"missing manifest: {manifest_path}")
        manifest_bytes = manifest_path.read_bytes()
        if sha256(manifest_bytes).hexdigest() != snapshot.manifest_sha256:
            raise SnapshotIntegrityError("manifest hash mismatch")
        try:
            manifest = json.loads(manifest_bytes)
        except (UnicodeDecodeError, json.JSONDecodeError) as error:
            raise SnapshotIntegrityError("manifest is not valid UTF-8 JSON") from error
        if not isinstance(manifest, dict) or manifest_bytes != _canonical_json_bytes(manifest):
            raise SnapshotIntegrityError("manifest is not canonical JSON")

        self._verify_manifest_identity(manifest, snapshot)
        expected_hashes = manifest.get("component_hashes")
        if not isinstance(expected_hashes, dict):
            raise SnapshotIntegrityError("manifest component_hashes must be an object")
        actual_hashes = self._component_hashes(snapshot_path)
        if set(actual_hashes) != set(expected_hashes):
            raise SnapshotIntegrityError("snapshot component inventory mismatch")
        for relative_path, expected_hash in expected_hashes.items():
            if (
                not isinstance(relative_path, str)
                or not isinstance(expected_hash, str)
                or self._SHA256_PATTERN.fullmatch(expected_hash) is None
            ):
                raise SnapshotIntegrityError("manifest contains an invalid component hash")
            if actual_hashes[relative_path] != expected_hash:
                raise SnapshotIntegrityError(f"component hash mismatch: {relative_path}")

    def load(self, snapshot: SnapshotInfo) -> VectorStoreIndex:
        self.verify(snapshot)
        storage_context = StorageContext.from_defaults(persist_dir=str(snapshot.path))
        index = load_index_from_storage(
            storage_context,
            index_id=snapshot.index_id,
            embed_model=self._embed_model,
        )
        if not isinstance(index, VectorStoreIndex):
            raise SnapshotIntegrityError("snapshot does not contain a VectorStoreIndex")
        return index

    def _verify_manifest_identity(
        self, manifest: Mapping[str, object], snapshot: SnapshotInfo
    ) -> None:
        expected = {
            "guideline_id": snapshot.guideline_id,
            "version_id": snapshot.version_id,
            "index_id": snapshot.index_id,
            "node_count": snapshot.node_count,
        }
        for key, value in expected.items():
            if manifest.get(key) != value:
                raise SnapshotIntegrityError(f"manifest {key} mismatch")
        node_ids = manifest.get("node_ids")
        if (
            not isinstance(node_ids, list)
            or any(not isinstance(node_id, str) for node_id in node_ids)
            or len(node_ids) != snapshot.node_count
            or node_ids != sorted(node_ids)
            or len(set(node_ids)) != len(node_ids)
        ):
            raise SnapshotIntegrityError("manifest node inventory is invalid")
        manifest_model = _normalize_manifest_model_metadata(manifest.get("model"))
        if manifest_model != self._model_metadata:
            raise SnapshotIntegrityError("manifest model metadata mismatch")

    def _component_hashes(self, snapshot_path: Path) -> dict[str, str]:
        hashes: dict[str, str] = {}
        for path in sorted(snapshot_path.rglob("*")):
            if path.is_file() and path != snapshot_path / self._MANIFEST_NAME:
                relative_path = path.relative_to(snapshot_path).as_posix()
                hashes[relative_path] = sha256(path.read_bytes()).hexdigest()
        return hashes

    def _canonical_snapshot_path(self, snapshot: SnapshotInfo) -> Path:
        _require_safe_path_component(snapshot.guideline_id, "guideline_id")
        _require_safe_path_component(snapshot.version_id, "version_id")
        expected_path = self._contained_path(
            self._index_root / snapshot.guideline_id / snapshot.version_id
        )
        actual_path = self._contained_path(snapshot.path)
        if actual_path != expected_path:
            raise SnapshotIntegrityError("snapshot path is not the canonical version directory")
        return actual_path

    def _contained_path(self, path: Path) -> Path:
        resolved = Path(path).resolve()
        if not resolved.is_relative_to(self._index_root):
            raise ValueError("snapshot path must remain below the index root")
        return resolved


def _canonical_json_bytes(value: Mapping[str, object]) -> bytes:
    return (
        json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n"
    ).encode("utf-8")


def _normalize_configured_model_metadata(
    metadata: Mapping[str, object], embed_model: BaseEmbedding
) -> dict[str, object]:
    values = dict(metadata)
    dimension = values.get("dimension", values.get("embed_dim"))
    if dimension is None:
        dimension = getattr(embed_model, "dimension", None)
    if dimension is None:
        dimension = getattr(embed_model, "embed_dim", None)
    model_name = values.get("model_name") or getattr(
        embed_model, "model_name", None
    )
    provider = values.get("provider")
    if provider == "huggingface" and model_name == _PINNED_LOCAL_MODEL:
        provider = "local"
    profile = _validated_model_profile(
        {
            "provider": provider,
            "model_name": model_name,
            "dimension": dimension,
            "normalize": values.get("normalize", True),
        }
    )
    revision = values.get("revision")
    if profile["provider"] == "local" and revision is not None:
        if not isinstance(revision, str) or not revision:
            raise ValueError("local embedding revision must be a non-empty string")
        profile["revision"] = revision
    return profile


def _normalize_manifest_model_metadata(value: object) -> dict[str, object]:
    if not isinstance(value, dict):
        raise SnapshotIntegrityError("manifest model metadata is invalid")
    if _MODEL_PROFILE_FIELDS.issubset(value):
        try:
            profile = _validated_model_profile(value)
        except ValueError as exc:
            raise SnapshotIntegrityError("manifest model metadata is invalid") from exc
        revision = value.get("revision")
        if profile["provider"] == "local" and revision is not None:
            if not isinstance(revision, str) or not revision:
                raise SnapshotIntegrityError("manifest model metadata is invalid")
            profile["revision"] = revision
        return profile

    if (
        value.get("provider") == "huggingface"
        and value.get("model_name") == _PINNED_LOCAL_MODEL
        and value.get("revision") in {None, _PINNED_LOCAL_REVISION}
    ):
        return {
            "provider": "local",
            "model_name": _PINNED_LOCAL_MODEL,
            "dimension": _PINNED_LOCAL_DIMENSION,
            "normalize": True,
            "revision": _PINNED_LOCAL_REVISION,
        }
    raise SnapshotIntegrityError("manifest model metadata is invalid")


def _validated_model_profile(value: Mapping[str, object]) -> dict[str, object]:
    provider = value.get("provider")
    model_name = value.get("model_name")
    dimension = value.get("dimension")
    normalize = value.get("normalize")
    if not isinstance(provider, str) or not provider:
        raise ValueError("embedding provider must be a non-empty string")
    if not isinstance(model_name, str) or not model_name:
        raise ValueError("embedding model_name must be a non-empty string")
    if (
        not isinstance(dimension, int)
        or isinstance(dimension, bool)
        or dimension < 1
    ):
        raise ValueError("embedding dimension must be a positive integer")
    if not isinstance(normalize, bool):
        raise ValueError("embedding normalize must be boolean")
    return {
        "provider": provider,
        "model_name": model_name,
        "dimension": dimension,
        "normalize": normalize,
    }


def _require_safe_path_component(value: str, label: str) -> None:
    candidate = Path(value)
    windows_reserved = {
        "CON",
        "PRN",
        "AUX",
        "NUL",
        *(f"COM{number}" for number in range(1, 10)),
        *(f"LPT{number}" for number in range(1, 10)),
    }
    invalid_windows_name = (
        any(character in '<>:"/\\|?*' or ord(character) < 32 for character in value)
        or value.endswith((" ", "."))
        or value.split(".", 1)[0].upper() in windows_reserved
    )
    if (
        not value
        or candidate.is_absolute()
        or value in {".", ".."}
        or len(candidate.parts) != 1
        or invalid_windows_name
    ):
        raise ValueError(f"{label} must be a safe path component")
