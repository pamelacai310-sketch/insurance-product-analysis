# annuity-product-intelligence v1.0.0

`annuity-product-intelligence` is an offline-first Agent Skill and command-line tool for auditable annuity product economics. It inspects product documents and analyzes the published configuration grid supplied in the closed product schema; the workflow requires the agent to enumerate the available grid and never asks for a customer profile or makes suitability recommendations.

The core engine uses Python's standard library. `pdfplumber` and `openpyxl` are optional deterministic parsers for PDFs and XLSX files. No OpenAI API key or network call is required.

## What it produces

For every published configuration, the engine generates an explicit policy-month cash-flow timeline and computes:

- cash-value-only, total-exit, income-only, survival-liquidation, real, and conditional death-outcome IRR curves;
- a complete policy-year decision table aligning cumulative premium, guaranteed annuity, maturity, cash value, CV IRR, death settlement, death wealth multiple, and loan capacity;
- every distinct IRR root in the documented rate domain, including tangent, close-root, multiple-root, and no-root states;
- cash-value ratio, liquidity penalty, surrender loss, lock ratio, recovery year, locked-capital years, and separately stated loan capacity;
- cumulative annuity, payout multiple, income conversion, 10-year longevity leverage, longevity break-even behavior, and guarantee-period continuation;
- early-death settlement, beneficiary continuation, nominal recovery, estate outcome, and shortfall;
- real purchasing power and income-retention ratios at 0%, 2%, 3%, and 4% hypothetical inflation by default;
- capital efficiency and conditional survival-path PV/NPV against an immutable benchmark snapshot;
- compatible common-configuration peer comparisons, with no opaque aggregate score;
- field-level evidence and metric-level formula provenance.

Guaranteed and illustrated/non-guaranteed benefits never share one label. Every non-guaranteed annuity or maturity schedule explicitly declares `scenario_composition`: `total` supplies a complete replacement schedule for that event type, while `incremental` adds only the disclosed increment to the guaranteed base. Cash-value and death-benefit schedules must be `total`; the engine never guesses whether an unlabeled value is total or incremental.

## Architecture

```text
local PDF / XLSX / CSV / JSON / text
        ↓ SHA-256 + native extraction
page/cell evidence + section locator
        ↓ confidence router
accept / second parser / targeted OCR / semantic review packet / block
        ↓ closed product schema + typed units
explicit policy-month cash-flow engine
        ↓ deterministic metrics
JSON audit artifacts + Markdown report
```

The LLM exception path is deliberately narrow: it sees only a minimal ambiguous clause snippet, returns a schema-constrained enum or safe AST patch, and cannot set unanchored numeric values. The deterministic validator must accept the patch before calculation resumes.

## Install

Copy the complete `annuity-product-intelligence` directory into a supported Skills directory. Do not copy only `SKILL.md`.

The calculation core needs Python 3.9 or later and no third-party packages. For PDF/XLSX inspection:

```bash
python3 -m pip install -r requirements-optional.txt
```

`pdftotext` is used as a local PDF fallback when available. Scanned pages route to targeted OCR; the tool never OCRs an entire document silently. Install the correct local Tesseract language pack before OCR. In particular, Chinese scans must remain unresolved if `chi_sim` or `chi_tra` is absent.

## One-command synthetic demo

```bash
python3 scripts/annuity_product_intelligence.py demo --out demo-results
```

This intentionally uses only the bundled synthetic fixture and writes:

```text
validation.json
product.normalized.json
cashflows.json
metrics.json
provenance.json
review_queue.json
report.md
```

The fixture is accepted only by `demo` and `self-test`; production commands cannot bypass source-file verification with a fixture flag.

## Analyze source materials

First fingerprint and extract local files:

```bash
python3 scripts/annuity_product_intelligence.py inspect \
  terms.pdf rate-table.xlsx cash-values.csv \
  --out work/product-a
```

Exit status `0` means deterministic inspection completed without a review item. Status `2` means a page/cell or semantic review remains. Status `3` means probable customer data was detected; the whole affected source is quarantined from extraction output and must be replaced with a product-only copy.

`review_queue.json` controls the next action. Only `llm_semantic_resolution` contains a snippet suitable for a model. Numeric conflicts, manual verification, and OCR needs are never silently sent to an LLM. A product JSON that still contains any `unresolved` state produces `validation.json` plus an `unresolved_input_block` queue and exits before cash flows or metrics are written.

Create a product JSON conforming to [`assets/schema/product-input.schema.json`](assets/schema/product-input.schema.json), then run:

```bash
python3 scripts/annuity_product_intelligence.py validate --input product.json

python3 scripts/annuity_product_intelligence.py run \
  --input product.json \
  --out results/product-a
```

Add an immutable, same-currency benchmark snapshot only when available:

```bash
python3 scripts/annuity_product_intelligence.py run \
  --input product.json \
  --benchmark benchmark.json \
  --out results/product-a
```

The benchmark must state its as-of date, annual-effective compounding, day count, source SHA-256, currency, and disclosed tenor points. The engine selects the nearest disclosed tenor and reports that choice; it does not hide interpolation assumptions.

## Bundled three-product reference data

The package includes product-only inputs for a common published-table slice: female age 40, five annual premiums of CNY 200,000, total premium CNY 1,000,000. They contain every disclosed annual cash-value point plus the complete guaranteed annuity, death-benefit AST, maturity, and policy-loan fields for DAO, PIA, and Allianz Anxiang Fengying C.

```bash
python3 scripts/build_reference_annuity_products.py

python3 scripts/annuity_product_intelligence.py run \
  --input assets/reference-products/products/pia-hsbc-jingcai-yannian-2026.json \
  --out results/pia
```

The lightweight source extracts retain each original PDF URL when known, the original PDF SHA-256, source page range, selected row, and transformation. Original PDFs are intentionally excluded from the Skill package. `skill://` source paths resolve relative to the installed Skill directory, so the examples remain portable across devices.

## Resolve a semantic exception

Prepare a patch conforming to [`assets/schema/semantic-resolution.schema.json`](assets/schema/semantic-resolution.schema.json):

```bash
python3 scripts/annuity_product_intelligence.py resolve \
  --input product.draft.json \
  --review-queue work/product-a/review_queue.json \
  --patch semantic-resolution.json \
  --output product.resolved.json
```

The resolver rejects:

- tasks not routed to semantic resolution;
- edits outside the semantic allowlist;
- high-confidence model claims;
- mismatched source record IDs;
- numeric tokens not present in the supplied evidence snippet;
- direct edits to evidence, sources, cashflows, metrics, or reports.

## Compare products

```bash
python3 scripts/annuity_product_intelligence.py compare \
  --input product-a.json product-b.json \
  --benchmark benchmark.json \
  --out results/comparison
```

Only matching jurisdiction, currency, issue-age option, product option code, rate class, proportional premium timing/term, annuity start/frequency, guarantee option, and scenario assumptions enter the same slice. Different total premiums require a provenance-backed `proportionality_verified: true` for every product; otherwise that slice is reported but not ranked. Non-common published slices remain visible with the missing products named.

## Product-only data boundary

Allowed product dimensions include published issue ages and rate classes. Prohibited data includes a customer's identity, actual age/DOB, assets, income, expenses, retirement goals, risk tolerance, family or health data, expected lifespan, inheritance goals, and personalized suitability fields.

The input schema is closed (`additionalProperties: false`), and the validator rejects prohibited keys and recognizable customer-data values recursively before calculation. If inspection detects probable customer data anywhere in a source, it writes no extracted records from that source, redacts its path/name in artifacts, and never places its values in model review packets.

## Timing and units

- Policy issue is month `0`; every event has an integer policy month and explicit same-time order.
- The reference inputs close each policy year after anniversary benefits and before the next renewal premium; this prevents an end-of-year cash value from silently counting the next year's premium.
- Money is normalized from decimal strings, not binary-float source values.
- Per-1,000 or percent units require an explicit basis: basic amount, annual premium, or total premium.
- Absolute currency units cannot masquerade as per-1,000 values.
- Currency conversion is prohibited without a separately versioned FX design (not included in v1.0.0).
- No surrender right is `not_applicable`; a known zero surrender value is `available` with amount `0`; missing is neither.

See `references/` for the complete operational definitions.

## Tests

```bash
python3 scripts/annuity_product_intelligence.py self-test
python3 -m unittest discover -s tests -v
```

The suite covers native PDF text and image-only page routing, CSV/XLSX extraction, customer-data blocking, local source hashes, typed units, long-horizon and multiple-root IRR, cash-flow timing, guarantee continuation, missing-state propagation, inflation, early death, benchmark mismatch, compatible comparison, and constrained semantic patches.

Use the bundled validator from the installed `skill-creator` package when available. The package also includes `agents/openai.yaml` for UI metadata.

## Exit statuses

| Code | Meaning |
|---:|---|
| 0 | Complete |
| 2 | Targeted review or semantic resolution required |
| 3 | Prohibited/customer data detected |
| 4 | Invalid schema, source, unit, or version conflict |
| 5 | Calculation or unexpected runtime failure |

## Limits

- Mortality-weighted EPV is unavailable unless a named, dated mortality table is added in a future schema version. The engine never treats a standard table as a customer's expected lifespan.
- Taxes, fees, FX, policyholder behavior, and insurer balance-sheet risk are excluded unless explicitly modeled in a future version.
- Market benchmarks are inputs, not automatically fetched data.
- OCR and difficult table reconstruction remain page-scoped exception routes; v1 queues OCR but does not invoke it or verify language packs itself.
- Output supports product review and reconciliation; it is not insurance, legal, tax, investment, or suitability advice.
