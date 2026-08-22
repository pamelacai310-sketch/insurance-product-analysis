# Confidence, provenance, and semantic review

V1 combines hard gates with an extraction score. A score never overrides missing units, customer data, a source/version conflict, or a disputed number.

## Acceptance gates

High-confidence acceptance requires native/exact-cell evidence, applicable source identity/version, explicit value/location, and no detected conflict or semantic ambiguity. A 0.70 to below-0.90 extraction needs deterministic review. Image-only pages need targeted OCR. A supported semantic pattern routes only its minimal text record to model review, and only after extraction confidence reaches 0.90.

Evidence labeled `verified` or `extracted` must carry confidence of at least 0.90. Evidence labeled `resolved` must remain in the medium band from 0.70 to below 0.90; an LLM resolution cannot claim high confidence. Numeric cells, IRR, PV, totals, rankings, and unit conversions are always deterministic.

## Field provenance

Canonical evidence records retain:

- unique evidence and source IDs;
- recomputed source SHA-256 and document version;
- page/bounding box or sheet/cell range;
- raw text/value plus its SHA-256;
- extractor/version, numeric confidence, and status;
- unit text and transformation when applicable.

Product metadata, dimensions, money events, rules, and options reference evidence IDs. A missing or forged evidence ID blocks validation.

## Metric provenance

Every metric record contains status, value, warnings, and:

- formula ID/version;
- configuration ID;
- dependent evidence IDs;
- assumption references;
- SHA-256 of its calculation configuration.

Every metric hash is additionally bound to the complete normalized configuration and dependent cash-flow timeline. `provenance.json` copies the source/evidence registry, creates an index from every metric path to this dependency record, and records an artifact chain for the input, optional benchmark, normalized product, cash flows, metrics, and report. `cashflows.json` holds the deterministic event timeline.

## Actual review queue

`inspect` writes items with a stable `id`, `route`, reason, source hash, safe location, and optional record/content hashes. Only `llm_semantic_resolution` may contain `snippet`; suspected personal values are redacted before queue creation.

The semantic patch matches `assets/schema/semantic-resolution.schema.json`:

```json
{
  "schema_version": "1.0.0",
  "resolutions": [
    {
      "task_id": "review-item-id",
      "target_path": "/configurations/0/death_benefit/rule",
      "value": {},
      "source_record_id": "extraction-record-id",
      "candidate_confidence": "medium",
      "rationale": "brief evidence-grounded explanation"
    }
  ]
}
```

`resolve` accepts only semantic task IDs, matching record IDs, medium confidence, allowlisted semantic targets, and numeric tokens already present in the snippet. It cannot edit sources, evidence, cashflows, metrics, or reports. The resulting raw product schema is validated again before use.

`run` never synthesizes an LLM task from an `unresolved` status. It emits `unresolved_input_block` and stops before normalization/calculation; the original typed inspection task remains the only authority for choosing the appropriate deterministic, OCR, manual, or semantic route.
