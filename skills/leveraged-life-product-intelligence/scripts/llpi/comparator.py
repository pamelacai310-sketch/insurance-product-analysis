"""Peer comparison under an identical, hash-checked benchmark basis."""

from __future__ import annotations

import json
from typing import Any, Dict, List, Optional, Sequence


COMPARATOR_VERSION = "1.0.0"
COMPARABLE_ANALYSIS_STATUSES = frozenset({"complete", "complete_with_warnings"})
CRITICAL_EVIDENCE_PROVENANCE_CODES = frozenset(
    {
        "content_hash",
        "critical_provenance_low_confidence",
        "dangling_evidence",
        "dangling_pointer",
        "dangling_source",
        "document_hash",
        "duplicate_evidence_id",
        "duplicate_source_id",
        "evidence_bbox",
        "evidence_item",
        "evidence_page",
        "evidence_shape",
        "evidence_text",
        "missing_provenance",
        "provenance_evidence",
        "provenance_extractor",
        "provenance_record",
        "provenance_status",
        "source_hash_mismatch",
    }
)


def _is_non_negative_int(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value >= 0


def _is_nonempty_string(value: Any) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _is_critical_evidence_provenance_issue(issue: dict) -> bool:
    code = issue.get("code")
    path = issue.get("path")
    if code in CRITICAL_EVIDENCE_PROVENANCE_CODES:
        return True
    if isinstance(code, str) and (
        code.startswith("evidence_") or code.startswith("provenance_")
    ):
        return True
    return isinstance(path, str) and path.startswith(
        ("/sources", "/evidence", "/provenance")
    )


def _report_eligibility_reason_codes(report: Any) -> List[str]:
    """Return deterministic blockers before any peer observations are ranked."""

    if not isinstance(report, dict):
        return [
            "analysis_status_not_comparable",
            "validation_missing",
        ]

    reason_codes = []
    product = report.get("product")
    if not isinstance(product, dict) or not all(
        _is_nonempty_string(product.get(field))
        for field in ("product_id", "name", "insurer", "currency", "product_type")
    ):
        reason_codes.append("product_identity_invalid")
    analysis_status = report.get("analysis_status")
    if analysis_status not in COMPARABLE_ANALYSIS_STATUSES:
        reason_codes.append("analysis_status_not_comparable")

    if "validation" not in report:
        reason_codes.append("validation_missing")
        return sorted(set(reason_codes))
    validation = report.get("validation")
    if not isinstance(validation, dict):
        reason_codes.append("validation_malformed")
        return sorted(set(reason_codes))

    ok = validation.get("ok")
    error_count = validation.get("error_count")
    warning_count = validation.get("warning_count")
    issues = validation.get("issues")
    internally_well_formed = (
        isinstance(ok, bool)
        and _is_non_negative_int(error_count)
        and _is_non_negative_int(warning_count)
        and isinstance(issues, list)
    )
    normalized_issues = []
    if isinstance(issues, list):
        for issue in issues:
            if not isinstance(issue, dict):
                internally_well_formed = False
                continue
            if (
                issue.get("severity") not in {"error", "warning"}
                or not isinstance(issue.get("code"), str)
                or not issue.get("code")
                or not isinstance(issue.get("path"), str)
                or not isinstance(issue.get("message"), str)
            ):
                internally_well_formed = False
                continue
            normalized_issues.append(issue)

    actual_error_count = sum(
        issue["severity"] == "error" for issue in normalized_issues
    )
    actual_warning_count = sum(
        issue["severity"] == "warning" for issue in normalized_issues
    )
    if internally_well_formed and (
        error_count != actual_error_count
        or warning_count != actual_warning_count
        or ok != (actual_error_count == 0)
    ):
        internally_well_formed = False
    if not internally_well_formed:
        reason_codes.append("validation_malformed")
    else:
        if not ok:
            reason_codes.append("validation_failed")
        expected_status = (
            "complete_with_warnings" if actual_warning_count else "complete"
        )
        if analysis_status in COMPARABLE_ANALYSIS_STATUSES and (
            analysis_status != expected_status
        ):
            reason_codes.append("analysis_validation_mismatch")

    if any(
        _is_critical_evidence_provenance_issue(issue) for issue in normalized_issues
    ):
        reason_codes.append("critical_evidence_provenance_issue")
    return sorted(set(reason_codes))


def _canonical_json(value: Any) -> Optional[str]:
    try:
        return json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        )
    except (TypeError, ValueError):
        return None


def _metric_value(metric: Optional[dict]) -> Optional[float]:
    if not metric or metric.get("status") != "ok" or metric.get("value") is None:
        return None
    return float(metric["value"])


def _find_case(report: dict, case_id: str) -> Optional[dict]:
    return next(
        (
            item
            for item in report.get("case_reports", [])
            if item.get("case_id") == case_id
        ),
        None,
    )


def _find_row(case: dict, horizon: int) -> Optional[dict]:
    return next(
        (row for row in case.get("rows", []) if row.get("policy_year") == horizon), None
    )


def _stress_real_amount(
    row: Optional[dict], rate: str, scenario_id: Optional[str] = None
) -> Optional[float]:
    if row is None:
        return None
    values = (
        row.get("guaranteed", {})
        if scenario_id is None
        else row.get("scenarios", {}).get(scenario_id, {})
    )
    stress = values.get("death_benefit_purchasing_power_stress", {}).get(rate, {})
    amount = stress.get("real_amount")
    return None if amount is None else float(amount)


def _rank(observations: List[dict], higher_is_mechanical: bool) -> List[dict]:
    available = [item for item in observations if item["value"] is not None]
    available.sort(
        key=lambda item: (
            (-item["value"] if higher_is_mechanical else item["value"]),
            item["product_id"],
        )
    )
    previous = None
    rank = 0
    for position, item in enumerate(available, start=1):
        if previous is None or abs(item["value"] - previous) > 1e-10 * max(
            1.0, abs(previous)
        ):
            rank = position
            previous = item["value"]
        item["rank"] = rank
    missing = sorted(
        (item for item in observations if item["value"] is None),
        key=lambda item: item["product_id"],
    )
    for item in missing:
        item["rank"] = None
    return available + missing


def _observation_set(
    peers: Sequence[tuple],
    getter,
    direction: str,
    interpretation: str,
) -> dict:
    observations = [
        {"product_id": product_id, "product_name": product_name, "value": getter(case)}
        for product_id, product_name, case in peers
    ]
    if direction == "orientation_only":
        observations = sorted(observations, key=lambda item: item["product_id"])
        for item in observations:
            item["rank"] = None
    else:
        observations = _rank(
            observations, higher_is_mechanical=direction == "higher_mechanical"
        )
    return {
        "direction": direction,
        "interpretation": interpretation,
        "observations": observations,
    }


def compare_reports(
    reports: Sequence[dict], case_id: str, horizons: Sequence[int]
) -> dict:
    """Compare analyzed products; never force ranking across mismatched bases."""

    report_list = list(reports)
    if len(report_list) < 2:
        return {
            "comparison_version": COMPARATOR_VERSION,
            "case_id": case_id,
            "comparable": False,
            "reason_codes": ["insufficient_peers"],
            "horizons": [],
        }
    eligibility_reason_codes = sorted(
        {
            code
            for report in report_list
            for code in _report_eligibility_reason_codes(report)
        }
    )
    if eligibility_reason_codes:
        return {
            "comparison_version": COMPARATOR_VERSION,
            "case_id": case_id,
            "comparable": False,
            "reason_codes": eligibility_reason_codes,
            "horizons": [],
        }

    product_ids = [report["product"]["product_id"] for report in report_list]
    if len(product_ids) != len(set(product_ids)):
        return {
            "comparison_version": COMPARATOR_VERSION,
            "case_id": case_id,
            "comparable": False,
            "reason_codes": ["duplicate_product_id"],
            "horizons": [],
        }

    peers = []
    missing = []
    for report in sorted(
        report_list, key=lambda item: item.get("product", {}).get("product_id", "")
    ):
        product = report.get("product", {})
        case = _find_case(report, case_id)
        if case is None:
            missing.append(product.get("product_id"))
        else:
            peers.append((product.get("product_id"), product.get("name"), case))
    if missing:
        return {
            "comparison_version": COMPARATOR_VERSION,
            "case_id": case_id,
            "comparable": False,
            "reason_codes": ["case_missing"],
            "missing_products": sorted(missing),
            "horizons": [],
        }
    digests = {case["basis_digest"] for _, _, case in peers}
    currencies = {report.get("product", {}).get("currency") for report in report_list}
    scenario_definitions = {
        _canonical_json(case.get("scenario_definitions", {})) for _, _, case in peers
    }
    reason_codes = []
    if len(digests) != 1:
        reason_codes.append("benchmark_basis_mismatch")
    if len(currencies) != 1:
        reason_codes.append("currency_mismatch")
    if None in scenario_definitions or len(scenario_definitions) != 1:
        reason_codes.append("scenario_definition_mismatch")
    if reason_codes:
        return {
            "comparison_version": COMPARATOR_VERSION,
            "case_id": case_id,
            "comparable": False,
            "reason_codes": sorted(reason_codes),
            "horizons": [],
        }

    horizon_results = []
    for horizon in sorted(set(int(value) for value in horizons)):
        horizon_peers = []
        for product_id, product_name, case in peers:
            row = _find_row(case, horizon)
            horizon_peers.append((product_id, product_name, row))

        def guaranteed_metric(name: str):
            return lambda row: (
                None if row is None else _metric_value(row["guaranteed"].get(name))
            )

        metrics: Dict[str, Any] = {
            "guaranteed_death_leverage": _observation_set(
                horizon_peers,
                guaranteed_metric("death_leverage"),
                "higher_mechanical",
                "Higher means more guaranteed death benefit per premium paid; it is not a suitability score.",
            ),
            "guaranteed_death_xirr": _observation_set(
                horizon_peers,
                guaranteed_metric("conditional_death_xirr"),
                "higher_mechanical",
                "Higher is a mechanical cashflow return conditional on death at this assumed date, not an investment promise or survival-weighted return.",
            ),
            "guaranteed_death_irr": _observation_set(
                horizon_peers,
                guaranteed_metric("conditional_death_irr"),
                "higher_mechanical",
                "Higher is a periodic-time cashflow return conditional on death at this assumed point, not an investment promise or survival-weighted return.",
            ),
            "guaranteed_cash_value_xirr": _observation_set(
                horizon_peers,
                guaranteed_metric("cash_value_xirr"),
                "higher_mechanical",
                "Higher is a mechanical surrender cashflow return at the common horizon.",
            ),
            "guaranteed_cash_value_irr": _observation_set(
                horizon_peers,
                guaranteed_metric("cash_value_irr"),
                "higher_mechanical",
                "Higher is a periodic-time mechanical surrender cashflow return at the common horizon.",
            ),
            "guaranteed_cash_value_premium_recovery": _observation_set(
                horizon_peers,
                guaranteed_metric("cash_value_premium_recovery"),
                "higher_mechanical",
                "Higher means more guaranteed surrender value per cumulative premium paid at the common horizon.",
            ),
            "guaranteed_inflation_adjusted_death_benefit": _observation_set(
                horizon_peers,
                guaranteed_metric("inflation_adjusted_death_benefit"),
                "higher_mechanical",
                "Higher is a larger death benefit in common benchmark-date purchasing-power units under the same explicit inflation assumption and premium basis.",
            ),
            "guaranteed_death_benefit_purchasing_power_retention": _observation_set(
                horizon_peers,
                guaranteed_metric("death_benefit_purchasing_power_retention"),
                "higher_mechanical",
                "Higher means a larger fraction of nominal death benefit purchasing power is retained under the same explicit inflation assumption.",
            ),
            "protection_liquidity_ratio": _observation_set(
                horizon_peers,
                guaranteed_metric("protection_liquidity_ratio"),
                "orientation_only",
                "Higher is more protection-weighted and lower is more liquidity-weighted; neither is universally superior.",
            ),
        }
        metrics["guaranteed_conditional_death_xirr"] = metrics[
            "guaranteed_death_xirr"
        ]
        metrics["guaranteed_conditional_death_irr"] = metrics[
            "guaranteed_death_irr"
        ]
        metrics["death_benefit_cv_ratio"] = metrics[
            "protection_liquidity_ratio"
        ]
        for stress_rate in ("0.00", "0.02", "0.03", "0.04"):
            metrics[f"guaranteed_real_death_benefit_inflation_{stress_rate}"] = (
                _observation_set(
                    horizon_peers,
                    lambda row, rate=stress_rate: _stress_real_amount(row, rate),
                    "higher_mechanical",
                    f"Higher is a larger guaranteed death benefit in today's money under a fixed {float(stress_rate):.0%} inflation stress.",
                )
            )
        common_scenarios = None
        for _, _, row in horizon_peers:
            row_scenarios = set() if row is None else set(row.get("scenarios", {}))
            common_scenarios = (
                row_scenarios
                if common_scenarios is None
                else common_scenarios & row_scenarios
            )
        for scenario_id in sorted(common_scenarios or set()):
            def scenario_metric(name: str, sid: str = scenario_id):
                return lambda row: (
                    None
                    if row is None
                    else _metric_value(row["scenarios"][sid].get(name))
                )

            metrics[f"{scenario_id}_death_leverage"] = _observation_set(
                horizon_peers,
                scenario_metric("death_leverage"),
                "higher_mechanical",
                "Higher means more illustrated death benefit per premium paid under this named non-guaranteed scenario.",
            )
            metrics[f"{scenario_id}_conditional_death_xirr"] = _observation_set(
                horizon_peers,
                scenario_metric("conditional_death_xirr"),
                "higher_mechanical",
                "Higher is an illustrated cashflow return conditional on death at this date; it remains non-guaranteed and is not an investment promise.",
            )
            metrics[f"{scenario_id}_conditional_death_irr"] = _observation_set(
                horizon_peers,
                scenario_metric("conditional_death_irr"),
                "higher_mechanical",
                "Higher is an illustrated periodic-time return conditional on death at this point; it remains non-guaranteed.",
            )
            metrics[f"{scenario_id}_cash_value_xirr"] = _observation_set(
                horizon_peers,
                scenario_metric("cash_value_xirr"),
                "higher_mechanical",
                "Higher is an illustrated surrender cashflow return under this named non-guaranteed scenario.",
            )
            metrics[f"{scenario_id}_cash_value_irr"] = _observation_set(
                horizon_peers,
                scenario_metric("cash_value_irr"),
                "higher_mechanical",
                "Higher is an illustrated periodic-time surrender return under this named non-guaranteed scenario.",
            )
            metrics[f"{scenario_id}_cash_value_premium_recovery"] = (
                _observation_set(
                    horizon_peers,
                    scenario_metric("cash_value_premium_recovery"),
                    "higher_mechanical",
                    "Higher means more illustrated surrender value per cumulative premium under this named non-guaranteed scenario.",
                )
            )
            metrics[f"{scenario_id}_death_benefit_cv_ratio"] = _observation_set(
                horizon_peers,
                scenario_metric("death_benefit_cv_ratio"),
                "orientation_only",
                "Higher is more protection-weighted and lower is more liquidity-weighted within this illustrated scenario; neither is universally superior.",
            )
            metrics[
                f"{scenario_id}_death_benefit_purchasing_power_retention"
            ] = _observation_set(
                horizon_peers,
                scenario_metric("death_benefit_purchasing_power_retention"),
                "higher_mechanical",
                "Higher means more purchasing power is retained under the common inflation assumption; the illustrated amount remains non-guaranteed.",
            )
            metrics[f"{scenario_id}_death_non_guaranteed_dependency"] = (
                _observation_set(
                    horizon_peers,
                    lambda row, sid=scenario_id: (
                        None
                        if row is None
                        else _metric_value(
                            row["scenarios"][sid].get("death_non_guaranteed_dependency")
                        )
                    ),
                    "lower_mechanical",
                    "Lower means less of the illustrated death benefit depends on non-guaranteed values.",
                )
            )
            metrics[f"{scenario_id}_cash_value_non_guaranteed_dependency"] = (
                _observation_set(
                    horizon_peers,
                    lambda row, sid=scenario_id: (
                        None
                        if row is None
                        else _metric_value(
                            row["scenarios"][sid].get(
                                "cash_value_non_guaranteed_dependency"
                            )
                        )
                    ),
                    "lower_mechanical",
                    "Lower means less of the illustrated surrender value depends on non-guaranteed values.",
                )
            )
            metrics[f"{scenario_id}_death_ngr"] = metrics[
                f"{scenario_id}_death_non_guaranteed_dependency"
            ]
            metrics[f"{scenario_id}_cash_value_ngr"] = metrics[
                f"{scenario_id}_cash_value_non_guaranteed_dependency"
            ]
            for stress_rate in ("0.00", "0.02", "0.03", "0.04"):
                metrics[
                    f"{scenario_id}_real_death_benefit_inflation_{stress_rate}"
                ] = _observation_set(
                    horizon_peers,
                    lambda row, sid=scenario_id, rate=stress_rate: (
                        _stress_real_amount(row, rate, sid)
                    ),
                    "higher_mechanical",
                    f"Higher is a larger illustrated death benefit in today's money under a fixed {float(stress_rate):.0%} inflation stress; the benefit remains non-guaranteed.",
                )
        horizon_results.append({"policy_year": horizon, "metrics": metrics})

    breakeven_peers = []
    for product_id, product_name, case in peers:
        value = case["summary"]["guaranteed_breakeven"]["first"].get("value")
        breakeven_peers.append((product_id, product_name, {"value": value}))
    breakeven = _observation_set(
        breakeven_peers,
        lambda item: (
            None if item is None or item["value"] is None else float(item["value"])
        ),
        "lower_mechanical",
        "Earlier observed guaranteed cash-value breakeven is mechanically earlier; no interpolation is used.",
    )
    irr_breakeven: Dict[str, Any] = {}
    for threshold in ("0.01", "0.02", "0.03"):
        threshold_peers = []
        for product_id, product_name, case in peers:
            item = case["summary"]["guaranteed_cash_value_irr_breakeven"].get(
                threshold, {}
            )
            value = item.get("first", {}).get("value")
            threshold_peers.append((product_id, product_name, {"value": value}))
        irr_breakeven[threshold] = _observation_set(
            threshold_peers,
            lambda item: (
                None
                if item is None or item["value"] is None
                else float(item["value"])
            ),
            "lower_mechanical",
            f"Earlier first observed guaranteed cash-value IRR at or above {float(threshold):.0%} is mechanically earlier; no interpolation is used.",
        )
    return {
        "comparison_version": COMPARATOR_VERSION,
        "case_id": case_id,
        "comparable": True,
        "reason_codes": [],
        "basis_digest": next(iter(digests)),
        "currency": next(iter(currencies)),
        "products": [product_id for product_id, _, _ in peers],
        "guaranteed_breakeven": breakeven,
        "guaranteed_cash_value_irr_breakeven": irr_breakeven,
        "decision_scope": {
            "ranking_unit": "metric_by_policy_year_and_named_scenario",
            "overall_winner": None,
            "statement": "Rankings are local to each disclosed horizon, metric, guarantee basis, and named scenario. They must not be described as a full-cycle overall winner.",
        },
        "horizons": horizon_results,
    }
