"""Versioned, rule-based product economic fingerprint."""

from __future__ import annotations

import hashlib
import json
from decimal import Decimal, ROUND_FLOOR
from typing import Any, Dict, List, Optional


RULES_VERSION = "fingerprint-1.0.0"


def _value(metric: Optional[dict]) -> Optional[float]:
    if not metric or metric.get("status") != "ok" or metric.get("value") is None:
        return None
    return float(metric["value"])


def _band(
    value: Optional[float], bands: List[tuple], missing: str = "unavailable"
) -> str:
    if value is None:
        return missing
    for threshold, label in bands:
        if value >= threshold:
            return label
    return bands[-1][1] if bands else missing


def _trend(values: List[float]) -> str:
    if len(values) < 2:
        return "unavailable"
    tolerance = max(abs(values[0]), 1.0) * 0.005
    if max(values) - min(values) <= tolerance:
        return "level"
    nondecreasing = all(
        right + tolerance >= left for left, right in zip(values, values[1:])
    )
    nonincreasing = all(
        right - tolerance <= left for left, right in zip(values, values[1:])
    )
    if nondecreasing:
        return "increasing"
    if nonincreasing:
        return "decreasing"
    return "mixed"


def product_fingerprint(case_report: dict) -> dict:
    rows = case_report["rows"]
    payment_count = case_report["summary"]["premium_payment_count"]
    premium_start = Decimal(case_report["summary"]["premium_start_time_years"])
    premium_end = Decimal(case_report["summary"]["premium_end_time_years"])
    premium_span = premium_end - premium_start
    if payment_count == 1:
        premium_pattern = "single_pay"
    elif premium_span <= Decimal("5"):
        premium_pattern = "short_limited_pay"
    elif premium_span <= Decimal("10"):
        premium_pattern = "limited_pay"
    else:
        premium_pattern = "extended_pay"

    initial_row = next((row for row in rows if row["policy_year"] == 1), None)
    initial_leverage = (
        _value(initial_row["guaranteed"]["death_leverage"]) if initial_row else None
    )
    leverage_band = _band(
        initial_leverage,
        [
            (5.0, "5x_or_more"),
            (2.0, "2x_to_below_5x"),
            (1.0, "1x_to_below_2x"),
            (float("-inf"), "below_1x"),
        ],
    )
    pay_end_target_year = int(premium_end.to_integral_value(rounding=ROUND_FLOOR)) + 1
    pay_end_row = next(
        (row for row in rows if row["policy_year"] == pay_end_target_year), None
    )
    recovery = None
    if pay_end_row and float(pay_end_row["cumulative_premium"]) > 0:
        recovery = float(pay_end_row["guaranteed"]["cash_surrender_value"]) / float(
            pay_end_row["cumulative_premium"]
        )
    recovery_band = _band(
        recovery,
        [
            (1.0, "at_or_above_100pct"),
            (0.8, "80_to_below_100pct"),
            (0.5, "50_to_below_80pct"),
            (float("-inf"), "below_50pct"),
        ],
    )
    death_values = [float(row["guaranteed"]["death_benefit"]) for row in rows]
    real_values = [
        float(row["guaranteed"]["inflation_adjusted_death_benefit"]["value"])
        for row in rows
        if row["guaranteed"]["inflation_adjusted_death_benefit"]["status"] == "ok"
    ]
    breakeven = case_report["summary"]["guaranteed_breakeven"]["first"].get("value")
    if breakeven is None:
        breakeven_band = "not_reached"
    elif breakeven <= 5:
        breakeven_band = "within_5y"
    elif breakeven <= 10:
        breakeven_band = "6_to_10y"
    else:
        breakeven_band = "after_10y"

    scenario_ids = sorted(case_report.get("scenario_definitions", {}))
    primary_scenario = scenario_ids[0] if scenario_ids else None
    horizon_row = next((row for row in rows if row["policy_year"] == 20), None)
    dependency = None
    if primary_scenario and horizon_row:
        dependency = _value(
            horizon_row["scenarios"]
            .get(primary_scenario, {})
            .get("death_non_guaranteed_dependency")
        )
    if dependency is None:
        dependency_band = "unavailable"
    elif dependency == 0:
        dependency_band = "none"
    elif dependency < 0.2:
        dependency_band = "below_20pct"
    elif dependency < 0.5:
        dependency_band = "20_to_below_50pct"
    else:
        dependency_band = "50pct_or_more"

    features: Dict[str, Any] = {
        "premium_pattern": premium_pattern,
        "guaranteed_death_benefit_pattern": _trend(death_values),
        "inflation_adjusted_death_benefit_pattern": _trend(real_values),
        "initial_guaranteed_death_leverage": leverage_band,
        "pay_end_liquidity_recovery": recovery_band,
        "guaranteed_breakeven": breakeven_band,
        "non_guaranteed_death_dependency_20y": dependency_band,
    }
    label = " | ".join([premium_pattern, leverage_band, recovery_band, dependency_band])
    encoded = json.dumps(
        {"rules_version": RULES_VERSION, "features": features},
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return {
        "rules_version": RULES_VERSION,
        "fingerprint_id": hashlib.sha256(encoded).hexdigest()[:16],
        "label": label,
        "features": features,
        "raw": {
            "initial_guaranteed_death_leverage": initial_leverage,
            "initial_observation_policy_year": (
                initial_row["policy_year"] if initial_row else None
            ),
            "pay_end_liquidity_recovery": None
            if recovery is None
            else round(recovery, 12),
            "pay_end_target_policy_year": pay_end_target_year,
            "pay_end_observation_policy_year": (
                pay_end_row["policy_year"] if pay_end_row else None
            ),
            "guaranteed_breakeven_year": breakeven,
            "non_guaranteed_death_dependency_horizon": dependency,
            "non_guaranteed_dependency_target_policy_year": 20,
            "non_guaranteed_dependency_observation_policy_year": (
                horizon_row["policy_year"] if horizon_row else None
            ),
            "premium_span_years": float(premium_span),
        },
    }
