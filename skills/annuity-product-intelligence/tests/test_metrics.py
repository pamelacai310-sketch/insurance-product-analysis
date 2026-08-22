from __future__ import annotations

import sys
import unittest
from decimal import Decimal
from pathlib import Path


SCRIPTS_DIR = Path(__file__).resolve().parents[1] / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

from annuity_intelligence.common import ValidationError  # noqa: E402
from annuity_intelligence.core import build_cashflows, normalize_product  # noqa: E402
from annuity_intelligence.metrics import (  # noqa: E402
    _real_amount,
    aggregate_cashflows,
    analyze_product,
    npv,
    xirr_all,
)
from test_core import make_product  # noqa: E402


def run_product(data: dict, benchmark: dict | None = None) -> dict:
    normalized = normalize_product(
        data,
        allow_embedded_fixtures=True,
    )
    cashflows = build_cashflows(normalized)
    metrics = analyze_product(normalized, cashflows, benchmark)
    return {"normalized": normalized, "cashflows": cashflows, "metrics": metrics}


class IrrTests(unittest.TestCase):
    def test_decimal_discounting_handles_values_beyond_float_range(self) -> None:
        amount = Decimal("1e400")
        rate = Decimal("-0.99999999999999999999")

        discounted = npv([(0, amount), (12, Decimal("-1"))], rate)
        real = _real_amount(amount, 1200, Decimal("0.02"))

        self.assertTrue(discounted.is_finite())
        self.assertTrue(real.is_finite())
        self.assertGreater(discounted, Decimal("9e399"))
        self.assertGreater(real, Decimal("0"))

    def test_even_multiplicity_root_is_reported(self) -> None:
        result = xirr_all(
            [(0, Decimal("-100")), (12, Decimal("220")), (24, Decimal("-121"))]
        )

        self.assertEqual(result["status"], "unique_root")
        self.assertAlmostEqual(float(result["selected_rate"]), 0.10, places=9)

    def test_close_distinct_roots_are_not_coalesced_or_replaced_by_stationary_point(
        self,
    ) -> None:
        first_rate = Decimal("0.1")
        second_rate = Decimal("0.1001")
        first_discount = Decimal(1) / (Decimal(1) + first_rate)
        second_discount = Decimal(1) / (Decimal(1) + second_rate)
        result = xirr_all(
            [
                (0, first_discount * second_discount),
                (12, -(first_discount + second_discount)),
                (24, Decimal(1)),
            ]
        )

        self.assertEqual(result["status"], "multiple_roots")
        roots = [Decimal(root["annual_effective_rate"]) for root in result["roots"]]
        self.assertEqual(len(roots), 2)
        self.assertLess(abs(roots[0] - first_rate), Decimal("1e-9"))
        self.assertLess(abs(roots[1] - second_rate), Decimal("1e-9"))

    def test_long_horizon_irr_is_stable(self) -> None:
        result = xirr_all([(0, Decimal("-100")), (900, Decimal("200"))])

        self.assertEqual(result["status"], "unique_root")
        expected = (Decimal("2") ** (Decimal("1") / Decimal("75"))) - Decimal("1")
        actual = Decimal(result["selected_rate"])
        self.assertLess(abs(actual - expected), Decimal("0.000000001"))

    def test_multiple_irr_roots_are_all_reported(self) -> None:
        result = xirr_all(
            [(0, Decimal("-100")), (12, Decimal("230")), (24, Decimal("-132"))]
        )

        self.assertEqual(result["status"], "multiple_roots")
        roots = sorted(
            Decimal(root["annual_effective_rate"]) for root in result["roots"]
        )
        self.assertEqual(len(roots), 2)
        self.assertLess(abs(roots[0] - Decimal("0.10")), Decimal("0.000000001"))
        self.assertLess(abs(roots[1] - Decimal("0.20")), Decimal("0.000000001"))
        self.assertIsNone(result["selected_rate"])

    def test_negative_root_and_no_root_are_distinct(self) -> None:
        negative = xirr_all([(0, Decimal("-100")), (12, Decimal("90"))])
        no_root = xirr_all(
            [(0, Decimal("-100")), (12, Decimal("50")), (24, Decimal("-100"))]
        )

        self.assertEqual(negative["status"], "unique_root")
        self.assertLess(
            abs(Decimal(negative["selected_rate"]) - Decimal("-0.10")),
            Decimal("0.000000001"),
        )
        self.assertEqual(no_root["status"], "no_root")
        self.assertEqual(no_root["roots"], [])

    def test_same_month_cashflows_are_aggregated_before_root_analysis(self) -> None:
        aggregated = aggregate_cashflows(
            [
                (12, Decimal("-100")),
                (12, Decimal("60")),
                (12, Decimal("40")),
                (24, Decimal("10")),
            ]
        )

        self.assertEqual(aggregated, [(24, Decimal("10"))])


class ProductMetricTests(unittest.TestCase):
    def test_analysis_end_age_caps_reported_metric_grid(self) -> None:
        data = make_product()
        data["analysis_assumptions"]["analysis_end_age"] = 61

        config_metrics = run_product(data)["metrics"]["configurations"][0]
        survival_curve = config_metrics["scenarios"]["guaranteed"][
            "survival_longevity_inflation_relative_value"
        ]["curve"]
        death_curve = config_metrics["scenarios"]["guaranteed"]["early_death"]["curve"]

        self.assertEqual([row["target_age"] for row in survival_curve], [61])
        self.assertEqual([row["target_age"] for row in death_curve], [61])

    def test_continuation_only_death_outcome_remains_calculable(self) -> None:
        data = make_product()
        config = data["configurations"][0]
        config["death_benefit"]["schedule"] = [
            {
                "policy_month": 12,
                "event_order": 50,
                "status": "not_applicable",
                "timing": "after_annuity",
                "evidence_refs": ["ev1"],
                "contingency": "contractual",
            }
        ]
        config["death_benefit"]["beneficiary_continuation"] = {
            "mode": "remaining_guaranteed_annuity",
            "through_policy_month": 36,
            "evidence_refs": ["ev1"],
        }

        result = run_product(data)["metrics"]["configurations"][0]
        row = result["scenarios"]["guaranteed"]["early_death"]["curve"][0]

        self.assertEqual(row["status"], "available")
        self.assertEqual(row["death_settlement"]["status"], "not_applicable")
        self.assertEqual(row["beneficiary_continuation"]["value"], "23100")
        self.assertEqual(row["net_estate_outcome"]["status"], "available")

    def test_death_schedule_only_scenario_is_included(self) -> None:
        data = make_product()
        data["configurations"][0]["death_benefit"]["schedule"].append(
            {
                **data["configurations"][0]["death_benefit"]["schedule"][0],
                "amount": {"value": "95000", "unit": "CNY"},
                "guarantee_basis": "illustrated",
                "scenario_id": "illustrated_death",
                "scenario_composition": "total",
            }
        )

        scenarios = run_product(data)["metrics"]["configurations"][0]["scenarios"]

        self.assertIn("illustrated_death", scenarios)

    def test_non_guaranteed_liquidity_uses_its_total_cash_value_schedule_only(
        self,
    ) -> None:
        data = make_product()
        config = data["configurations"][0]
        config["cash_values"].extend(
            [
                {
                    **config["cash_values"][0],
                    "amount": {"value": "95000", "unit": "CNY"},
                    "guarantee_basis": "illustrated",
                    "scenario_id": "illustrated_cash",
                    "scenario_composition": "total",
                },
                {
                    **config["cash_values"][1],
                    "amount": {"value": "105000", "unit": "CNY"},
                    "guarantee_basis": "illustrated",
                    "scenario_id": "illustrated_cash",
                    "scenario_composition": "total",
                },
            ]
        )

        scenario = run_product(data)["metrics"]["configurations"][0]["scenarios"][
            "illustrated_cash"
        ]
        curve = scenario["liquidity"]["curve"]

        self.assertEqual([row["policy_month"] for row in curve], [12, 24])
        self.assertEqual(
            [row["cash_value"]["value"] for row in curve], ["95000", "105000"]
        )

    def test_metric_provenance_hash_binds_cashflow_amounts(self) -> None:
        first = run_product(make_product())
        changed = make_product()
        changed["configurations"][0]["annuity_rules"][0]["amount"]["value"] = "20000"
        second = run_product(changed)

        first_metric = first["metrics"]["configurations"][0]["capital_efficiency"][
            "income_conversion_rate"
        ]
        second_metric = second["metrics"]["configurations"][0]["capital_efficiency"][
            "income_conversion_rate"
        ]

        self.assertNotEqual(first_metric["value"], second_metric["value"])
        self.assertNotEqual(
            first_metric["provenance"]["calculation_config_sha256"],
            second_metric["provenance"]["calculation_config_sha256"],
        )

    def test_liquidity_counts_annuity_received_before_surrender(self) -> None:
        run = run_product(make_product())
        liquidity = run["metrics"]["configurations"][0]["scenarios"]["guaranteed"][
            "liquidity"
        ]
        month_24 = next(row for row in liquidity["curve"] if row["policy_month"] == 24)

        self.assertEqual(month_24["cash_value_ratio"]["value"], "0.85")
        self.assertEqual(month_24["capital_returned_ratio"]["value"], "1.06")
        self.assertEqual(liquidity["total_benefit_recovery_month"]["value"], 24)
        self.assertEqual(liquidity["cash_value_recovery_month"]["status"], "missing")

    def test_inflation_deflates_nominal_annuity_cashflows(self) -> None:
        run = run_product(make_product())
        survival = run["metrics"]["configurations"][0]["scenarios"]["guaranteed"]
        curve = survival["survival_longevity_inflation_relative_value"]["curve"]
        age_62 = next(row for row in curve if row["target_age"] == 62)
        inflation = age_62["inflation_scenarios"][0]

        nominal = Decimal(age_62["cumulative_annuity"]["value"])
        real = Decimal(inflation["real_cumulative_annuity"]["value"])
        self.assertEqual(nominal, Decimal("21000"))
        self.assertLess(real, nominal)
        self.assertLess(abs(real - Decimal("18181.81818181818")), Decimal("0.000001"))

    def test_early_death_includes_prior_annuity_and_settlement(self) -> None:
        run = run_product(make_product())
        early_death = run["metrics"]["configurations"][0]["scenarios"]["guaranteed"][
            "early_death"
        ]
        age_62 = next(row for row in early_death["curve"] if row["target_age"] == 62)

        self.assertEqual(age_62["status"], "available")
        self.assertEqual(age_62["prior_contract_receipts"]["value"], "21000")
        self.assertEqual(age_62["death_settlement"]["value"], "80000")
        self.assertEqual(age_62["nominal_recovery_ratio"]["value"], "1.01")
        self.assertEqual(age_62["net_estate_outcome"]["value"], "1000")

    def test_benchmark_currency_mismatch_blocks_relative_value(self) -> None:
        benchmark = {
            "benchmark_id": "usd-govt",
            "currency": "USD",
            "as_of_date": "2026-01-01",
            "source_sha256": "f" * 64,
            "points": [{"term_years": "2", "annual_effective_rate": "0.03"}],
        }

        with self.assertRaisesRegex(ValidationError, "benchmark currency"):
            run_product(make_product(), benchmark)


if __name__ == "__main__":
    unittest.main()
