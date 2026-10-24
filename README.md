# UNIQ2Me PDF builder

The manual workflow renders a PDF from an exact commit of the public `uniq2me` or `uniq2me-ai` repository. It publishes one file to the configured Nexus Raw repository at:

```text
<PDF_NEXUS_URL>/<CATALOG_ALIAS>/YYYYMMDD-<template-code>-<language>.pdf
```

Examples: `dora/20261024-full_Catalog-en.pdf` and `nis2/20261024-nis2_Full-el.pdf`.

## Workflow inputs

- `CATALOG_REPOSITORY`: `uniq2me` or `uniq2me-ai`
- `COMMIT_SHA`: full commit SHA to render
- `CATALOG_ALIAS`: output folder name such as `main`, `dora`, or `nis2`
- `Template`: `fullCatalog`, `shortList`, `doraShort`, or `nis2Full`
- `Language`: `en`, `el`, `fr`, or `de`
- `shortlist_mask`: required by `shortList` and `doraShort`; path to a mask JSON inside the selected source commit

`fullCatalog` and `nis2Full` render all 16 SFS covers and 256 SF pages (272 A4 pages). `shortList` and `doraShort` render a context cover and the SF pages selected by the mask. The mask language must match the requested PDF language. The chosen source commit must contain the JSON records needed for that language.

## Template layout

Each template folder contains only its LaTeX files and translated labels:

```text
fullCatalog/
shortList/
doraShort/
nis2Full/
```

Generation and publication scripts live in `.github/scripts/`; the workflow is `.github/workflows/build-and-publish.yml`.

## Nexus configuration

In **uniq2me-pdf → Settings → Secrets and variables → Actions**, set repository variables `PDF_NEXUS_URL` (HTTPS Raw repository URL ending in `/repository/<name>/`) and `PDF_NEXUS_USERNAME`, and secret `PDF_NEXUS_TOKEN`. Anonymous Nexus read access must be enabled for public downloads; after upload the workflow downloads the PDF without credentials and verifies its SHA-256.

The source repositories are public, so no source-read token is required. The PDF workflow does not push to either source repository.

## Provenance in the PDF

Pages include the catalog commit and JSON fingerprint. QR links point to records pinned to that commit where the source catalog exposes a resolvable URL. The filename date is the UTC date of the workflow run.
