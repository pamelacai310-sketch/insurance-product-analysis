from decimal import Decimal
import unittest

from ric_dividend_estimator import (
    REFERENCE_ANNUAL_PREMIUM,
    REFERENCE_CONFIGURATION,
    REFERENCE_PREMIUM_RATE_PER_1000,
    RICConfiguration,
    UnsupportedConfigurationError,
    calculate_basic_amount,
    estimate_dividends,
    load_reference_rows,
    validate_reference_rows,
)


class RICDividendEstimatorTests(unittest.TestCase):
    def test_reference_rate_reconstructs_basic_amount(self) -> None:
        self.assertEqual(
            calculate_basic_amount(
                REFERENCE_ANNUAL_PREMIUM, REFERENCE_PREMIUM_RATE_PER_1000
            ),
            Decimal("100000"),
        )

    def test_reference_schedule_and_rounding_audit(self) -> None:
        rows = load_reference_rows()
        self.assertEqual(len(rows), 60)
        self.assertEqual(rows[0].scenario2_annual_increment, Decimal("634"))
        self.assertEqual(rows[9].scenario2_annual_increment, Decimal("3780"))
        self.assertEqual(rows[59].scenario2_annual_increment, Decimal("29673"))
        self.assertEqual(rows[59].scenario2_cumulative_increment, Decimal("354817"))
        self.assertEqual(rows[59].scenario2_terminal_dividend, Decimal("1849185"))
        self.assertTrue(validate_reference_rows(rows))

    def test_same_configuration_scales_linearly(self) -> None:
        result = estimate_dividends(REFERENCE_CONFIGURATION, Decimal("200000"))
        self.assertEqual(
            result[0]["scenario2_illustrated_annual_increment"], Decimal("1268")
        )
        self.assertEqual(
            result[-1]["scenario2_illustrated_annual_increment"], Decimal("59346")
        )
        self.assertTrue(
            all(row["scenario1_illustrated_annual_increment"] == 0 for row in result)
        )
        self.assertTrue(
            all(row["actual_declared_annual_increment"] is None for row in result)
        )

    def test_historical_realization_rate_is_only_a_proxy(self) -> None:
        result = estimate_dividends(
            REFERENCE_CONFIGURATION,
            Decimal("100000"),
            realization_rate=Decimal("0.857"),
        )
        self.assertEqual(
            result[0]["historical_rate_adjusted_proxy"], Decimal("543.338")
        )
        self.assertIsNone(result[0]["actual_declared_annual_increment"])

    def test_cross_configuration_inference_is_blocked(self) -> None:
        female_32_case = RICConfiguration(
            entry_age=32,
            gender="F",
            payment_years=5,
            coverage_to_age=85,
            first_annuity_policy_year=5,
            extra_annuity_age=50,
        )
        with self.assertRaises(UnsupportedConfigurationError):
            estimate_dividends(female_32_case, Decimal("3000"))


if __name__ == "__main__":
    unittest.main()
