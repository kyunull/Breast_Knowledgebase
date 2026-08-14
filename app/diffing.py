from __future__ import annotations

from hashlib import sha256
import unicodedata

from app.constants import ChangeType
from app.contracts import RawChunkRecord, VersionDiffRecord
from app.registry import Registry


def normalize_text(text: str) -> str:
    """Normalize with Unicode NFKC and collapse all whitespace runs.

    Case and punctuation remain significant so clinically meaningful distinctions are
    not silently discarded.
    """
    return " ".join(unicodedata.normalize("NFKC", text).split())


def normalized_text_sha256(text: str) -> str:
    return sha256(normalize_text(text).encode("utf-8")).hexdigest()


class VersionDiffer:
    """Compare and persist two versions of the same guideline by source chunk ID."""

    def __init__(self, registry: Registry) -> None:
        self._registry = registry

    def compare(
        self, prior_version_id: str, current_version_id: str, *, actor: str
    ) -> list[VersionDiffRecord]:
        prior_version = self._registry.get_version(prior_version_id)
        current_version = self._registry.get_version(current_version_id)
        if prior_version.guideline_id != current_version.guideline_id:
            raise ValueError("version diff requires versions from the same guideline")
        if prior_version.id == current_version.id:
            raise ValueError("version diff requires two distinct versions")

        prior = self._by_chunk_id(
            self._registry.list_raw_chunks_for_version(prior_version_id), prior_version_id
        )
        current = self._by_chunk_id(
            self._registry.list_raw_chunks_for_version(current_version_id), current_version_id
        )
        records: list[VersionDiffRecord] = []
        for chunk_id in sorted(set(prior) | set(current)):
            old = prior.get(chunk_id)
            new = current.get(chunk_id)
            old_hash = normalized_text_sha256(old.text) if old else None
            new_hash = normalized_text_sha256(new.text) if new else None
            if old is None:
                change_type = ChangeType.ADDED
            elif new is None:
                change_type = ChangeType.REMOVED
            elif old_hash == new_hash:
                change_type = ChangeType.UNCHANGED
            else:
                change_type = ChangeType.MODIFIED
            record_id = sha256(
                f"{prior_version_id}\0{current_version_id}\0{chunk_id}".encode("utf-8")
            ).hexdigest()
            records.append(
                VersionDiffRecord(
                    id=record_id,
                    prior_version_id=prior_version_id,
                    current_version_id=current_version_id,
                    chunk_id=chunk_id,
                    change_type=change_type,
                    prior_raw_chunk_id=old.id if old else None,
                    current_raw_chunk_id=new.id if new else None,
                    prior_normalized_sha256=old_hash,
                    current_normalized_sha256=new_hash,
                )
            )
        self._registry.replace_version_diffs(records, actor=actor)
        return records

    @staticmethod
    def _by_chunk_id(
        chunks: list[RawChunkRecord], version_id: str
    ) -> dict[str, RawChunkRecord]:
        result: dict[str, RawChunkRecord] = {}
        for chunk in chunks:
            if chunk.chunk_id in result:
                raise ValueError(
                    f"version {version_id} contains duplicate original chunk ID: {chunk.chunk_id}"
                )
            result[chunk.chunk_id] = chunk
        return result
