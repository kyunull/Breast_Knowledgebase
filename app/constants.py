from __future__ import annotations

from enum import StrEnum


class VersionStatus(StrEnum):
    DRAFT = "draft"
    ACTIVE = "active"
    SUPERSEDED = "superseded"
    ARCHIVED = "archived"


class AuthorityLevel(StrEnum):
    PRIMARY_GUIDELINE = "primary_guideline"
    PRIMARY_PUBLICATION = "primary_publication"
    SECONDARY_SUMMARY = "secondary_summary"


class SourceKind(StrEnum):
    PDF = "pdf"
    HTML = "html"
    JSONL = "jsonl"


class ChangeType(StrEnum):
    ADDED = "added"
    REMOVED = "removed"
    MODIFIED = "modified"
    UNCHANGED = "unchanged"
