# Three-product annuity reference set

This directory contains product-only, deterministic inputs for one comparable premium scale:

| Product | Published slice | Cash-value coverage | Guaranteed income | Death and loan fields |
|---|---|---:|---|---|
| DAO 汇丰精彩丰年2026 | Female 40, 5-pay, CNY 200,000/year | Policy years 1-65 | Years 5-64 plus maturity | Complete AST and loan terms |
| PIA 汇丰精彩延年2026 | Female 40, 5-pay, age-60 start | Policy years 1-65 | Age 60 to maturity, 20-year certain | Three-stage AST, continuation, loan cutoff |
| 安联安享丰赢C | Female 40, 5-pay, age-60 start | Policy years 1-66 | Lifetime, expanded through age 106 | Complete AST and loan terms |

All three use total scheduled premium CNY 1,000,000. Guaranteed base benefits are modeled separately; participating dividends are excluded because they are non-guaranteed and no common illustrated scenario was supplied.

`source-extracts/` preserves selected rows, original PDF hashes, pages, and public URLs where known. It does not contain the original PDFs. `products/` is valid production input for the Skill, not an embedded synthetic fixture.

Regenerate and validate from the Skill root:

```bash
python3 scripts/build_reference_annuity_products.py
python3 scripts/annuity_product_intelligence.py validate \
  --input assets/reference-products/products/dao-hsbc-jingcai-fengnian-2026.json
```

The PIA year-20 source table value is retained immediately before the first annuity; the final year-20 contract state is zero after the first annuity. DAO similarly retains the year-65 pre-maturity table value while the final post-maturity cash-value state is not applicable. These paired states prevent double counting.
