from __future__ import annotations

import json
import re
import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Iterable, Iterator

from app.constants import AuthorityLevel, ChangeType, VersionStatus
from app.contracts import (
    AuditEvent,
    GuidelineRecord,
    GuidelineInput,
    NodeManifestRecord,
    RawChunkRecord,
    SourceFileRecord,
    VersionInput,
    VersionDiffRecord,
    VersionRecord,
)


SCHEMA = """
PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS guideline (
    id TEXT PRIMARY KEY,
    title TEXT NOT NULL,
    title_zh TEXT,
    publisher TEXT,
    language TEXT NOT NULL,
    authority_level TEXT NOT NULL CHECK(authority_level IN ('primary_guideline', 'primary_publication', 'secondary_summary')),
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS document_version (
    id TEXT PRIMARY KEY,
    guideline_id TEXT NOT NULL REFERENCES guideline(id),
    version_label TEXT NOT NULL,
    status TEXT NOT NULL CHECK(status IN ('draft', 'active', 'superseded', 'archived')),
    snapshot_path TEXT,
    snapshot_manifest_sha256 TEXT CHECK(
        snapshot_manifest_sha256 IS NULL OR (
            length(snapshot_manifest_sha256) = 64
            AND snapshot_manifest_sha256 NOT GLOB '*[^0-9A-Fa-f]*'
        )
    ),
    published_at TEXT,
    approved_at TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(guideline_id, version_label)
);
CREATE UNIQUE INDEX IF NOT EXISTS one_active_version_per_guideline
ON document_version(guideline_id) WHERE status = 'active';

CREATE TABLE IF NOT EXISTS source_file (
    id TEXT PRIMARY KEY,
    document_version_id TEXT NOT NULL REFERENCES document_version(id),
    source_kind TEXT NOT NULL CHECK(source_kind IN ('pdf', 'html', 'jsonl')),
    original_path TEXT NOT NULL,
    managed_path TEXT NOT NULL UNIQUE,
    sha256 TEXT NOT NULL CHECK(length(sha256) = 64 AND sha256 NOT GLOB '*[^0-9A-Fa-f]*'),
    byte_size INTEGER NOT NULL CHECK(byte_size >= 0),
    provenance_json TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS source_file_version_idx ON source_file(document_version_id);

CREATE TABLE IF NOT EXISTS raw_chunk (
    id TEXT PRIMARY KEY,
    source_file_id TEXT NOT NULL REFERENCES source_file(id),
    source_ordinal INTEGER NOT NULL CHECK(source_ordinal >= 1),
    chunk_id TEXT NOT NULL,
    text TEXT NOT NULL,
    content_sha256 TEXT NOT NULL CHECK(length(content_sha256) = 64 AND content_sha256 NOT GLOB '*[^0-9A-Fa-f]*'),
    locator_json TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(source_file_id, source_ordinal),
    UNIQUE(source_file_id, chunk_id)
);
CREATE INDEX IF NOT EXISTS raw_chunk_source_idx ON raw_chunk(source_file_id, source_ordinal);

CREATE TABLE IF NOT EXISTS node_manifest (
    node_id TEXT PRIMARY KEY,
    document_version_id TEXT NOT NULL REFERENCES document_version(id),
    raw_chunk_id TEXT NOT NULL REFERENCES raw_chunk(id),
    fragment_ordinal INTEGER NOT NULL CHECK(fragment_ordinal >= 0),
    source_ordinal INTEGER NOT NULL CHECK(source_ordinal >= 1),
    content_sha256 TEXT NOT NULL CHECK(length(content_sha256) = 64 AND content_sha256 NOT GLOB '*[^0-9A-Fa-f]*'),
    char_start INTEGER NOT NULL CHECK(char_start >= 0),
    char_end INTEGER NOT NULL CHECK(char_end >= char_start),
    metadata_json TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(document_version_id, raw_chunk_id, fragment_ordinal)
);
CREATE INDEX IF NOT EXISTS node_manifest_version_idx ON node_manifest(document_version_id, source_ordinal);

CREATE TABLE IF NOT EXISTS version_diff (
    id TEXT PRIMARY KEY,
    prior_version_id TEXT NOT NULL REFERENCES document_version(id),
    current_version_id TEXT NOT NULL REFERENCES document_version(id),
    change_type TEXT NOT NULL CHECK(change_type IN ('added', 'removed', 'modified', 'unchanged')),
    prior_raw_chunk_id TEXT,
    current_raw_chunk_id TEXT,
    detail_json TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS version_diff_versions_idx ON version_diff(prior_version_id, current_version_id);

CREATE TABLE IF NOT EXISTS audit_event (
    id INTEGER PRIMARY KEY,
    actor TEXT NOT NULL,
    action TEXT NOT NULL,
    entity_type TEXT NOT NULL,
    entity_id TEXT NOT NULL,
    payload_json TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS audit_event_entity_idx ON audit_event(entity_type, entity_id, created_at);
CREATE TRIGGER IF NOT EXISTS audit_event_no_update
BEFORE UPDATE ON audit_event BEGIN SELECT RAISE(ABORT, 'audit_event is append-only'); END;
CREATE TRIGGER IF NOT EXISTS audit_event_no_delete
BEFORE DELETE ON audit_event BEGIN SELECT RAISE(ABORT, 'audit_event is append-only'); END;
"""


class Registry:
    """SQLite source of truth for guideline lifecycle and provenance."""

    def __init__(self, path: Path) -> None:
        self.path = Path(path)

    def connect(self) -> sqlite3.Connection:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(self.path)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("PRAGMA journal_mode = WAL")
        return connection

    def initialize(self) -> None:
        with self.connect() as connection:
            connection.executescript(SCHEMA)

    @contextmanager
    def transaction(self) -> Iterator[sqlite3.Connection]:
        connection = self.connect()
        try:
            connection.execute("BEGIN IMMEDIATE")
            yield connection
        except BaseException:
            connection.rollback()
            raise
        else:
            connection.commit()
        finally:
            connection.close()

    def create_guideline(self, value: GuidelineInput, *, actor: str) -> None:
        with self.transaction() as connection:
            connection.execute(
                """
                INSERT INTO guideline(id, title, title_zh, publisher, language, authority_level)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (value.id, value.title, value.title_zh, value.publisher, value.language, value.authority_level.value),
            )
            self._record_audit(connection, actor, "guideline_created", "guideline", value.id, {})

    def create_draft_version(self, value: VersionInput, *, actor: str) -> VersionRecord:
        with self.transaction() as connection:
            connection.execute(
                """
                INSERT INTO document_version(id, guideline_id, version_label, status, snapshot_path, published_at)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (value.id, value.guideline_id, value.version_label, VersionStatus.DRAFT.value, value.snapshot_path, value.published_at),
            )
            self._record_audit(connection, actor, "draft_created", "document_version", value.id, {})
        return self.get_version(value.id)

    def add_source_file(self, value: SourceFileRecord, *, actor: str) -> None:
        self._validate_sha256(value.sha256, "source file")
        with self.transaction() as connection:
            connection.execute(
                """
                INSERT INTO source_file(id, document_version_id, source_kind, original_path, managed_path, sha256, byte_size, provenance_json)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    value.id,
                    value.version_id,
                    value.source_kind.value,
                    value.original_path,
                    value.managed_path,
                    value.sha256,
                    value.byte_size,
                    value.provenance_json,
                ),
            )
            self._record_audit(connection, actor, "source_file_added", "source_file", value.id, {})

    def add_raw_chunks(self, values: Iterable[RawChunkRecord], *, actor: str) -> None:
        rows = list(values)
        for value in rows:
            self._validate_sha256(value.content_sha256, "raw chunk")
        with self.transaction() as connection:
            connection.executemany(
                """
                INSERT INTO raw_chunk(id, source_file_id, source_ordinal, chunk_id, text, content_sha256, locator_json)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                [
                    (
                        value.id,
                        value.source_file_id,
                        value.source_ordinal,
                        value.chunk_id,
                        value.text,
                        value.content_sha256,
                        value.locator_json,
                    )
                    for value in rows
                ],
            )
            for value in rows:
                self._record_audit(connection, actor, "raw_chunk_added", "raw_chunk", value.id, {})

    def add_node_manifest(self, values: Iterable[NodeManifestRecord], *, actor: str) -> None:
        rows = list(values)
        for value in rows:
            self._validate_sha256(value.content_sha256, "node manifest")
        with self.transaction() as connection:
            connection.executemany(
                """
                INSERT INTO node_manifest(
                    node_id, document_version_id, raw_chunk_id, fragment_ordinal,
                    source_ordinal, content_sha256, char_start, char_end, metadata_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                [
                    (
                        value.node_id,
                        value.version_id,
                        value.raw_chunk_id,
                        value.fragment_ordinal,
                        value.source_ordinal,
                        value.content_sha256,
                        value.char_start,
                        value.char_end,
                        value.metadata_json,
                    )
                    for value in rows
                ],
            )
            for value in rows:
                self._record_audit(connection, actor, "node_manifest_added", "node_manifest", value.node_id, {})

    def approve_version(self, version_id: str, *, actor: str, snapshot_manifest_sha256: str) -> VersionRecord:
        self._validate_sha256(snapshot_manifest_sha256, "snapshot manifest")
        with self.transaction() as connection:
            row = connection.execute(
                "SELECT id, guideline_id, status FROM document_version WHERE id = ?", (version_id,)
            ).fetchone()
            if row is None:
                raise KeyError(f"unknown document version: {version_id}")
            if row["status"] != VersionStatus.DRAFT.value:
                raise ValueError(f"only draft versions can be approved: {version_id}")
            connection.execute(
                """
                UPDATE document_version
                SET status = ?, approved_at = CURRENT_TIMESTAMP
                WHERE guideline_id = ? AND status = ?
                """,
                (VersionStatus.SUPERSEDED.value, row["guideline_id"], VersionStatus.ACTIVE.value),
            )
            connection.execute(
                """
                UPDATE document_version
                SET status = ?, snapshot_manifest_sha256 = ?, approved_at = CURRENT_TIMESTAMP
                WHERE id = ?
                """,
                (VersionStatus.ACTIVE.value, snapshot_manifest_sha256, version_id),
            )
            self._record_audit(
                connection,
                actor,
                "version_approved",
                "document_version",
                version_id,
                {"snapshot_manifest_sha256": snapshot_manifest_sha256},
            )
        return self.get_version(version_id)

    def set_draft_snapshot(
        self,
        version_id: str,
        *,
        snapshot_path: str,
        snapshot_manifest_sha256: str,
        actor: str,
    ) -> VersionRecord:
        self._validate_sha256(snapshot_manifest_sha256, "snapshot manifest")
        with self.transaction() as connection:
            row = connection.execute(
                "SELECT status FROM document_version WHERE id = ?", (version_id,)
            ).fetchone()
            if row is None:
                raise KeyError(f"unknown document version: {version_id}")
            if row["status"] != VersionStatus.DRAFT.value:
                raise ValueError("snapshot can only be registered for a draft version")
            connection.execute(
                """
                UPDATE document_version
                SET snapshot_path = ?, snapshot_manifest_sha256 = ?
                WHERE id = ?
                """,
                (snapshot_path, snapshot_manifest_sha256, version_id),
            )
            self._record_audit(
                connection,
                actor,
                "snapshot_registered",
                "document_version",
                version_id,
                {
                    "snapshot_path": snapshot_path,
                    "snapshot_manifest_sha256": snapshot_manifest_sha256,
                },
            )
        return self.get_version(version_id)

    def archive_version(self, version_id: str, *, actor: str) -> VersionRecord:
        """Archive an already superseded version without changing active search."""
        with self.transaction() as connection:
            row = connection.execute(
                "SELECT id, status FROM document_version WHERE id = ?", (version_id,)
            ).fetchone()
            if row is None:
                raise KeyError(f"unknown document version: {version_id}")
            if row["status"] != VersionStatus.SUPERSEDED.value:
                raise ValueError("only superseded versions can be archived")
            if row["status"] == VersionStatus.ARCHIVED.value:
                raise ValueError(f"version is already archived: {version_id}")
            connection.execute(
                "UPDATE document_version SET status = ? WHERE id = ?",
                (VersionStatus.ARCHIVED.value, version_id),
            )
            self._record_audit(connection, actor, "version_archived", "document_version", version_id, {})
        return self.get_version(version_id)

    def rebase_runtime_paths(
        self,
        *,
        project_root: Path,
        managed_sources_dir: Path,
        index_root: Path,
        actor: str,
    ) -> int:
        root = Path(project_root).resolve()
        managed_root = Path(managed_sources_dir).resolve()
        snapshot_root = Path(index_root).resolve()
        for runtime_root in (managed_root, snapshot_root):
            if not runtime_root.is_relative_to(root):
                raise ValueError(
                    f"runtime path must remain below project root: {runtime_root}"
                )

        with self.transaction() as connection:
            version_rows = connection.execute(
                """
                SELECT id, guideline_id, snapshot_path
                FROM document_version
                WHERE snapshot_path IS NOT NULL
                ORDER BY id
                """
            ).fetchall()
            source_rows = connection.execute(
                """
                SELECT id, document_version_id, managed_path
                FROM source_file
                ORDER BY id
                """
            ).fetchall()

            snapshot_updates: list[tuple[str, str]] = []
            source_updates: list[tuple[str, str]] = []
            for row in version_rows:
                stored = Path(row["snapshot_path"])
                if not stored.is_absolute():
                    continue
                target = (snapshot_root / row["guideline_id"] / row["id"]).resolve()
                if not target.is_relative_to(root) or not target.is_dir():
                    raise FileNotFoundError(
                        f"snapshot target missing for version {row['id']}: {target}"
                    )
                snapshot_updates.append((target.relative_to(root).as_posix(), row["id"]))

            for row in source_rows:
                stored = Path(row["managed_path"])
                if not stored.is_absolute():
                    continue
                target = (
                    managed_root / row["document_version_id"] / stored.name
                ).resolve()
                if not target.is_relative_to(root) or not target.is_file():
                    raise FileNotFoundError(
                        f"managed source target missing for source {row['id']}: {target}"
                    )
                source_updates.append((target.relative_to(root).as_posix(), row["id"]))

            connection.executemany(
                "UPDATE document_version SET snapshot_path = ? WHERE id = ?",
                snapshot_updates,
            )
            connection.executemany(
                "UPDATE source_file SET managed_path = ? WHERE id = ?",
                source_updates,
            )
            path_count = len(snapshot_updates) + len(source_updates)
            if path_count:
                self._record_audit(
                    connection,
                    actor,
                    "project_paths_rebased",
                    "project",
                    "runtime_paths",
                    {"path_count": path_count},
                )
        return path_count

    def get_version(self, version_id: str) -> VersionRecord:
        with self.connect() as connection:
            row = connection.execute(
                """
                SELECT id, guideline_id, version_label, status, snapshot_path,
                       snapshot_manifest_sha256, published_at, created_at, approved_at
                FROM document_version WHERE id = ?
                """,
                (version_id,),
            ).fetchone()
        if row is None:
            raise KeyError(f"unknown document version: {version_id}")
        return self._version_from_row(row)

    def get_guideline(self, guideline_id: str) -> GuidelineRecord:
        with self.connect() as connection:
            row = connection.execute(
                """
                SELECT id, title, title_zh, publisher, language, authority_level
                FROM guideline WHERE id = ?
                """,
                (guideline_id,),
            ).fetchone()
        if row is None:
            raise KeyError(f"unknown guideline: {guideline_id}")
        return GuidelineRecord(
            id=row["id"],
            title=row["title"],
            title_zh=row["title_zh"],
            publisher=row["publisher"],
            language=row["language"],
            authority_level=AuthorityLevel(row["authority_level"]),
        )

    def list_guidelines(self) -> list[GuidelineRecord]:
        with self.connect() as connection:
            rows = connection.execute(
                """
                SELECT id, title, title_zh, publisher, language, authority_level
                FROM guideline ORDER BY id
                """
            ).fetchall()
        return [
            GuidelineRecord(
                id=row["id"],
                title=row["title"],
                title_zh=row["title_zh"],
                publisher=row["publisher"],
                language=row["language"],
                authority_level=AuthorityLevel(row["authority_level"]),
            )
            for row in rows
        ]

    def list_versions(self, guideline_id: str | None = None) -> list[VersionRecord]:
        query = """
            SELECT id, guideline_id, version_label, status, snapshot_path,
                   snapshot_manifest_sha256, published_at, created_at, approved_at
            FROM document_version
        """
        parameters: tuple[object, ...] = ()
        if guideline_id is not None:
            query += " WHERE guideline_id = ?"
            parameters = (guideline_id,)
        query += " ORDER BY guideline_id, created_at, id"
        with self.connect() as connection:
            rows = connection.execute(query, parameters).fetchall()
        return [self._version_from_row(row) for row in rows]

    def list_searchable_versions(self) -> list[VersionRecord]:
        with self.connect() as connection:
            rows = connection.execute(
                """
                SELECT id, guideline_id, version_label, status, snapshot_path,
                       snapshot_manifest_sha256, published_at, created_at, approved_at
                FROM document_version
                WHERE status = ?
                ORDER BY guideline_id, approved_at, id
                """,
                (VersionStatus.ACTIVE.value,),
            ).fetchall()
        return [self._version_from_row(row) for row in rows]

    def list_raw_chunks_for_version(self, version_id: str) -> list[RawChunkRecord]:
        with self.connect() as connection:
            rows = connection.execute(
                """
                SELECT raw_chunk.id, raw_chunk.source_file_id, raw_chunk.source_ordinal,
                       raw_chunk.chunk_id, raw_chunk.text, raw_chunk.content_sha256,
                       raw_chunk.locator_json
                FROM raw_chunk
                JOIN source_file ON source_file.id = raw_chunk.source_file_id
                WHERE source_file.document_version_id = ?
                ORDER BY raw_chunk.source_ordinal, raw_chunk.id
                """,
                (version_id,),
            ).fetchall()
        return [
            RawChunkRecord(
                id=row["id"],
                source_file_id=row["source_file_id"],
                source_ordinal=row["source_ordinal"],
                chunk_id=row["chunk_id"],
                text=row["text"],
                content_sha256=row["content_sha256"],
                locator_json=row["locator_json"],
            )
            for row in rows
        ]

    def count_nodes_for_version(self, version_id: str) -> int:
        with self.connect() as connection:
            row = connection.execute(
                "SELECT COUNT(*) FROM node_manifest WHERE document_version_id = ?",
                (version_id,),
            ).fetchone()
        return int(row[0])

    def replace_version_diffs(
        self, records: Iterable[VersionDiffRecord], *, actor: str
    ) -> None:
        rows = list(records)
        if not rows:
            return
        prior_version_id = rows[0].prior_version_id
        current_version_id = rows[0].current_version_id
        if any(
            row.prior_version_id != prior_version_id
            or row.current_version_id != current_version_id
            for row in rows
        ):
            raise ValueError("all diff records must describe the same version pair")
        with self.transaction() as connection:
            connection.execute(
                "DELETE FROM version_diff WHERE prior_version_id = ? AND current_version_id = ?",
                (prior_version_id, current_version_id),
            )
            connection.executemany(
                """
                INSERT INTO version_diff(
                    id, prior_version_id, current_version_id, change_type,
                    prior_raw_chunk_id, current_raw_chunk_id, detail_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                [
                    (
                        row.id,
                        row.prior_version_id,
                        row.current_version_id,
                        row.change_type.value,
                        row.prior_raw_chunk_id,
                        row.current_raw_chunk_id,
                        json.dumps(
                            {
                                "chunk_id": row.chunk_id,
                                "prior_normalized_sha256": row.prior_normalized_sha256,
                                "current_normalized_sha256": row.current_normalized_sha256,
                            },
                            sort_keys=True,
                        ),
                    )
                    for row in rows
                ],
            )
            self._record_audit(
                connection,
                actor,
                "version_diff_recorded",
                "document_version",
                current_version_id,
                {"prior_version_id": prior_version_id, "record_count": len(rows)},
            )

    def list_version_diffs(
        self, prior_version_id: str, current_version_id: str
    ) -> list[VersionDiffRecord]:
        with self.connect() as connection:
            rows = connection.execute(
                """
                SELECT id, prior_version_id, current_version_id, change_type,
                       prior_raw_chunk_id, current_raw_chunk_id, detail_json
                FROM version_diff
                WHERE prior_version_id = ? AND current_version_id = ?
                ORDER BY json_extract(detail_json, '$.chunk_id')
                """,
                (prior_version_id, current_version_id),
            ).fetchall()
        result: list[VersionDiffRecord] = []
        for row in rows:
            detail = json.loads(row["detail_json"])
            result.append(
                VersionDiffRecord(
                    id=row["id"],
                    prior_version_id=row["prior_version_id"],
                    current_version_id=row["current_version_id"],
                    chunk_id=detail["chunk_id"],
                    change_type=ChangeType(row["change_type"]),
                    prior_raw_chunk_id=row["prior_raw_chunk_id"],
                    current_raw_chunk_id=row["current_raw_chunk_id"],
                    prior_normalized_sha256=detail["prior_normalized_sha256"],
                    current_normalized_sha256=detail["current_normalized_sha256"],
                )
            )
        return result

    def record_audit(self, actor: str, action: str, entity_type: str, entity_id: str, payload: dict[str, object]) -> int:
        with self.transaction() as connection:
            return self._record_audit(connection, actor, action, entity_type, entity_id, payload)

    def list_audit(self) -> list[AuditEvent]:
        with self.connect() as connection:
            rows = connection.execute(
                "SELECT id, actor, action, entity_type, entity_id, payload_json, created_at FROM audit_event ORDER BY id"
            ).fetchall()
        return [
            AuditEvent(
                id=row["id"],
                actor=row["actor"],
                action=row["action"],
                entity_type=row["entity_type"],
                entity_id=row["entity_id"],
                payload_json=row["payload_json"],
                created_at=row["created_at"],
            )
            for row in rows
        ]

    def count_rows(self, table: str) -> int:
        if table not in {"source_file", "raw_chunk", "node_manifest"}:
            raise ValueError(f"unsupported table: {table}")
        with self.connect() as connection:
            return int(connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0])

    def execute_for_test(self, statement: str, parameters: tuple[object, ...] = ()) -> None:
        with self.connect() as connection:
            connection.execute(statement, parameters)

    @staticmethod
    def _record_audit(
        connection: sqlite3.Connection,
        actor: str,
        action: str,
        entity_type: str,
        entity_id: str,
        payload: dict[str, object],
    ) -> int:
        cursor = connection.execute(
            """
            INSERT INTO audit_event(actor, action, entity_type, entity_id, payload_json)
            VALUES (?, ?, ?, ?, ?)
            """,
            (actor, action, entity_type, entity_id, json.dumps(payload, sort_keys=True)),
        )
        return int(cursor.lastrowid)

    @staticmethod
    def _validate_sha256(value: str, subject: str) -> None:
        if re.fullmatch(r"[0-9a-fA-F]{64}", value) is None:
            raise ValueError(f"{subject} SHA-256 must contain 64 hexadecimal characters")

    @staticmethod
    def _version_from_row(row: sqlite3.Row) -> VersionRecord:
        return VersionRecord(
            id=row["id"],
            guideline_id=row["guideline_id"],
            version_label=row["version_label"],
            status=VersionStatus(row["status"]),
            snapshot_path=row["snapshot_path"],
            snapshot_manifest_sha256=row["snapshot_manifest_sha256"],
            published_at=row["published_at"],
            created_at=row["created_at"],
            approved_at=row["approved_at"],
        )
