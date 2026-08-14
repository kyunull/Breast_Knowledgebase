from __future__ import annotations

import http.client
import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, call, patch

from scripts import verify_wheelhouse


PROJECT_ROOT = Path(__file__).resolve().parents[1]


class JsonResponse(io.BytesIO):
    def __enter__(self) -> JsonResponse:
        return self

    def __exit__(self, exc_type, exc_value, traceback) -> None:
        self.close()


def json_response(payload: dict[str, object]) -> JsonResponse:
    return JsonResponse(json.dumps(payload).encode("utf-8"))


class FetchPyPIReleaseTests(unittest.TestCase):
    def test_rejects_malformed_json_after_successful_transport_read(self) -> None:
        malformed_json = JsonResponse(b'{"urls": [')

        with (
            patch.object(
                verify_wheelhouse.urllib.request,
                "urlopen",
                return_value=malformed_json,
            ) as urlopen,
            patch.object(verify_wheelhouse.urllib.request, "build_opener") as build_opener,
            patch("time.sleep") as sleep,
        ):
            with self.assertRaisesRegex(
                verify_wheelhouse.WheelhouseVerificationError,
                "Could not fetch PyPI metadata",
            ):
                verify_wheelhouse.fetch_pypi_release("example", "1.0")

        self.assertEqual(1, urlopen.call_count)
        build_opener.assert_not_called()
        sleep.assert_not_called()

    def test_default_proxy_success_never_uses_direct_fallback(self) -> None:
        payload = {"urls": [{"filename": "example-1.0-py3-none-any.whl"}]}

        with (
            patch.object(
                verify_wheelhouse.urllib.request,
                "urlopen",
                return_value=json_response(payload),
            ) as urlopen,
            patch.object(verify_wheelhouse.urllib.request, "build_opener") as build_opener,
        ):
            result = verify_wheelhouse.fetch_pypi_release("example", "1.0")

        self.assertEqual(payload["urls"], result)
        self.assertEqual(1, urlopen.call_count)
        build_opener.assert_not_called()

    def test_retries_two_incomplete_reads_then_default_proxy_succeeds(self) -> None:
        payload = {"urls": [{"filename": "example-1.0-py3-none-any.whl"}]}
        incomplete = http.client.IncompleteRead(b"", 10)

        with (
            patch.object(
                verify_wheelhouse.urllib.request,
                "urlopen",
                side_effect=[incomplete, incomplete, json_response(payload)],
            ) as urlopen,
            patch.object(verify_wheelhouse.urllib.request, "build_opener") as build_opener,
            patch("time.sleep") as sleep,
        ):
            result = verify_wheelhouse.fetch_pypi_release("example", "1.0")

        self.assertEqual(payload["urls"], result)
        self.assertEqual(3, urlopen.call_count)
        self.assertEqual(
            [
                call("https://pypi.org/pypi/example/1.0/json", timeout=20.0),
                call("https://pypi.org/pypi/example/1.0/json", timeout=20.0),
                call("https://pypi.org/pypi/example/1.0/json", timeout=20.0),
            ],
            urlopen.call_args_list,
        )
        self.assertEqual([call(0.25), call(0.5)], sleep.call_args_list)
        build_opener.assert_not_called()

    def test_uses_direct_official_fallback_after_three_proxy_incomplete_reads(self) -> None:
        payload = {"urls": [{"filename": "example-1.0-py3-none-any.whl"}]}
        incomplete = http.client.IncompleteRead(b"", 10)
        direct_opener = Mock()
        direct_opener.open.return_value = json_response(payload)

        with (
            patch.object(
                verify_wheelhouse.urllib.request,
                "urlopen",
                side_effect=[incomplete, incomplete, incomplete],
            ) as urlopen,
            patch.object(
                verify_wheelhouse.urllib.request,
                "build_opener",
                return_value=direct_opener,
            ) as build_opener,
            patch("time.sleep") as sleep,
        ):
            result = verify_wheelhouse.fetch_pypi_release("example", "1.0")

        self.assertEqual(payload["urls"], result)
        self.assertEqual(3, urlopen.call_count)
        build_opener.assert_called_once()
        self.assertEqual({}, build_opener.call_args.args[0].proxies)
        direct_opener.open.assert_called_once_with(
            "https://pypi.org/pypi/example/1.0/json", timeout=20.0
        )
        self.assertEqual([call(0.25), call(0.5)], sleep.call_args_list)

    def test_stops_after_three_proxy_and_three_direct_incomplete_reads(self) -> None:
        incomplete = http.client.IncompleteRead(b"", 10)
        direct_opener = Mock()
        direct_opener.open.side_effect = [incomplete, incomplete, incomplete]

        with (
            patch.object(
                verify_wheelhouse.urllib.request,
                "urlopen",
                side_effect=[incomplete, incomplete, incomplete],
            ) as urlopen,
            patch.object(
                verify_wheelhouse.urllib.request,
                "build_opener",
                return_value=direct_opener,
            ) as build_opener,
            patch("time.sleep") as sleep,
        ):
            with self.assertRaisesRegex(
                verify_wheelhouse.WheelhouseVerificationError,
                "Could not fetch PyPI metadata",
            ):
                verify_wheelhouse.fetch_pypi_release("example", "1.0")

        self.assertEqual(3, urlopen.call_count)
        build_opener.assert_called_once()
        self.assertEqual(3, direct_opener.open.call_count)
        self.assertEqual(
            [call(0.25), call(0.5), call(0.25), call(0.5)],
            sleep.call_args_list,
        )

class VerifyWheelTests(unittest.TestCase):
    def test_sha256_mismatch_still_fails_after_metadata_is_accepted(self) -> None:
        with tempfile.TemporaryDirectory(dir=PROJECT_ROOT) as temporary_root:
            wheel = Path(temporary_root) / "example-1.0-py3-none-any.whl"
            wheel.write_bytes(b"local wheel content")

            with patch.object(
                verify_wheelhouse,
                "fetch_pypi_release",
                return_value=[
                    {
                        "filename": wheel.name,
                        "digests": {"sha256": "0" * 64},
                    }
                ],
            ):
                with self.assertRaisesRegex(
                    verify_wheelhouse.WheelhouseVerificationError,
                    "SHA-256 mismatch",
                ):
                    verify_wheelhouse.verify_wheel(wheel)


if __name__ == "__main__":
    unittest.main()
