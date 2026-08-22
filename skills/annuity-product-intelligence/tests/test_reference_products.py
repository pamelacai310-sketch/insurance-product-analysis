from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path


SKILL_ROOT = Path(__file__).resolve().parents[1]
SCRIPTS_DIR = SKILL_ROOT / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

from annuity_intelligence.cli import run_pipeline  # noqa: E402


PRODUCT_ROOT = SKILL_ROOT / "assets" / "reference-products" / "products"


class ReferenceProductRegressionTests(unittest.TestCase):
    def _run(self, filename: str) -> dict:
        with tempfile.TemporaryDirectory() as temporary_directory:
            return run_pipeline(
                PRODUCT_ROOT / filename,
                Path(temporary_directory) / "results",
            )

    @staticmethod
    def _configuration(run: dict) -> dict:
        return run["metrics"]["configurations"][0]

    @staticmethod
    def _annual_row(configuration: dict, policy_year: int) -> dict:
        rows = configuration["scenarios"]["guaranteed"][
            "annual_decision_table"
        ]["rows"]
        return next(row for row in rows if row["policy_year"] == policy_year)

    def test_dao_complete_annual_schedule_and_maturity_boundary(self) -> None:
        config = self._configuration(
            self._run("dao-hsbc-jingcai-fengnian-2026.json")
        )
        annual = config["scenarios"]["guaranteed"]["annual_decision_table"]

        self.assertEqual(annual["year_count"], 65)
        self.assertTrue(annual["complete_annual_cash_value_coverage"])
        self.assertEqual(
            self._annual_row(config, 1)["cumulative_premium"]["value"], "200000"
        )
        self.assertEqual(
            self._annual_row(config, 1)["cash_value"]["value"], "87155.71"
        )
        self.assertEqual(
            self._annual_row(config, 5)["annual_guaranteed_annuity"]["value"],
            "23944.93",
        )
        final = self._annual_row(config, 65)
        self.assertEqual(final["cash_value"]["status"], "not_applicable")
        self.assertEqual(final["annual_maturity_benefit"]["value"], "23944.93")

    def test_pia_first_annuity_zeroes_cash_value_and_preserves_guarantee(self) -> None:
        config = self._configuration(
            self._run("pia-hsbc-jingcai-yannian-2026.json")
        )
        year_20 = self._annual_row(config, 20)

        self.assertEqual(year_20["cash_value"]["value"], "0")
        self.assertEqual(year_20["annual_guaranteed_annuity"]["value"], "47284.9")
        self.assertEqual(year_20["death_settlement"]["value"], "54302")
        self.assertEqual(year_20["maximum_policy_loan"]["status"], "not_applicable")
        death_curve = config["scenarios"]["guaranteed"]["early_death"]["curve"]
        age_60 = next(row for row in death_curve if row["target_age"] == 60)
        self.assertEqual(age_60["beneficiary_continuation"]["value"], "898413.1")
        self.assertEqual(age_60["death_wealth_multiple"]["value"], "1")

    def test_allianz_full_cash_values_recover_at_year_66(self) -> None:
        config = self._configuration(
            self._run("allianz-anxiang-fengying-c.json")
        )
        annual = config["scenarios"]["guaranteed"]["annual_decision_table"]
        liquidity = config["scenarios"]["guaranteed"]["liquidity"]

        self.assertEqual(annual["year_count"], 66)
        self.assertEqual(
            self._annual_row(config, 20)["annual_guaranteed_annuity"]["value"],
            "26608",
        )
        self.assertEqual(self._annual_row(config, 66)["cash_value"]["value"], "1000000")
        self.assertEqual(liquidity["capital_recovery_year"]["value"], "66")
        self.assertEqual(liquidity["locked_capital_years"]["value"], 65)

    def test_reference_outputs_include_zero_inflation_and_age_irr_curve(self) -> None:
        config = self._configuration(
            self._run("pia-hsbc-jingcai-yannian-2026.json")
        )
        curve = config["scenarios"]["guaranteed"][
            "survival_longevity_inflation_relative_value"
        ]["curve"]
        age_80 = next(row for row in curve if row["target_age"] == 80)
        zero_inflation = next(
            row
            for row in age_80["inflation_scenarios"]
            if row["inflation_rate"] == "0"
        )

        self.assertEqual(zero_inflation["real_income_retention"]["value"], "1")
        self.assertEqual(age_80["longevity_leverage_10y"]["value"], "0.472849")
        self.assertEqual(age_80["income_only_irr"]["value"]["status"], "unique_root")


if __name__ == "__main__":
    unittest.main()
