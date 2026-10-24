#!/usr/bin/env python3
"""Upload the selected PDF to Nexus at its catalog-alias path and verify public access."""

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


def configuration() -> tuple[str, str]:
    username = os.environ.get("PDF_NEXUS_USERNAME", "").strip()
    token = os.environ.get("PDF_NEXUS_TOKEN", "")
    if not username or not token:
        fail("Set variable PDF_NEXUS_USERNAME and secret PDF_NEXUS_TOKEN for Nexus uploads")
    raw = os.environ.get("PDF_NEXUS_URL", "").strip()
    parsed = urllib.parse.urlparse(raw)
    if parsed.scheme != "https" or not parsed.netloc or parsed.query or parsed.fragment:
        fail("PDF_NEXUS_URL must be an HTTPS Nexus Raw repository URL")
    if not re.search(r"/repository/[A-Za-z0-9._-]+/?$", parsed.path):
        fail("PDF_NEXUS_URL must end with /repository/<raw-repository-name>/")
    authorization = "Basic " + base64.b64encode(f"{username}:{token}".encode()).decode()
    return raw.rstrip("/") + "/", authorization


def request(url: str, method: str, *, data: bytes | None = None,
            authorization: str | None = None):
    headers = {"User-Agent": "uniq2me-pdf/1.0"}
    if authorization:
        headers["Authorization"] = authorization
    if data is not None:
        headers["Content-Type"] = "application/pdf"
    last_error = "unknown error"
    for attempt in range(4):
        try:
            return urllib.request.urlopen(
                urllib.request.Request(url, data=data, headers=headers, method=method), timeout=120
            )
        except urllib.error.HTTPError as exc:
            last_error = f"HTTP {exc.code}"
            if exc.code not in {408, 425, 429, 500, 502, 503, 504}:
                fail(f"Nexus {method} {url}: {last_error}")
        except (urllib.error.URLError, TimeoutError) as exc:
            reason = type(exc.reason).__name__ if isinstance(exc, urllib.error.URLError) else "timeout"
            last_error = f"network error ({reason})"
        if attempt < 3:
            time.sleep(2 ** attempt)
    fail(f"Nexus {method} {url} failed after retries: {last_error}")


def digest_file(path: Path) -> str:
    result = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            result.update(block)
    return result.hexdigest()


def main() -> None:
    if len(sys.argv) != 2:
        fail("Usage: publish_nexus.py OUTPUT_DIRECTORY")
    root = Path(sys.argv[1]).resolve()
    if not root.is_dir():
        fail(f"Output directory not found: {root}")
    pdfs = sorted(path for path in root.rglob("*.pdf") if path.is_file())
    if len(pdfs) != 1:
        fail(f"Expected exactly one PDF under {root}; found {len(pdfs)}")
    pdf = pdfs[0]
    relative = pdf.relative_to(root).as_posix()
    if len(Path(relative).parts) != 2:
        fail("PDF output must use <catalog-alias>/<date-template-language>.pdf structure")
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,63}/[0-9]{8}-(full_Catalog|short_List)-[a-z]{2,3}\.pdf", relative):
        fail(f"Unexpected PDF filename or directory: {relative}")
    base, authorization = configuration()
    url = base + "/".join(urllib.parse.quote(segment, safe="-._~") for segment in relative.split("/"))
    body = pdf.read_bytes()
    expected = digest_file(pdf)
    with request(url, "PUT", data=body, authorization=authorization) as response:
        response.read(1)
    print(f"Uploaded {relative} ({len(body)} bytes, sha256 {expected})", flush=True)
    public_response = request(url, "GET")
    actual = hashlib.sha256()
    count = 0
    with public_response:
        for chunk in iter(lambda: public_response.read(1024 * 1024), b""):
            actual.update(chunk)
            count += len(chunk)
    if actual.hexdigest() != expected or count != len(body):
        fail("Anonymous Nexus download did not match the uploaded PDF")
    print(f"Public PDF URL: {url}", flush=True)


if __name__ == "__main__":
    main()
