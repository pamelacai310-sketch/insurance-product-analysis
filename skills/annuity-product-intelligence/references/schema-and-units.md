# Product schema, time, and units

The executable input contract is `assets/schema/product-input.schema.json`. V1 uses these top-level objects:

- `product`: unique ID, name, insurer, currency, jurisdiction, version/effective date, type, product-only flag, evidence refs;
- `sources`: local artifact identity, SHA-256, authority, and version;
- `evidence`: page/cell-level raw evidence and extraction provenance;
- `configurations`: published product dimensions plus premium events, annuity rules, cash values, optional death/maturity/loan terms;
- `analysis_assumptions`: standardized survival/death ages, hypothetical inflation rates, and benchmark selection rule.

Unknown properties are rejected. Configuration IDs are unique within a product; product IDs must also be unique in peer comparison.

Production sources may use `skill://` paths for small bundled artifacts; these resolve relative to the installed Skill root. A verified lightweight extract can additionally retain `original_url`, `original_sha256`, and `original_page_range`. The local extract hash remains independently verified. This does not permit a missing original document identity to be invented.

## Product dimensions, not customer inputs

`published_issue_age`, `rate_class`, premium term/mode, annuity start/frequency, guarantee option, and product option code identify a published table cell or product option. Enumerate the available grid; never map it to a person's data in this skill.

## Value states and guarantee basis

Input state is one of `available`, `missing`, `not_applicable`, or `unresolved`. A known amount of zero is `available` with value `0`.

Guarantee basis is exactly:

- `guaranteed`;
- `illustrated`;
- `non_guaranteed`.

Each illustrated scenario uses a distinct `scenario_id`. A non-guaranteed annuity or maturity schedule must declare `scenario_composition`: `total` is a complete replacement for guaranteed events of that type, and `incremental` is added to the guaranteed base. Do not mark a partial schedule `total`. Cash-value and death-benefit schedules must use `total` because their point-in-time values cannot be safely accumulated. The engine never promotes either form to guaranteed.

## Policy-month timing

- Issue is policy month 0.
- Every source event states an integer `policy_month` and `event_order`.
- Premium events are positive, available, guaranteed contractual owner outflows in the selected published configuration; annuity and maturity events become inflows.
- Annuity rules state first month, frequency, advance/arrears label, growth interval/rate, end condition, contingency, and contractual rounding. `annual_growth_rate` is an annual-effective rate; at each `growth_interval_months` boundary the engine applies `(1 + rate) ** (elapsed_months / 12)` to the base payment.
- A lifetime rule uses its sourced `contract_end_age` as the finite contractual expansion boundary. A non-lifetime rule declares exactly one of `last_payment_month` or `payment_count`. Optional `analysis_end_age` can shorten the reported metric grid, but never extend contractual cash flows.
- Cash values are state values added only to the appropriate surrender/survival-liquidation scenario.
- Same-time death uses sourced `before_annuity`, `after_annuity`, or `unresolved`; unresolved order blocks all calculation. Premium paid, prior receipts, and AST cumulative fields share the same death cutoff. Guarantee-period continuation contains only annuity events after that cutoff.
- Reference annual-premium schedules use event order 50 for renewal premiums: anniversary annuity and end-of-year cash value are therefore evaluated before the next policy year's premium at the same policy month.
- A rule that reads `cash_value` must declare `cash_value_timing`: `policy_month_state` uses the disclosed month snapshot independent of death order, while `respect_event_order` applies the same-month event cutoff. Never infer this timing from surrender-table row order.

Duration-only IRR uses `policy_month / 12` and annual-effective rates. V1 does not mix exact-calendar day-count cashflows into a policy-month calculation.

## Money normalization

Money is an object with decimal `value`, explicit `unit`, and optional basis. Supported absolute units for product currency `CNY` illustrate the pattern:

- `CNY`;
- `thousand_CNY`;
- `ten_thousand_CNY`;
- `million_CNY`.

Replace `CNY` with the product's own three-letter currency. Cross-currency units are rejected.

Supported relative units are:

- `<CCY>_per_1000_basic_amount`;
- `<CCY>_per_1000_annual_premium`;
- `<CCY>_per_1000_total_premium`;
- `percent_of_basic_amount`, `percent_of_annual_premium`, `percent_of_total_premium`;
- `decimal_of_basic_amount`, `decimal_of_annual_premium`, `decimal_of_total_premium`.

The matching `basis_kind` is mandatory. An explicit basis value must agree with the computed configuration context. Absolute units cannot carry a hidden per-1,000 denominator. V1 normalizes benefit amounts; it does not infer a basic sum assured from an ambiguous premium-rate direction.

Keep full Decimal precision unless the source specifies `cent` or `whole` event rounding. JSON outputs use decimal strings.

Loan terms can record availability start/end month, maximum term, eligible-value basis, disclosed or missing rate, rate basis/reset interval, repayment terms, benefit deduction, lapse trigger, and annuity effect. Loan proceeds and loan capacity are debt, not return cash flows.

## Proportional comparison

Different total premiums are normalized to 1,000,000 only when every compared configuration has provenance-backed `proportionality_verified: true`. Minimums, bands, caps, fixed fees, bonuses, or nonlinear rounding invalidate that flag. Otherwise comparison requires the same total premium.
