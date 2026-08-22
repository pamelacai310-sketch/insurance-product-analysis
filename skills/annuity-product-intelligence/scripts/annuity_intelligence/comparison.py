from __future__ import annotations

from decimal import Decimal
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

from .common import (
    SCHEMA_VERSION,
    TOOL_VERSION,
    ValidationError,
    decimal_string,
    decimal_value,
    stable_json_data,
)


COMPARISON_DIMENSIONS = (
    "published_issue_age",
    "rate_class",
    "premium_term_months",
    "annuity_start_age",
    "annuity_frequency_per_year",
    "guarantee_option",
    "premium_mode",
    "product_option_code",
)


def configuration_key(
    config: Mapping[str, Any], currency: str, jurisdiction: str
) -> Tuple[Any, ...]:
    dimensions = config["dimensions"]
    return (currency, jurisdiction) + tuple(
        dimensions.get(key) for key in COMPARISON_DIMENSIONS
    )


def _premium_schedule_signature(
    config: Mapping[str, Any],
) -> Tuple[Tuple[int, int, str], ...]:
    total = decimal_value(config["calculation_context"]["total_premium"])
    if total <= 0:
        return tuple()
    return tuple(
        sorted(
            (
                int(event["policy_month"]),
                int(event["event_order"]),
                decimal_string(decimal_value(event["amount"]["value"]) / total),
            )
            for event in config["premium_events"]
        )
    )


def _metric_value(record: Mapping[str, Any]) -> Optional[Decimal]:
    if record.get("status") != "available" or record.get("value") is None:
        return None
    try:
        return decimal_value(record["value"])
    except ValidationError:
        return None


def _unique_irr_value(record: Mapping[str, Any]) -> Optional[Decimal]:
    if record.get("status") != "available":
        return None
    result = record.get("value")
    if not isinstance(result, Mapping) or result.get("status") != "unique_root":
        return None
    return decimal_value(result.get("selected_rate"))


def _rank(rows: List[Dict[str, Any]], field: str, direction: str) -> None:
    values = sorted(
        {row[field] for row in rows if row.get(field) is not None},
        reverse=direction == "higher",
    )
    rank_by_value = {value: index + 1 for index, value in enumerate(values)}
    for row in rows:
        row[f"{field}_rank"] = (
            None if row.get(field) is None else rank_by_value[row[field]]
        )


def _find_age_row(
    metrics_config: Mapping[str, Any], age: int
) -> Optional[Mapping[str, Any]]:
    curve = metrics_config["scenarios"]["guaranteed"][
        "survival_longevity_inflation_relative_value"
    ]["curve"]
    return next((row for row in curve if int(row["target_age"]) == age), None)


def _find_month_row(
    metrics_config: Mapping[str, Any], month: int
) -> Optional[Mapping[str, Any]]:
    curve = metrics_config["scenarios"]["guaranteed"]["liquidity"]["curve"]
    return next((row for row in curve if int(row["policy_month"]) == month), None)


def compare_products(product_runs: Sequence[Mapping[str, Any]]) -> Dict[str, Any]:
    if len(product_runs) < 2:
        raise ValidationError(["comparison requires at least two products"])
    product_ids = [run["normalized"]["product"]["product_id"] for run in product_runs]
    if len(set(product_ids)) != len(product_ids):
        raise ValidationError(
            ["product_id values must be globally unique in a comparison"]
        )
    indexes: List[Dict[Tuple[Any, ...], Mapping[str, Any]]] = []
    metric_indexes: List[Dict[str, Mapping[str, Any]]] = []
    for run in product_runs:
        normalized = run["normalized"]
        currency = normalized["product"]["currency"]
        jurisdiction = normalized["product"]["jurisdiction"]
        index: Dict[Tuple[Any, ...], Mapping[str, Any]] = {}
        for config in normalized["configurations"]:
            key = configuration_key(config, currency, jurisdiction)
            if key in index:
                raise ValidationError(
                    [
                        f"product {normalized['product']['product_id']} has duplicate comparable configuration dimensions"
                    ]
                )
            index[key] = config
        indexes.append(index)
        metric_indexes.append(
            {
                item["configuration_id"]: item
                for item in run["metrics"]["configurations"]
            }
        )
    common_keys = set(indexes[0])
    for index in indexes[1:]:
        common_keys &= set(index)
    all_keys = set().union(*(set(index) for index in indexes))
    assumptions = [
        stable_json_data(run["normalized"].get("analysis_assumptions", {}))
        for run in product_runs
    ]
    assumptions_compatible = all(value == assumptions[0] for value in assumptions[1:])
    slices = []
    for key in sorted(all_keys, key=lambda value: tuple(str(item) for item in value)):
        present = [
            (index, product_index[key])
            for index, product_index in enumerate(indexes)
            if key in product_index
        ]
        base_dimensions = {
            "currency": key[0],
            "jurisdiction": key[1],
            **dict(zip(COMPARISON_DIMENSIONS, key[2:])),
        }
        if len(present) != len(product_runs):
            slices.append(
                {
                    "dimensions": base_dimensions,
                    "compatible": False,
                    "normalization": None,
                    "products": [
                        {
                            "product_id": product_ids[index],
                            "configuration_id": config["configuration_id"],
                        }
                        for index, config in present
                    ],
                    "missing_product_ids": [
                        product_ids[index]
                        for index in range(len(product_runs))
                        if key not in indexes[index]
                    ],
                    "survival_age_comparisons": [],
                    "liquidity_month_comparisons": [],
                    "warnings": [
                        "This published configuration is not common to every product; no ranking is produced"
                    ],
                }
            )
            continue
        configs = [index[key] for index in indexes]
        premiums = [
            decimal_value(config["calculation_context"]["total_premium"])
            for config in configs
        ]
        same_premium = len(set(premiums)) == 1
        proportional = all(
            config["dimensions"].get("proportionality_verified") is True
            for config in configs
        )
        same_premium_schedule = (
            len({_premium_schedule_signature(config) for config in configs}) == 1
        )
        slice_record: Dict[str, Any] = {
            "dimensions": base_dimensions,
            "compatible": (same_premium or proportional)
            and same_premium_schedule
            and assumptions_compatible,
            "normalization": "same_total_premium"
            if same_premium and same_premium_schedule and assumptions_compatible
            else "per_1m_total_premium"
            if proportional and same_premium_schedule and assumptions_compatible
            else None,
            "products": [],
            "survival_age_comparisons": [],
            "liquidity_month_comparisons": [],
            "warnings": [],
        }
        if not slice_record["compatible"]:
            if not same_premium and not proportional:
                slice_record["warnings"].append(
                    "Total premiums differ and proportional scaling is not proven; this slice is excluded from rankings"
                )
            if not same_premium_schedule:
                slice_record["warnings"].append(
                    "Premium timing or proportional installment pattern differs; this slice is excluded from rankings"
                )
            if not assumptions_compatible:
                slice_record["warnings"].append(
                    "Analysis assumptions differ; this slice is excluded from rankings"
                )
            slices.append(slice_record)
            continue
        factors = [
            Decimal("1000000") / premium if not same_premium else Decimal("1")
            for premium in premiums
        ]
        metrics_configs = [
            metric_indexes[index][config["configuration_id"]]
            for index, config in enumerate(configs)
        ]
        for index, config in enumerate(configs):
            capital = metrics_configs[index]["capital_efficiency"]
            slice_record["products"].append(
                {
                    "product_id": product_ids[index],
                    "configuration_id": config["configuration_id"],
                    "total_premium": decimal_string(premiums[index]),
                    "scale_factor": decimal_string(factors[index]),
                    "income_conversion_rate": None
                    if _metric_value(capital["income_conversion_rate"]) is None
                    else decimal_string(
                        _metric_value(capital["income_conversion_rate"]) or Decimal("0")
                    ),
                    "first_income_month": capital["first_income_month"].get("value"),
                }
            )
        ages_sets = []
        for metrics_config in metrics_configs:
            curve = metrics_config["scenarios"]["guaranteed"][
                "survival_longevity_inflation_relative_value"
            ]["curve"]
            ages_sets.append({int(row["target_age"]) for row in curve})
        common_ages = set.intersection(*ages_sets) if ages_sets else set()
        for age in sorted(common_ages):
            rows = []
            for index, metrics_config in enumerate(metrics_configs):
                age_row = _find_age_row(metrics_config, age)
                assert age_row is not None
                cumulative = _metric_value(age_row["cumulative_annuity"])
                payout = _metric_value(age_row["payout_multiple"])
                irr = _unique_irr_value(age_row["survival_liquidation_irr"])
                rows.append(
                    {
                        "product_id": product_ids[index],
                        "cumulative_annuity": None
                        if cumulative is None
                        else decimal_string(cumulative * factors[index]),
                        "payout_multiple": None
                        if payout is None
                        else decimal_string(payout),
                        "unique_survival_liquidation_irr": None
                        if irr is None
                        else decimal_string(irr),
                    }
                )
            for field in (
                "cumulative_annuity",
                "payout_multiple",
                "unique_survival_liquidation_irr",
            ):
                for row in rows:
                    row[field] = None if row[field] is None else Decimal(row[field])
                _rank(rows, field, "higher")
                for row in rows:
                    if isinstance(row[field], Decimal):
                        row[field] = decimal_string(row[field])
            slice_record["survival_age_comparisons"].append(
                {"target_age": age, "rows": rows}
            )
        month_sets = []
        for metrics_config in metrics_configs:
            curve = metrics_config["scenarios"]["guaranteed"]["liquidity"]["curve"]
            month_sets.append({int(row["policy_month"]) for row in curve})
        common_months = set.intersection(*month_sets) if month_sets else set()
        for month in sorted(common_months):
            rows = []
            for index, metrics_config in enumerate(metrics_configs):
                month_row = _find_month_row(metrics_config, month)
                assert month_row is not None
                cash_value = _metric_value(month_row["cash_value"])
                cv_ratio = _metric_value(month_row["cash_value_ratio"])
                lock_ratio = _metric_value(month_row["lock_ratio"])
                irr = _unique_irr_value(month_row["total_exit_irr"])
                rows.append(
                    {
                        "product_id": product_ids[index],
                        "cash_value": None
                        if cash_value is None
                        else cash_value * factors[index],
                        "cash_value_ratio": cv_ratio,
                        "lock_ratio": lock_ratio,
                        "unique_total_exit_irr": irr,
                    }
                )
            for field, direction in (
                ("cash_value", "higher"),
                ("cash_value_ratio", "higher"),
                ("lock_ratio", "lower"),
                ("unique_total_exit_irr", "higher"),
            ):
                _rank(rows, field, direction)
            for row in rows:
                for field in (
                    "cash_value",
                    "cash_value_ratio",
                    "lock_ratio",
                    "unique_total_exit_irr",
                ):
                    if isinstance(row[field], Decimal):
                        row[field] = decimal_string(row[field])
            slice_record["liquidity_month_comparisons"].append(
                {"policy_month": month, "rows": rows}
            )
        slices.append(slice_record)
    return {
        "schema_version": SCHEMA_VERSION,
        "tool_version": TOOL_VERSION,
        "product_ids": product_ids,
        "common_configuration_count": len(common_keys),
        "comparison_slices": stable_json_data(slices),
        "aggregate_score": None,
        "aggregate_score_reason": "Only compatible dimensions are compared; no subjective composite score is produced",
    }
