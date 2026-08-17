from __future__ import annotations

import json
from pathlib import Path

import pytest

from scripts.tencent_table_ocr import (
    TencentCredentials,
    TencentTableOcrClient,
    build_tc3_headers,
    resolve_credentials,
    write_response_atomic,
)


def test_resolve_credentials_process_wins_and_repr_is_secret_safe() -> None:
    credentials = resolve_credentials(
        {"TENCENTCLOUD_SECRET_ID": "process-id", "TENCENTCLOUD_SECRET_KEY": "process-key"},
        user_environment=lambda name: {"TENCENTCLOUD_SECRET_ID": "user-id", "TENCENTCLOUD_SECRET_KEY": "user-key"}[name],
    )
    assert credentials.secret_id == "process-id"
    assert credentials.secret_key == "process-key"
    assert "process-key" not in repr(credentials)
    assert "process-id" not in repr(credentials)


def test_resolve_credentials_falls_back_to_user_environment() -> None:
    credentials = resolve_credentials(
        {},
        user_environment=lambda name: {"TENCENTCLOUD_SECRET_ID": "user-id", "TENCENTCLOUD_SECRET_KEY": "user-key"}[name],
    )
    assert credentials.secret_id == "user-id"
    assert credentials.secret_key == "user-key"


def test_resolve_credentials_reports_only_missing_names() -> None:
    with pytest.raises(RuntimeError, match="TENCENTCLOUD_SECRET_ID") as error:
        resolve_credentials({}, user_environment=lambda _name: None)
    assert "user-id" not in str(error.value)
    assert "user-key" not in str(error.value)


def test_tc3_headers_are_deterministic_and_secret_key_is_not_exposed() -> None:
    credentials = TencentCredentials("AKIDEXAMPLE", "SecretKeyExample")
    headers = build_tc3_headers(
        credentials,
        {"ImageBase64": "YWJj", "UseNewModel": True},
        timestamp=1786896000,
    )
    assert headers["Host"] == "ocr.tencentcloudapi.com"
    assert headers["X-TC-Action"] == "RecognizeTableAccurateOCR"
    assert headers["X-TC-Version"] == "2018-11-19"
    assert headers["X-TC-Timestamp"] == "1786896000"
    assert "Credential=AKIDEXAMPLE/2026-08-16/ocr/tc3_request" in headers["Authorization"]
    assert "SecretKeyExample" not in repr(headers)


def test_client_unwraps_response_and_retries_transient_failures(tmp_path: Path) -> None:
    image = tmp_path / "page.png"
    image.write_bytes(b"abc")
    calls: list[tuple[bytes, dict[str, str]]] = []
    responses = [(503, b"temporary"), (200, json.dumps({"Response": {"RequestId": "req-1", "TableDetections": []}}).encode())]

    def transport(body: bytes, headers: dict[str, str]) -> tuple[int, bytes]:
        calls.append((body, headers))
        return responses.pop(0)

    client = TencentTableOcrClient(
        TencentCredentials("id", "key"),
        transport=transport,
        timestamp=lambda: 1786896000,
        sleep=lambda _seconds: None,
    )
    result = client.recognize_png(image)
    assert result["Response"]["RequestId"] == "req-1"
    sent = json.loads(calls[-1][0])
    assert sent["UseNewModel"] is True
    assert len(calls) == 2


def test_client_rejects_tencent_errors_without_secrets(tmp_path: Path) -> None:
    image = tmp_path / "page.png"
    image.write_bytes(b"abc")

    def transport(_body: bytes, _headers: dict[str, str]) -> tuple[int, bytes]:
        return 200, json.dumps({"Response": {"Error": {"Code": "InvalidParameter", "Message": "bad"}}}).encode()

    client = TencentTableOcrClient(TencentCredentials("id", "key"), transport=transport)
    with pytest.raises(RuntimeError, match="InvalidParameter") as error:
        client.recognize_png(image)
    assert "key" not in str(error.value)


def test_atomic_response_writer(tmp_path: Path) -> None:
    path = tmp_path / "nested" / "response.json"
    write_response_atomic(path, {"Response": {"RequestId": "abc"}})
    assert json.loads(path.read_text(encoding="utf-8"))["Response"]["RequestId"] == "abc"
