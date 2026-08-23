# Metric definitions v1.0.0

Let gross contractual premiums be `P_i > 0` at explicit time `τ_i`, and let a projection value be observed at `t`. Only premiums whose dates and offsets are at or before the projection endpoint are included.

## Guaranteed death leverage

```text
guaranteed death leverage(t)
  = guaranteed death benefit(t) / cumulative premiums paid through t
```

A zero denominator returns `null / zero_denominator`.

## Death and cash-value IRR/XIRR

Periodic IRR solves:

```text
0 = -Σ P_i/(1+r)^τ_i + terminal benefit(t)/(1+r)^t
```

XIRR uses the same cashflows with exponent `(date_i - first_date).days / 365` (`ACT/365F`). Death proceeds and net cash surrender value are calculated separately. A result requires both cashflow signs. Multiple possible roots return `ambiguous`; the engine never silently chooses one.

The explicit output names are `conditional_death_irr` and `conditional_death_xirr`; `death_irr` and `death_xirr` remain compatibility aliases. This is a mechanical return conditional on death at the stated endpoint. It is not an investment forecast, an unconditional expected return, or a survival-weighted return.

## Breakeven

First observed breakeven is the earliest disclosed projection row where net cash surrender value is at least cumulative premium. Sustained breakeven is the earliest such row for which every later disclosed row also qualifies. v1 does not interpolate between rows.

The same observed-year rule is applied to guaranteed and named-scenario cash-value IRR thresholds of 1%, 2%, and 3%. `first` is the first disclosed row at or above the threshold; `sustained` requires every later disclosed row to remain at or above it. A missing result means the threshold was not observed within the disclosed horizon.

## Non-guaranteed dependency

For each named scenario and each value type `X`:

```text
dependency(X,t) = (scenario_total(X,t) - guaranteed(X,t)) / scenario_total(X,t)
```

The aliases `death_ngr` and `cash_value_ngr` expose the same formula as non-guaranteed ratio (`NGR`). Death benefit and cash value are reported separately. A missing scenario is unknown (`null`), not zero. A scenario total below the same-basis guaranteed value is a validation error. A `document_illustration` scenario must be supported by evidence whose source kind is `illustration`.

## Protection-liquidity ratio

```text
guaranteed death benefit(t) / guaranteed cash surrender value(t)
```

This is an orientation: a higher result is more protection-weighted and a lower result is more liquidity-weighted. It is not a universal preference score. Zero cash value returns `null / zero_liquidity` with `unbounded: true` when death benefit is positive; JSON infinity is forbidden.

The explicit alias is `death_benefit_cv_ratio`; `protection_liquidity_ratio` remains available for compatibility.

## Real death benefit

The output name is `inflation_adjusted_death_benefit`:

```text
nominal death benefit(t) / (1 + explicit benchmark inflation rate)^t
```

No default inflation rate is supplied. Missing inflation returns `null / inflation_missing`. The assumption is benchmark metadata, not a product guarantee or customer input.

Each annual row also reports `death_benefit_purchasing_power_stress` at fixed 0%, 2%, 3%, and 4% inflation. Each stress contains the real amount and retained purchasing-power fraction. These stresses do not alter the contractual benefit and are not insurer projections.

## Audit lineage

Every derived metric carries RFC 6901 `inputs`. Periodic IRR cites premium amounts and nominal `time_years`; XIRR cites premium amounts and exact dates; inflation-adjusted benefits cite the projection time; breakeven cites the complete premium and projection containers it scans. Summary aggregates carry a separate `lineage` map. Container pointers are used where listing every scanned cell would duplicate the report.

## Fingerprint anchors

The versioned fingerprint never substitutes a nearby disclosed row. “Initial” requires policy year 1, pay-end recovery requires the exact policy year containing the final scheduled payment (`floor(premium_end_time)+1`), and non-guaranteed dependency requires policy year 20. A missing anchor is `unavailable`, with target and observed years retained in `raw`. Premium-pattern bands use payment-span years, not payment count alone.
