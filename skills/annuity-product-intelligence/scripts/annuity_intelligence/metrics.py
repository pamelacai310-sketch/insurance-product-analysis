from __future__ import annotations

import math
from decimal import Decimal, localcontext
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple

from .common import (
    DECIMAL_ONE,
    DECIMAL_ZERO,
    SCHEMA_VERSION,
    TOOL_VERSION,
    ValidationError,
    calculation_hash,
    decimal_string,
    decimal_value,
    flatten_evidence_refs,
    metric_record,
    percentile,
    safe_ratio,
    stable_json_data,
)
from .core import (
    beneficiary_continuation_events,
    cash_value_at,
    death_benefit_at,
    events_through_boundary,
    money_value,
    scenario_events,
)


IRR_RATE_MIN = -0.999999
IRR_RATE_MAX = 1_000_000.0
IRR_DECIMAL_PRECISION = 70
IRR_TANGENT_RESIDUAL = Decimal("1e-45")


def aggregate_cashflows(
    cashflows: Iterable[Tuple[int, Decimal]],
) -> List[Tuple[int, Decimal]]:
    by_month: Dict[int, Decimal] = {}
    for month, amount in cashflows:
        by_month[int(month)] = by_month.get(int(month), DECIMAL_ZERO) + amount
    return [
        (month, by_month[month]) for month in sorted(by_month) if by_month[month] != 0
    ]


def _polynomial_value(
    terms: Sequence[Tuple[int, Decimal]], z_value: Decimal
) -> Decimal:
    return sum(
        (coefficient * (z_value**exponent) for exponent, coefficient in terms),
        DECIMAL_ZERO,
    )


def _polynomial_residual(
    terms: Sequence[Tuple[int, Decimal]], z_value: Decimal
) -> Decimal:
    signed = _polynomial_value(terms, z_value)
    absolute = sum(
        (abs(coefficient) * (z_value**exponent) for exponent, coefficient in terms),
        DECIMAL_ZERO,
    )
    return abs(signed) / absolute if absolute else DECIMAL_ZERO


def _sign_variations(terms: Sequence[Tuple[int, Decimal]]) -> int:
    signs = [
        1 if coefficient > 0 else -1 for _, coefficient in terms if coefficient != 0
    ]
    return sum(left != right for left, right in zip(signs, signs[1:]))


def _normalized_derivative_terms(
    terms: Sequence[Tuple[int, Decimal]],
) -> List[Tuple[int, Decimal]]:
    derivative = [
        (exponent - 1, coefficient * Decimal(exponent))
        for exponent, coefficient in terms
        if exponent > 0 and coefficient != 0
    ]
    if not derivative:
        return []
    minimum = min(exponent for exponent, _ in derivative)
    return [(exponent - minimum, coefficient) for exponent, coefficient in derivative]


def _bisect_polynomial_root(
    terms: Sequence[Tuple[int, Decimal]], left: Decimal, right: Decimal
) -> Decimal:
    f_left = _polynomial_value(terms, left)
    f_right = _polynomial_value(terms, right)
    if f_left == 0:
        return left
    if f_right == 0:
        return right
    for _ in range(IRR_DECIMAL_PRECISION * 4):
        middle = (left + right) / Decimal(2)
        f_middle = _polynomial_value(terms, middle)
        if f_middle == 0 or abs(right - left) <= Decimal("1e-60"):
            return middle
        if (f_left < 0 < f_middle) or (f_left > 0 > f_middle):
            right = middle
            f_right = f_middle
        else:
            left = middle
            f_left = f_middle
    return (left + right) / Decimal(2)


def _positive_polynomial_roots(
    terms: Sequence[Tuple[int, Decimal]], left: Decimal, right: Decimal
) -> List[Decimal]:
    terms = sorted(
        (exponent, coefficient) for exponent, coefficient in terms if coefficient != 0
    )
    if len(terms) < 2 or _sign_variations(terms) == 0:
        return []
    f_left = _polynomial_value(terms, left)
    f_right = _polynomial_value(terms, right)
    if _sign_variations(terms) == 1:
        if f_left == 0:
            return [left]
        if f_right == 0:
            return [right]
        if (f_left < 0 < f_right) or (f_left > 0 > f_right):
            return [_bisect_polynomial_root(terms, left, right)]
        return []

    derivative_terms = _normalized_derivative_terms(terms)
    critical_points = _positive_polynomial_roots(derivative_terms, left, right)
    boundaries = [left, *critical_points, right]
    roots: List[Decimal] = []
    for point in boundaries:
        if _polynomial_residual(terms, point) <= IRR_TANGENT_RESIDUAL:
            roots.append(point)
    for interval_left, interval_right in zip(boundaries, boundaries[1:]):
        value_left = _polynomial_value(terms, interval_left)
        value_right = _polynomial_value(terms, interval_right)
        if (value_left < 0 < value_right) or (value_left > 0 > value_right):
            roots.append(_bisect_polynomial_root(terms, interval_left, interval_right))
    unique: List[Decimal] = []
    for candidate in sorted(roots):
        if not unique or abs(candidate - unique[-1]) > Decimal("1e-40"):
            unique.append(candidate)
    return unique


def xirr_all(cashflows: Iterable[Tuple[int, Decimal]]) -> Dict[str, Any]:
    flows = aggregate_cashflows(cashflows)
    positives = any(amount > 0 for _, amount in flows)
    negatives = any(amount < 0 for _, amount in flows)
    trace = [
        {"policy_month": month, "amount": decimal_string(amount)}
        for month, amount in flows
    ]
    if not flows or not positives or not negatives:
        return {
            "status": "insufficient_cashflows",
            "roots": [],
            "selected_rate": None,
            "cashflows": trace,
        }
    minimum_month = min(month for month, _ in flows)
    polynomial_terms = [(month - minimum_month, amount) for month, amount in flows]
    with localcontext() as context:
        context.prec = IRR_DECIMAL_PRECISION
        x_min = Decimal(str(math.log1p(IRR_RATE_MIN)))
        x_max = Decimal(str(math.log1p(IRR_RATE_MAX)))
        z_min = (-x_max / Decimal(12)).exp()
        z_max = (-x_min / Decimal(12)).exp()
        roots_z = _positive_polynomial_roots(polynomial_terms, z_min, z_max)
        roots = []
        for z_value in roots_z:
            rate = (z_value ** Decimal(-12)) - DECIMAL_ONE
            residual = _polynomial_residual(polynomial_terms, z_value)
            if Decimal(str(IRR_RATE_MIN)) <= rate <= Decimal(str(IRR_RATE_MAX)):
                roots.append(
                    {
                        "annual_effective_rate": format(float(rate), ".12g"),
                        "normalized_residual": format(float(residual), ".6g"),
                    }
                )
    roots.sort(key=lambda item: Decimal(item["annual_effective_rate"]))
    if not roots:
        status = "no_root"
        selected = None
    elif len(roots) == 1:
        status = "unique_root"
        selected = roots[0]["annual_effective_rate"]
    else:
        status = "multiple_roots"
        selected = None
    return {
        "status": status,
        "roots": roots,
        "selected_rate": selected,
        "cashflows": trace,
    }


def npv(
    cashflows: Iterable[Tuple[int, Decimal]], annual_effective_rate: Decimal
) -> Decimal:
    if annual_effective_rate <= Decimal("-1"):
        raise ValidationError(["discount rate must be greater than -1"])
    if not annual_effective_rate.is_finite():
        raise ValidationError(["discount rate must be finite"])
    with localcontext() as context:
        context.prec = IRR_DECIMAL_PRECISION
        annual_log = (DECIMAL_ONE + annual_effective_rate).ln()
        total = DECIMAL_ZERO
        for month, amount in aggregate_cashflows(cashflows):
            discount_factor = (annual_log * Decimal(month) / Decimal(12)).exp()
            total += amount / discount_factor
        if not total.is_finite():
            raise ValidationError(["discounted cash-flow result is not finite"])
        return +total


def _event_amount(event: Mapping[str, Any]) -> Decimal:
    return decimal_value(event["amount"], "cashflow event amount")


def _signed_event(event: Mapping[str, Any]) -> Tuple[int, Decimal]:
    amount = _event_amount(event)
    if event.get("owner_direction") == "outflow":
        amount = -amount
    return int(event["policy_month"]), amount


def _evidence_from_events(events: Iterable[Mapping[str, Any]]) -> List[str]:
    return flatten_evidence_refs(*(event.get("evidence_refs", []) for event in events))


def _metric(
    value: Any,
    formula_id: str,
    config_id: str,
    refs: Iterable[str],
    calc_config: Any,
    status: str = "available",
    warnings: Optional[Sequence[str]] = None,
    assumptions: Optional[Sequence[str]] = None,
) -> Dict[str, Any]:
    return metric_record(
        value, formula_id, config_id, refs, calc_config, status, warnings, assumptions
    )


def _irr_metric(
    flows: Iterable[Tuple[int, Decimal]],
    formula_id: str,
    config_id: str,
    refs: Iterable[str],
    calc_config: Any,
) -> Dict[str, Any]:
    result = xirr_all(flows)
    warnings = (
        ["IRR has multiple mathematically valid roots; no headline rate selected"]
        if result["status"] == "multiple_roots"
        else []
    )
    return _metric(
        result, formula_id, config_id, refs, calc_config, "available", warnings
    )


def _select_benchmark(
    benchmark: Optional[Mapping[str, Any]], currency: str, duration_years: Decimal
) -> Optional[Dict[str, Any]]:
    if not benchmark:
        return None
    if benchmark.get("currency") != currency:
        raise ValidationError(["benchmark currency does not match product currency"])
    points = benchmark.get("points")
    if not isinstance(points, list) or not points:
        raise ValidationError(["benchmark points are required"])
    candidates = []
    for point in points:
        term = decimal_value(point.get("term_years"), "benchmark term_years")
        rate = decimal_value(
            point.get("annual_effective_rate"), "benchmark annual_effective_rate"
        )
        if rate <= Decimal("-1"):
            raise ValidationError(["benchmark rate must be greater than -1"])
        candidates.append((abs(term - duration_years), term, rate, point))
    best_distance = min(item[0] for item in candidates)
    tied = [item for item in candidates if item[0] == best_distance]
    _, term, rate, point = min(tied, key=lambda item: item[1])
    return {
        "benchmark_id": benchmark.get("benchmark_id"),
        "as_of_date": benchmark.get("as_of_date"),
        "source_sha256": benchmark.get("source_sha256"),
        "selection_method": "nearest_disclosed_tenor_no_interpolation",
        "selection_tie_break": "lower_tenor" if len(tied) > 1 else None,
        "selected_term_years": decimal_string(term),
        "annual_effective_rate": decimal_string(rate),
        "point": point,
    }


def _scenario_ids(
    config_events: Sequence[Mapping[str, Any]], config: Mapping[str, Any]
) -> List[str]:
    values = {"guaranteed"}
    for event in config_events:
        if event.get("scenario_id"):
            values.add(str(event["scenario_id"]))
    for item in config.get("cash_values", []):
        if item.get("scenario_id"):
            values.add(str(item["scenario_id"]))
    death = config.get("death_benefit") or {}
    if death.get("scenario_id"):
        values.add(str(death["scenario_id"]))
    for item in death.get("schedule", []):
        if item.get("scenario_id"):
            values.add(str(item["scenario_id"]))
    return sorted(values, key=lambda value: (value != "guaranteed", value))


def _bind_metric_provenance(value: Any, dependency_sha256: str) -> None:
    if isinstance(value, dict):
        provenance = value.get("provenance")
        if isinstance(provenance, dict):
            original = provenance.get("calculation_config_sha256")
            provenance["configuration_dependency_sha256"] = dependency_sha256
            provenance["calculation_config_sha256"] = calculation_hash(
                {
                    "metric_calculation_config_sha256": original,
                    "configuration_dependency_sha256": dependency_sha256,
                }
            )
        for child in value.values():
            _bind_metric_provenance(child, dependency_sha256)
    elif isinstance(value, list):
        for child in value:
            _bind_metric_provenance(child, dependency_sha256)


def _liquidity_metrics(
    config: Mapping[str, Any],
    events: Sequence[Mapping[str, Any]],
    scenario_id: str,
    config_id: str,
) -> Dict[str, Any]:
    curve: List[Dict[str, Any]] = []
    cash_value_recovery_month: Optional[int] = None
    total_benefit_recovery_month: Optional[int] = None
    all_cash_values = list(config.get("cash_values", []))
    scenario_cash_values = [
        item
        for item in all_cash_values
        if item.get("scenario_id", "guaranteed") == scenario_id
    ]
    selected_cash_values = (
        scenario_cash_values
        if scenario_id != "guaranteed" and scenario_cash_values
        else [
            item
            for item in all_cash_values
            if item.get("scenario_id", "guaranteed") == "guaranteed"
        ]
    )
    for item in sorted(
        selected_cash_values,
        key=lambda row: (int(row["policy_month"]), int(row.get("event_order", 0))),
    ):
        month = int(item["policy_month"])
        order = int(item.get("event_order", 99))
        boundary_events = events_through_boundary(events, month, order, scenario_id)
        premiums = [
            event for event in boundary_events if event["event_type"] == "premium"
        ]
        receipts = [
            event for event in boundary_events if event["owner_direction"] == "inflow"
        ]
        cumulative_premium = sum(
            (_event_amount(event) for event in premiums), DECIMAL_ZERO
        )
        prior_receipts = sum((_event_amount(event) for event in receipts), DECIMAL_ZERO)
        refs = flatten_evidence_refs(
            item.get("evidence_refs", []), _evidence_from_events(boundary_events)
        )
        calc = {"scenario_id": scenario_id, "policy_month": month, "event_order": order}
        status = item.get("status", "missing")
        row: Dict[str, Any] = {
            "policy_month": month,
            "status": status,
            "cumulative_premium": _metric(
                decimal_string(cumulative_premium),
                "liquidity.cumulative_premium",
                config_id,
                refs,
                calc,
            ),
        }
        if status != "available":
            unavailable_status = (
                "not_applicable" if status == "not_applicable" else "missing"
            )
            for key, formula in (
                ("cash_value", "liquidity.cash_value"),
                ("cash_value_ratio", "liquidity.cash_value_ratio"),
                ("liquidity_gap", "liquidity.gap"),
                ("surrender_loss", "liquidity.surrender_loss"),
                ("lock_ratio", "liquidity.lock_ratio"),
                ("capital_returned_ratio", "capital.returned_ratio"),
                ("cash_value_only_irr", "irr.cash_value_only"),
                ("total_exit_irr", "irr.total_exit"),
            ):
                row[key] = _metric(
                    None, formula, config_id, refs, calc, unavailable_status
                )
            curve.append(row)
            continue
        cash_value = money_value(item["amount"])
        gap = cumulative_premium - cash_value
        surrender_loss = max(gap, DECIMAL_ZERO)
        cash_ratio = safe_ratio(cash_value, cumulative_premium)
        lock_ratio = safe_ratio(surrender_loss, cumulative_premium)
        returned_ratio = safe_ratio(cash_value + prior_receipts, cumulative_premium)
        if (
            cash_value_recovery_month is None
            and cumulative_premium > 0
            and cash_value >= cumulative_premium
        ):
            cash_value_recovery_month = month
        if (
            total_benefit_recovery_month is None
            and cumulative_premium > 0
            and cash_value + prior_receipts >= cumulative_premium
        ):
            total_benefit_recovery_month = month
        pure_flows = [_signed_event(event) for event in premiums] + [
            (month, cash_value)
        ]
        exit_flows = [_signed_event(event) for event in boundary_events] + [
            (month, cash_value)
        ]
        row.update(
            {
                "cash_value": _metric(
                    decimal_string(cash_value),
                    "liquidity.cash_value",
                    config_id,
                    refs,
                    calc,
                ),
                "cash_value_ratio": _metric(
                    None if cash_ratio is None else decimal_string(cash_ratio),
                    "liquidity.cash_value_ratio",
                    config_id,
                    refs,
                    calc,
                    "not_applicable" if cash_ratio is None else "available",
                ),
                "liquidity_gap": _metric(
                    decimal_string(gap), "liquidity.gap", config_id, refs, calc
                ),
                "surrender_loss": _metric(
                    decimal_string(surrender_loss),
                    "liquidity.surrender_loss",
                    config_id,
                    refs,
                    calc,
                ),
                "lock_ratio": _metric(
                    None if lock_ratio is None else decimal_string(lock_ratio),
                    "liquidity.lock_ratio",
                    config_id,
                    refs,
                    calc,
                    "not_applicable" if lock_ratio is None else "available",
                ),
                "capital_returned_ratio": _metric(
                    None if returned_ratio is None else decimal_string(returned_ratio),
                    "capital.returned_ratio",
                    config_id,
                    refs,
                    calc,
                    "not_applicable" if returned_ratio is None else "available",
                ),
                "cash_value_only_irr": _irr_metric(
                    pure_flows, "irr.cash_value_only", config_id, refs, calc
                ),
                "total_exit_irr": _irr_metric(
                    exit_flows, "irr.total_exit", config_id, refs, calc
                ),
            }
        )
        loan = config.get("loan_terms") or {}
        if loan.get("available") is True and loan.get("limit_ratio") is not None:
            loan_amount = cash_value * decimal_value(loan["limit_ratio"])
            row["maximum_policy_loan"] = _metric(
                decimal_string(loan_amount),
                "liquidity.maximum_policy_loan",
                config_id,
                flatten_evidence_refs(refs, loan.get("evidence_refs", [])),
                calc,
                warnings=[
                    "Loan proceeds are debt and are excluded from investment return cash flows"
                ],
            )
        else:
            row["maximum_policy_loan"] = _metric(
                None,
                "liquidity.maximum_policy_loan",
                config_id,
                refs,
                calc,
                "not_applicable",
            )
        curve.append(row)
    coverage_warning = []
    months = [int(item["policy_month"]) for item in selected_cash_values]
    if months and any(b - a > 12 for a, b in zip(sorted(months), sorted(months)[1:])):
        coverage_warning.append(
            "Cash-value schedule has gaps; no interpolation was performed"
        )
    calc = {"scenario_id": scenario_id, "cash_value_points": months}
    refs = flatten_evidence_refs(
        *(item.get("evidence_refs", []) for item in selected_cash_values)
    )
    return {
        "curve": curve,
        "cash_value_recovery_month": _metric(
            cash_value_recovery_month,
            "liquidity.cash_value_recovery_month",
            config_id,
            refs,
            calc,
            "missing" if cash_value_recovery_month is None else "available",
            coverage_warning,
        ),
        "total_benefit_recovery_month": _metric(
            total_benefit_recovery_month,
            "liquidity.total_benefit_recovery_month",
            config_id,
            refs,
            calc,
            "missing" if total_benefit_recovery_month is None else "available",
            coverage_warning,
        ),
    }


def _real_amount(amount: Decimal, policy_month: int, inflation: Decimal) -> Decimal:
    if inflation <= Decimal("-1") or not inflation.is_finite():
        raise ValidationError(["inflation rate must be finite and greater than -1"])
    with localcontext() as context:
        context.prec = IRR_DECIMAL_PRECISION
        inflation_factor = (
            (DECIMAL_ONE + inflation).ln() * Decimal(policy_month) / Decimal(12)
        ).exp()
        result = amount / inflation_factor
        if not result.is_finite():
            raise ValidationError(["inflation-adjusted amount is not finite"])
        return +result


def _survival_metrics(
    config: Mapping[str, Any],
    events: Sequence[Mapping[str, Any]],
    scenario_id: str,
    target_ages: Sequence[int],
    inflation_rates: Sequence[Decimal],
    benchmark: Optional[Mapping[str, Any]],
    currency: str,
    config_id: str,
) -> Dict[str, Any]:
    issue_age = int(config["dimensions"]["published_issue_age"])
    total_premium = decimal_value(config["calculation_context"]["total_premium"])
    curve = []
    for age in target_ages:
        horizon = (int(age) - issue_age) * 12
        if horizon < 0:
            continue
        selected = scenario_events(events, scenario_id, horizon)
        premiums = [event for event in selected if event["event_type"] == "premium"]
        annuities = [
            event for event in selected if event["event_type"] == "annuity_payment"
        ]
        refs = _evidence_from_events(selected)
        calc = {"scenario_id": scenario_id, "target_age": age, "horizon_month": horizon}
        cumulative_annuity = sum(
            (_event_amount(event) for event in annuities), DECIMAL_ZERO
        )
        payout_multiple = safe_ratio(cumulative_annuity, total_premium)
        income_flows = [_signed_event(event) for event in selected]
        cv_status, cv_amount, cv_refs, cv_month = cash_value_at(
            config, horizon, scenario_id, "exact"
        )
        liquidation_flows = list(income_flows)
        if cv_status == "available" and cv_amount is not None:
            liquidation_flows.append((horizon, cv_amount))
        refs = flatten_evidence_refs(refs, cv_refs)
        row: Dict[str, Any] = {
            "target_age": age,
            "policy_month": horizon,
            "cumulative_annuity": _metric(
                decimal_string(cumulative_annuity),
                "longevity.cumulative_annuity",
                config_id,
                refs,
                calc,
            ),
            "payout_multiple": _metric(
                None if payout_multiple is None else decimal_string(payout_multiple),
                "longevity.payout_multiple",
                config_id,
                refs,
                calc,
                "not_applicable" if payout_multiple is None else "available",
            ),
            "income_only_irr": _irr_metric(
                income_flows, "irr.income_only", config_id, refs, calc
            ),
            "residual_cash_value": _metric(
                None if cv_amount is None else decimal_string(cv_amount),
                "longevity.residual_cash_value",
                config_id,
                cv_refs,
                calc,
                cv_status,
                ["No cash-value interpolation was performed"]
                if cv_status == "missing"
                else [],
            ),
            "survival_liquidation_irr": _irr_metric(
                liquidation_flows, "irr.survival_liquidation", config_id, refs, calc
            )
            if cv_status == "available"
            else _metric(
                None, "irr.survival_liquidation", config_id, refs, calc, cv_status
            ),
        }
        inflation_rows = []
        for inflation in inflation_rates:
            real_flows = [
                (
                    int(event["policy_month"]),
                    _real_amount(
                        _signed_event(event)[1], int(event["policy_month"]), inflation
                    ),
                )
                for event in selected
            ]
            real_annuity = sum(
                (
                    _real_amount(
                        _event_amount(event), int(event["policy_month"]), inflation
                    )
                    for event in annuities
                ),
                DECIMAL_ZERO,
            )
            real_premiums = sum(
                (
                    _real_amount(
                        _event_amount(event), int(event["policy_month"]), inflation
                    )
                    for event in premiums
                ),
                DECIMAL_ZERO,
            )
            twelve_month_income = sum(
                (
                    _real_amount(
                        _event_amount(event), int(event["policy_month"]), inflation
                    )
                    for event in annuities
                    if horizon - 12 < int(event["policy_month"]) <= horizon
                ),
                DECIMAL_ZERO,
            )
            inflation_calc = {
                **calc,
                "inflation_rate": decimal_string(inflation),
                "hypothetical": True,
            }
            inflation_rows.append(
                {
                    "inflation_rate": decimal_string(inflation),
                    "hypothetical": True,
                    "real_cumulative_annuity": _metric(
                        decimal_string(real_annuity),
                        "inflation.real_cumulative_annuity",
                        config_id,
                        refs,
                        inflation_calc,
                        assumptions=[
                            "constant hypothetical inflation from policy issue"
                        ],
                    ),
                    "real_annualized_income_at_age": _metric(
                        decimal_string(twelve_month_income),
                        "inflation.real_annualized_income_at_age",
                        config_id,
                        refs,
                        inflation_calc,
                        assumptions=[
                            "sum of payments in the preceding 12 policy months"
                        ],
                    ),
                    "real_payout_multiple": _metric(
                        None
                        if real_premiums == 0
                        else decimal_string(real_annuity / real_premiums),
                        "inflation.real_payout_multiple",
                        config_id,
                        refs,
                        inflation_calc,
                        "not_applicable" if real_premiums == 0 else "available",
                    ),
                    "real_income_only_irr": _irr_metric(
                        real_flows,
                        "irr.real_income_only",
                        config_id,
                        refs,
                        inflation_calc,
                    ),
                }
            )
        row["inflation_scenarios"] = inflation_rows
        benchmark_point = _select_benchmark(
            benchmark, currency, Decimal(horizon) / Decimal(12)
        )
        if benchmark_point:
            rate = decimal_value(benchmark_point["annual_effective_rate"])
            benchmark_flows = list(
                liquidation_flows if cv_status == "available" else income_flows
            )
            premium_flows = [flow for flow in benchmark_flows if flow[1] < 0]
            benefit_flows = [flow for flow in benchmark_flows if flow[1] > 0]
            premium_pv = -npv(premium_flows, rate)
            benefit_pv = npv(benefit_flows, rate)
            contract_npv = benefit_pv - premium_pv
            irr_result = xirr_all(benchmark_flows)
            spread = None
            if irr_result["status"] == "unique_root":
                spread = Decimal(irr_result["selected_rate"]) - rate
            benchmark_refs = refs
            benchmark_assumptions = [
                f"benchmark:{benchmark_point.get('benchmark_id')}",
                f"benchmark_source_sha256:{benchmark_point.get('source_sha256')}",
            ]
            benchmark_calc = {**calc, "benchmark": benchmark_point}
            row["relative_value"] = {
                "benchmark": benchmark_point,
                "conditional_survival_npv": _metric(
                    decimal_string(contract_npv),
                    "relative_value.conditional_survival_npv",
                    config_id,
                    benchmark_refs,
                    benchmark_calc,
                    warnings=[
                        "Conditional survival path; no mortality weighting applied"
                    ],
                    assumptions=benchmark_assumptions,
                ),
                "benefit_pv_to_premium_pv": _metric(
                    None
                    if premium_pv == 0
                    else decimal_string(benefit_pv / premium_pv),
                    "capital.benefit_pv_to_premium_pv",
                    config_id,
                    benchmark_refs,
                    benchmark_calc,
                    "not_applicable" if premium_pv == 0 else "available",
                    assumptions=benchmark_assumptions,
                ),
                "unique_irr_spread": _metric(
                    None if spread is None else decimal_string(spread),
                    "relative_value.unique_irr_spread",
                    config_id,
                    benchmark_refs,
                    benchmark_calc,
                    "not_applicable" if spread is None else "available",
                    [
                        "Spread is unavailable when the contract IRR is absent or non-unique"
                    ]
                    if spread is None
                    else [],
                    benchmark_assumptions,
                ),
            }
        else:
            row["relative_value"] = {
                "status": "missing",
                "reason": "No immutable benchmark snapshot supplied",
                "provenance": {
                    "formula_id": "relative_value.unavailable",
                    "formula_version": "1.0.0",
                    "configuration_id": config_id,
                    "evidence_refs": refs,
                    "calculation_config_sha256": calculation_hash(calc),
                },
            }
        curve.append(row)
    return {"curve": curve}


def _death_metrics(
    config: Mapping[str, Any],
    events: Sequence[Mapping[str, Any]],
    scenario_id: str,
    target_ages: Sequence[int],
    config_id: str,
) -> Dict[str, Any]:
    issue_age = int(config["dimensions"]["published_issue_age"])
    curve = []
    for age in target_ages:
        month = (int(age) - issue_age) * 12
        if month < 0:
            continue
        definition = config.get("death_benefit") or {}
        boundary = definition.get("boundary_order", "before_annuity")
        if boundary == "before_annuity":
            event_order = 29
        elif boundary == "after_annuity":
            event_order = 39
        else:
            curve.append(
                {
                    "target_age": age,
                    "policy_month": month,
                    "status": "unresolved",
                    "reason": "Death-boundary ordering is unresolved",
                }
            )
            continue
        selected = events_through_boundary(events, month, event_order, scenario_id)
        premiums = [event for event in selected if event["event_type"] == "premium"]
        prior_inflows = [
            event for event in selected if event["owner_direction"] == "inflow"
        ]
        paid = sum((_event_amount(event) for event in premiums), DECIMAL_ZERO)
        received = sum((_event_amount(event) for event in prior_inflows), DECIMAL_ZERO)
        settlement = death_benefit_at(config, events, month, scenario_id, event_order)
        continuation = beneficiary_continuation_events(
            config, events, month, event_order
        )
        continuation_amount = sum(
            (_event_amount(event) for event in continuation), DECIMAL_ZERO
        )
        refs = flatten_evidence_refs(
            _evidence_from_events(selected),
            settlement.get("evidence_refs", []),
            _evidence_from_events(continuation),
        )
        calc = {
            "scenario_id": scenario_id,
            "target_age": age,
            "policy_month": month,
            "boundary_order": boundary,
        }
        if settlement["status"] in {"missing", "unresolved"}:
            curve.append(
                {
                    "target_age": age,
                    "policy_month": month,
                    "status": f"partial_{settlement['status']}",
                    "cumulative_premium_paid": _metric(
                        decimal_string(paid),
                        "early_death.cumulative_premium",
                        config_id,
                        refs,
                        calc,
                    ),
                    "prior_contract_receipts": _metric(
                        decimal_string(received),
                        "early_death.prior_receipts",
                        config_id,
                        refs,
                        calc,
                    ),
                    "death_settlement": _metric(
                        None,
                        "early_death.settlement",
                        config_id,
                        refs,
                        calc,
                        settlement["status"],
                    ),
                    "beneficiary_continuation": _metric(
                        decimal_string(continuation_amount),
                        "early_death.beneficiary_continuation",
                        config_id,
                        refs,
                        calc,
                    ),
                    "reason": "Known continuation is retained, but total outcome metrics require the missing settlement",
                    "trace": settlement.get("trace"),
                }
            )
            continue
        settlement_amount = (
            settlement["amount"] or DECIMAL_ZERO
            if settlement["status"] == "available"
            else DECIMAL_ZERO
        )
        total_benefit = received + settlement_amount + continuation_amount
        recovery = safe_ratio(total_benefit, paid)
        shortfall = max(paid - total_benefit, DECIMAL_ZERO)
        outcome_flows = [_signed_event(event) for event in selected]
        if settlement_amount != 0:
            outcome_flows.append((month, settlement_amount))
        outcome_flows.extend(_signed_event(event) for event in continuation)
        curve.append(
            {
                "target_age": age,
                "policy_month": month,
                "status": "available",
                "cumulative_premium_paid": _metric(
                    decimal_string(paid),
                    "early_death.cumulative_premium",
                    config_id,
                    refs,
                    calc,
                ),
                "prior_contract_receipts": _metric(
                    decimal_string(received),
                    "early_death.prior_receipts",
                    config_id,
                    refs,
                    calc,
                ),
                "death_settlement": _metric(
                    decimal_string(settlement_amount)
                    if settlement["status"] == "available"
                    else None,
                    "early_death.settlement",
                    config_id,
                    refs,
                    calc,
                    settlement["status"],
                ),
                "beneficiary_continuation": _metric(
                    decimal_string(continuation_amount),
                    "early_death.beneficiary_continuation",
                    config_id,
                    refs,
                    calc,
                ),
                "nominal_recovery_ratio": _metric(
                    None if recovery is None else decimal_string(recovery),
                    "early_death.nominal_recovery_ratio",
                    config_id,
                    refs,
                    calc,
                    "not_applicable" if recovery is None else "available",
                ),
                "net_estate_outcome": _metric(
                    decimal_string(total_benefit - paid),
                    "early_death.net_estate_outcome",
                    config_id,
                    refs,
                    calc,
                ),
                "early_death_shortfall": _metric(
                    decimal_string(shortfall),
                    "early_death.shortfall",
                    config_id,
                    refs,
                    calc,
                ),
                "conditional_death_outcome_irr": _irr_metric(
                    outcome_flows,
                    "irr.conditional_death_outcome",
                    config_id,
                    refs,
                    calc,
                ),
                "trace": settlement.get("trace"),
            }
        )
    return {"curve": curve}


def _capital_metrics(
    config: Mapping[str, Any], events: Sequence[Mapping[str, Any]], config_id: str
) -> Dict[str, Any]:
    guaranteed = scenario_events(events, "guaranteed")
    annuities = [
        event
        for event in guaranteed
        if event["event_type"] == "annuity_payment"
        and event.get("guarantee_basis") == "guaranteed"
    ]
    total_premium = decimal_value(config["calculation_context"]["total_premium"])
    refs = _evidence_from_events(guaranteed)
    calc = {"scenario_id": "guaranteed"}
    if not annuities:
        return {
            "first_income_month": _metric(
                None, "capital.first_income_month", config_id, refs, calc, "missing"
            ),
            "first_12_month_income": _metric(
                None, "capital.first_12_month_income", config_id, refs, calc, "missing"
            ),
            "income_conversion_rate": _metric(
                None, "capital.income_conversion_rate", config_id, refs, calc, "missing"
            ),
            "income_only_break_even_month": _metric(
                None,
                "longevity.income_only_break_even_month",
                config_id,
                refs,
                calc,
                "missing",
            ),
            "capital_per_unit_first_income": _metric(
                None, "capital.per_unit_first_income", config_id, refs, calc, "missing"
            ),
        }
    first = min(int(event["policy_month"]) for event in annuities)
    first_year_income = sum(
        (
            _event_amount(event)
            for event in annuities
            if first <= int(event["policy_month"]) < first + 12
        ),
        DECIMAL_ZERO,
    )
    conversion = safe_ratio(first_year_income, total_premium)
    capital_per_income = safe_ratio(total_premium, first_year_income)
    cumulative_income = DECIMAL_ZERO
    income_break_even_month = None
    for event in sorted(
        annuities,
        key=lambda item: (int(item["policy_month"]), int(item["event_order"])),
    ):
        cumulative_income += _event_amount(event)
        if cumulative_income >= total_premium:
            income_break_even_month = int(event["policy_month"])
            break
    return {
        "first_income_month": _metric(
            first, "capital.first_income_month", config_id, refs, calc
        ),
        "first_12_month_income": _metric(
            decimal_string(first_year_income),
            "capital.first_12_month_income",
            config_id,
            refs,
            calc,
        ),
        "income_conversion_rate": _metric(
            None if conversion is None else decimal_string(conversion),
            "capital.income_conversion_rate",
            config_id,
            refs,
            calc,
            "not_applicable" if conversion is None else "available",
        ),
        "income_only_break_even_month": _metric(
            income_break_even_month,
            "longevity.income_only_break_even_month",
            config_id,
            refs,
            calc,
            "missing" if income_break_even_month is None else "available",
        ),
        "capital_per_unit_first_income": _metric(
            None if capital_per_income is None else decimal_string(capital_per_income),
            "capital.per_unit_first_income",
            config_id,
            refs,
            calc,
            "not_applicable" if capital_per_income is None else "available",
        ),
    }


def analyze_product(
    normalized: Dict[str, Any],
    cashflow_output: Dict[str, Any],
    benchmark: Optional[Mapping[str, Any]] = None,
) -> Dict[str, Any]:
    assumptions = normalized.get("analysis_assumptions", {})
    inflation_rates = [
        decimal_value(value)
        for value in assumptions.get("inflation_rates", ["0.02", "0.03", "0.04"])
    ]
    currency = normalized["product"]["currency"]
    cashflows_by_id = {
        item["configuration_id"]: item for item in cashflow_output["configurations"]
    }
    results = []
    summary_conversion: List[Decimal] = []
    for config in normalized["configurations"]:
        config_id = config["configuration_id"]
        cashflow_data = cashflows_by_id[config_id]
        events = cashflow_data["events"]
        issue_age = int(config["dimensions"]["published_issue_age"])
        contract_end_ages = [
            int(rule["contract_end_age"])
            for rule in config.get("annuity_rules", [])
            if rule.get("contract_end_age") is not None
        ]
        default_end_age = max(contract_end_ages or [issue_age + 60])
        if assumptions.get("analysis_end_age") is not None:
            default_end_age = min(default_end_age, int(assumptions["analysis_end_age"]))
        target_survival = [
            int(value)
            for value in assumptions.get(
                "target_survival_ages", [70, 75, 80, 85, 90, 95, 100]
            )
            if issue_age <= int(value) <= default_end_age
        ]
        annuity_start_age = int(config["dimensions"]["annuity_start_age"])
        default_death = sorted(
            {
                issue_age + 1,
                issue_age + 5,
                max(issue_age, annuity_start_age - 1),
                min(default_end_age, annuity_start_age + 5),
                min(default_end_age, 75),
                min(default_end_age, 85),
                min(default_end_age, 95),
            }
        )
        target_death = [
            int(value)
            for value in assumptions.get("target_death_ages", default_death)
            if issue_age <= int(value) <= default_end_age
        ]
        scenarios = {}
        for scenario_id in _scenario_ids(events, config):
            scenarios[scenario_id] = {
                "liquidity": _liquidity_metrics(config, events, scenario_id, config_id),
                "survival_longevity_inflation_relative_value": _survival_metrics(
                    config,
                    events,
                    scenario_id,
                    target_survival,
                    inflation_rates,
                    benchmark,
                    currency,
                    config_id,
                ),
                "early_death": _death_metrics(
                    config, events, scenario_id, target_death, config_id
                ),
            }
        capital = _capital_metrics(config, events, config_id)
        dependency_sha256 = calculation_hash(
            {"normalized_configuration": config, "cashflow_events": events}
        )
        _bind_metric_provenance(scenarios, dependency_sha256)
        _bind_metric_provenance(capital, dependency_sha256)
        conversion_metric = capital["income_conversion_rate"]
        if conversion_metric["status"] == "available":
            summary_conversion.append(decimal_value(conversion_metric["value"]))
        results.append(
            {
                "configuration_id": config_id,
                "dimensions": stable_json_data(config["dimensions"]),
                "currency": currency,
                "configuration_dependency_sha256": dependency_sha256,
                "scenarios": scenarios,
                "capital_efficiency": capital,
                "warnings": [],
            }
        )
    summary = {
        "configuration_count": len(results),
        "income_conversion_rate_distribution": {
            "minimum": None
            if not summary_conversion
            else decimal_string(min(summary_conversion)),
            "p10": None
            if not summary_conversion
            else decimal_string(
                percentile(summary_conversion, Decimal("0.1")) or DECIMAL_ZERO
            ),
            "median": None
            if not summary_conversion
            else decimal_string(
                percentile(summary_conversion, Decimal("0.5")) or DECIMAL_ZERO
            ),
            "p90": None
            if not summary_conversion
            else decimal_string(
                percentile(summary_conversion, Decimal("0.9")) or DECIMAL_ZERO
            ),
            "maximum": None
            if not summary_conversion
            else decimal_string(max(summary_conversion)),
        },
        "aggregate_score": None,
        "aggregate_score_reason": "Opaque weighted product scores are intentionally not produced",
    }
    return {
        "schema_version": SCHEMA_VERSION,
        "tool_version": TOOL_VERSION,
        "product_id": normalized["product"]["product_id"],
        "product_analysis_only": True,
        "guaranteed_and_illustrated_separated": True,
        "benchmark_snapshot": stable_json_data(benchmark) if benchmark else None,
        "configurations": results,
        "summary": summary,
    }
