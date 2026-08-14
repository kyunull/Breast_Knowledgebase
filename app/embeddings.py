from __future__ import annotations

import asyncio
import ipaddress
import json
import math
from typing import Any
from urllib import error, parse, request

from llama_index.core.base.embeddings.base import BaseEmbedding
from pydantic import Field, PrivateAttr


class RemoteEmbeddingError(RuntimeError):
    """A remote embedding request or response violated the configured contract."""


class RemoteEmbedding(BaseEmbedding):
    base_url: str
    dimension: int = Field(gt=0)
    timeout_seconds: float = Field(gt=0)
    max_retries: int = Field(ge=0)

    _api_key: str = PrivateAttr()
    _endpoint: str = PrivateAttr()

    def __init__(self, *, api_key: str, **data: Any) -> None:
        if not api_key.strip():
            raise ValueError("remote embedding API key must not be empty")
        endpoint = _embedding_endpoint(str(data.get("base_url", "")))
        data["base_url"] = endpoint.removesuffix("/embeddings")
        super().__init__(**data)
        self._api_key = api_key
        self._endpoint = endpoint

    def to_payload(self) -> dict[str, Any]:
        return {
            **super().to_payload(),
            "provider": "remote",
            "base_url": self.base_url,
            "dimension": self.dimension,
        }

    def _get_query_embedding(self, query: str) -> list[float]:
        return self._embed([query])[0]

    async def _aget_query_embedding(self, query: str) -> list[float]:
        return (await asyncio.to_thread(self._embed, [query]))[0]

    def _get_text_embedding(self, text: str) -> list[float]:
        return self._embed([text])[0]

    def _get_text_embeddings(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []
        return self._embed(texts)

    async def _aget_text_embeddings(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []
        return await asyncio.to_thread(self._embed, texts)

    def _embed(self, inputs: list[str]) -> list[list[float]]:
        payload = json.dumps(
            {"input": inputs, "model": self.model_name},
            ensure_ascii=False,
            separators=(",", ":"),
        ).encode("utf-8")
        response_bytes = self._post(payload)
        try:
            response_payload = json.loads(response_bytes)
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise RemoteEmbeddingError(
                "remote embedding response is not valid JSON"
            ) from exc
        return self._parse_vectors(response_payload, expected_count=len(inputs))

    def _post(self, payload: bytes) -> bytes:
        for attempt in range(self.max_retries + 1):
            http_request = request.Request(
                self._endpoint,
                data=payload,
                headers={
                    "Accept": "application/json",
                    "Authorization": f"Bearer {self._api_key}",
                    "Content-Type": "application/json",
                },
                method="POST",
            )
            try:
                with request.urlopen(
                    http_request, timeout=self.timeout_seconds
                ) as response:
                    return response.read()
            except error.HTTPError as exc:
                status = exc.code
                exc.close()
                if _is_retryable_status(status) and attempt < self.max_retries:
                    continue
                raise RemoteEmbeddingError(
                    f"remote embedding request failed with HTTP {status}"
                ) from exc
            except (error.URLError, TimeoutError, OSError) as exc:
                if attempt < self.max_retries:
                    continue
                raise RemoteEmbeddingError("remote embedding request failed") from exc
        raise RemoteEmbeddingError("remote embedding request failed")

    def _parse_vectors(
        self, payload: object, *, expected_count: int
    ) -> list[list[float]]:
        if not isinstance(payload, dict) or not isinstance(payload.get("data"), list):
            raise RemoteEmbeddingError(
                "remote embedding response data must be an array"
            )
        rows = payload["data"]
        if len(rows) != expected_count:
            raise RemoteEmbeddingError(
                "remote embedding response count does not match input count"
            )

        ordered: list[list[float] | None] = [None] * expected_count
        for row in rows:
            if not isinstance(row, dict):
                raise RemoteEmbeddingError(
                    "remote embedding response entries must be objects"
                )
            index = row.get("index")
            vector = row.get("embedding")
            if (
                not isinstance(index, int)
                or isinstance(index, bool)
                or not 0 <= index < expected_count
                or ordered[index] is not None
            ):
                raise RemoteEmbeddingError(
                    "remote embedding response contains invalid indices"
                )
            if not isinstance(vector, list) or any(
                isinstance(value, bool)
                or not isinstance(value, (int, float))
                or not math.isfinite(float(value))
                for value in vector
            ):
                raise RemoteEmbeddingError(
                    "remote embedding vectors must contain only numeric values"
                )
            if len(vector) != self.dimension:
                raise RemoteEmbeddingError(
                    "remote embedding vector dimension does not match configuration"
                )
            ordered[index] = [float(value) for value in vector]
        return [vector for vector in ordered if vector is not None]


def _embedding_endpoint(base_url: str) -> str:
    value = base_url.strip().rstrip("/")
    parsed = parse.urlsplit(value)
    if (
        parsed.scheme not in {"http", "https"}
        or not parsed.hostname
        or parsed.username is not None
        or parsed.password is not None
        or parsed.query
        or parsed.fragment
    ):
        raise ValueError("remote embedding base URL is invalid")
    if parsed.scheme == "http" and not _is_loopback_host(parsed.hostname):
        raise ValueError("remote embedding base URL must use HTTPS except for loopback")
    return f"{value}/embeddings"


def _is_loopback_host(host: str) -> bool:
    if host.casefold() == "localhost":
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


def _is_retryable_status(status: int) -> bool:
    return status in {408, 429} or 500 <= status <= 599
