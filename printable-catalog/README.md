# Printable catalog records

This folder contains an A4 LaTeX layout and a small Python renderer for a single scoring-factor (SF) record and a scoring-factor-set (SFS) cover. The same files are kept in `uniq2me` and `uniq2me-ai` so either catalog can be used as the input.

## Requirements

- Python 3.10 or newer
- LuaLaTeX (TeX Live or MacTeX), with the `fontspec`, `tcolorbox`, `hyperref`, and `amssymb` packages
- `qrencode` when the input JSON contains a detail URL

## Render one SF page

From the repository root:

```sh
python3 printable-catalog/render.py sf repo-sf/en/0000.json \
  --sfs json/en/0.json \
  --commit FULL_SOURCE_COMMIT_SHA \
  --edition 'en/qwen3' \
  --output printable-output/sf-0000.pdf
```

If `--sfs` is omitted, the renderer looks for the matching `json/<language>/<SFS ID>.json`. The final score comes from the SF `resultScore`, then from its SFS `set[]` entry. A null score is printed as `NOT SCORED`. Each of the three signer panels has a 0/1 choice, a name field, signature line, date, and a separate `MARKED` checkbox. Existing votes and marked states are checked only when the JSON explicitly contains them.

## Render an SFS cover

```sh
python3 printable-catalog/render.py sfs json/en/0.json \
  --commit FULL_SOURCE_COMMIT_SHA \
  --edition 'en/qwen3' \
  --output printable-output/sfs-0-cover.pdf
```

The cover lists the 16 SF positions and includes each factor's question when the corresponding file exists under `repo-sf/<language>/`. Otherwise it clearly identifies the missing factor text.

## Record identity and links

The printed record includes the supplied source commit and a SHA-256 fingerprint of the JSON inputs used for the page. For a cover, that fingerprint includes its SFS JSON and available SF JSON files. The QR code and clickable label prefer `--detail-url`, then a stable glacier link, then the GitHub URL pinned to the supplied commit. A mutable catalog link in the JSON is used only when no pinned link can be formed. Pass the full commit that contains the JSON; the renderer records identity metadata but does not create a digital signature or attest that a human signed the page.

Generated `.tex` and QR image sidecars are saved beside the PDF for review and reproducibility. Use `--no-compile` to emit the `.tex` source without running LuaLaTeX.
