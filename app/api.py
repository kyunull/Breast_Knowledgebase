from __future__ import annotations

from dataclasses import asdict
from pathlib import Path
from typing import Annotated, Any

from fastapi import FastAPI, Query, status
from pydantic import BaseModel, Field, field_validator

from app.constants import AuthorityLevel, SourceKind
from app.contracts import GuidelineInput, SearchRequest, VersionInput
from app.ingestion import ManagedSourceInput
from app.lifecycle import GuidelineIngestRequest
from app.service import GuidelineService


NonEmptyText = Annotated[str, Field(min_length=1)]


class GuidelineModel(BaseModel):
    id: NonEmptyText
    title: NonEmptyText
    language: NonEmptyText
    authority_level: AuthorityLevel
    title_zh: str | None = None
    publisher: str | None = None


class VersionModel(BaseModel):
    id: NonEmptyText
    guideline_id: NonEmptyText
    version_label: NonEmptyText
    published_at: str | None = None


class SourceModel(BaseModel):
    id: NonEmptyText
    path: Path
    source_kind: SourceKind
    provenance: dict[str, object] = Field(default_factory=dict)


class IngestModel(BaseModel):
    actor: NonEmptyText
    version: VersionModel
    language: NonEmptyText
    authority_level: AuthorityLevel
    sources: list[SourceModel] = Field(min_length=2)
    jsonl_source_id: NonEmptyText
    citation_source_id: NonEmptyText
    guideline: GuidelineModel | None = None

    @field_validator("actor", "language", "jsonl_source_id", "citation_source_id")
    @classmethod
    def reject_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("must not be blank")
        return value.strip()


class ApprovalModel(BaseModel):
    reviewer: Annotated[str, Field(min_length=1)]

    @field_validator("reviewer")
    @classmethod
    def reject_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("reviewer must not be blank")
        return value.strip()


class SearchModel(BaseModel):
    query: Annotated[str, Field(min_length=1)]
    guideline_ids: list[str] = Field(default_factory=list)
    version_ids: list[str] = Field(default_factory=list)
    language: str | None = None
    top_k: int = Field(default=5, ge=1, le=100)
    use_bm25: bool = False

    @field_validator("query")
    @classmethod
    def reject_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("query must not be blank")
        return value.strip()


def to_domain_ingest(value: IngestModel) -> tuple[GuidelineIngestRequest, GuidelineInput | None]:
    request = GuidelineIngestRequest(
        version=VersionInput(**value.version.model_dump()),
        language=value.language,
        authority_level=value.authority_level,
        sources=tuple(
            ManagedSourceInput(
                id=source.id,
                path=source.path,
                source_kind=source.source_kind,
                provenance=source.provenance,
            )
            for source in value.sources
        ),
        jsonl_source_id=value.jsonl_source_id,
        citation_source_id=value.citation_source_id,
    )
    guideline = GuidelineInput(**value.guideline.model_dump()) if value.guideline else None
    return request, guideline


def create_app(service: GuidelineService) -> FastAPI:
    app = FastAPI(title="Versioned Guideline Evidence API", version="0.1.0")

    @app.post("/ingest", status_code=status.HTTP_201_CREATED)
    def ingest(value: IngestModel) -> dict[str, Any]:
        request, guideline = to_domain_ingest(value)
        return asdict(
            service.ingest(request, actor=value.actor, guideline=guideline)
        )

    @app.post("/versions/{version_id}/approve")
    def approve(version_id: str, value: ApprovalModel) -> dict[str, Any]:
        return asdict(service.approve(version_id, reviewer=value.reviewer))

    @app.post("/search")
    def search(value: SearchModel) -> dict[str, Any]:
        response = service.search(
            SearchRequest(
                query=value.query,
                guideline_ids=tuple(value.guideline_ids),
                version_ids=tuple(value.version_ids),
                language=value.language,
                top_k=value.top_k,
                use_bm25=value.use_bm25,
            )
        )
        return asdict(response)

    @app.get("/guidelines")
    def guidelines() -> list[dict[str, object]]:
        return service.list_guidelines()

    @app.get("/versions/{version_id}/diff")
    def diff(
        version_id: str,
        prior_version_id: Annotated[str, Query(min_length=1)],
    ) -> list[dict[str, Any]]:
        return [asdict(item) for item in service.diff(prior_version_id, version_id)]

    @app.get("/audit")
    def audit() -> list[dict[str, Any]]:
        return [asdict(item) for item in service.audit()]

    @app.exception_handler(KeyError)
    async def key_error_handler(_, error: KeyError):
        return _validation_response(str(error).strip("'"))

    @app.exception_handler(ValueError)
    async def value_error_handler(_, error: ValueError):
        return _validation_response(str(error))

    @app.exception_handler(FileNotFoundError)
    async def missing_file_handler(_, error: FileNotFoundError):
        return _validation_response(f"source file does not exist: {error.filename or error}")

    return app


def _validation_response(detail: str):
    from fastapi.responses import JSONResponse

    return JSONResponse(status_code=422, content={"detail": detail})
