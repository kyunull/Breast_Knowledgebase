from __future__ import annotations

import base64
from dataclasses import dataclass, field
from datetime import datetime, timezone
import hashlib
import hmac
import json
import os
from pathlib import Path
import tempfile
import time
from typing import Callable, Mapping
from urllib import request as urllib_request
from urllib.error import HTTPError, URLError


_HOST = "ocr.tencentcloudapi.com"
_SERVICE = "ocr"
_ACTION = "RecognizeTableAccurateOCR"
_VERSION = "2018-11-19"


@dataclass(frozen=True, slots=True)
class TencentCredentials:
    secret_id: str = field(repr=False)
    secret_key: str = field(repr=False)


def resolve_credentials(
    environment: Mapping[str, str] | None = None,
    *,
    user_environment: Callable[[str], str | None] | None = None,
) -> TencentCredentials:
    process = environment if environment is not None else os.environ
    if user_environment is None:
        user_environment = _read_windows_user_environment
    missing: list[str] = []
    values: dict[str, str] = {}
    for name in ("TENCENTCLOUD_SECRET_ID", "TENCENTCLOUD_SECRET_KEY"):
        value = process.get(name)
        if not value:
            value = user_environment(name)
        if value:
            values[name] = value
        else:
            missing.append(name)
    if missing:
        raise RuntimeError("missing Tencent Cloud environment variable(s): " + ", ".join(missing))
    return TencentCredentials(values["TENCENTCLOUD_SECRET_ID"], values["TENCENTCLOUD_SECRET_KEY"])


def build_tc3_headers(
    credentials: TencentCredentials,
    payload: Mapping[str, object],
    *,
    timestamp: int | None = None,
) -> dict[str, str]:
    body = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    timestamp_value = int(time.time()) if timestamp is None else int(timestamp)
    date = datetime.fromtimestamp(timestamp_value, tz=timezone.utc).strftime("%Y-%m-%d")
    canonical_headers = f"content-type:application/json\nhost:{_HOST}\n"
    signed_headers = "content-type;host"
    hashed_payload = hashlib.sha256(body).hexdigest()
    canonical_request = "\n".join(("POST", "/", "", canonical_headers, signed_headers, hashed_payload))
    credential_scope = f"{date}/{_SERVICE}/tc3_request"
    string_to_sign = "\n".join(
        (
            "TC3-HMAC-SHA256",
            str(timestamp_value),
            credential_scope,
            hashlib.sha256(canonical_request.encode("utf-8")).hexdigest(),
        )
    )
    secret_date = hmac.new(
        ("TC3" + credentials.secret_key).encode("utf-8"), date.encode("utf-8"), hashlib.sha256
    ).digest()
    secret_service = hmac.new(secret_date, _SERVICE.encode("utf-8"), hashlib.sha256).digest()
    secret_signing = hmac.new(secret_service, b"tc3_request", hashlib.sha256).digest()
    signature = hmac.new(secret_signing, string_to_sign.encode("utf-8"), hashlib.sha256).hexdigest()
    authorization = (
        f"TC3-HMAC-SHA256 Credential={credentials.secret_id}/{credential_scope}, "
        f"SignedHeaders={signed_headers}, Signature={signature}"
    )
    return {
        "Authorization": authorization,
        "Content-Type": "application/json",
        "Host": _HOST,
        "X-TC-Action": _ACTION,
        "X-TC-Version": _VERSION,
        "X-TC-Timestamp": str(timestamp_value),
    }


Transport = Callable[[bytes, dict[str, str]], tuple[int, bytes]]


class TencentTableOcrClient:
    def __init__(
        self,
        credentials: TencentCredentials,
        *,
        transport: Transport | None = None,
        timestamp: Callable[[], int] | None = None,
        sleep: Callable[[float], None] = time.sleep,
        max_attempts: int = 3,
        timeout_seconds: float = 120.0,
    ) -> None:
        if max_attempts < 1:
            raise ValueError("max_attempts must be positive")
        self.credentials = credentials
        self.transport = transport or _https_transport(timeout_seconds)
        self.timestamp = timestamp or (lambda: int(time.time()))
        self.sleep = sleep
        self.max_attempts = max_attempts

    def recognize_png(self, png_path: Path) -> dict[str, object]:
        path = Path(png_path)
        if not path.is_file():
            raise FileNotFoundError(path)
        payload = {
            "ImageBase64": base64.b64encode(path.read_bytes()).decode("ascii"),
            "UseNewModel": True,
        }
        body = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
        last_error: Exception | None = None
        for attempt in range(self.max_attempts):
            headers = build_tc3_headers(self.credentials, payload, timestamp=self.timestamp())
            try:
                status, response_body = self.transport(body, headers)
                if status >= 500:
                    raise _TransientHttpError(f"Tencent OCR HTTP status {status}")
                if status >= 400:
                    raise RuntimeError(f"Tencent OCR HTTP status {status}")
                try:
                    response = json.loads(response_body.decode("utf-8"))
                except (UnicodeDecodeError, json.JSONDecodeError) as error:
                    raise RuntimeError("Tencent OCR returned invalid JSON") from error
                if not isinstance(response, dict):
                    raise RuntimeError("Tencent OCR response must be a JSON object")
                response_body_mapping = response.get("Response")
                if not isinstance(response_body_mapping, Mapping):
                    raise RuntimeError("Tencent OCR response is missing Response")
                error = response_body_mapping.get("Error")
                if isinstance(error, Mapping):
                    code = error.get("Code", "UnknownError")
                    message = error.get("Message", "request failed")
                    raise RuntimeError(f"Tencent OCR error {code}: {message}")
                return response
            except _TransientHttpError as error:
                last_error = error
            except (TimeoutError, URLError, OSError) as error:
                last_error = RuntimeError("Tencent OCR transport failed")
                last_error.__cause__ = error
            if attempt + 1 < self.max_attempts:
                self.sleep(2**attempt)
        raise RuntimeError("Tencent OCR request failed after retries") from last_error


class _TransientHttpError(RuntimeError):
    pass


def write_response_atomic(path: Path, payload: Mapping[str, object]) -> None:
    destination = Path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    content = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    with tempfile.NamedTemporaryFile(
        mode="w", encoding="utf-8", dir=destination.parent, prefix=f".{destination.name}.", suffix=".tmp", delete=False
    ) as handle:
        temporary = Path(handle.name)
        handle.write(content)
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(temporary, destination)


def _read_windows_user_environment(name: str) -> str | None:
    if os.name != "nt":
        return None
    try:
        import winreg

        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, "Environment") as key:
            value, _ = winreg.QueryValueEx(key, name)
    except (FileNotFoundError, OSError):
        return None
    return value if isinstance(value, str) else None


def _https_transport(timeout_seconds: float) -> Transport:
    def send(body: bytes, headers: dict[str, str]) -> tuple[int, bytes]:
        request = urllib_request.Request(
            "https://" + _HOST,
            data=body,
            headers=headers,
            method="POST",
        )
        try:
            with urllib_request.urlopen(request, timeout=timeout_seconds) as response:
                return int(response.status), response.read()
        except HTTPError as error:
            return int(error.code), error.read()

    return send
