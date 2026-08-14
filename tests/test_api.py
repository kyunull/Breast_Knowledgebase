from __future__ import annotations

import asyncio
import json
from pathlib import Path
from uuid import uuid4

import httpx
from llama_index.core.embeddings import MockEmbedding

from app.api import create_app
from app.constants import AuthorityLevel
from app.contracts import GuidelineInput
from app.service import GuidelineService
from app.settings import Settings
from scripts.ingest_guideline import load_ingest_config
from scripts.verify_snapshot import verify_registered_snapshot


PROJECT_ROOT = Path(r"D:\coding\knowledgebase")


class LocalApiClient:
    """Small synchronous facade over httpx's warning-free ASGI transport."""

    def __init__(self, app) -> None:
        self._app = app

    def request(self, method: str, url: str, **kwargs) -> httpx.Response:
        async def send() -> httpx.Response:
            transport = httpx.ASGITransport(app=self._app)
            async with httpx.AsyncClient(
                transport=transport, base_url="http://testserver"
            ) as client:
                return await client.request(method, url, **kwargs)

        return asyncio.run(send())

    def post(self, url: str, **kwargs) -> httpx.Response:
        return self.request("POST", url, **kwargs)

    def get(self, url: str, **kwargs) -> httpx.Response:
        return self.request("GET", url, **kwargs)


def _system() -> tuple[LocalApiClient, GuidelineService, Path]:
    root = PROJECT_ROOT / "data" / "runtime_cache" / "test_task6_api" / uuid4().hex
    settings = Settings.from_env(PROJECT_ROOT)
    settings = Settings(
        project_root=settings.project_root,
        data_dir=root,
        registry_db_path=root / "registry" / "knowledge.sqlite3",
        managed_sources_dir=root / "managed_sources",
        index_root=root / "llama_indices",
        model_cache_dir=root / "model_cache",
        runtime_cache_dir=root / "runtime_cache",
        model_name="mock-8",
        model_revision=None,
        model_device="cpu",
        model_max_seq_length=512,
        embedding_batch_size=4,
        model_local_files_only=False,
        bm25_enabled=False,
    )
    service = GuidelineService(
        settings,
        embed_model=MockEmbedding(embed_dim=8),
        model_metadata={"provider": "mock", "model_name": "mock-8", "embed_dim": 8},
    )
    service.registry.create_guideline(
        GuidelineInput(
            id="nccn",
            title="NCCN Breast Cancer",
            language="en",
            authority_level=AuthorityLevel.PRIMARY_GUIDELINE,
        ),
        actor="fixture",
    )
    return LocalApiClient(create_app(service)), service, root


def _source_payload(root: Path, version_id: str, text: str) -> dict[str, object]:
    input_root = root / "input"
    input_root.mkdir(parents=True, exist_ok=True)
    source_path = input_root / f"{version_id}.pdf"
    jsonl_path = input_root / f"{version_id}.jsonl"
    source_path.write_bytes(b"%PDF-1.4\nfixture only\n")
    jsonl_path.write_text(
        json.dumps(
            {
                "chunk_id": "her2-treatment",
                "doc_id": "nccn",
                "doc_title": "NCCN Breast Cancer",
                "section_path": "HER2-positive disease",
                "page_code": "BINV-1",
                "page_start": 0,
                "page_end": 0,
                "block_type": "paragraph",
                "text": text,
            }
        )
        + "\n",
        encoding="utf-8",
    )
    return {
        "actor": "importer",
        "version": {
            "id": version_id,
            "guideline_id": "nccn",
            "version_label": version_id,
        },
        "language": "en",
        "authority_level": "primary_guideline",
        "sources": [
            {
                "id": f"{version_id}-document",
                "path": str(source_path),
                "source_kind": "pdf",
                "provenance": {"role": "citation_source"},
            },
            {
                "id": f"{version_id}-chunks",
                "path": str(jsonl_path),
                "source_kind": "jsonl",
                "provenance": {"role": "chunk_input"},
            },
        ],
        "jsonl_source_id": f"{version_id}-chunks",
        "citation_source_id": f"{version_id}-document",
    }


def test_search_api_returns_only_traceable_evidence_after_approval() -> None:
    client, _, root = _system()
    ingested = client.post(
        "/ingest",
        json=_source_payload(root, "nccn-v1", "Trastuzumab is recommended evidence."),
    )
    assert ingested.status_code == 201
    assert ingested.json()["status"] == "draft"

    approved = client.post(
        "/versions/nccn-v1/approve", json={"reviewer": "reviewer-a"}
    )
    assert approved.status_code == 200
    assert approved.json()["status"] == "active"

    response = client.post(
        "/search",
        json={"query": "trastuzumab", "version_ids": ["nccn-v1"], "top_k": 1},
    )
    assert response.status_code == 200
    body = response.json()
    assert "answer" not in body
    assert body["resolved_version_ids"] == ["nccn-v1"]
    assert body["retrieval_modes"] == ["vector"]
    assert body["evidence"][0]["raw_chunk_id"]
    assert body["evidence"][0]["text"] == "Trastuzumab is recommended evidence."
    assert body["evidence"][0]["citation"]["raw_chunk_id"] == body["evidence"][0]["raw_chunk_id"]
    assert body["evidence"][0]["citation"]["locator"]


def test_approve_requires_a_non_empty_reviewer() -> None:
    client, _, _ = _system()

    missing = client.post("/versions/missing/approve", json={})
    blank = client.post("/versions/missing/approve", json={"reviewer": "   "})

    assert missing.status_code == 422
    assert blank.status_code == 422


def test_explicit_unknown_search_version_is_a_validation_error() -> None:
    client, _, _ = _system()

    response = client.post(
        "/search", json={"query": "trastuzumab", "version_ids": ["not-registered"]}
    )

    assert response.status_code == 422
    assert "unknown document version" in response.json()["detail"]


def test_ingest_rejects_non_d_drive_source_paths() -> None:
    client, _, root = _system()
    payload = _source_payload(root, "nccn-v1", "Evidence")
    payload["sources"][0]["path"] = r"C:\source\guide.pdf"

    response = client.post("/ingest", json=payload)

    assert response.status_code == 422
    assert "D drive" in str(response.json()["detail"])


def test_ingest_rejects_relative_source_paths_even_when_cwd_is_on_d_drive() -> None:
    client, _, root = _system()
    payload = _source_payload(root, "nccn-v1", "Evidence")
    payload["sources"][0]["path"] = "relative-guide.pdf"

    response = client.post("/ingest", json=payload)

    assert response.status_code == 422
    assert "absolute D-drive path" in str(response.json()["detail"])


def test_guidelines_diff_and_audit_endpoints_expose_version_governance() -> None:
    client, _, root = _system()
    client.post("/ingest", json=_source_payload(root, "nccn-v1", "First evidence"))
    client.post("/versions/nccn-v1/approve", json={"reviewer": "reviewer-a"})
    client.post("/ingest", json=_source_payload(root, "nccn-v2", "Updated evidence"))

    guidelines = client.get("/guidelines")
    diff = client.get("/versions/nccn-v2/diff", params={"prior_version_id": "nccn-v1"})
    audit = client.get("/audit")

    assert guidelines.status_code == 200
    assert guidelines.json()[0]["id"] == "nccn"
    assert {item["id"] for item in guidelines.json()[0]["versions"]} == {"nccn-v1", "nccn-v2"}
    assert diff.status_code == 200
    assert diff.json()[0]["change_type"] == "modified"
    assert audit.status_code == 200
    assert any(item["action"] == "version_approved" for item in audit.json())


def test_diff_rejects_an_unknown_version_explicitly() -> None:
    client, _, _ = _system()

    response = client.get(
        "/versions/not-registered/diff", params={"prior_version_id": "also-missing"}
    )

    assert response.status_code == 422
    assert "unknown document version" in response.json()["detail"]


def test_cli_config_loader_builds_the_same_validated_ingest_request() -> None:
    _, _, root = _system()
    payload = _source_payload(root, "nccn-v1", "Evidence")
    config_path = root / "ingest.json"
    config_path.write_text(json.dumps(payload), encoding="utf-8")

    actor, request, guideline = load_ingest_config(config_path, project_root=PROJECT_ROOT)

    assert actor == "importer"
    assert request.version.id == "nccn-v1"
    assert request.jsonl_source_id == "nccn-v1-chunks"
    assert guideline is None


def test_cli_config_loader_rejects_config_outside_the_d_project() -> None:
    try:
        load_ingest_config(Path(r"C:\ingest.json"), project_root=PROJECT_ROOT)
    except ValueError as error:
        assert "below project root" in str(error)
    else:
        raise AssertionError("C-drive config must be rejected")


def test_verify_snapshot_cli_helper_reopens_and_verifies_registered_snapshot() -> None:
    client, service, root = _system()
    client.post("/ingest", json=_source_payload(root, "nccn-v1", "Evidence"))

    snapshot = verify_registered_snapshot(service, "nccn-v1")

    assert snapshot.version_id == "nccn-v1"
    assert snapshot.path.is_dir()


def test_model_loader_passes_explicit_offline_and_revision_controls(monkeypatch) -> None:
    root = PROJECT_ROOT / "data" / "runtime_cache" / "test_task6_model" / uuid4().hex
    settings = Settings(
        project_root=PROJECT_ROOT,
        data_dir=root,
        registry_db_path=root / "registry" / "knowledge.sqlite3",
        managed_sources_dir=root / "managed_sources",
        index_root=root / "llama_indices",
        model_cache_dir=root / "model_cache",
        runtime_cache_dir=root / "runtime_cache",
        model_name="BAAI/bge-m3",
        model_revision="pinned-test-revision",
        model_device="cpu",
        model_max_seq_length=512,
        embedding_batch_size=4,
        model_local_files_only=True,
        bm25_enabled=False,
    )
    captured: dict[str, object] = {}

    class CapturingEmbedding:
        def __init__(self, **kwargs) -> None:
            captured.update(kwargs)
            captured["HF_HUB_OFFLINE"] = __import__("os").environ.get(
                "HF_HUB_OFFLINE"
            )

    monkeypatch.setattr("app.service._create_huggingface_embedding", CapturingEmbedding)
    service = GuidelineService(settings)
    _ = service.index_store

    assert captured["local_files_only"] is True
    assert captured["revision"] == "pinned-test-revision"
    assert captured["HF_HUB_OFFLINE"] == "1"
    assert service._model_metadata["revision"] == captured["revision"]
