#!/usr/bin/env python3
"""Render a contextual shortlist cover page from a catalog-bound mask JSON."""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

from render import (
    HERE, SFS_IDS, clip, github_record_url, macro, raw_macro, read_json,
    source_digest, tex_escape, translated_macros,
)


def selected_fields(selection: dict) -> dict[str, str]:
    fields = {digit: "0000" for digit in SFS_IDS}
    kind = selection.get("type")
    if kind == "catalog":
        incoming = selection.get("fields") or {}
        for sfs_id in SFS_IDS:
            value = str(incoming.get(sfs_id, "")).upper()
            if len(value) != 4 or any(char not in SFS_IDS for char in value):
                raise SystemExit(f"Catalog mask must include a four-digit hexadecimal field for SFS {sfs_id}")
            fields[sfs_id] = value
    elif kind == "sfs":
        sfs_id = str(selection.get("sfsId", "")).upper()
        value = str(selection.get("mask", "")).upper()
        if sfs_id not in SFS_IDS or len(value) != 4 or any(char not in SFS_IDS for char in value):
            raise SystemExit("SFS selection must contain a valid SFS position and four-digit hexadecimal mask")
        fields[sfs_id] = value
    elif kind == "sf":
        seen = set()
        for position in selection.get("positions", []):
            sfs_id, sf_id = str(position.get("sfsId", "")).upper(), str(position.get("sfId", "")).upper()
            if sfs_id not in SFS_IDS or sf_id not in SFS_IDS or (sfs_id, sf_id) in seen:
                raise SystemExit(f"Invalid or duplicate shortlist position: {sfs_id}/{sf_id}")
            seen.add((sfs_id, sf_id))
            fields[sfs_id] = f"{int(fields[sfs_id], 16) | (1 << (15 - SFS_IDS.index(sf_id))):04X}"
    else:
        raise SystemExit("Mask selection type must be catalog, sfs, or sf")
    return fields


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--catalog", type=Path, required=True)
    parser.add_argument("--mask", type=Path, required=True)
    parser.add_argument("--language", required=True)
    parser.add_argument("--repository", required=True)
    parser.add_argument("--commit", required=True)
    parser.add_argument("--alias", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    root = args.catalog.resolve()
    mask_path = args.mask.resolve()
    if not mask_path.is_file():
        raise SystemExit(f"Shortlist mask not found: {mask_path}")
    try:
        mask_path.relative_to(root)
    except ValueError:
        raise SystemExit("Shortlist mask must be inside the selected catalog checkout") from None
    mask = read_json(mask_path)
    language = args.language
    if mask.get("language") != language or (mask.get("catalog") or {}).get("language") != language:
        raise SystemExit(f"Mask language must match selected PDF language {language!r}")
    fields = selected_fields(mask.get("selection") or {})
    labels = json_labels(language)
    factor_positions = [(sfs_id, sf_id) for sfs_id in SFS_IDS for sf_id in SFS_IDS
                        if int(fields[sfs_id], 16) & (1 << (15 - SFS_IDS.index(sf_id)))]
    if not factor_positions:
        raise SystemExit("Shortlist mask selects no scoring factors")

    source_paths = [mask_path]
    source_sets: dict[str, dict] = {}
    rows: dict[str, tuple[str, str]] = {}
    for sfs_id in SFS_IDS:
        sfs_path = root / "json" / language / f"{sfs_id}.json"
        if int(fields[sfs_id], 16):
            if not sfs_path.is_file():
                raise SystemExit(f"Selected SFS {sfs_id} has no JSON for language {language}")
            sfs = read_json(sfs_path)
            source_sets[sfs_id] = sfs
            source_paths.append(sfs_path)
            rows[sfs_id] = (fields[sfs_id], clip(sfs.get("keyTitle") or sfs.get("meta", {}).get("title"), 48))
        else:
            source_sets[sfs_id] = {}
            rows[sfs_id] = (fields[sfs_id], "")
    for sfs_id, sf_id in factor_positions:
        sfs = source_sets[sfs_id]
        item = next((row for row in sfs.get("set", []) if str(row.get("id", "")).upper() == sf_id), None)
        if not item:
            raise SystemExit(f"Selected position {sfs_id}/{sf_id} is absent from its SFS JSON")
        repo_id = str(item.get("repoId") or f"{sfs_id}{sf_id}").upper()
        sf_path = root / "repo-sf" / language / f"{repo_id}.json"
        sf = read_json(sf_path)
        identity = sf.get("identity") or {}
        if str(identity.get("sfsId", "")).upper() != sfs_id or str(identity.get("sfId", "")).upper() != sf_id:
            raise SystemExit(f"Selected factor identity mismatch in {sf_path.relative_to(root)}")
        source_paths.append(sf_path)

    translated, translations = translated_macros(language)
    out = translated
    detail_url = github_record_url(root, mask_path, args.commit)
    digest = source_digest(*source_paths)
    for name, value in {
        "RecordType": translations["shortlistRecord"], "RecordCode": f"{args.alias} · {language.upper()} · {args.commit[:12]}",
        "RecordCommit": args.commit, "RecordDigest": digest, "RecordLanguage": language,
        "EntityTitle": mask.get("title") or args.alias,
        "EntitySummary": clip(mask.get("description"), 420), "Edition": f"{args.alias} / {mask.get('id', '')}",
        "HeaderScoreLabel": translations["selectedFactors"],
        "HeaderScore": f"{len(factor_positions)} / 256",
        "DetailURL": detail_url,
        "MaskId": mask.get("id", "mask"), "MaskTitle": mask.get("title", args.alias),
        "MaskDescription": clip(mask.get("description"), 540),
        "MaskPurpose": clip(mask.get("purpose"), 620), "MaskScope": clip(mask.get("scope"), 620),
        "MaskEvidencePeriod": clip(mask.get("evidencePeriod"), 300),
        "MaskStatus": mask.get("status", "unspecified"),
        "MaskCatalogDigest": (mask.get("catalog") or {}).get("digest", "not recorded"),
    }.items():
        out += macro(name, value)
    references = []
    for ref in (mask.get("references") or [])[:6]:
        title = tex_escape(clip(ref.get("title") or "Reference", 84))
        url = ref.get("url") or ""
        if isinstance(url, str) and url.startswith(("https://", "http://")):
            url = url.replace("#", "%23").replace("{", "%7B").replace("}", "%7D")
            references.append(rf"\href{{\detokenize{{{url}}}}}{{\textbf{{{title}}}}}")
        else:
            references.append(rf"\textbf{{{title}}}")
    if not references:
        references = [rf"\textit{{{tex_escape(translations['noReferences'])}}}"]
    out += raw_macro("MaskReferences", r"\par\medskip ".join(references))
    paired = []
    for index in range(8):
        left_id, right_id = SFS_IDS[index], SFS_IDS[index + 8]
        left_mask, left_title = rows[left_id]
        right_mask, right_title = rows[right_id]
        left_sfs = ",".join(sf for sf in SFS_IDS if int(left_mask, 16) & (1 << (15 - SFS_IDS.index(sf)))) or "—"
        right_sfs = ",".join(sf for sf in SFS_IDS if int(right_mask, 16) & (1 << (15 - SFS_IDS.index(sf)))) or "—"
        paired.append(
            rf"\textbf{{{left_id} / {left_mask}}} & {left_sfs} & {tex_escape(clip(left_title, 48))} & "
            rf"\textbf{{{right_id} / {right_mask}}} & {right_sfs} & {tex_escape(clip(right_title, 48))}\\[-0.3mm]"
        )
    out += raw_macro("MaskRows", "\n".join(paired))
    out += macro("QRImage", "shortlist-qr.png" if detail_url else "")

    output = args.output.resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    tex_path = output.with_suffix(".tex")
    generated = out + f"\\input{{{(HERE / 'common.tex').as_posix()}}}\n"
    generated += f"\\input{{{(HERE / 'shortlist-cover.tex').as_posix()}}}\n"
    tex_path.write_text(generated, encoding="utf-8")
    if detail_url:
        qrencode = shutil.which("qrencode")
        if not qrencode:
            raise SystemExit("qrencode is required to create the shortlist mask QR code")
        qr_path = output.with_name("shortlist-qr.png")
        result = subprocess.run([qrencode, "-o", str(qr_path), detail_url], capture_output=True, text=True)
        if result.returncode:
            raise SystemExit(f"qrencode failed: {result.stderr.strip()}")
    engine = shutil.which("lualatex")
    if not engine:
        raise SystemExit("LuaLaTeX is required to render a PDF")
    with tempfile.TemporaryDirectory(prefix="uniq2me-shortlist-") as temporary:
        work = Path(temporary)
        local_tex = work / "record.tex"
        local_tex.write_text(generated, encoding="utf-8")
        if detail_url:
            shutil.copy2(qr_path, work / qr_path.name)
        env = os.environ.copy()
        env.setdefault("TEXMFCACHE", str(work / "tex-cache"))
        Path(env["TEXMFCACHE"]).mkdir(parents=True, exist_ok=True)
        result = subprocess.run([engine, "-interaction=nonstopmode", "-halt-on-error", "-output-directory",
                                 str(work), str(local_tex)], cwd=work, env=env,
                                stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
        if result.returncode:
            print(result.stdout[-8000:], file=sys.stderr)
            raise SystemExit(f"LuaLaTeX failed; source remains at {tex_path}")
        shutil.copy2(work / "record.pdf", output)
    print(f"Rendered shortlist cover for {len(factor_positions)} factors: {output}")


def json_labels(language: str) -> dict:
    return json.loads((HERE / "labels.json").read_text(encoding="utf-8"))[language]


if __name__ == "__main__":
    main()
