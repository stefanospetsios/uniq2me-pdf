#!/usr/bin/env python3
"""Render one UNIQ2Me SFS cover or SF record from catalog JSON using LuaLaTeX."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from urllib.parse import urlparse


SCRIPT_DIR = Path(__file__).resolve().parent
REPO_ROOT = SCRIPT_DIR.parents[1]
TEMPLATE_NAMES = ("fullCatalog", "shortList", "doraShort", "nis2Full")


def template_dir(name: str) -> Path:
    if name not in TEMPLATE_NAMES:
        raise SystemExit(f"Unknown template {name!r}; choose one of {', '.join(TEMPLATE_NAMES)}")
    return REPO_ROOT / name
SFS_IDS = "0123456789ABCDEF"


def read_json(path: Path) -> dict:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise SystemExit(f"Cannot read JSON {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise SystemExit(f"Expected a JSON object in {path}")
    return value


def tex_escape(value: object) -> str:
    text = str(value if value is not None else "")
    replacements = {
        "\\": r"\textbackslash{}", "&": r"\&", "%": r"\%", "$": r"\$",
        "#": r"\#", "_": r"\_", "{": r"\{", "}": r"\}",
        "~": r"\textasciitilde{}", "^": r"\textasciicircum{}",
    }
    return "".join(replacements.get(char, char) for char in text)


def macro(name: str, value: object) -> str:
    return rf"\newcommand{{\{name}}}{{{tex_escape(value)}}}" + "\n"


def raw_macro(name: str, value: str) -> str:
    return rf"\newcommand{{\{name}}}{{{value}}}" + "\n"


def clip(value: object, limit: int) -> str:
    text = " ".join(str(value or "").split())
    if len(text) <= limit:
        return text
    return text[: limit - 1].rsplit(" ", 1)[0] + "…"


def repository_root(path: Path) -> Path:
    path = path.resolve()
    for candidate in (path, *path.parents):
        if candidate.name in {"json", "repo-sf"}:
            return candidate.parent
    return path.parent


def safe_id(value: object, name: str) -> str:
    value = str(value or "").upper()
    if len(value) != 1 or value not in SFS_IDS:
        raise SystemExit(f"Invalid {name}: expected one hexadecimal catalog position, got {value!r}")
    return value


def source_digest(*paths: Path) -> str:
    digest = hashlib.sha256()
    for path in paths:
        digest.update(path.read_bytes())
        digest.update(b"\0")
    return digest.hexdigest()


def git_commit(root: Path) -> str:
    try:
        return subprocess.check_output(
            ["git", "-C", str(root), "rev-parse", "HEAD"], stderr=subprocess.DEVNULL, text=True
        ).strip()
    except (OSError, subprocess.CalledProcessError):
        return "unavailable"


def github_record_url(root: Path, source_path: Path, commit: str) -> str:
    try:
        remote = subprocess.check_output(
            ["git", "-C", str(root), "remote", "get-url", "origin"],
            stderr=subprocess.DEVNULL, text=True,
        ).strip()
    except (OSError, subprocess.CalledProcessError):
        return ""
    match = re.fullmatch(r"git@github\.com:([^/]+/[^/]+?)(?:\.git)?", remote)
    if not match:
        match = re.fullmatch(r"https://github\.com/([^/]+/[^/]+?)(?:\.git)?", remote)
    if not match or commit == "unavailable":
        return ""
    try:
        relative = source_path.resolve().relative_to(root.resolve()).as_posix()
    except ValueError:
        return ""
    return f"https://github.com/{match.group(1)}/blob/{commit}/{relative}"


def signer_macros(sf: dict) -> str:
    signatures = sf.get("signatures") or {}
    out = ""
    for letter, key in zip("ABC", ("signerA", "signerB", "signerC")):
        signer = signatures.get(key) or {}
        vote = signer.get("vote")
        marked = bool(signer.get("marked", signer.get("signatureMarked", False)))
        full_name = signer.get("fullName") or signer.get("nickname") or ""
        timestamp = signer.get("timestamp") or ""
        for suffix, value in (("Name", full_name), ("Date", timestamp)):
            out += macro(f"Signer{letter}{suffix}", value)
        out += raw_macro(f"Vote{letter}Zero", r"$\blacksquare$" if str(vote) == "0" else r"$\square$")
        out += raw_macro(f"Vote{letter}One", r"$\blacksquare$" if str(vote) == "1" else r"$\square$")
        out += raw_macro(f"Marked{letter}", r"$\blacksquare$" if marked else r"$\square$")
    return out


def translated_macros(language: str, template: str) -> tuple[str, dict]:
    labels = json.loads((template_dir(template) / "labels.json").read_text(encoding="utf-8"))
    if language not in labels:
        raise SystemExit(f"No printable-template translations are available for language {language!r}")
    names = {
        "brandSubtitle": "BrandSubtitle", "footerRecord": "FooterRecord",
        "scoreLabel": "ScoreLabel", "setSizeLabel": "SetSizeLabel", "notScored": "NotScoredLabel",
        "noClarification": "NoClarificationLabel", "noTechnicalQuestion": "NoTechnicalQuestionLabel",
        "noReferences": "NoReferencesLabel", "noCanonicalSolution": "NoCanonicalSolutionLabel",
        "missingFactorDetail": "MissingFactorDetailLabel", "factorCount": "FactorCountLabel",
        "sfsMask": "SFSMaskLabel", "sfPositions": "SFPositionsLabel", "setName": "SetNameLabel",
        "shortlistRecord": "ShortlistRecordLabel",
        "scoringFactorLabel": "ScoringFactorLabel", "scoringFactorSetLabel": "ScoringFactorSetLabel",
        "assessmentDetail": "AssessmentDetailLabel", "clarificationReasoning": "ClarificationReasoningLabel",
        "canonicalSolution": "CanonicalSolutionLabel", "references": "ReferencesLabel",
        "noCatalogUrl": "NoCatalogURLLabel", "openRecord": "OpenRecordLabel",
        "signoff": "SignoffLabel", "signoffInstructions": "SignoffInstructionsLabel",
        "signer": "SignerLabel", "name": "NameLabel", "value": "ValueLabel",
        "signature": "SignatureLabel", "marked": "MarkedLabel", "date": "DateLabel",
        "factorList": "FactorListLabel", "factorListNote": "FactorListNoteLabel",
        "factorId": "FactorIdLabel", "question": "QuestionLabel", "purposeScope": "PurposeScopeLabel",
        "keywords": "KeywordsLabel", "catalogCoverNote": "CatalogCoverNoteLabel",
        "context": "ContextLabel", "purpose": "PurposeLabel", "scope": "ScopeLabel",
        "evidencePeriod": "EvidencePeriodLabel", "selectedFactors": "SelectedFactorsLabel",
        "selectionNote": "SelectionNoteLabel", "sourceCommit": "SourceCommitLabel",
        "inputFingerprint": "InputFingerprintLabel",
    }
    selected = labels[language]
    return "".join(macro(names[key], value) for key, value in selected.items()), selected


def record_url(sf: dict, args: argparse.Namespace, root: Path | None = None,
               source_path: Path | None = None) -> str:
    candidates = [args.detail_url, sf.get("glacierLink")]
    for candidate in candidates:
        if isinstance(candidate, str) and urlparse(candidate).scheme in {"http", "https"}:
            return candidate
    if root is not None and source_path is not None:
        pinned = github_record_url(root, source_path, args.commit or git_commit(root))
        if pinned:
            return pinned
    for candidate in (sf.get("linkLatest"), sf.get("jsonLink")):
        if isinstance(candidate, str) and urlparse(candidate).scheme in {"http", "https"}:
            return candidate
    return ""


def base_macros(root: Path, args: argparse.Namespace, kind: str, entity: dict,
                source_paths: list[Path], sfs: dict | None = None, sf: dict | None = None,
                context: dict | None = None) -> str:
    language = str((sf or {}).get("identity", {}).get("language") or args.language or "en")
    commit = args.commit or git_commit(root)
    digest = source_digest(*source_paths)
    detail_url = record_url(sf or entity, args, root, source_paths[0])
    code = f"{language.upper()} · {commit[:12]}"
    out, labels = translated_macros(language, args.template)
    for name, value in {
        "RecordType": kind,
        "RecordCode": code,
        "RecordCommit": commit,
        "RecordDigest": digest,
        "RecordLanguage": language,
        "DetailURL": detail_url,
        "QRLabel": "OPEN CATALOG RECORD" if detail_url else "NO RELEASE LINK RECORDED",
        "EntityTitle": clip(entity.get("keyTitle") or entity.get("meta", {}).get("title") or "UNIQ2Me catalog", 84),
        "EntitySummary": clip(entity.get("keyShortInfo") or entity.get("keyDescription"), 440),
        "EntityDescription": clip(entity.get("keyDescription"), 1100),
        "Keywords": clip(entity.get("keyWords"), 240),
        "Edition": args.edition or "Catalog release not specified",
    }.items():
        out += macro(name, value)
    out += macro("HeaderScoreLabel", labels["scoreLabel"] if sf is not None else labels["setSizeLabel"])
    out += macro("HeaderScore", labels["notScored"] if sf is not None else labels["factorCount"])
    if sf is not None:
        identity = sf.get("identity") or {}
        question = sf.get("question") or {}
        repo_id = identity.get("repoId") or source_paths[0].stem
        score = sf.get("resultScore")
        if score is None and sfs is not None:
            for item in sfs.get("set", []):
                if str(item.get("id")) == str(identity.get("sfId")):
                    score = item.get("score")
                    break
        score_text = labels["notScored"] if score is None else str(score)
        clarifications = sf.get("clarificationQuestion") or []
        clarification_text = "\n".join(
            f"\\textbf{{{tex_escape(clip(item.get('key1') or 'Clarification', 70))}}}\\par "
            f"{tex_escape(clip(item.get('key2'), 250))}\\par\\medskip"
            for item in clarifications[:2] if isinstance(item, dict)
        ) or rf"\textit{{{tex_escape(labels['noClarification'])}}}"
        refs = sf.get("wikiLinks") or []
        ref_lines = []
        for item in refs[:3]:
            if isinstance(item, dict):
                title = clip(item.get("key1") or "Reference", 90)
                url = item.get("key2") or ""
                if isinstance(url, str) and urlparse(url).scheme in {"http", "https"}:
                    safe_url = url.replace("#", "%23").replace("{", "%7B").replace("}", "%7D")
                    ref_lines.append(rf"\href{{\detokenize{{{safe_url}}}}}{{\textbf{{{tex_escape(title)}}}}}")
                else:
                    ref_lines.append(rf"\textbf{{{tex_escape(title)}}}")
        if not ref_lines:
            ref_lines.append(rf"\textit{{{tex_escape(labels['noReferences'])}}}")
        out += macro("SFCode", f"SFS {safe_id(identity.get('sfsId'), 'SFS ID')}  /  SF {safe_id(identity.get('sfId'), 'SF ID')}  ·  {repo_id}")
        out += macro("SFTitle", clip(sf.get("meta", {}).get("title") or "Scoring factor", 100))
        out += macro("SFQuestion", clip(question.get("shortBinaryQuestion") or question.get("plain") or "Question text is missing.", 440))
        out += macro("SFTechnical", clip(question.get("technical-short"), 360) or labels["noTechnicalQuestion"])
        out += macro("SFScore", score_text)
        out += raw_macro("SFClarifications", clarification_text)
        out += macro("SFApproach", clip(sf.get("openSourceApproach"), 680) or labels["noCanonicalSolution"])
        out += raw_macro("SFReferences", r"\par\medskip ".join(ref_lines))
        out += macro("SFID", identity.get("sfId"))
        out += macro("SFSID", identity.get("sfsId"))
        out += macro("SFRepoID", repo_id)
        out += signer_macros(sf)
        if context:
            out += macro("ContextTitle", context.get("title"))
            out += macro("ContextBrief", clip(context.get("purpose"), 280))
            out += macro("ContextScope", clip(context.get("scope"), 320))
            out += macro("ContextEvidencePeriod", clip(context.get("evidencePeriod"), 180))
    else:
        set_items = entity.get("set", [])
        if not isinstance(set_items, list):
            set_items = []
        rows = []
        lang = args.language or "en"
        sf_dir = root / "repo-sf" / lang
        for index in range(16):
            digit = SFS_IDS[index]
            item = next((x for x in set_items if isinstance(x, dict) and str(x.get("id", "")).upper() == digit), {})
            repo_id = str(item.get("repoId") or f"{safe_id(args.sfs_id, 'SFS ID')}{digit}").upper()
            sf_path = sf_dir / f"{repo_id}.json"
            question = labels["missingFactorDetail"]
            score = item.get("score")
            if sf_path.is_file():
                data = read_json(sf_path)
                q = data.get("question") or {}
                question = q.get("shortBinaryQuestion") or q.get("plain") or question
                if score is None:
                    score = data.get("resultScore")
            rows.append((digit, repo_id, clip(question, 120)))
        out += macro("SFSCode", f"SFS {safe_id(args.sfs_id, 'SFS ID')}  ·  {language.upper()}")
        paired = []
        for row in range(8):
            left, right = rows[row], rows[row + 8]
            cell = lambda item: rf"\textbf{{{item[0]} / \texttt{{{tex_escape(item[1])}}}}} & {tex_escape(item[2])}"
            paired.append(cell(left) + " & " + cell(right) + r"\\[-0.3mm]")
        out += raw_macro("SFSFactors", "\n".join(paired))
    return out


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("kind", choices=("sf", "sfs"))
    parser.add_argument("json", type=Path, help="SF JSON file or SFS JSON file")
    parser.add_argument("--sfs", type=Path, help="SFS JSON for an SF page (auto-detected when possible)")
    parser.add_argument("--context-json", type=Path, help="Shortlist mask JSON to add its scope/evidence context to an SF sheet")
    parser.add_argument("--language", help="Language directory, e.g. en, el, fr")
    parser.add_argument("--commit", help="Full source catalog commit SHA to print (defaults to local HEAD)")
    parser.add_argument("--edition", help="Human-readable catalog release label")
    parser.add_argument("--detail-url", help="Preferred stable catalog or release URL for the QR code")
    parser.add_argument("--output", type=Path, help="Output PDF path (default: current directory)")
    parser.add_argument("--template", choices=TEMPLATE_NAMES, default="fullCatalog")
    parser.add_argument("--no-compile", action="store_true", help="Write the generated .tex without running LuaLaTeX")
    args = parser.parse_args()
    args.json = args.json.resolve()
    args.language = args.language or args.json.parent.name
    args.root = repository_root(args.json)
    if args.kind == "sfs":
        args.sfs_id = safe_id(args.json.stem, "SFS ID")
    return args


def main() -> None:
    args = parse_args()
    data = read_json(args.json)
    root = args.root
    source_paths = [args.json]
    if args.kind == "sf":
        identity = data.get("identity") or {}
        sfs_id = safe_id(identity.get("sfsId"), "SFS ID")
        sf_id = safe_id(identity.get("sfId"), "SF ID")
        inferred_sfs = args.sfs or root / "json" / args.language / f"{sfs_id}.json"
        sfs = read_json(inferred_sfs) if inferred_sfs.is_file() else None
        if sfs is not None:
            source_paths.append(inferred_sfs)
        context_path = args.context_json.resolve() if args.context_json and args.context_json.is_absolute() else \
            (root / args.context_json).resolve() if args.context_json else None
        context = read_json(context_path) if context_path else None
        if args.context_json:
            source_paths.append(context_path)
        template_file = ("sf-shortlist-page.tex" if context else "sf-page.tex")
        macros = base_macros(root, args, "SF", sfs or {}, source_paths,
                             sfs=sfs, sf=data, context=context)
        default_name = f"sf-{sfs_id}{sf_id}.pdf"
    else:
        template_file = "sfs-cover.tex"
        for item in data.get("set", []):
            repo_id = item.get("repoId") if isinstance(item, dict) else None
            sf_path = root / "repo-sf" / args.language / f"{repo_id}.json" if repo_id else None
            if sf_path and sf_path.is_file():
                source_paths.append(sf_path)
        macros = base_macros(root, args, "SFS", data, source_paths)
        default_name = f"sfs-{args.sfs_id}-cover.pdf"
    output = (args.output or Path.cwd() / default_name).resolve()
    tex_path = output.with_suffix(".tex")
    tex_path.parent.mkdir(parents=True, exist_ok=True)
    detail_url = record_url(data, args, root, args.json)
    qr_path = output.with_name(output.stem + "-qr.png")
    if detail_url:
        qrencode = shutil.which("qrencode")
        if not qrencode:
            raise SystemExit("A detail URL is available, but qrencode is missing. Install qrencode or use --detail-url later.")
        qr_run = subprocess.run([qrencode, "-o", str(qr_path), detail_url], text=True, capture_output=True)
        if qr_run.returncode:
            raise SystemExit(f"qrencode failed: {qr_run.stderr.strip()}")
        macros += macro("QRImage", qr_path.name)
    else:
        macros += raw_macro("QRImage", "")
    selected_template = template_dir(args.template)
    tex = selected_template / template_file
    common = selected_template / "common.tex"
    generated = macros + "\\input{" + str(common).replace("\\", "/") + "}\n"
    generated += "\\input{" + str(tex).replace("\\", "/") + "}\n"
    tex_path.write_text(generated, encoding="utf-8")
    if args.no_compile:
        print(f"Wrote {tex_path}")
        return
    engine = shutil.which("lualatex")
    if not engine:
        raise SystemExit("LuaLaTeX not found. Install TeX Live/MacTeX, or use --no-compile to emit the .tex file.")
    with tempfile.TemporaryDirectory(prefix="uniq2me-print-") as temp:
        work = Path(temp)
        local_tex = work / "record.tex"
        local_tex.write_text(generated, encoding="utf-8")
        if detail_url:
            shutil.copy2(qr_path, work / qr_path.name)
        env = os.environ.copy()
        env.setdefault("TEXMFCACHE", str(work / "tex-cache"))
        Path(env["TEXMFCACHE"]).mkdir(parents=True, exist_ok=True)
        run = subprocess.run(
            [engine, "-interaction=nonstopmode", "-halt-on-error", "-output-directory", str(work), str(local_tex)],
            cwd=work, env=env, text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
        )
        if run.returncode:
            print(run.stdout[-9000:], file=sys.stderr)
            raise SystemExit(f"LuaLaTeX failed; generated source remains at {tex_path}")
        shutil.copy2(work / "record.pdf", output)
    print(f"Wrote {output}")
    print(f"Wrote {tex_path}")


if __name__ == "__main__":
    main()
