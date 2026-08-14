from __future__ import annotations

from dataclasses import asdict
import os
from pathlib import Path
from typing import Mapping

from llama_index.core.base.embeddings.base import BaseEmbedding

from app.contracts import GuidelineInput, SearchRequest, SearchResponse, VersionRecord
from app.index_store import IndexSnapshotStore, SnapshotInfo
from app.lifecycle import GuidelineIngestRequest, GuidelineLifecycle
from app.registry import Registry
from app.retrieval import EvidenceRetriever
from app.settings import Settings


class GuidelineService:
    """Use-case boundary shared by the local API and command-line tools."""

    def __init__(
        self,
        settings: Settings,
        *,
        embed_model: BaseEmbedding | None = None,
        model_metadata: Mapping[str, object] | None = None,
    ) -> None:
        self.settings = settings
        self._validate_settings()
        self.settings.ensure_directories()
        os.environ.update(self.settings.runtime_environment())
        self.registry = Registry(self.settings.registry_db_path)
        self.registry.initialize()
        self._embed_model = embed_model
        self._model_metadata = dict(model_metadata or self._default_model_metadata())
        self._index_store: IndexSnapshotStore | None = None
        self._lifecycle: GuidelineLifecycle | None = None
        self._retriever: EvidenceRetriever | None = None

    @property
    def index_store(self) -> IndexSnapshotStore:
        if self._index_store is None:
            self._index_store = IndexSnapshotStore(
                self.settings.index_root,
                embed_model=self._get_embed_model(),
                model_metadata=self._model_metadata,
            )
        return self._index_store

    @property
    def lifecycle(self) -> GuidelineLifecycle:
        if self._lifecycle is None:
            self._lifecycle = GuidelineLifecycle(
                registry=self.registry,
                managed_sources_dir=self.settings.managed_sources_dir,
                index_store=self.index_store,
                project_root=self.settings.project_root,
            )
        return self._lifecycle

    @property
    def retriever(self) -> EvidenceRetriever:
        if self._retriever is None:
            self._retriever = EvidenceRetriever(
                registry=self.registry,
                index_store=self.index_store,
            )
        return self._retriever

    def ingest(
        self,
        request: GuidelineIngestRequest,
        *,
        actor: str,
        guideline: GuidelineInput | None = None,
    ) -> VersionRecord:
        for source in request.sources:
            submitted_path = Path(source.path)
            if not submitted_path.is_absolute():
                raise ValueError(f"absolute source path required: {submitted_path}")
            source_path = submitted_path.resolve()
            if not source_path.is_file():
                raise FileNotFoundError(source_path)
        if guideline is not None:
            try:
                existing = self.registry.get_guideline(guideline.id)
            except KeyError:
                self.registry.create_guideline(guideline, actor=actor)
            else:
                if asdict(existing) != asdict(guideline):
                    raise ValueError(
                        f"guideline metadata conflicts with registered guideline: {guideline.id}"
                    )
        return self.lifecycle.ingest(request, actor=actor)

    def approve(self, version_id: str, *, reviewer: str) -> VersionRecord:
        if not reviewer.strip():
            raise ValueError("reviewer must not be empty")
        self.registry.get_version(version_id)
        return self.lifecycle.approve(version_id, actor=reviewer.strip())

    def search(self, request: SearchRequest) -> SearchResponse:
        return self.retriever.search(request)

    def list_guidelines(self) -> list[dict[str, object]]:
        versions = self.registry.list_versions()
        return [
            {
                **asdict(guideline),
                "versions": [
                    asdict(version)
                    for version in versions
                    if version.guideline_id == guideline.id
                ],
            }
            for guideline in self.registry.list_guidelines()
        ]

    def diff(self, prior_version_id: str, current_version_id: str):
        prior = self.registry.get_version(prior_version_id)
        current = self.registry.get_version(current_version_id)
        if prior.guideline_id != current.guideline_id:
            raise ValueError("version diff requires versions from the same guideline")
        return self.registry.list_version_diffs(prior.id, current.id)

    def audit(self):
        return self.registry.list_audit()

    def snapshot_info(self, version_id: str) -> SnapshotInfo:
        version = self.registry.get_version(version_id)
        if not version.snapshot_path or not version.snapshot_manifest_sha256:
            raise ValueError(f"version has no registered snapshot: {version_id}")
        return SnapshotInfo(
            guideline_id=version.guideline_id,
            version_id=version.id,
            index_id=f"{version.guideline_id}:{version.id}",
            path=Path(version.snapshot_path),
            node_count=self.registry.count_nodes_for_version(version.id),
            manifest_sha256=version.snapshot_manifest_sha256,
        )

    def _get_embed_model(self) -> BaseEmbedding:
        if self._embed_model is None:
            model_options: dict[str, object] = {
                "local_files_only": self.settings.model_local_files_only,
            }
            if self.settings.model_revision is not None:
                model_options["revision"] = self.settings.model_revision
            self._embed_model = _create_huggingface_embedding(
                model_name=self.settings.model_name,
                max_length=self.settings.model_max_seq_length,
                embed_batch_size=self.settings.embedding_batch_size,
                cache_folder=str(self.settings.model_cache_dir),
                device=self.settings.model_device,
                trust_remote_code=False,
                show_progress_bar=False,
                **model_options,
            )
        return self._embed_model

    def _default_model_metadata(self) -> dict[str, object]:
        return {
            "provider": "huggingface",
            "model_name": self.settings.model_name,
            "revision": self.settings.model_revision,
            "device": self.settings.model_device,
            "max_length": self.settings.model_max_seq_length,
        }

    def _validate_settings(self) -> None:
        project_root = self.settings.project_root.resolve()
        for writable in (
            self.settings.data_dir,
            self.settings.registry_db_path,
            self.settings.managed_sources_dir,
            self.settings.index_root,
            self.settings.model_cache_dir,
            self.settings.runtime_cache_dir,
        ):
            if not Path(writable).resolve().is_relative_to(project_root):
                raise ValueError(f"writable path must remain below project root: {writable}")


def _create_huggingface_embedding(**kwargs: object) -> BaseEmbedding:
    """Import the Hugging Face adapter only after local/offline environment setup."""
    from llama_index.embeddings.huggingface import HuggingFaceEmbedding

    return HuggingFaceEmbedding(**kwargs)
