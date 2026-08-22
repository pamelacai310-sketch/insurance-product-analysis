# Safe semantic rule grammar

V1 uses a small declarative AST only when a death benefit cannot be represented by a direct schedule. It never evaluates source code, expressions, imports, loops, functions, or network content.

Every node has `op` and nonempty `evidence_refs`.

## Value nodes

- `constant`: explicit typed money object in `amount`;
- `scalar_constant`: dimensionless decimal `value`;
- `field`: one of `basic_amount`, `cash_value`, `cumulative_annuity`, `cumulative_premium`, `policy_month`, or `total_premium`.

Missing fields propagate `missing`; they never become zero.

## Expression nodes

- `add`, `multiply`, `max`, `min`: `args` with at least two child nodes;
- `subtract`: `left` and `right` child nodes;
- `floor_zero`: one `arg`;
- `if_period`: optional `policy_month_min`/`policy_month_max` plus `then` and `else`.

No divide, power, arbitrary predicate, string formula, or customer attribute exists in v1.

Example:

```json
{
  "op": "max",
  "evidence_refs": ["ev-death"],
  "args": [
    {
      "op": "floor_zero",
      "evidence_refs": ["ev-death"],
      "arg": {
        "op": "subtract",
        "evidence_refs": ["ev-death"],
        "left": {"op": "field", "name": "cumulative_premium", "evidence_refs": ["ev-death"]},
        "right": {"op": "field", "name": "cumulative_annuity", "evidence_refs": ["ev-death"]}
      }
    },
    {"op": "field", "name": "cash_value", "evidence_refs": ["ev-death", "ev-cash"]}
  ]
}
```

This means `max(floor_zero(cumulative premium - annuity paid), cash value)` only when the controlling clause supports every node.

## Death timing and continuation

The death-benefit envelope states `before_annuity`, `after_annuity`, or `unresolved` for same-month ordering. Any unresolved boundary blocks normalization and calculation.

If the AST reads `cash_value`, the envelope also states `cash_value_timing`. Use `policy_month_state` when the disclosed cash value is a month-end/month-state table value independent of the death cutoff. Use `respect_event_order` only when the source explicitly places that value on the same event-order timeline. This flag is deterministic contract semantics, not an LLM guess.

Optional `remaining_guaranteed_annuity` reuses already generated guaranteed annuity events through an explicit policy month. It applies only after the first annuity payment; death before annuitization does not receive inferred continuation.

## LLM limits

An LLM may map a minimal ambiguous snippet to this exact grammar. The resolution must cite the queue task and source record, claim only medium confidence, and use numeric tokens anchored in that snippet. It may not transcribe a disputed table cell, create an operator, infer a unit/timing/version, calculate a benefit/IRR/PV, or edit evidence and metrics. The deterministic validator and example reconciliation remain authoritative.
