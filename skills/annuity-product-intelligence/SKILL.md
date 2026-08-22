---
name: annuity-product-intelligence
description: Analyze annuity product terms, rate tables, cash-value schedules, illustrations, or normalized product data without customer data. Use for auditable product cash flows, IRR curves, liquidity, longevity, early-death, inflation, capital-efficiency, provenance, or compatible peer comparisons; do not use for customer suitability or personalized recommendations.
metadata:
  short-description: Auditable annuity product economics without customer data
  version: "1.0.0"
---

# Annuity Product Intelligence

Evaluate the product, not a customer. Keep the workflow offline and deterministic except for a schema-constrained semantic exception.

## Scope gate

- Accept public product materials and published dimensions such as issue-age options, rate class, premium term, annuity start option, payment frequency, and guarantee option.
- Never request or use a customer's age, identity, assets, income, expenses, goals, risk tolerance, family or health data, expected lifespan, or estate objectives. If supplied material contains them, stop before analysis and ask for a redacted product-only copy. Read [no-customer-data.md](references/no-customer-data.md) when scope is unclear.
- Keep guaranteed, illustrated, and other non-guaranteed cash flows separate. Missing, zero, unavailable, unresolved, and not applicable are different states.
- Do not produce suitability advice, a subjective composite score, or an overall winner across incompatible configurations.

## Workflow

1. Inspect source files without sending them to an LLM:

```bash
python3 scripts/annuity_product_intelligence.py inspect INPUT... --out WORKDIR
```

Read [extraction-routing.md](references/extraction-routing.md) when PDFs, OCR, spreadsheets, parser disagreement, or extraction confidence matters. Preserve the generated hashes, page/bounding-box or sheet/cell locations, raw-value hashes, extractor versions, and review routes.

2. Resolve the review queue by route:

- `direct_accept`: no model review.
- `deterministic_second_pass`, `targeted_ocr`, `manual_verification`, or `deterministic_manual_verification`: use the named local route; never ask an LLM to choose a disputed number.
- `reject_prohibited_customer_data`: stop and request redaction.
- `llm_semantic_resolution`: read only that item's minimal snippet and [semantic-rule-grammar.md](references/semantic-rule-grammar.md). Return a patch matching `assets/schema/semantic-resolution.schema.json`, then run `resolve`. The patch may map evidence to enums or the safe AST, but cannot invent numbers or edit raw evidence or computed metrics. A model resolution can reach only medium confidence.

3. Build the product-only JSON using `assets/schema/product-input.schema.json`. Map ordinary fields only from deterministic extraction records or explicit manual verification; do not have an LLM transcribe tables or fill routine fields. Enumerate the full published configuration grid rather than asking for a customer's configuration. Read [schema-and-units.md](references/schema-and-units.md) for policy-month timing, typed units, per-1,000 bases, source versions, and guarantee classification.

   For the bundled DAO, PIA, and Allianz examples, use `assets/reference-products/products/`. Their product-only source extracts preserve original PDF hashes and pages; regenerate them deterministically with `scripts/build_reference_annuity_products.py`.

4. Validate before calculating:

```bash
python3 scripts/annuity_product_intelligence.py validate --input product.json
python3 scripts/annuity_product_intelligence.py run \
  --input product.json --out results \
  --benchmark benchmark.json
```

The benchmark is optional, immutable input matching `assets/schema/benchmark.schema.json`; never silently fetch current rates. Omit it when unavailable and leave relative-value metrics missing.

Any remaining `unresolved` input blocks normalization and calculation. Return to the original inspection task; do not relabel low-confidence evidence to bypass the router.

5. For peer comparison, use only common compatible product dimensions:

```bash
python3 scripts/annuity_product_intelligence.py compare \
  --input product-a.json product-b.json --out comparison
```

Normalize monetary values to total premium 1,000,000 only when every product explicitly proves proportionality. Otherwise require identical total premiums. Rank metrics independently with their correct direction.

## Calculation rules

The script alone calculates schedules, unit conversions, IRR roots, present values, totals, inflation deflation, death scenarios, and rankings. Never reproduce these calculations in prose or with an LLM. Read [metric-definitions.md](references/metric-definitions.md) when interpreting formulas, cash-flow boundaries, multiple IRR roots, longevity, early-death, inflation, capital efficiency, or relative value. Read [confidence-and-provenance.md](references/confidence-and-provenance.md) for audit and resolution status.

Use explicit policy months and same-time event order. Report every distinct IRR root within the declared rate domain; select a headline IRR only when the root is unique. Label death-outcome IRR as conditional, policy loans as debt, survival-path PV as conditional without mortality weighting, and hypothetical inflation as a scenario rather than a forecast.

Read the complete annual table before summarizing a product. Report cash-value recovery year and locked-capital years separately; use the age IRR curve rather than one terminal IRR; keep 10-year longevity leverage, standard early-death outcomes, and 0%/2%/3%/4% inflation rows visible. Do not merge cash value, prior annuity receipts, death settlement, guarantee-period continuation, or maturity benefits into an unlabeled total.

## Required outputs

After all gates clear, `run` writes stable `validation.json`, `product.normalized.json`, `cashflows.json`, `metrics.json`, `provenance.json`, `review_queue.json`, and `report.md`. `provenance.json` binds input, normalized data, cash flows, metrics, and report hashes. Cite the source page/cell and evidence ID for conclusions. State that the output is product-only analytical review, not insurance, legal, tax, investment, or customer-suitability advice.

Read `report.md` first. Query only the requested JSON paths for supporting values or provenance; do not load complete `metrics.json` or `provenance.json` into model context.

For installation, CLI examples, optional parser dependencies, and the synthetic demo, read [README.md](README.md).
