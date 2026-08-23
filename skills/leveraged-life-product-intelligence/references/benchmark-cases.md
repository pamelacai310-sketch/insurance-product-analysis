# Standard benchmark cases v1.0.0

Benchmarks are impersonal cashflow coordinates. They do not represent a customer and contain no age, sex, income, assets, liabilities, health, family, or preference data.

## Shipped cases

| Case ID | Premium schedule | Purpose |
|---|---|---|
| `LLPI-STD-1PAY-100K-v1` | CNY 100,000 at `t=0` | Analytical single-pay IRR, liquidity trade-off, peer comparison |
| `LLPI-STD-3PAY-100K-v1` | CNY 100,000 at `t=0,1,2` | Cumulative-premium leverage curve and participating-scenario dependency |
| `LLPI-STD-10PAY-100K-v1` | CNY 100,000 at `t=0..9` | Full annual WWA/WWB/Allianz same-premium reference comparison |

Synthetic inputs live in `assets/benchmarks/`; expected metrics live in the repository's `tests/gold/leveraged_life/`. Audited real-product inputs for the ten-pay experiment live in `assets/reference-products/`; they retain official document hashes and source URLs but still represent a standardized product experiment, not a quotation or insurer promise for a specific person.

The engine registry locks each standard ID to its version, CNY currency, issue date, `currency_unit` scale, inflation assumption, and exact premium schedule. Changing any of those coordinates while retaining the standard ID is a validation error. Custom or rescaled experiments must use `basis.kind: document_illustration` and a distinct case ID.

## Peer comparability

The comparator hashes case ID/version, currency, timing, inflation assumption, and the full premium schedule. It also requires identical named-scenario definitions and verified critical evidence. It returns `comparable: false` rather than ranking when any of those gates fail.

For comparable cases it reports mechanical per-metric ranks for guaranteed leverage, conditional-death periodic IRR and ACT/365F XIRR, cash-value/premium recovery, real death benefit, breakeven, IRR threshold years, and non-guaranteed dependency. `DeathBenefit/CV` remains unranked orientation data. Rankings are local to a disclosed year, metric, guarantee basis, and named scenario; there is no composite score or overall winner in v1.

To compare real products, obtain product schedules on the same external pricing basis and preserve that basis as a source digest. Do not use `case_id` to conceal materially different quotation conditions.
