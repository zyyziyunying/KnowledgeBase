#!/usr/bin/env python3
"""Validate KnowledgeBase evidence manifests and optionally verify remote sources."""

from __future__ import annotations

import argparse
import base64
import datetime as dt
import hashlib
import ipaddress
import json
import re
import socket
import sys
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[1]
EVIDENCE_ROOT = REPO_ROOT / "evidence"
CANONICAL_SCHEMA_PATH = EVIDENCE_ROOT / "schema/evidence-manifest.schema.json"
HEX_40 = re.compile(r"^[0-9a-f]{40}$")
HEX_64 = re.compile(r"^[0-9a-f]{64}$")
SOURCE_CLASSES = {"official_source", "official_document", "authoritative_blog"}
USER_AGENT = "KnowledgeBaseEvidenceVerifier/1.0"
MAX_RESPONSE_BYTES = 16 * 1024 * 1024
PROXY_FAKE_IP_NETWORK = ipaddress.ip_network("198.18.0.0/15")
LOCAL_HOST_SUFFIXES = (".localhost", ".local", ".internal", ".home.arpa")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "manifests",
        nargs="*",
        type=Path,
        help="Manifest paths relative to the repository root; defaults to every evidence manifest.",
    )
    parser.add_argument(
        "--online",
        action="store_true",
        help="Download pinned sources, verify SHA-256/assertions, and check document URLs.",
    )
    return parser.parse_args()


def require_fields(value: dict[str, Any], fields: tuple[str, ...], label: str) -> list[str]:
    return [f"{label}: missing required field '{field}'" for field in fields if field not in value]


def validate_date(value: Any, label: str) -> list[str]:
    if not isinstance(value, str):
        return [f"{label}: expected YYYY-MM-DD string"]
    try:
        dt.date.fromisoformat(value)
    except ValueError:
        return [f"{label}: invalid date '{value}'"]
    return []


def display_path(path: Path, root: Path = REPO_ROOT) -> str:
    try:
        return str(path.resolve().relative_to(root.resolve()))
    except ValueError:
        return str(path)


def resolve_schema_ref(schema_root: dict[str, Any], reference: str) -> dict[str, Any]:
    if not reference.startswith("#/"):
        raise ValueError(f"unsupported schema reference {reference!r}")
    value: Any = schema_root
    for raw_part in reference[2:].split("/"):
        part = raw_part.replace("~1", "/").replace("~0", "~")
        if not isinstance(value, dict) or part not in value:
            raise ValueError(f"unresolved schema reference {reference!r}")
        value = value[part]
    if not isinstance(value, dict):
        raise ValueError(f"schema reference {reference!r} does not resolve to an object")
    return value


def matches_type(value: Any, expected: str) -> bool:
    if expected == "object":
        return isinstance(value, dict)
    if expected == "array":
        return isinstance(value, list)
    if expected == "string":
        return isinstance(value, str)
    if expected == "integer":
        return isinstance(value, int) and not isinstance(value, bool)
    if expected == "number":
        return isinstance(value, (int, float)) and not isinstance(value, bool)
    if expected == "boolean":
        return isinstance(value, bool)
    if expected == "null":
        return value is None
    raise ValueError(f"unsupported schema type {expected!r}")


def validate_uri(value: str, label: str) -> list[str]:
    try:
        parsed = urllib.parse.urlsplit(value)
        parsed.port
    except ValueError as exc:
        return [f"{label}: invalid URI: {exc}"]
    if not parsed.scheme:
        return [f"{label}: invalid URI {value!r}"]
    return []


def validate_schema_instance(
    value: Any,
    schema: dict[str, Any],
    schema_root: dict[str, Any],
    label: str,
) -> list[str]:
    """Validate the JSON Schema subset used by the repository-owned manifest schema."""
    errors: list[str] = []

    if "$ref" in schema:
        referenced = resolve_schema_ref(schema_root, schema["$ref"])
        errors += validate_schema_instance(value, referenced, schema_root, label)

    for child in schema.get("allOf", []):
        errors += validate_schema_instance(value, child, schema_root, label)

    if "oneOf" in schema:
        branch_errors = [
            validate_schema_instance(value, child, schema_root, label)
            for child in schema["oneOf"]
        ]
        matching_branches = sum(not candidate for candidate in branch_errors)
        if matching_branches != 1:
            errors.append(
                f"{label}: expected exactly one schema variant, matched {matching_branches}"
            )
            if matching_branches == 0 and branch_errors:
                errors += min(branch_errors, key=len)

    expected_type = schema.get("type")
    if expected_type is not None and not matches_type(value, expected_type):
        return errors + [f"{label}: expected {expected_type}"]

    if "const" in schema and value != schema["const"]:
        errors.append(f"{label}: expected constant {schema['const']!r}")
    if "enum" in schema and value not in schema["enum"]:
        errors.append(f"{label}: value {value!r} is not in the allowed set")

    if isinstance(value, dict):
        properties = schema.get("properties", {})
        for field in schema.get("required", []):
            if field not in value:
                errors.append(f"{label}: missing required field '{field}'")
        if schema.get("additionalProperties") is False:
            for field in value.keys() - properties.keys():
                errors.append(f"{label}: unexpected field '{field}'")
        for field, child_schema in properties.items():
            if field in value:
                errors += validate_schema_instance(
                    value[field], child_schema, schema_root, f"{label}.{field}"
                )

    if isinstance(value, list):
        if len(value) < schema.get("minItems", 0):
            errors.append(f"{label}: expected at least {schema['minItems']} items")
        if schema.get("uniqueItems"):
            normalized = [
                json.dumps(item, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
                for item in value
            ]
            if len(normalized) != len(set(normalized)):
                errors.append(f"{label}: items must be unique")
        child_schema = schema.get("items")
        if child_schema:
            for index, item in enumerate(value):
                errors += validate_schema_instance(
                    item, child_schema, schema_root, f"{label}[{index}]"
                )

    if isinstance(value, str):
        if len(value) < schema.get("minLength", 0):
            errors.append(f"{label}: string is shorter than {schema['minLength']}")
        pattern = schema.get("pattern")
        if pattern and re.search(pattern, value) is None:
            errors.append(f"{label}: value {value!r} does not match {pattern!r}")
        if schema.get("format") == "date":
            errors += validate_date(value, label)
        elif schema.get("format") == "uri":
            errors += validate_uri(value, label)

    return errors


def validate_manifest(
    path: Path,
    repo_root: Path = REPO_ROOT,
    canonical_schema_path: Path = CANONICAL_SCHEMA_PATH,
) -> tuple[dict[str, Any] | None, list[str]]:
    errors: list[str] = []
    path = path.resolve()
    try:
        path.relative_to(repo_root.resolve())
    except ValueError:
        return None, [f"{path}: manifest must stay inside the repository"]

    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return None, [f"{path}: cannot read JSON: {exc}"]

    label = display_path(path, repo_root)
    try:
        schema = json.loads(canonical_schema_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return data, [f"{label}: cannot read canonical schema: {exc}"]
    if not isinstance(schema, dict):
        return data, [f"{label}: canonical schema must be a JSON object"]

    try:
        errors += validate_schema_instance(data, schema, schema, label)
    except (TypeError, ValueError) as exc:
        errors.append(f"{label}: canonical schema cannot be evaluated: {exc}")
    if errors or not isinstance(data, dict):
        return data, errors

    schema_ref = data.get("$schema")
    if schema_ref:
        referenced_schema_path = (path.parent / schema_ref).resolve()
        if referenced_schema_path != canonical_schema_path.resolve():
            errors.append(f"{label}: $schema must reference the repository canonical schema")

    topic_path = (path.parent / data["topic_document"]).resolve()
    try:
        topic_path.relative_to(repo_root.resolve())
    except ValueError:
        errors.append(f"{label}: topic_document must stay inside the repository")
    if not errors and not topic_path.is_file():
        errors.append(f"{label}: topic_document does not resolve: {data['topic_document']}")

    claims = data["claims"]
    sources = data["sources"]
    if not isinstance(claims, list) or not claims:
        errors.append(f"{label}: claims must be a non-empty array")
        claims = []
    if not isinstance(sources, list) or not sources:
        errors.append(f"{label}: sources must be a non-empty array")
        sources = []

    source_ids: set[str] = set()
    for index, source in enumerate(sources):
        source_label = f"{label}.sources[{index}]"
        if not isinstance(source, dict):
            errors.append(f"{source_label}: expected object")
            continue
        errors += require_fields(
            source,
            ("id", "source_class", "title", "publisher", "retrieved_at", "license"),
            source_label,
        )
        source_id = source.get("id")
        if not isinstance(source_id, str) or not source_id:
            errors.append(f"{source_label}: id must be a non-empty string")
        elif source_id in source_ids:
            errors.append(f"{source_label}: duplicate source id '{source_id}'")
        else:
            source_ids.add(source_id)
        errors += validate_date(source.get("retrieved_at"), f"{source_label}.retrieved_at")

        source_class = source.get("source_class")
        if source_class not in SOURCE_CLASSES:
            errors.append(f"{source_label}: unsupported source_class {source_class!r}")
            continue
        if source_class == "official_source":
            errors += require_fields(
                source,
                (
                    "repository_url", "revision", "path", "web_url", "raw_url",
                    "raw_encoding", "sha256", "assertions",
                ),
                source_label,
            )
            if not HEX_40.fullmatch(str(source.get("revision", ""))):
                errors.append(f"{source_label}: revision must be a 40-character lowercase SHA")
            if not HEX_64.fullmatch(str(source.get("sha256", ""))):
                errors.append(f"{source_label}: sha256 must be a 64-character lowercase digest")
            assertions = source.get("assertions")
            if not isinstance(assertions, list) or not assertions or not all(
                isinstance(item, str) and item for item in assertions
            ):
                errors.append(f"{source_label}: assertions must be a non-empty string array")
        elif source_class == "official_document":
            errors += require_fields(source, ("url", "last_updated", "applies_to"), source_label)
            errors += validate_date(source.get("last_updated"), f"{source_label}.last_updated")
        else:
            errors += require_fields(
                source,
                ("url", "author", "published_at", "applies_to", "credibility_note"),
                source_label,
            )
            errors += validate_date(source.get("published_at"), f"{source_label}.published_at")

    claim_ids: set[str] = set()
    for index, claim in enumerate(claims):
        claim_label = f"{label}.claims[{index}]"
        if not isinstance(claim, dict):
            errors.append(f"{claim_label}: expected object")
            continue
        errors += require_fields(claim, ("id", "section", "statement", "source_ids"), claim_label)
        claim_id = claim.get("id")
        if not isinstance(claim_id, str) or not claim_id:
            errors.append(f"{claim_label}: id must be a non-empty string")
        elif claim_id in claim_ids:
            errors.append(f"{claim_label}: duplicate claim id '{claim_id}'")
        else:
            claim_ids.add(claim_id)
        refs = claim.get("source_ids")
        if not isinstance(refs, list) or not refs:
            errors.append(f"{claim_label}: source_ids must be a non-empty array")
        else:
            for source_id in refs:
                if source_id not in source_ids:
                    errors.append(f"{claim_label}: unknown source id '{source_id}'")

    return data, errors


def validate_remote_url(url: str) -> None:
    try:
        parsed = urllib.parse.urlsplit(url)
        port = parsed.port or 443
    except ValueError as exc:
        raise ValueError(f"invalid evidence URL: {exc}") from exc
    if parsed.scheme.lower() != "https":
        raise ValueError("evidence URL must use HTTPS")
    if not parsed.hostname:
        raise ValueError("evidence URL must include a hostname")
    if parsed.username is not None or parsed.password is not None:
        raise ValueError("evidence URL must not include credentials")

    hostname = parsed.hostname.lower().rstrip(".")
    if hostname == "localhost" or hostname.endswith(LOCAL_HOST_SUFFIXES):
        raise ValueError(f"evidence host {hostname!r} is local")
    try:
        literal_address = ipaddress.ip_address(hostname)
    except ValueError:
        literal_address = None
    if literal_address is not None and not literal_address.is_global:
        raise ValueError(f"evidence URL uses non-public address {literal_address}")

    try:
        addresses = socket.getaddrinfo(
            hostname,
            port,
            type=socket.SOCK_STREAM,
        )
    except socket.gaierror as exc:
        raise ValueError(f"cannot resolve evidence host {hostname!r}: {exc}") from exc
    if not addresses:
        raise ValueError(f"evidence host {hostname!r} resolved to no addresses")
    for address in addresses:
        host = address[4][0].split("%", 1)[0]
        resolved_ip = ipaddress.ip_address(host)
        proxy_fake_ip = literal_address is None and resolved_ip in PROXY_FAKE_IP_NETWORK
        if not resolved_ip.is_global and not proxy_fake_ip:
            raise ValueError(
                f"evidence host {hostname!r} resolves to non-public address {resolved_ip}"
            )


class SafeRedirectHandler(urllib.request.HTTPRedirectHandler):
    def redirect_request(
        self,
        request: urllib.request.Request,
        file_pointer: Any,
        code: int,
        message: str,
        headers: Any,
        new_url: str,
    ) -> urllib.request.Request | None:
        validate_remote_url(new_url)
        return super().redirect_request(
            request,
            file_pointer,
            code,
            message,
            headers,
            new_url,
        )


def fetch(
    url: str,
    *,
    max_bytes: int = MAX_RESPONSE_BYTES,
    opener: Any | None = None,
) -> bytes:
    validate_remote_url(url)
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    safe_opener = opener or urllib.request.build_opener(SafeRedirectHandler())
    with safe_opener.open(request, timeout=30) as response:
        content_length = response.headers.get("Content-Length")
        if content_length is not None and int(content_length) > max_bytes:
            raise ValueError(f"evidence response exceeds {max_bytes} bytes")
        payload = response.read(max_bytes + 1)
        if len(payload) > max_bytes:
            raise ValueError(f"evidence response exceeds {max_bytes} bytes")
        return payload


def verify_online(path: Path, data: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    label = str(path.relative_to(REPO_ROOT))
    for source in data["sources"]:
        source_label = f"{label}:{source['id']}"
        try:
            if source["source_class"] == "official_source":
                payload = fetch(source["raw_url"])
                if source["raw_encoding"] == "gitiles-base64":
                    payload = base64.b64decode(payload, validate=False)
                digest = hashlib.sha256(payload).hexdigest()
                if digest != source["sha256"]:
                    errors.append(
                        f"{source_label}: SHA-256 mismatch; expected {source['sha256']}, got {digest}"
                    )
                text = payload.decode("utf-8", errors="replace")
                for assertion in source["assertions"]:
                    if assertion not in text:
                        errors.append(f"{source_label}: missing assertion {assertion!r}")
            else:
                fetch(source["url"])
        except (OSError, ValueError, urllib.error.URLError) as exc:
            errors.append(f"{source_label}: online verification failed: {exc}")
    return errors


def resolve_manifest_paths(arguments: list[Path]) -> list[Path]:
    if not arguments:
        return sorted(EVIDENCE_ROOT.glob("**/manifest.json"))
    return [path if path.is_absolute() else REPO_ROOT / path for path in arguments]


def main() -> int:
    args = parse_args()
    manifests = resolve_manifest_paths(args.manifests)
    if not manifests:
        print("error: no evidence manifests found", file=sys.stderr)
        return 1

    all_errors: list[str] = []
    for path in manifests:
        data, errors = validate_manifest(path)
        if data is not None and not errors and args.online:
            errors += verify_online(path, data)
        if errors:
            all_errors.extend(errors)
        else:
            mode = "structure + online evidence" if args.online else "structure"
            print(f"[ok] {path.relative_to(REPO_ROOT)} ({mode})")

    if all_errors:
        for error in all_errors:
            print(f"error: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
