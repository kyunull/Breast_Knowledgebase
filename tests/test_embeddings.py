from __future__ import annotations

import json
import os
import threading
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Iterator
from unittest.mock import patch

import pytest
from llama_index.core.schema import TextNode

from app.embeddings import RemoteEmbedding, RemoteEmbeddingError
from app.constants import VersionStatus
from app.contracts import VersionRecord
from app.index_store import IndexSnapshotStore
from app.service import GuidelineService
from app.settings import Settings


PROJECT_ROOT = Path(__file__).resolve().parents[1]


@contextmanager
def embedding_server(
    responses: list[tuple[int, object]],
) -> Iterator[tuple[str, list[dict[str, object]]]]:
    requests: list[dict[str, object]] = []

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self) -> None:
            length = int(self.headers.get("Content-Length", "0"))
            requests.append(
                {
                    "path": self.path,
                    "authorization": self.headers.get("Authorization"),
                    "body": json.loads(self.rfile.read(length)),
                }
            )
            status, payload = responses.pop(0)
            body = (
                payload
                if isinstance(payload, bytes)
                else json.dumps(payload).encode("utf-8")
            )
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, format: str, *args: object) -> None:
            return

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        host, port = server.server_address
        yield f"http://{host}:{port}/v1", requests
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def _remote(base_url: str, *, api_key: str = "test-secret", **kwargs: object) -> RemoteEmbedding:
    options: dict[str, object] = {
        "dimension": 2,
        "embed_batch_size": 8,
        "timeout_seconds": 2,
        "max_retries": 0,
    }
    options.update(kwargs)
    return RemoteEmbedding(
        base_url=base_url,
        api_key=api_key,
        model_name="BAAI/bge-m3",
        **options,
    )


def test_remote_embedding_batches_inputs_and_sorts_response_indices() -> None:
    response = {
        "data": [
            {"index": 1, "embedding": [3, 4]},
            {"index": 0, "embedding": [1, 2]},
        ]
    }
    with embedding_server([(200, response)]) as (base_url, requests):
        model = _remote(base_url)

        vectors = model.get_text_embedding_batch(["first", "second"])

    assert vectors == [[1.0, 2.0], [3.0, 4.0]]
    assert requests == [
        {
            "path": "/v1/embeddings",
            "authorization": "Bearer test-secret",
            "body": {"input": ["first", "second"], "model": "BAAI/bge-m3"},
        }
    ]


def test_remote_embedding_retries_only_retryable_http_status() -> None:
    with embedding_server(
        [
            (429, {"error": "limited"}),
            (200, {"data": [{"index": 0, "embedding": [1, 2]}]}),
        ]
    ) as (base_url, requests):
        model = _remote(base_url, max_retries=1)

        assert model.get_query_embedding("query") == [1.0, 2.0]

    assert len(requests) == 2


@pytest.mark.parametrize(
    ("response", "message"),
    [
        ((200, b"not-json"), "valid JSON"),
        ((200, {"data": []}), "count"),
        (
            (200, {"data": [{"index": 0, "embedding": [1, "bad"]}]}),
            "numeric",
        ),
        (
            (200, {"data": [{"index": 0, "embedding": [1, 2, 3]}]}),
            "dimension",
        ),
    ],
)
def test_remote_embedding_rejects_malformed_responses(
    response: tuple[int, object], message: str
) -> None:
    with embedding_server([response]) as (base_url, _):
        with pytest.raises(RemoteEmbeddingError, match=message):
            _remote(base_url).get_query_embedding("query")


def test_remote_embedding_errors_and_payloads_never_expose_api_key() -> None:
    secret = "do-not-leak-this-key"
    with embedding_server([(401, {"error": secret})]) as (base_url, _):
        model = _remote(base_url, api_key=secret)

        with pytest.raises(RemoteEmbeddingError) as caught:
            model.get_query_embedding("query")

    assert secret not in str(caught.value)
    assert secret not in repr(model)
    assert secret not in json.dumps(model.to_payload())


def test_remote_embedding_requires_key_and_https_except_for_loopback() -> None:
    with pytest.raises(ValueError, match="API key"):
        _remote("https://embedding.example.com/v1", api_key="")
    with pytest.raises(ValueError, match="HTTPS"):
        _remote("http://embedding.example.com/v1")
    with pytest.raises(ValueError, match="base URL"):
        _remote("not-a-url")


def test_settings_select_remote_provider_and_service_does_not_load_huggingface(
    tmp_path: Path,
) -> None:
    root = (tmp_path / "project").resolve()
    root.mkdir()
    environment = {
        "KB_EMBEDDING_PROVIDER": "remote",
        "KB_EMBEDDING_BASE_URL": "http://127.0.0.1:8765/v1",
        "KB_EMBEDDING_API_KEY": "process-only-secret",
        "KB_EMBEDDING_MODEL": "BAAI/bge-m3",
        "KB_EMBEDDING_DIMENSION": "1024",
    }
    with patch.dict(os.environ, environment, clear=False):
        settings = Settings.from_env(root)

    with patch(
        "app.service._create_huggingface_embedding",
        side_effect=AssertionError("local model must not load in remote mode"),
    ):
        model = GuidelineService(settings)._get_embed_model()

    assert isinstance(model, RemoteEmbedding)
    assert settings.embedding_provider == "remote"


@pytest.mark.parametrize(
    "environment",
    [
        {"KB_EMBEDDING_PROVIDER": "unknown"},
        {
            "KB_EMBEDDING_PROVIDER": "remote",
            "KB_EMBEDDING_BASE_URL": "https://embedding.example.com/v1",
            "KB_EMBEDDING_MODEL": "BAAI/bge-m3",
        },
    ],
)
def test_settings_rejects_unknown_provider_or_remote_mode_without_key(
    environment: dict[str, str],
) -> None:
    clean = {name: value for name, value in os.environ.items() if not name.startswith("KB_")}
    with patch.dict(os.environ, {**clean, **environment}, clear=True):
        with pytest.raises(ValueError):
            Settings.from_env(PROJECT_ROOT)


def test_remote_embedding_builds_and_loads_a_compatible_snapshot(
    tmp_path: Path,
) -> None:
    with embedding_server(
        [
            (200, {"data": [{"index": 0, "embedding": [1, 0]}]}),
            (200, {"data": [{"index": 0, "embedding": [1, 0]}]}),
        ]
    ) as (base_url, _):
        model = _remote(base_url)
        store = IndexSnapshotStore(
            tmp_path / "indices",
            embed_model=model,
            model_metadata={
                "provider": "remote",
                "model_name": "BAAI/bge-m3",
                "dimension": 2,
                "normalize": True,
            },
        )
        version = VersionRecord(
            id="nccn-v1",
            guideline_id="nccn",
            version_label="6.2026",
            status=VersionStatus.DRAFT,
            snapshot_path=None,
            snapshot_manifest_sha256=None,
            published_at=None,
            created_at="2026-08-14T00:00:00",
            approved_at=None,
        )
        snapshot = store.build(
            version,
            [TextNode(id_="nccn:nccn-v1:chunk:0", text="HER2 evidence")],
        )
        loaded = store.load(snapshot)
        results = loaded.as_retriever(similarity_top_k=1).retrieve("HER2")

    assert results[0].node.node_id == "nccn:nccn-v1:chunk:0"
