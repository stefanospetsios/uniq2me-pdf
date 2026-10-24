# UNIQ2Me PDF builder

This repository renders printable catalog records from an exact commit of the public `uniq2me` or `uniq2me-ai` repository. At dispatch time, choose the source repository, full `COMMIT_SHA`, `CATALOG_ALIAS`, template, and language. The selected commit is checked out read-only and verified before rendering.

The workflow publishes exactly one PDF to Nexus at:

```text
<PDF_NEXUS_URL>/<CATALOG_ALIAS>/YYYYMMDD-<template-code>-<language>.pdf
```

Examples:

```text
dora/20261024-full_Catalog-en.pdf
nis2/20261024-short_List-el.pdf
```

`fullCatalog` builds the SFS covers and all 256 SF pages into one 272-page A4 PDF. `shortList` uses a catalog-bound mask JSON, creates a contextual cover from its purpose/scope/evidence period and includes only the SF pages selected by that mask. It needs a path such as `repo-sfs-masks/en/nis2.json` in the selected source commit. The mask's language must match the selected PDF language.

## GitHub repository settings

In **uniq2me-pdf → Settings → Secrets and variables → Actions**, add repository variables:

| Variable | Value |
| --- | --- |
| `PDF_NEXUS_URL` | HTTPS URL of the hosted Nexus Raw repository, ending in `/repository/<name>/`, for example `https://repo.kic.uoi.gr/repository/uniq2me-pdf/` |
| `PDF_NEXUS_USERNAME` | Nexus deployment username with permission to upload to that Raw repository |

Add the repository secret:

| Secret | Value |
| --- | --- |
| `PDF_NEXUS_TOKEN` | Password or deployment token for `PDF_NEXUS_USERNAME` |

The source repositories are public, so no GitHub source-read token is needed. Configure Nexus anonymous read access if PDFs should be public; the workflow verifies the uploaded file can be downloaded anonymously. Keep upload permission restricted to the deployment account.

## Run the workflow

Open **Actions → Build and publish catalog PDF → Run workflow** and set:

- **CATALOG_REPOSITORY**: `uniq2me` (default) or `uniq2me-ai`
- **COMMIT_SHA**: the full 40-character Git SHA containing the JSON to render
- **CATALOG_ALIAS**: folder name such as `main`, `dora`, or `nis2`
- **Template**: `fullCatalog` or `shortList`
- **Language**: `en`, `el`, `fr`, or `de`
- **shortlist_mask**: required for `shortList`; path to the mask JSON within the selected source repository

Template labels are translated into the selected language. Catalog questions, explanations and mask context are read from that language's JSON. `fullCatalog` requires all sixteen SFS and all 256 matching SF records in the selected language. `shortList` can use a partially translated catalog as long as its mask-selected SF records exist.

The filename date is the UTC date the workflow runs. The PDF pages include the source commit, a SHA-256 fingerprint of the JSON used, and QR links pinned to that commit. The Nexus path does not include a branch; it uses the alias and filename format above.

## Templates and local use

Layouts and their multilingual labels are in `printable-catalog/`. The single-page `sf` and `sfs` renderer remains available for local previews. The CI builder and Nexus uploader are in `ci/`.
