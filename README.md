# UNIQ2Me PDF builder

This repository owns the printable SF and SFS layouts and builds paper records from a selected catalog commit. It creates one A4 cover for each SFS, one A4 page for each of the 256 SFs, a 272-page PDF per complete language, and a ZIP containing the 272 individual PDFs. The source catalog is read only. Generated files are uploaded to a public Nexus Raw repository under a path containing the source repository, ref, and full commit SHA.

## Run the workflow

Open **Actions → Build and publish catalog PDFs → Run workflow**. Enter a source ref such as `dora`, `en/qwen3`, or a full commit SHA. Set language to `all` to build every complete locale or enter one locale code such as `en`. Incomplete locales are reported and skipped when `all` is selected; explicitly selecting an incomplete locale fails with the missing-file detail.

The workflow is manual by design. It checks out the selected catalog revision, renders the PDFs, combines and validates the pages, uploads the PDF, ZIP, and manifest to Nexus, then verifies that each uploaded file can be read anonymously.

## GitHub repository settings

In **Settings → Secrets and variables → Actions**, add these repository variables:

| Variable | Value |
| --- | --- |
| `PDF_CATALOG_REPOSITORY` | `stefanospetsios/uniq2me-ai` |
| `PDF_NEXUS_URL` | The HTTPS URL of the new hosted Raw repository, ending in `/repository/<name>/`, for example `https://repo.kic.uoi.gr/repository/uniq2me-pdf/` |

Add these repository secrets:

| Secret | Value |
| --- | --- |
| `PDF_NEXUS_USERNAME` | Nexus account with permission to add assets to the hosted Raw repository |
| `PDF_NEXUS_TOKEN` | That account's Nexus password or deployment token |
| `PDF_CATALOG_READ_TOKEN` | Optional fine-grained GitHub token with **Contents: read** on the catalog repository; leave unset while the source catalog is public |

Configure the Nexus repository for anonymous read access if the PDFs should be publicly available. Keep write access restricted to the Nexus deployment account. The token is only used by the upload step and is never included in the PDF or manifest.

Assets are stored below:

```text
<owner>/<repository>/<ref-slug>/<full-commit>/catalog/<language>/catalog-<language>.pdf
<owner>/<repository>/<ref-slug>/<full-commit>/catalog/<language>/individual-pages-<language>.zip
<owner>/<repository>/<ref-slug>/<full-commit>/catalog/manifest.json
```

For example, the DORA English PDF will be available at a path like:
`stefanospetsios/uniq2me-ai/dora/<full-sha>/catalog/en/catalog-en.pdf` beneath the configured Nexus URL.

## Local rendering

Install Python 3, LuaLaTeX with the TeX Gyre fonts and `tcolorbox`, `qrencode`, and the Python packages in `requirements.txt`. Then render a single sheet from a catalog checkout:

```sh
python3 printable-catalog/render.py sf catalog/repo-sf/en/0000.json \
  --sfs catalog/json/en/0.json --commit FULL_SOURCE_COMMIT_SHA \
  --edition 'en/dora' --output output/sf-0000.pdf

python3 printable-catalog/render.py sfs catalog/json/en/0.json \
  --commit FULL_SOURCE_COMMIT_SHA --edition 'en/dora' \
  --output output/sfs-0-cover.pdf
```

To build a complete locale locally, use the same builder as CI:

```sh
python3 -m pip install -r requirements.txt
python3 ci/build_catalog.py catalog --output dist \
  --repository stefanospetsios/uniq2me-ai --ref dora \
  --commit FULL_SOURCE_COMMIT_SHA --language en
```

Layouts and their JSON mapping are in `printable-catalog/`. The SHA-256 input fingerprint and pinned catalog link are printed on each page. Signature fields remain blank unless the source JSON explicitly records a vote or marked state; the form does not itself prove a signature or compliance decision.
