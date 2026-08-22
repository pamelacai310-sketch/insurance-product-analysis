# Metric definitions

All metrics are deterministic per product configuration and labeled scenario. Premiums are owner outflows; benefits are inflows. Guaranteed and illustrated/non-guaranteed results remain separate.

## IRR

For policy-month cashflows `(m_i, C_i)`, annual-effective IRR satisfies:

```text
sum(C_i * (1 + r) ** (-m_i / 12)) = 0, r > -1
```

The solver first aggregates same-month flows and converts integer policy months to a sparse polynomial in the positive monthly discount factor. Over the explicit annual-rate domain `r=-0.999999` through `r=1,000,000`, recursive derivative isolation partitions monotone intervals, Decimal bisection finds sign-changing roots, and a strict normalized residual admits tangent/even-multiplicity roots without confusing a nearby nonzero stationary point for a root. Distinct close roots remain separate. Output status is `unique_root`, `multiple_roots`, `no_root`, or `insufficient_cashflows`. Algebraic multiplicity does not create multiple economic rates; only a single distinct rate receives `selected_rate`.

Implemented curves:

- `cash_value_only_irr`: premiums through the cash-value boundary plus terminal cash value; excludes prior benefits by definition;
- `total_exit_irr`: premiums and prior contractual receipts plus terminal cash value;
- `income_only_irr`: premiums and benefits through survival horizon, with no terminal value;
- `survival_liquidation_irr`: income-only set plus an exactly available residual cash value;
- `conditional_death_outcome_irr`: actual prior receipts, death settlement, and future guarantee-period continuation at their event dates;
- `real_income_only_irr`: event amounts deflated by the stated hypothetical inflation scenario.

Do not present a multiple-root result as one rate. Death IRR is a conditional contract outcome, not an investment-return promise.

## Liquidity

With cumulative premium `P_t`, cash value `SV_t`, and prior receipts `R_t`:

```text
cash_value_ratio = SV_t / P_t
liquidity_gap = P_t - SV_t
surrender_loss = max(P_t - SV_t, 0)
lock_ratio = surrender_loss / P_t
capital_returned_ratio = (R_t + SV_t) / P_t
```

Cash-value recovery is the first disclosed point where `SV_t >= P_t`. Total-benefit recovery is the first disclosed point where `R_t + SV_t >= P_t`. V1 does not interpolate missing cash-value months. Loan capacity is `limit_ratio × cash value`, reported separately as debt and never included in return cashflows.

`capital_recovery_year` is the policy year of the first final annual state where cash value reaches cumulative premium. `locked_capital_years` counts disclosed policy-year endpoints whose final cash-value state remains below cumulative premium. If recovery never occurs, the count is explicitly bounded by the last disclosed annual point. `liquidity_penalty = 1 - cash_value_ratio`; unlike the non-negative `lock_ratio`, it may be negative after cash value exceeds premium.

The annual decision table uses a policy-year closing boundary after anniversary annuity/maturity events and before a renewal premium due for the next policy year. It reports every year through the maximum disclosed cash-flow or cash-value month. A first-annuity or maturity boundary may retain both the source table's immediately-before state and the contract's after-event state; the final annual row uses the latter and never double-counts cash value with maturity.

## Longevity and capital efficiency

At each standardized survival age:

- cumulative annuity;
- payout multiple = cumulative annuity / total scheduled nominal premium;
- income-only and survival-liquidation IRR;
- exact residual cash-value status;
- first income month;
- first 12 policy months of guaranteed income;
- income conversion = first-12-month income / total premium;
- income-only break-even month = first guaranteed annuity event where cumulative annuity reaches total premium;
- capital per unit first income = total premium / first-12-month income.
- 10-year longevity leverage = additional cumulative annuity over ten survival years / total premium, only when both endpoint ages are on the disclosed analysis grid.

No mortality table is part of the v1 schema, so mortality-weighted EPV, fair annuity factor, mortality credit, and actuarial expected value stay unavailable. Conditional survival-path PV must be labeled as such.

For non-guaranteed annuity and maturity scenarios, `scenario_composition=total` replaces the complete guaranteed schedule of that event type, while `scenario_composition=incremental` keeps the guaranteed schedule and adds only the disclosed increment. Cash-value and death-benefit schedules are point-in-time totals. Missing composition is never inferred.

## Early-death outcome

The safe schedule/AST produces the death settlement without defaulting missing operands to zero. The output reports cumulative paid premium, prior receipts, settlement, post-death guaranteed installments, recovery ratio, net estate outcome, shortfall, and conditional IRR.

`death_wealth_multiple` uses total scheduled premium as denominator and includes prior contractual receipts, death settlement, and remaining guaranteed annuity. `nominal_recovery_ratio` instead uses premium actually paid by the death boundary. Standard labels distinguish premium-period death, pre-income death, first-payment death, one/five years after income, and ages 70/75/80 when those ages are requested.

```text
early_death_shortfall = max(0, premium_paid - all_contractual_receipts_and_value)
```

`remaining_guaranteed_annuity` applies only after annuity payments have begun. Pre-annuitization death uses its separate death-benefit rule.

## Inflation

For hypothetical constant inflation `pi`:

```text
real_cashflow_m = nominal_cashflow_m / (1 + pi) ** (m / 12)
```

V1 reports real cumulative annuity, preceding-12-month real income at each age, real-income retention, real payout multiple, and real income-only IRR. The default grid is 0%, 2%, 3%, and 4%; 0% is the nominal-control row. These are sensitivities, not forecasts.

## Benchmark relative value

The benchmark snapshot states currency, as-of date, source hash, annual-effective compounding, day count, and disclosed tenor points. Product and benchmark currency must match. V1 selects the nearest disclosed tenor without interpolation and reports the selected point.

For each survival horizon it reports conditional-survival NPV, benefit-PV/premium-PV, and unique IRR spread. Spread is unavailable when the contract IRR is absent or non-unique. The tool never silently fetches a market curve.

Peer comparison intersects exact product dimensions and ranks transparent metrics independently. Incompatible slices remain visible but exit rankings. No composite score is generated.
