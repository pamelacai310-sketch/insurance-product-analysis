"""Deterministic cashflow reconstruction and leveraged-life metrics."""

from __future__ import annotations

from datetime import date
from decimal import Decimal, ROUND_HALF_EVEN
import hashlib
import json
from typing import Any, Dict, List, Optional, Sequence, Tuple

from .irr import RootResult, irr, xirr
from .validate import validate_product


ENGINE_VERSION = "1.0.0"
MONEY_QUANTUM = Decimal("0.01")
CASH_VALUE_IRR_THRESHOLDS = (Decimal("0.01"), Decimal("0.02"), Decimal("0.03"))
INFLATION_STRESS_RATES = (
    Decimal("0.00"),
    Decimal("0.02"),
    Decimal("0.03"),
    Decimal("0.04"),
)


def as_decimal(value: Any) -> Decimal:
    return Decimal(str(value))


def money(value: Decimal) -> str:
    return format(value.quantize(MONEY_QUANTUM, rounding=ROUND_HALF_EVEN), "f")


def ratio(value: Decimal) -> float:
    return round(float(value), 12)


def metric(
    value: Any,
    method: str,
    inputs: Sequence[str],
    status: str = "ok",
    reason: Optional[str] = None,
    **extra: Any,
) -> dict:
    result = {
        "value": value,
        "status": status,
        "reason": reason,
        "method": method,
        "inputs": list(inputs),
    }
    result.update(extra)
    return result


def root_metric(result: RootResult, inputs: Sequence[str]) -> dict:
    payload = result.to_dict()
    payload["inputs"] = list(inputs)
    return payload


def _basis_digest(case: dict, currency: str) -> str:
    basis = {
        "case_id": case.get("case_id"),
        "basis": case.get("basis", {}),
        "timing": case.get("timing", {}),
        "amount_scale": case.get("amount_scale"),
        "inflation_rate": case.get("inflation_rate"),
        "currency": currency,
        "premium_cashflows": [
            {
                "date": item.get("date"),
                "time_years": item.get("time_years"),
                "amount": str(item.get("amount")),
            }
            for item in case.get("premium_cashflows", [])
        ],
    }
    encoded = json.dumps(
        basis, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _terminal_cashflows(
    case: dict,
    point: dict,
    terminal_amount: Decimal,
    terminal_path: str,
    point_path: str,
    case_index: int,
) -> Tuple[
    List[Tuple[float, Decimal]],
    List[Tuple[date, Decimal]],
    List[str],
    List[str],
    List[str],
    Decimal,
]:
    point_time = as_decimal(point["time_years"])
    point_date = date.fromisoformat(point["date"])
    periodic: List[Tuple[float, Decimal]] = []
    dated: List[Tuple[date, Decimal]] = []
    periodic_inputs: List[str] = []
    dated_inputs: List[str] = []
    cumulative_inputs: List[str] = []
    cumulative = Decimal("0")
    for premium_index, premium in enumerate(case["premium_cashflows"]):
        premium_time = as_decimal(premium["time_years"])
        premium_date = date.fromisoformat(premium["date"])
        if premium_time <= point_time and premium_date <= point_date:
            amount = as_decimal(premium["amount"])
            periodic.append((float(premium_time), -amount))
            dated.append((premium_date, -amount))
            cumulative += amount
            prefix = f"/cases/{case_index}/premium_cashflows/{premium_index}"
            amount_path = f"{prefix}/amount"
            periodic_inputs.extend([amount_path, f"{prefix}/time_years"])
            dated_inputs.extend([amount_path, f"{prefix}/date"])
            cumulative_inputs.extend(
                [amount_path, f"{prefix}/time_years", f"{prefix}/date"]
            )
    periodic.append((float(point_time), terminal_amount))
    dated.append((point_date, terminal_amount))
    periodic_inputs.extend([terminal_path, f"{point_path}/time_years"])
    dated_inputs.extend([terminal_path, f"{point_path}/date"])
    cumulative_inputs.extend([f"{point_path}/time_years", f"{point_path}/date"])
    return (
        periodic,
        dated,
        periodic_inputs,
        dated_inputs,
        cumulative_inputs,
        cumulative,
    )


def _dependency(
    guaranteed: Decimal, scenario: Optional[Decimal], inputs: Sequence[str]
) -> dict:
    if scenario is None:
        return metric(
            None,
            "scenario_minus_guaranteed_over_scenario",
            inputs,
            "not_computable",
            "scenario_missing",
        )
    if scenario == 0:
        return metric(
            None,
            "scenario_minus_guaranteed_over_scenario",
            inputs,
            "undefined",
            "zero_scenario_total",
        )
    return metric(
        ratio((scenario - guaranteed) / scenario),
        "scenario_minus_guaranteed_over_scenario",
        inputs,
    )


def _real_death_benefit(
    amount: Decimal,
    inflation_rate: Optional[Decimal],
    time_years: Decimal,
    inputs: Sequence[str],
) -> dict:
    if inflation_rate is None:
        return metric(
            None,
            "nominal_divided_by_one_plus_inflation_power_time",
            inputs,
            "not_computable",
            "inflation_missing",
        )
    adjusted = amount / ((Decimal("1") + inflation_rate) ** time_years)
    return metric(
        money(adjusted), "nominal_divided_by_one_plus_inflation_power_time", inputs
    )


def _purchasing_power_retention(
    inflation_rate: Optional[Decimal], time_years: Decimal, inputs: Sequence[str]
) -> dict:
    if inflation_rate is None:
        return metric(
            None,
            "one_over_one_plus_inflation_power_time",
            inputs,
            "not_computable",
            "inflation_missing",
        )
    retention = Decimal("1") / (
        (Decimal("1") + inflation_rate) ** time_years
    )
    return metric(
        ratio(retention), "one_over_one_plus_inflation_power_time", inputs
    )


def _purchasing_power_stress(
    amount: Decimal,
    time_years: Decimal,
    amount_path: str,
    time_path: str,
    rates: Sequence[Decimal] = INFLATION_STRESS_RATES,
) -> dict:
    """Convert a nominal benefit into today's money under fixed stresses."""

    results: Dict[str, dict] = {}
    for rate in rates:
        key = format(rate, "f")
        retention = Decimal("1") / ((Decimal("1") + rate) ** time_years)
        results[key] = {
            "inflation_rate": ratio(rate),
            "real_amount": money(amount * retention),
            "purchasing_power_retention": ratio(retention),
            "method": "nominal_divided_by_one_plus_stress_inflation_power_time",
            "inputs": [amount_path, time_path],
        }
    return results


def _value_metrics(
    case: dict,
    point: dict,
    amount: Decimal,
    amount_path: str,
    point_path: str,
    case_index: int,
) -> Tuple[dict, Decimal, List[str]]:
    periodic, dated, periodic_inputs, dated_inputs, cumulative_inputs, cumulative = (
        _terminal_cashflows(case, point, amount, amount_path, point_path, case_index)
    )
    return (
        {
            "irr": root_metric(irr(periodic), periodic_inputs),
            "xirr": root_metric(xirr(dated), dated_inputs),
        },
        cumulative,
        cumulative_inputs,
    )


def _breakeven(
    rows: Sequence[dict], case_index: int, scenario_id: Optional[str] = None
) -> dict:
    inputs = [
        f"/cases/{case_index}/premium_cashflows",
        f"/cases/{case_index}/projection",
    ]
    eligible: List[int] = []
    for index, row in enumerate(rows):
        if scenario_id is None:
            value = row["guaranteed"]["cash_surrender_value"]
        else:
            value = row["scenarios"].get(scenario_id, {}).get("cash_surrender_value")
        if value is not None and as_decimal(value) >= as_decimal(
            row["cumulative_premium"]
        ):
            eligible.append(index)
    if not eligible:
        return {
            "first": metric(
                None,
                "first_observed_csv_gte_cumulative_premium",
                inputs,
                "not_computable",
                "outside_projection_horizon",
            ),
            "sustained": metric(
                None,
                "all_later_csv_gte_cumulative_premium",
                inputs,
                "not_computable",
                "outside_projection_horizon",
            ),
        }
    first_index = eligible[0]
    sustained_index = None
    for candidate in eligible:
        if all(index in eligible for index in range(candidate, len(rows))):
            sustained_index = candidate
            break
    return {
        "first": metric(
            rows[first_index]["policy_year"],
            "first_observed_csv_gte_cumulative_premium",
            inputs,
        ),
        "sustained": (
            metric(
                rows[sustained_index]["policy_year"],
                "all_later_csv_gte_cumulative_premium",
                inputs,
            )
            if sustained_index is not None
            else metric(
                None,
                "all_later_csv_gte_cumulative_premium",
                inputs,
                "not_computable",
                "not_sustained",
            )
        ),
    }


def _irr_threshold_breakeven(
    rows: Sequence[dict],
    case_index: int,
    scenario_id: Optional[str] = None,
    thresholds: Sequence[Decimal] = CASH_VALUE_IRR_THRESHOLDS,
) -> dict:
    """Return first and sustained observed years at each cash-value IRR threshold."""

    inputs = [
        f"/cases/{case_index}/premium_cashflows",
        f"/cases/{case_index}/projection",
    ]
    results: Dict[str, dict] = {}
    for threshold in thresholds:
        eligible: List[int] = []
        for index, row in enumerate(rows):
            if scenario_id is None:
                value_metric = row["guaranteed"]["cash_value_irr"]
            else:
                value_metric = row["scenarios"].get(scenario_id, {}).get(
                    "cash_value_irr"
                )
            if (
                value_metric
                and value_metric.get("status") == "ok"
                and value_metric.get("value") is not None
                and as_decimal(value_metric["value"]) >= threshold
            ):
                eligible.append(index)

        key = format(threshold, "f")
        method_suffix = f"cash_value_irr_gte_{key}"
        if not eligible:
            results[key] = {
                "threshold": ratio(threshold),
                "first": metric(
                    None,
                    f"first_observed_{method_suffix}",
                    inputs,
                    "not_computable",
                    "outside_projection_horizon",
                ),
                "sustained": metric(
                    None,
                    f"all_later_{method_suffix}",
                    inputs,
                    "not_computable",
                    "outside_projection_horizon",
                ),
            }
            continue

        first_index = eligible[0]
        sustained_index = next(
            (
                candidate
                for candidate in eligible
                if all(index in eligible for index in range(candidate, len(rows)))
            ),
            None,
        )
        results[key] = {
            "threshold": ratio(threshold),
            "first": metric(
                rows[first_index]["policy_year"],
                f"first_observed_{method_suffix}",
                inputs,
            ),
            "sustained": (
                metric(
                    rows[sustained_index]["policy_year"],
                    f"all_later_{method_suffix}",
                    inputs,
                )
                if sustained_index is not None
                else metric(
                    None,
                    f"all_later_{method_suffix}",
                    inputs,
                    "not_computable",
                    "not_sustained",
                )
            ),
        }
    return results


def analyze_case(case: dict, case_index: int, currency: str) -> dict:
    """Analyze one canonical standard/document benchmark case."""

    scenario_ids = sorted(case.get("scenario_definitions", {}))
    inflation = case.get("inflation_rate")
    inflation_rate = None if inflation is None else as_decimal(inflation)
    rows: List[dict] = []
    for row_index, point in enumerate(case["projection"]):
        prefix = f"/cases/{case_index}/projection/{row_index}"
        guaranteed_death = as_decimal(point["death_benefit"]["guaranteed"])
        guaranteed_cash = as_decimal(point["cash_surrender_value"]["guaranteed"])
        death_path = f"{prefix}/death_benefit/guaranteed"
        cash_path = f"{prefix}/cash_surrender_value/guaranteed"
        death_returns, cumulative, cumulative_inputs = _value_metrics(
            case, point, guaranteed_death, death_path, prefix, case_index
        )
        cash_returns, _, _ = _value_metrics(
            case, point, guaranteed_cash, cash_path, prefix, case_index
        )
        if cumulative == 0:
            leverage = metric(
                None,
                "guaranteed_death_benefit_over_cumulative_premium",
                [death_path] + cumulative_inputs,
                "undefined",
                "zero_denominator",
            )
        else:
            leverage = metric(
                ratio(guaranteed_death / cumulative),
                "guaranteed_death_benefit_over_cumulative_premium",
                [death_path] + cumulative_inputs,
            )
        if guaranteed_cash == 0:
            protection_liquidity = metric(
                None,
                "guaranteed_death_benefit_over_guaranteed_cash_surrender_value",
                [death_path, cash_path],
                "undefined",
                "zero_liquidity",
                unbounded=guaranteed_death > 0,
            )
        else:
            protection_liquidity = metric(
                ratio(guaranteed_death / guaranteed_cash),
                "guaranteed_death_benefit_over_guaranteed_cash_surrender_value",
                [death_path, cash_path],
            )
        if cumulative == 0:
            cash_value_recovery = metric(
                None,
                "guaranteed_cash_surrender_value_over_cumulative_premium",
                [cash_path] + cumulative_inputs,
                "undefined",
                "zero_denominator",
            )
        else:
            cash_value_recovery = metric(
                ratio(guaranteed_cash / cumulative),
                "guaranteed_cash_surrender_value_over_cumulative_premium",
                [cash_path] + cumulative_inputs,
            )
        real_guaranteed = _real_death_benefit(
            guaranteed_death,
            inflation_rate,
            as_decimal(point["time_years"]),
            [
                death_path,
                f"{prefix}/time_years",
                f"/cases/{case_index}/inflation_rate",
            ],
        )
        retention_inputs = [
            f"{prefix}/time_years",
            f"/cases/{case_index}/inflation_rate",
        ]
        guaranteed_retention = _purchasing_power_retention(
            inflation_rate,
            as_decimal(point["time_years"]),
            retention_inputs,
        )
        guaranteed_metrics = {
            "death_leverage": leverage,
            "conditional_death_irr": death_returns["irr"],
            "conditional_death_xirr": death_returns["xirr"],
            "death_irr": death_returns["irr"],
            "death_xirr": death_returns["xirr"],
            "cash_value_irr": cash_returns["irr"],
            "cash_value_xirr": cash_returns["xirr"],
            "cash_value_premium_recovery": cash_value_recovery,
            "death_benefit_cv_ratio": protection_liquidity,
            "protection_liquidity_ratio": protection_liquidity,
            "inflation_adjusted_death_benefit": real_guaranteed,
            "death_benefit_purchasing_power_retention": guaranteed_retention,
            "death_benefit_purchasing_power_stress": _purchasing_power_stress(
                guaranteed_death,
                as_decimal(point["time_years"]),
                death_path,
                f"{prefix}/time_years",
            ),
        }

        scenario_values: Dict[str, dict] = {}
        for scenario_id in scenario_ids:
            scenario_death_raw = (
                point["death_benefit"].get("scenarios", {}).get(scenario_id)
            )
            scenario_cash_raw = (
                point["cash_surrender_value"].get("scenarios", {}).get(scenario_id)
            )
            scenario_death = (
                None if scenario_death_raw is None else as_decimal(scenario_death_raw)
            )
            scenario_cash = (
                None if scenario_cash_raw is None else as_decimal(scenario_cash_raw)
            )
            scenario_death_path = f"{prefix}/death_benefit/scenarios/{scenario_id}"
            scenario_cash_path = (
                f"{prefix}/cash_surrender_value/scenarios/{scenario_id}"
            )
            death_ngr = _dependency(
                guaranteed_death,
                scenario_death,
                [death_path, scenario_death_path],
            )
            cash_ngr = _dependency(
                guaranteed_cash,
                scenario_cash,
                [cash_path, scenario_cash_path],
            )
            scenario_payload: Dict[str, Any] = {
                "death_benefit": None
                if scenario_death is None
                else money(scenario_death),
                "cash_surrender_value": None
                if scenario_cash is None
                else money(scenario_cash),
                "death_non_guaranteed_dependency": death_ngr,
                "cash_value_non_guaranteed_dependency": cash_ngr,
                "death_ngr": death_ngr,
                "cash_value_ngr": cash_ngr,
            }
            if scenario_death is not None:
                returns, _, _ = _value_metrics(
                    case,
                    point,
                    scenario_death,
                    scenario_death_path,
                    prefix,
                    case_index,
                )
                if cumulative == 0:
                    scenario_leverage = metric(
                        None,
                        "scenario_death_benefit_over_cumulative_premium",
                        [scenario_death_path] + cumulative_inputs,
                        "undefined",
                        "zero_denominator",
                    )
                else:
                    scenario_leverage = metric(
                        ratio(scenario_death / cumulative),
                        "scenario_death_benefit_over_cumulative_premium",
                        [scenario_death_path] + cumulative_inputs,
                    )
                scenario_payload.update(
                    {
                        "death_leverage": scenario_leverage,
                        "conditional_death_irr": returns["irr"],
                        "conditional_death_xirr": returns["xirr"],
                        "death_irr": returns["irr"],
                        "death_xirr": returns["xirr"],
                        "inflation_adjusted_death_benefit": _real_death_benefit(
                            scenario_death,
                            inflation_rate,
                            as_decimal(point["time_years"]),
                            [
                                scenario_death_path,
                                f"{prefix}/time_years",
                                f"/cases/{case_index}/inflation_rate",
                            ],
                        ),
                        "death_benefit_purchasing_power_retention": (
                            _purchasing_power_retention(
                                inflation_rate,
                                as_decimal(point["time_years"]),
                                retention_inputs,
                            )
                        ),
                        "death_benefit_purchasing_power_stress": (
                            _purchasing_power_stress(
                                scenario_death,
                                as_decimal(point["time_years"]),
                                scenario_death_path,
                                f"{prefix}/time_years",
                            )
                        ),
                    }
                )
            if scenario_cash is not None:
                returns, _, _ = _value_metrics(
                    case,
                    point,
                    scenario_cash,
                    scenario_cash_path,
                    prefix,
                    case_index,
                )
                if cumulative == 0:
                    scenario_recovery = metric(
                        None,
                        "scenario_cash_surrender_value_over_cumulative_premium",
                        [scenario_cash_path] + cumulative_inputs,
                        "undefined",
                        "zero_denominator",
                    )
                else:
                    scenario_recovery = metric(
                        ratio(scenario_cash / cumulative),
                        "scenario_cash_surrender_value_over_cumulative_premium",
                        [scenario_cash_path] + cumulative_inputs,
                    )
                scenario_payload.update(
                    {
                        "cash_value_irr": returns["irr"],
                        "cash_value_xirr": returns["xirr"],
                        "cash_value_premium_recovery": scenario_recovery,
                    }
                )
            if scenario_death is not None and scenario_cash is not None:
                if scenario_cash == 0:
                    scenario_protection_liquidity = metric(
                        None,
                        "scenario_death_benefit_over_scenario_cash_surrender_value",
                        [scenario_death_path, scenario_cash_path],
                        "undefined",
                        "zero_liquidity",
                        unbounded=scenario_death > 0,
                    )
                else:
                    scenario_protection_liquidity = metric(
                        ratio(scenario_death / scenario_cash),
                        "scenario_death_benefit_over_scenario_cash_surrender_value",
                        [scenario_death_path, scenario_cash_path],
                    )
                scenario_payload.update(
                    {
                        "death_benefit_cv_ratio": scenario_protection_liquidity,
                        "protection_liquidity_ratio": scenario_protection_liquidity,
                    }
                )
            scenario_values[scenario_id] = scenario_payload

        rows.append(
            {
                "policy_year": point["policy_year"],
                "date": point["date"],
                "time_years": str(point["time_years"]),
                "cumulative_premium": money(cumulative),
                "cumulative_premium_inputs": cumulative_inputs,
                "guaranteed": {
                    "death_benefit": money(guaranteed_death),
                    "cash_surrender_value": money(guaranteed_cash),
                    **guaranteed_metrics,
                },
                "scenarios": scenario_values,
            }
        )

    total_premium = sum(
        (as_decimal(item["amount"]) for item in case["premium_cashflows"]), Decimal("0")
    )
    summary = {
        "guaranteed_breakeven": _breakeven(rows, case_index),
        "guaranteed_cash_value_irr_breakeven": _irr_threshold_breakeven(
            rows, case_index
        ),
        "scenario_breakeven": {
            scenario_id: _breakeven(rows, case_index, scenario_id)
            for scenario_id in scenario_ids
        },
        "scenario_cash_value_irr_breakeven": {
            scenario_id: _irr_threshold_breakeven(
                rows, case_index, scenario_id
            )
            for scenario_id in scenario_ids
        },
        "total_scheduled_premium": money(total_premium),
        "premium_payment_count": len(case["premium_cashflows"]),
        "premium_start_time_years": str(
            min(as_decimal(item["time_years"]) for item in case["premium_cashflows"])
        ),
        "premium_end_time_years": str(
            max(as_decimal(item["time_years"]) for item in case["premium_cashflows"])
        ),
        "premium_end_date": max(item["date"] for item in case["premium_cashflows"]),
        "lineage": {
            "total_scheduled_premium": [
                f"/cases/{case_index}/premium_cashflows/{index}/amount"
                for index, _ in enumerate(case["premium_cashflows"])
            ],
            "premium_payment_count": [f"/cases/{case_index}/premium_cashflows"],
            "premium_start_time_years": [
                f"/cases/{case_index}/premium_cashflows/{index}/time_years"
                for index, _ in enumerate(case["premium_cashflows"])
            ],
            "premium_end_time_years": [
                f"/cases/{case_index}/premium_cashflows/{index}/time_years"
                for index, _ in enumerate(case["premium_cashflows"])
            ],
            "premium_end_date": [
                f"/cases/{case_index}/premium_cashflows/{index}/date"
                for index, _ in enumerate(case["premium_cashflows"])
            ],
        },
    }
    report = {
        "case_id": case["case_id"],
        "basis": case.get("basis", {}),
        "basis_digest": _basis_digest(case, currency),
        "scenario_definitions": case.get("scenario_definitions", {}),
        "summary": summary,
        "rows": rows,
    }
    # Local import avoids a metrics/fingerprint import cycle.
    from .fingerprint import product_fingerprint

    report["fingerprint"] = product_fingerprint(report)
    return report


def analyze_product(data: dict, strict_evidence: bool = True) -> dict:
    validation = validate_product(data, strict_evidence=strict_evidence)
    status = "complete"
    if validation.errors:
        status = "invalid"
    elif validation.warnings:
        status = "complete_with_warnings"
    reports = []
    if not validation.errors:
        reports = [
            analyze_case(case, case_index, data["product"]["currency"])
            for case_index, case in enumerate(data["cases"])
        ]
    return {
        "analysis_version": ENGINE_VERSION,
        "analysis_scope": "product_only",
        "analysis_status": status,
        "product": data.get("product", {}),
        "validation": validation.to_dict(),
        "case_reports": reports,
    }
