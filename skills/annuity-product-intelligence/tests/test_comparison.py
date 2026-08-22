from __future__ import annotations

import sys
import unittest
from pathlib import Path


SCRIPTS_DIR = Path(__file__).resolve().parents[1] / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

from annuity_intelligence.comparison import compare_products  # noqa: E402
from test_core import make_product  # noqa: E402
from test_metrics import run_product  # noqa: E402


class ProductComparisonTests(unittest.TestCase):
    def test_same_dimensions_and_premium_are_compatible(self) -> None:
        first = make_product("annuity-a")
        second = make_product("annuity-b")
        second_config = second["configurations"][0]
        second_config["annuity_rules"][0]["amount"]["value"] = "12000"
        second_config["cash_values"][0]["amount"]["value"] = "90000"

        comparison = compare_products([run_product(first), run_product(second)])

        self.assertEqual(comparison["common_configuration_count"], 1)
        self.assertIsNone(comparison["aggregate_score"])
        comparison_slice = comparison["comparison_slices"][0]
        self.assertTrue(comparison_slice["compatible"])
        self.assertEqual(comparison_slice["normalization"], "same_total_premium")
        age_62 = next(
            item
            for item in comparison_slice["survival_age_comparisons"]
            if item["target_age"] == 62
        )
        ranks = {
            row["product_id"]: row["cumulative_annuity_rank"] for row in age_62["rows"]
        }
        self.assertEqual(ranks, {"annuity-a": 2, "annuity-b": 1})

    def test_different_premium_without_proportionality_is_incompatible(self) -> None:
        first = make_product(
            "annuity-a", premium="100000", proportionality_verified=False
        )
        second = make_product(
            "annuity-b", premium="120000", proportionality_verified=False
        )

        comparison = compare_products([run_product(first), run_product(second)])

        self.assertEqual(comparison["common_configuration_count"], 1)
        comparison_slice = comparison["comparison_slices"][0]
        self.assertFalse(comparison_slice["compatible"])
        self.assertIsNone(comparison_slice["normalization"])
        self.assertEqual(comparison_slice["survival_age_comparisons"], [])
        self.assertEqual(comparison_slice["liquidity_month_comparisons"], [])
        self.assertTrue(
            any(
                "excluded from rankings" in warning
                for warning in comparison_slice["warnings"]
            )
        )

    def test_different_product_options_remain_visible_but_are_not_compared(
        self,
    ) -> None:
        first = make_product("annuity-a")
        second = make_product("annuity-b")
        second["configurations"][0]["dimensions"]["product_option_code"] = "B"

        comparison = compare_products([run_product(first), run_product(second)])

        self.assertEqual(comparison["common_configuration_count"], 0)
        self.assertEqual(len(comparison["comparison_slices"]), 2)
        self.assertTrue(
            all(not item["compatible"] for item in comparison["comparison_slices"])
        )
        self.assertTrue(
            all(item["missing_product_ids"] for item in comparison["comparison_slices"])
        )

    def test_premium_timing_mismatch_blocks_ranking(self) -> None:
        first = make_product("annuity-a")
        second = make_product("annuity-b")
        second["configurations"][0]["premium_events"][0]["policy_month"] = 1

        comparison = compare_products([run_product(first), run_product(second)])

        comparison_slice = comparison["comparison_slices"][0]
        self.assertFalse(comparison_slice["compatible"])
        self.assertTrue(
            any("Premium timing" in warning for warning in comparison_slice["warnings"])
        )


if __name__ == "__main__":
    unittest.main()
