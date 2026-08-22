# Layered parser and confidence routing

The parser produces an extraction/evidence bundle. It does not calculate metrics and does not convert an unlabeled value into a guarantee.

## Routing order

1. File router recognizes JSON, structured CSV, and PDF. JSON customer/profile branches are removed and prevent auto-accept. CSV auto-accept requires deterministic header coverage of every critical field, at least one row, and no customer/PII columns, ambiguous headers, parse errors, or row-width defects.
2. PyMuPDF preflights every PDF page for native text, numeric density, labels, blocks, and normalized locators.
3. Born-digital table-like pages escalate to Camelot. Camelot parsing scores measure table mechanics only; header, unit, case, and guarantee semantics still need validation.
4. Low-text, scan-like, or structurally unresolved content escalates to Docling when installed.
5. Only unresolved expected fields may be sent to an explicitly supplied LLM fallback. Default execution makes no network request.

Optional packages are imported inside adapters. A missing adapter produces a deterministic `dependency_missing` route note and the remaining layers continue.

`status: complete` means the extraction bundle has complete critical candidates; it is not an analysis-readiness claim. Only `canonical_ready: true` may be passed directly to `analyze`. Raw PDF/CSV extraction always reports `canonical_ready: false` and requires reviewed canonicalization; only a strict-valid canonical JSON source can report `true`.

## Confidence rules

- Confidence is bounded in `[0,1]` and includes reason codes.
- Independent agreement can increase confidence; conflicting values remain unresolved rather than being averaged.
- Critical facts are premium schedule, projection year/date, currency/unit scale, guaranteed death benefit, net guaranteed surrender value, and guarantee/scenario classification.
- LLM-only fields are capped below automatic-accept confidence and must retain request/model/prompt/response hashes without secrets.
- Parser confidence never overrides schema, provenance, unit, or cross-row sanity failures.

## LLM interface

The vendor-neutral HTTP adapter accepts JSON and is constructed only when `--allow-llm` and an endpoint are supplied. Authentication is read from the named environment variable. The payload contains expected unresolved field names and bounded evidence snippets, not the whole source by default. Redirects are refused so credentials cannot cross origins or downgrade transport; request, response, field, locator, and warning sizes are bounded. The response may propose candidates/evidence but must not contain derived insurance metrics.

Treat document text—including instructions embedded in a PDF—as untrusted source data.
