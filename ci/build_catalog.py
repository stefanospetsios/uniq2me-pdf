#!/usr/bin/env python3
"""Render a complete 16 × 16 catalog as individual PDFs and one ordered PDF per locale."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import zipfile
from datetime import datetime, timezone
from pathlib import Path

SFS_IDS = "0123456789ABCDEF"


def load_json(path: Path) -> dict:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise SystemExit(f"Cannot read {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise SystemExit(f"Expected a JSON object in {path}")
    return value


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def catalog_records(root: Path, language: str) -> tuple[list[tuple[str, Path]], list[Path]]:
    json_dir = root / "json" / language
    sf_dir = root / "repo-sf" / language
    if not json_dir.is_dir():
        raise ValueError(f"missing json/{language}/")
    records: list[tuple[str, Path]] = []
    sources: list[Path] = []
    found_sfs = set()
    for sfs_id in SFS_IDS:
        sfs_path = json_dir / f"{sfs_id}.json"
        if not sfs_path.is_file():
            raise ValueError(f"missing SFS JSON {sfs_path.relative_to(root)}")
        sfs = load_json(sfs_path)
        items = sfs.get("set")
        if not isinstance(items, list):
            raise ValueError(f"{sfs_path.relative_to(root)} has no set[] list")
        item_map = {str(item.get("id", "")).upper(): item for item in items if isinstance(item, dict)}
        if set(item_map) != set(SFS_IDS):
            raise ValueError(f"{sfs_path.relative_to(root)} must contain one SF position for each 0–F")
        sources.append(sfs_path)
        records.append(("sfs", sfs_path))
        for sf_id in SFS_IDS:
            repo_id = str(item_map[sf_id].get("repoId") or f"{sfs_id}{sf_id}").upper()
            if not re.fullmatch(r"[0-9A-F]{4}", repo_id):
                raise ValueError(f"Invalid repoId {repo_id!r} in {sfs_path.relative_to(root)}")
            sf_path = sf_dir / f"{repo_id}.json"
            if not sf_path.is_file():
                raise ValueError(f"missing SF JSON {sf_path.relative_to(root)}")
            sf = load_json(sf_path)
            identity = sf.get("identity") or {}
            if str(identity.get("sfsId", "")).upper() != sfs_id or str(identity.get("sfId", "")).upper() != sf_id:
                raise ValueError(f"SF identity mismatch in {sf_path.relative_to(root)}")
            records.append(("sf", sf_path))
            sources.append(sf_path)
            found_sfs.add(sf_path)
    if len(found_sfs) != 256:
        raise ValueError(f"expected 256 distinct SF files; found {len(found_sfs)}")
    return records, sources


def complete_languages(root: Path) -> tuple[list[str], dict[str, str]]:
    json_root = root / "json"
    if not json_root.is_dir():
        raise SystemExit("Catalog checkout has no json/ directory")
    complete, incomplete = [], {}
    for directory in sorted(path for path in json_root.iterdir() if path.is_dir()):
        language = directory.name
        try:
            catalog_records(root, language)
            complete.append(language)
        except (ValueError, SystemExit) as exc:
            incomplete[language] = str(exc)
    return complete, incomplete


def render_one(renderer: Path, kind: str, source: Path, output: Path, *, language: str,
               commit: str, edition: str, sfs: Path | None = None) -> None:
    command = [sys.executable, str(renderer), kind, str(source), "--language", language,
               "--commit", commit, "--edition", edition, "--output", str(output)]
    if sfs:
        command.extend(("--sfs", str(sfs)))
    result = subprocess.run(command, text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    if result.returncode:
        raise SystemExit(f"Failed to render {source}:\n{result.stdout[-6000:]}")


def build_language(root: Path, output_root: Path, language: str, repository: str,
                   source_ref: str, commit: str, renderer: Path) -> dict:
    records, sources = catalog_records(root, language)
    language_dir = output_root / language
    language_dir.mkdir(parents=True, exist_ok=True)
    edition = f"{source_ref} · {commit[:12]}"
    pages: list[Path] = []
    for kind, source in records:
        if kind == "sfs":
            sfs_id = source.stem.upper()
            target = language_dir / f"sfs-{sfs_id}-cover.pdf"
            render_one(renderer, "sfs", source, target, language=language,
                       commit=commit, edition=edition)
        else:
            sf = load_json(source)
            identity = sf["identity"]
            sfs_id, sf_id = str(identity["sfsId"]).upper(), str(identity["sfId"]).upper()
            sfs_source = root / "json" / language / f"{sfs_id}.json"
            target = language_dir / f"sf-{sfs_id}{sf_id}.pdf"
            render_one(renderer, "sf", source, target, language=language,
                       commit=commit, edition=edition, sfs=sfs_source)
        pages.append(target)

    from pypdf import PdfReader, PdfWriter

    bundle = language_dir / f"catalog-{language}.pdf"
    writer = PdfWriter()
    for page_pdf in pages:
        reader = PdfReader(str(page_pdf), strict=True)
        if len(reader.pages) != 1:
            raise SystemExit(f"Expected one A4 page in {page_pdf.name}; found {len(reader.pages)}")
        page = reader.pages[0]
        width, height = float(page.mediabox.width), float(page.mediabox.height)
        if abs(width - 595.28) > 1.0 or abs(height - 841.89) > 1.0:
            raise SystemExit(f"{page_pdf.name} is not A4: {width:.1f} × {height:.1f} pt")
        writer.add_page(page)
    if len(writer.pages) != 272:
        raise SystemExit(f"Expected 272 pages for {language}; assembled {len(writer.pages)}")
    writer.add_metadata({
        "/Title": f"UNIQ2Me catalog · {language} · {source_ref}",
        "/Author": "UNIQ2Me",
        "/Subject": f"16 SFS covers and 256 SF records from {repository}@{commit}",
    })
    with bundle.open("wb") as stream:
        writer.write(stream)

    page_zip = language_dir / f"individual-pages-{language}.zip"
    with zipfile.ZipFile(page_zip, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=6) as archive:
        for page_pdf in pages:
            archive.write(page_pdf, page_pdf.name)

    return {
        "language": language,
        "pageCount": 272,
        "coverCount": 16,
        "sfCount": 256,
        "bundle": str(bundle.relative_to(output_root)),
        "bundleSha256": sha256(bundle),
        "individualPages": str(page_zip.relative_to(output_root)),
        "individualPagesSha256": sha256(page_zip),
        "sourceJsonCount": len(sources),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("catalog", type=Path, help="Root of checked-out catalog repository")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--repository", required=True)
    parser.add_argument("--ref", required=True)
    parser.add_argument("--commit", required=True)
    parser.add_argument("--language", default="all", help="all or one complete locale such as en")
    args = parser.parse_args()
    root = args.catalog.resolve()
    output = args.output.resolve()
    renderer = Path(__file__).resolve().parents[1] / "printable-catalog" / "render.py"
    if not renderer.is_file():
        raise SystemExit(f"Missing renderer: {renderer}")
    output.mkdir(parents=True, exist_ok=True)
    complete, incomplete = complete_languages(root)
    if args.language.lower() == "all":
        languages = complete
    else:
        languages = [args.language]
        if args.language not in complete:
            reason = incomplete.get(args.language, "locale directory not found")
            raise SystemExit(f"Requested locale {args.language} is incomplete: {reason}")
    if not languages:
        raise SystemExit("No complete 16 × 16 locale is available")

    built = [build_language(root, output, language, args.repository, args.ref, args.commit, renderer)
             for language in languages]
    manifest = {
        "formatVersion": 1,
        "repository": args.repository,
        "sourceRef": args.ref,
        "sourceCommit": args.commit,
        "generatedAt": datetime.now(timezone.utc).isoformat(),
        "languages": built,
        "skippedIncompleteLocales": incomplete if args.language.lower() == "all" else {},
        "note": "Pages identify catalog questions and signature fields; they are not an assessment or compliance decision.",
    }
    manifest_path = output / "manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(json.dumps(manifest, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
