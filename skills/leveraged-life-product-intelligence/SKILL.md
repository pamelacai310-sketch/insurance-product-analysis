---
name: leveraged-life-product-intelligence
description: Extract and audit leveraged whole-life product economics from official contracts, illustrations, cash-value tables, rate tables, or canonical JSON. Use for product-only death leverage, death/cash-value IRR or XIRR, breakeven, non-guaranteed dependency, protection-versus-liquidity, inflation-adjusted death benefit, fingerprints, and same-benchmark peer comparisons. Do not use for customer suitability, needs analysis, or advice based on age, income, assets, liabilities, family duties, health, or risk preferences.
---

# Leveraged Life Product Intelligence

Keep the model thin: extract ambiguous semantics only when needed; run all validation, cashflow reconstruction, metrics, fingerprints, and comparisons through the deterministic engine.

## Route the task

- For PDF or table extraction, read [references/parser-routing.md](references/parser-routing.md), then run `extract`.
- For canonical input or metric work, read [references/canonical-schema.md](references/canonical-schema.md) and [references/metric-definitions.md](references/metric-definitions.md).
- For peers or standard cases, also read [references/benchmark-cases.md](references/benchmark-cases.md).

```bash
python3 scripts/llpi.py validate --input product.json --strict-evidence
python3 scripts/llpi.py analyze --input product.json --output analysis.json
python3 scripts/llpi.py compare --inputs a.json b.json \
  --case-id LLPI-STD-1PAY-100K-v1 --output comparison.json
```

## Invariants

- Accept only `analysis_scope: product_only`; reject customer/profile fields and PII.
- Do not invent dates, units, guarantee status, benefit rules, premiums, inflation, or missing table values.
- Keep guaranteed and each illustrated scenario separate. Missing illustrated values are unknown, never zero.
- Require evidence and RFC 6901 provenance for critical source facts; derived metrics cite input pointers, not fabricated document pages.
- Use explicit year offsets for IRR and explicit dates with ACT/365F for XIRR.
- Treat LLM extraction as a disabled-by-default fallback for unresolved fields only. It must not calculate metrics.
- Refuse peer ranking when benchmark hashes or currencies differ. Do not create a composite winner score.
- Describe the protection-liquidity ratio as an orientation, not as universally better when higher.

If critical facts are invalid, conflicting, or unsupported, return the validation findings and stop the metric comparison instead of filling gaps.
