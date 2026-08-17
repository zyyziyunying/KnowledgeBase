#!/usr/bin/env python3
"""Focused regression tests for the evidence verifier trust boundaries."""

from __future__ import annotations

import io
import json
import socket
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import verify_evidence as verifier


REPO_ROOT = Path(__file__).resolve().parents[1]
MANIFEST_PATH = REPO_ROOT / "evidence/android/framework/boot/manifest.json"
SCHEMA_PATH = REPO_ROOT / "evidence/schema/evidence-manifest.schema.json"


class FakeResponse(io.BytesIO):
    def __init__(self, payload: bytes, headers: dict[str, str] | None = None) -> None:
        super().__init__(payload)
        self.headers = headers or {}

    def __enter__(self) -> FakeResponse:
        return self

    def __exit__(self, *args: object) -> None:
        self.close()


class FakeOpener:
    def __init__(self, response: FakeResponse) -> None:
        self.response = response

    def open(self, request: object, timeout: int) -> FakeResponse:
        return self.response


class EvidenceSchemaTests(unittest.TestCase):
    def test_validate_manifest_executes_canonical_schema(self) -> None:
        manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
        manifest["topic_id"] = 7
        manifest["unexpected_root_field"] = True
        manifest["claims"][0]["id"] = "INVALID ID"
        manifest["claims"][0]["source_ids"] *= 2
        manifest["sources"][0]["title"] = ""

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            manifest_path = root / "evidence/android/framework/boot/manifest.json"
            schema_path = root / "evidence/schema/evidence-manifest.schema.json"
            topic_path = root / "knowledge/android/framework/Android-Framework-高频核心讲义.md"
            manifest_path.parent.mkdir(parents=True)
            schema_path.parent.mkdir(parents=True)
            topic_path.parent.mkdir(parents=True)
            schema_path.write_text(SCHEMA_PATH.read_text(encoding="utf-8"), encoding="utf-8")
            topic_path.write_text("test", encoding="utf-8")
            manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

            _, errors = verifier.validate_manifest(
                manifest_path,
                repo_root=root,
                canonical_schema_path=schema_path,
            )

        joined = "\n".join(errors)
        self.assertIn("expected string", joined)
        self.assertIn("unexpected_root_field", joined)
        self.assertIn("does not match", joined)
        self.assertIn("items must be unique", joined)
        self.assertIn("string is shorter", joined)


class EvidenceFetchTests(unittest.TestCase):
    def test_rejects_non_https_url_before_opening(self) -> None:
        with self.assertRaisesRegex(ValueError, "must use HTTPS"):
            verifier.fetch("file:///etc/hosts")

    @mock.patch.object(verifier.socket, "getaddrinfo")
    def test_rejects_private_resolved_address(self, getaddrinfo: mock.Mock) -> None:
        getaddrinfo.return_value = [
            (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("127.0.0.1", 443))
        ]
        with self.assertRaisesRegex(ValueError, "non-public address"):
            verifier.validate_remote_url("https://example.test/evidence")

    @mock.patch.object(verifier.socket, "getaddrinfo")
    def test_allows_proxy_fake_ip_for_domain_name(self, getaddrinfo: mock.Mock) -> None:
        getaddrinfo.return_value = [
            (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("198.18.0.10", 443))
        ]
        verifier.validate_remote_url("https://android.googlesource.com/evidence")

    def test_rejects_proxy_fake_ip_as_literal_url(self) -> None:
        with self.assertRaisesRegex(ValueError, "non-public address"):
            verifier.validate_remote_url("https://198.18.0.10/evidence")

    def test_revalidates_redirect_target(self) -> None:
        handler = verifier.SafeRedirectHandler()
        request = verifier.urllib.request.Request("https://example.com/evidence")
        with self.assertRaisesRegex(ValueError, "must use HTTPS"):
            handler.redirect_request(
                request,
                None,
                302,
                "Found",
                {},
                "file:///etc/hosts",
            )

    @mock.patch.object(verifier, "validate_remote_url")
    def test_caps_response_without_content_length(self, validate_url: mock.Mock) -> None:
        opener = FakeOpener(FakeResponse(b"12345"))
        with self.assertRaisesRegex(ValueError, "exceeds 4 bytes"):
            verifier.fetch(
                "https://example.test/evidence",
                max_bytes=4,
                opener=opener,
            )
        validate_url.assert_called_once()

    @mock.patch.object(verifier, "validate_remote_url")
    def test_rejects_oversized_declared_response(self, validate_url: mock.Mock) -> None:
        response = FakeResponse(b"", {"Content-Length": "5"})
        with self.assertRaisesRegex(ValueError, "exceeds 4 bytes"):
            verifier.fetch(
                "https://example.test/evidence",
                max_bytes=4,
                opener=FakeOpener(response),
            )
        validate_url.assert_called_once()


if __name__ == "__main__":
    unittest.main()
