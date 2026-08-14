from __future__ import annotations

import argparse
import hashlib
import http.client
import json
import re
import sys
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable


class WheelhouseVerificationError(RuntimeError):
    """Raised when a local wheel cannot be verified against PyPI metadata."""


@dataclass(frozen=True, slots=True)
class WheelIdentity:
    distribution: str
    version: str
    filename: str


def parse_wheel_identity(path: Path) -> WheelIdentity:
    match = re.fullmatch(r"(?P<name>.+)-(?P<version>[^-]+)-[^-]+-[^-]+-[^-]+\.whl", path.name)
    if match is None:
        raise WheelhouseVerificationError(f"Invalid wheel filename: {path.name}")
    return WheelIdentity(
        distribution=match.group("name").replace("_", "-").lower(),
        version=match.group("version"),
        filename=path.name,
    )


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _fetch_json_with_incomplete_read_retries(
    open_request: Callable[..., Any],
    url: str,
    timeout: float,
) -> dict[str, Any]:
    for attempt in range(3):
        try:
            with open_request(url, timeout=timeout) as response:
                return json.load(response)
        except http.client.IncompleteRead:
            if attempt == 2:
                raise
            time.sleep((0.25, 0.5)[attempt])


def fetch_pypi_release(distribution: str, version: str, timeout: float = 20.0) -> list[dict[str, Any]]:
    url = f"https://pypi.org/pypi/{distribution}/{version}/json"
    try:
        payload = _fetch_json_with_incomplete_read_retries(
            urllib.request.urlopen, url, timeout
        )
    except http.client.IncompleteRead:
        direct_opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        try:
            payload = _fetch_json_with_incomplete_read_retries(
                direct_opener.open, url, timeout
            )
        except http.client.IncompleteRead as error:
            raise WheelhouseVerificationError(
                f"Could not fetch PyPI metadata for {distribution}=={version}: {error}"
            ) from error
    except (
        urllib.error.URLError,
        urllib.error.HTTPError,
        http.client.HTTPException,
        json.JSONDecodeError,
    ) as error:
        raise WheelhouseVerificationError(
            f"Could not fetch PyPI metadata for {distribution}=={version}: {error}"
        ) from error

    urls = payload.get("urls")
    if not isinstance(urls, list):
        raise WheelhouseVerificationError(f"PyPI metadata is missing urls for {distribution}=={version}")
    return urls


def verify_wheel(path: Path) -> None:
    identity = parse_wheel_identity(path)
    local_hash = sha256_file(path)
    files = fetch_pypi_release(identity.distribution, identity.version)
    matching_file = next((item for item in files if item.get("filename") == identity.filename), None)
    if matching_file is None:
        raise WheelhouseVerificationError(
            f"PyPI has no matching file for {identity.distribution}=={identity.version}: {identity.filename}"
        )
    expected_hash = matching_file.get("digests", {}).get("sha256")
    if not isinstance(expected_hash, str) or local_hash != expected_hash:
        raise WheelhouseVerificationError(
            f"SHA-256 mismatch for {identity.filename}: expected {expected_hash}, got {local_hash}"
        )


def verify_wheelhouse(wheelhouse: Path) -> int:
    wheels = sorted(wheelhouse.glob("*.whl"))
    if not wheels:
        raise WheelhouseVerificationError(f"No wheels found in {wheelhouse}")
    for wheel in wheels:
        verify_wheel(wheel)
        print(f"verified {wheel.name}")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Verify local wheels against official PyPI SHA-256 metadata.")
    parser.add_argument("wheelhouse", type=Path, help="Directory containing downloaded wheel files")
    arguments = parser.parse_args(argv)
    try:
        return verify_wheelhouse(arguments.wheelhouse.resolve())
    except WheelhouseVerificationError as error:
        print(f"verification failed: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
