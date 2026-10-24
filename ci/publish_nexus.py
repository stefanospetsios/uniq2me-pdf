#!/usr/bin/env python3
"""Upload generated catalog PDFs to a Nexus Raw repository and verify public reads."""

from __future__ import annotations

import base64
import hashlib
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path


def fail(message: str) -> None:
    raise SystemExit(message)


def auth_header() -> str:
    username = os.environ.get("PDF_NEXUS_USERNAME", "").strip()
    token = os.environ.get("PDF_NEXUS_TOKEN", "")
    if not username or not token:
        fail("Set PDF_NEXUS_USERNAME and PDF_NEXUS_TOKEN as repository secrets with Nexus deploy permission")
    return "Basic " + base64.b64encode(f"{username}:{token}".encode()).decode()


def base_url() -> str:
    raw = os.environ.get("PDF_NEXUS_URL", "").strip()
    parsed = urllib.parse.urlparse(raw)
    if parsed.scheme != "https" or not parsed.netloc or parsed.query or parsed.fragment:
        fail("PDF_NEXUS_URL must be an HTTPS Nexus Raw repository URL")
    if not re.search(r"/repository/[A-Za-z0-9._-]+/?$", parsed.path):
        fail("PDF_NEXUS_URL must end with /repository/<raw-repository-name>/")
    return raw.rstrip("/") + "/"


def request(url: str, method: str, data: bytes | None = None,
            content_type: str | None = None, auth: str | None = None):
    headers = {"User-Agent": "uniq2me-pdf/1.0"}
    if auth:
        headers["Authorization"] = auth
    if content_type:
        headers["Content-Type"] = content_type
    last_error = "unknown error"
    for attempt in range(4):
        try:
            return urllib.request.urlopen(urllib.request.Request(url, data=data, headers=headers, method=method), timeout=120)
        except urllib.error.HTTPError as exc:
            last_error = f"HTTP {exc.code}"
            if exc.code not in {408, 425, 429, 500, 502, 503, 504}:
                fail(f"Nexus {method} {url}: {last_error}")
        except (urllib.error.URLError, TimeoutError) as exc:
            last_error = f"network error ({type(exc.reason).__name__ if isinstance(exc, urllib.error.URLError) else 'timeout'})"
        if attempt < 3:
            time.sleep(2 ** attempt)
    fail(f"Nexus {method} {url} failed after retries: {last_error}")


def file_digest(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def main() -> None:
    if len(sys.argv) != 6:
        fail("Usage: publish_nexus.py OUTPUT_DIR SOURCE_REPOSITORY SOURCE_REF SOURCE_COMMIT PUBLICATION_PREFIX")
    root = Path(sys.argv[1]).resolve()
    repository, source_ref, commit, publication_prefix = sys.argv[2:]
    base = base_url()
    authorization = auth_header()
    if not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", repository):
        fail("Source repository must use owner/repository form, e.g. stefanospetsios/uniq2me-ai")
    repo_path = repository
    ref_path = re.sub(r"[^A-Za-z0-9._-]+", "-", source_ref.strip("/")) or "ref"
    if not re.fullmatch(r"[0-9a-fA-F]{40,64}", commit):
        fail("Source commit must be a full 40- or 64-character Git SHA")
    prefix = re.sub(r"[^A-Za-z0-9._-]+", "-", publication_prefix.strip("/")) or "catalog"
    release_path = "/".join((repo_path, ref_path, commit.lower(), prefix))
    candidates = sorted(path for path in root.rglob("*") if path.is_file() and path.suffix.lower() in {".pdf", ".zip", ".json"})
    if not candidates:
        fail(f"No PDF, ZIP, or JSON publication files found under {root}")
    for path in candidates:
        relative = path.relative_to(root).as_posix()
        encoded_path = "/".join(urllib.parse.quote(segment, safe="-._~") for segment in (release_path + "/" + relative).split("/"))
        url = base + encoded_path
        mime = {".pdf": "application/pdf", ".zip": "application/zip", ".json": "application/json"}[path.suffix.lower()]
        body = path.read_bytes()
        response = request(url, "PUT", body, mime, authorization)
        response.close()
        expected = file_digest(path)
        print(f"Uploaded {relative} ({len(body)} bytes, sha256 {expected})", flush=True)

        # Ensure anonymous readers can retrieve the published public asset and verify its bytes.
        public_response = request(url, "GET")
        actual_hash = hashlib.sha256()
        count = 0
        with public_response:
            for chunk in iter(lambda: public_response.read(1024 * 1024), b""):
                actual_hash.update(chunk)
                count += len(chunk)
        if actual_hash.hexdigest() != expected or count != len(body):
            fail(f"Public Nexus download verification failed for {relative}")
        print(f"Public URL: {url}", flush=True)


if __name__ == "__main__":
    main()
