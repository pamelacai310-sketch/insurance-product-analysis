# Canonical product schema

Machine schema: [`canonical-product-1.0.0.schema.json`](canonical-product-1.0.0.schema.json).

## Topology

```text
canonical product
├── schema_version = 1.0.0
├── analysis_scope = product_only
├── product               identity, currency, type only
├── sources[]             versioned source documents + SHA-256
├── evidence[]            page/bbox/raw text/extractor/confidence
├── cases[]
│   ├── basis             benchmark kind + version
│   ├── timing            explicit date conventions
│   ├── amount_scale      currency_unit after evidenced normalization
│   ├── inflation_rate    optional explicit benchmark assumption
│   ├── premium_cashflows[]
│   ├── scenario_definitions{}
│   └── projection[]      guaranteed + named illustrated scenarios
└── provenance{}          RFC 6901 pointer → evidence IDs
```

Money is a non-negative decimal string and `amount_scale` must be `currency_unit`. Source tables expressed per thousand, 千元, or 万元 must be normalized before canonicalization while their raw unit and scale remain in evidence/provenance. `time_years` is an explicit decimal offset; dates are ISO 8601. This permits periodic IRR and calendar XIRR to be calculated independently without synthesizing dates.

`death_benefit.guaranteed` and `cash_surrender_value.guaranteed` are source facts. Each illustrated total belongs under a named `scenarios` key. Never place a dividend, account value, fund value, or bonus balance into `cash_surrender_value` unless the source explicitly identifies it as net surrender value.

## Provenance

Provenance keys are RFC 6901 JSON pointers. A table-level record may point to `/cases/0/projection`; a field-level record may point to `/cases/0/projection/4/death_benefit/guaranteed`. Currency, benchmark/timing/scale assumptions, inflation, premiums, projection coordinates, and every guaranteed or illustrated benefit used by the engine are critical fields. Each must resolve to accepted evidence with effective confidence of at least 0.85. A provenance record cannot claim confidence above its strongest referenced evidence, and LLM-only evidence is capped below auto-accept.

Evidence IDs and content hashes should be deterministic. Each record carries:

- source/document SHA-256;
- 1-based page and normalized bbox when applicable;
- bounded raw text or table cell;
- extractor name/version;
- confidence and reason codes.

Derived metrics never reuse a document page as if the metric appeared there. They instead list the canonical input pointers used by the algorithm.

## Excluded data

The v1 core schema is closed. Root `extensions`, when present, is reserved and must be an empty object; new fields require a schema-version change. The validator also rejects customer/profile semantics at any depth, including age, sex, income, assets, liabilities, family responsibilities, health, occupation, and risk preferences. Standard cases are impersonal premium/timing coordinates and never solicit PII or suitability inputs.
