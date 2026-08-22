# Deterministic extraction routing

Use this reference for local PDF, XLSX, CSV, TSV, JSON, Markdown, and text inputs. The implemented v1 route is deliberately modest and fail-closed.

## Implemented route order

1. `inspect` fingerprints each file with path, size, media type, extension, and SHA-256.
2. CSV/TSV uses Python's CSV parser; JSON is flattened to scalar records with JSON Pointers; text/Markdown is retained by line.
3. XLSX uses optional `openpyxl` with formula text (`data_only=False`). It records sheet and cell; it does not execute formulas, macros, external links, or code.
4. PDF uses optional `pdfplumber` native words and tables first, preserving page and bounding box/table coordinates.
5. Local `pdftotext -layout` is a text fallback. It has no cell geometry and therefore receives lower confidence.
6. A page with no recovered text/cells routes to `targeted_ocr`. V1 does not invoke OCR itself and never OCRs a whole document silently.
7. Keyword classification locates annuity, premium, cash value, death, longevity, escalation, guarantee, and eligibility sections without embeddings.
8. Output is stable `manifest.json`, `extraction.json`, and `review_queue.json`.

`inspect` is evidence preparation, not automatic clause-to-product normalization. Build or repair the canonical product JSON only after its values, units, timing, guarantee basis, and applicable document version are established.

## Route meanings

- `direct_accept`: native/exact-cell record with score at least 0.90 and no detected ambiguity.
- `deterministic_second_pass`: score from 0.70 to below 0.90; verify with another local method or the visible source.
- `targeted_ocr`: image-only page; OCR only the identified page with a locally installed language pack.
- `deterministic_manual_verification`: numeric/parser conflict; a model must not choose the value.
- `manual_verification`: low-confidence non-semantic extraction.
- `llm_semantic_resolution`: high-confidence (at least 0.90) extracted text matches a supported semantic ambiguity pattern. Only this route may include a snippet; lower-confidence text must first use a deterministic or manual verification route.
- `reject_prohibited_customer_data`: stop and request a sanitized source.

## PDF and OCR safeguards

- Preserve raw token hashes, page, coordinates when available, and extractor/version.
- A blank, dash, missing decimal, `%`, sign, or unit marker never becomes zero.
- `pdftotext` recovery proves only text availability, not table-cell identity.
- Chinese scan OCR stays unresolved when `chi_sim`/`chi_tra` is unavailable.
- Numeric conflict, cross-page header propagation, rotated/complex tables, and OCR reconciliation require visible deterministic review in v1.

## Spreadsheet safeguards

- V1 supports `.xlsx`, not legacy `.xls`.
- It records populated cell values/formula text, but does not claim cached formula results, merged-header propagation, or hidden-row interpretation.
- Do not treat a formula string as a calculated number.
- Confirm whether a table basis is absolute, per 1,000 basic amount, per 1,000 annual premium, or per 1,000 total premium before normalization.

## Authority and identity

Current controlling terms govern definitions and contingencies; matching rate/cash-value tables govern their numeric schedules; illustrations govern only the scenario they explicitly illustrate. Marketing material cannot override a controlling source.

Each authoritative source requires a nonempty version. A local production artifact must exist and its SHA-256 is recomputed. Embedded sources are accepted only by the bundled `demo`/`self-test`. Do not merge mismatched editions merely because names are similar.
