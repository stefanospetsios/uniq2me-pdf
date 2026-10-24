#!/usr/bin/env python3
"""Build one dated full-catalog or mask-selected shortlist PDF."""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

from pypdf import PdfReader, PdfWriter

SFS_IDS = "0123456789ABCDEF"
TEMPLATES = {"fullCatalog": "full_Catalog", "shortList": "short_List"}


def load_json(path: Path) -> dict:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise SystemExit(f"Cannot read {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise SystemExit(f"Expected a JSON object in {path}")
    return value


def full_catalog_records(root: Path, language: str) -> list[tuple[str, Path, Path | None]]:
    result = []
    for sfs_id in SFS_IDS:
        sfs_path = root / "json" / language / f"{sfs_id}.json"
        if not sfs_path.is_file():
            raise SystemExit(f"Full catalog requires {sfs_path.relative_to(root)}")
        sfs = load_json(sfs_path)
        factors = {str(item.get("id", "")).upper(): item for item in sfs.get("set", []) if isinstance(item, dict)}
        if set(factors) != set(SFS_IDS):
            raise SystemExit(f"{sfs_path.relative_to(root)} must include all sixteen SF positions 0–F")
        result.append(("sfs", sfs_path, None))
        for sf_id in SFS_IDS:
            repo_id = str(factors[sf_id].get("repoId") or f"{sfs_id}{sf_id}").upper()
            if not re.fullmatch(r"[0-9A-F]{4}", repo_id):
                raise SystemExit(f"Invalid repoId {repo_id!r} in {sfs_path.relative_to(root)}")
            sf_path = root / "repo-sf" / language / f"{repo_id}.json"
            if not sf_path.is_file():
                raise SystemExit(f"Full catalog requires {sf_path.relative_to(root)}")
            sf = load_json(sf_path)
            identity = sf.get("identity") or {}
            if str(identity.get("sfsId", "")).upper() != sfs_id or str(identity.get("sfId", "")).upper() != sf_id:
                raise SystemExit(f"Position mismatch in {sf_path.relative_to(root)}")
            result.append(("sf", sf_path, sfs_path))
    if len(result) != 272:
        raise SystemExit(f"Expected 16 SFS covers and 256 SF pages, got {len(result)} records")
    return result


def selected_positions(mask: dict) -> list[tuple[str, str]]:
    import sys
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "printable-catalog"))
    from render_shortlist import selected_fields
    fields = selected_fields(mask.get("selection") or {})
    return [(sfs_id, sf_id) for sfs_id in SFS_IDS for sf_id in SFS_IDS
            if int(fields[sfs_id], 16) & (1 << (15 - SFS_IDS.index(sf_id)))]


def render_page(renderer: Path, kind: str, source: Path, output: Path, *, language: str,
                repository: str, commit: str, alias: str, sfs: Path | None = None,
                context: Path | None = None) -> None:
    command = [sys.executable, str(renderer), kind, str(source), "--language", language,
               "--commit", commit, "--edition", alias, "--output", str(output)]
    if sfs:
        command.extend(("--sfs", str(sfs)))
    if context:
        command.extend(("--context-json", str(context)))
    result = subprocess.run(command, text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    if result.returncode:
        raise SystemExit(f"Rendering {source} failed:\n{result.stdout[-8000:]}")


def compile_pdf(root: Path, records: list[tuple[str, Path, Path | None]], *,
                output: Path, temp_root: Path, language: str, repository: str,
                commit: str, alias: str, template: str,
                shortlist_mask: Path | None = None) -> None:
    renderer_dir = Path(__file__).resolve().parents[1] / "printable-catalog"
    renderer = renderer_dir / "render.py"
    page_files = []
    for index, (kind, source, sfs) in enumerate(records, start=1):
        page = temp_root / f"page-{index:03}.pdf"
        render_page(renderer, kind, source, page, language=language, repository=repository,
                    commit=commit, alias=alias, sfs=sfs, context=shortlist_mask)
        page_files.append(page)
    if shortlist_mask:
        cover = temp_root / "page-000-cover.pdf"
        command = [sys.executable, str(renderer_dir / "render_shortlist.py"),
                   "--catalog", str(root), "--mask", str(shortlist_mask), "--language", language,
                   "--repository", repository, "--commit", commit, "--alias", alias,
                   "--output", str(cover)]
        result = subprocess.run(command, text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
        if result.returncode:
            raise SystemExit(f"Shortlist cover rendering failed:\n{result.stdout[-8000:]}")
        page_files.insert(0, cover)

    writer = PdfWriter()
    for pdf in page_files:
        reader = PdfReader(str(pdf), strict=True)
        if len(reader.pages) != 1:
            raise SystemExit(f"Expected one page in {pdf.name}; got {len(reader.pages)}")
        page = reader.pages[0]
        width, height = float(page.mediabox.width), float(page.mediabox.height)
        if abs(width - 595.28) > 1.0 or abs(height - 841.89) > 1.0:
            raise SystemExit(f"{pdf.name} is not A4: {width:.1f} × {height:.1f} pt")
        writer.add_page(page)
    expected = 272 if template == "fullCatalog" else len(records) + 1
    if len(writer.pages) != expected:
        raise SystemExit(f"Expected {expected} pages for {template}, assembled {len(writer.pages)}")
    writer.add_metadata({
        "/Title": f"UNIQ2Me {template} · {alias} · {language}",
        "/Author": "UNIQ2Me",
        "/Subject": f"{repository}@{commit}; template={template}; language={language}",
    })
    with output.open("wb") as stream:
        writer.write(stream)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("catalog", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--repository", required=True, help="Public source repository name, without owner")
    parser.add_argument("--commit", required=True)
    parser.add_argument("--alias", required=True)
    parser.add_argument("--template", choices=tuple(TEMPLATES), required=True)
    parser.add_argument("--language", choices=("en", "el", "fr", "de"), required=True)
    parser.add_argument("--shortlist-mask", type=Path)
    parser.add_argument("--date", help="Output date in YYYYMMDD, defaults to current UTC date")
    args = parser.parse_args()
    root = args.catalog.resolve()
    output_root = args.output.resolve()
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,63}", args.alias):
        raise SystemExit("Catalog alias must be 1–64 letters/numbers/dot/underscore/hyphen")
    if not re.fullmatch(r"[A-Za-z0-9_-]+", args.repository):
        raise SystemExit("CATALOG_REPOSITORY must be the repository name, e.g. uniq2me or uniq2me-ai")
    if not re.fullmatch(r"[0-9a-fA-F]{40,64}", args.commit):
        raise SystemExit("COMMIT_SHA must be a full 40- or 64-character commit SHA")
    date_stamp = args.date or datetime.now(timezone.utc).strftime("%Y%m%d")
    try:
        datetime.strptime(date_stamp, "%Y%m%d")
    except ValueError:
        raise SystemExit("Date must use YYYYMMDD") from None
    if args.template == "fullCatalog":
        if args.shortlist_mask:
            raise SystemExit("Do not set --shortlist-mask for fullCatalog")
        records = full_catalog_records(root, args.language)
    else:
        if not args.shortlist_mask:
            raise SystemExit("shortList requires --shortlist-mask pointing to a catalog-bound mask JSON")
        mask_path = args.shortlist_mask.resolve() if args.shortlist_mask.is_absolute() else (root / args.shortlist_mask).resolve()
        mask_path.relative_to(root)
        mask = load_json(mask_path)
        if mask.get("language") != args.language or (mask.get("catalog") or {}).get("language") != args.language:
            raise SystemExit(f"Shortlist mask language must match --language {args.language}")
        positions = selected_positions(mask)
        if not positions:
            raise SystemExit("Shortlist mask selects no SF positions")
        records = []
        for sfs_id, sf_id in positions:
            sfs_path = root / "json" / args.language / f"{sfs_id}.json"
            if not sfs_path.is_file():
                raise SystemExit(f"Selected SFS JSON missing: {sfs_path.relative_to(root)}")
            sfs = load_json(sfs_path)
            factor = next((item for item in sfs.get("set", []) if str(item.get("id", "")).upper() == sf_id), None)
            if factor is None:
                raise SystemExit(f"Selected position {sfs_id}/{sf_id} is absent from its SFS JSON")
            repo_id = str(factor.get("repoId") or f"{sfs_id}{sf_id}").upper()
            sf_path = root / "repo-sf" / args.language / f"{repo_id}.json"
            if not sf_path.is_file():
                raise SystemExit(f"Selected SF JSON missing: {sf_path.relative_to(root)}")
            records.append(("sf", sf_path, sfs_path))

    output = output_root / args.alias / f"{date_stamp}-{TEMPLATES[args.template]}-{args.language}.pdf"
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="uniq2me-catalog-pdf-") as directory:
        compile_pdf(root, records, output=output, temp_root=Path(directory), language=args.language,
                    repository=args.repository, commit=args.commit, alias=args.alias,
                    template=args.template,
                    shortlist_mask=(args.shortlist_mask.resolve() if args.shortlist_mask and args.shortlist_mask.is_absolute()
                                    else (root / args.shortlist_mask).resolve() if args.shortlist_mask else None))
    print(f"Created {output}")


if __name__ == "__main__":
    main()
