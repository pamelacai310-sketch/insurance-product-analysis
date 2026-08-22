from __future__ import annotations

# The portable Skill keeps its package under scripts/, so tests add that
# directory before importing the package.
# ruff: noqa: E402

import copy
from datetime import date
from decimal import Decimal
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest import mock


REPO_ROOT = Path(__file__).resolve().parents[1]
SKILL_ROOT = REPO_ROOT / "skills" / "leveraged-life-product-intelligence"
SCRIPT = SKILL_ROOT / "scripts" / "llpi.py"
sys.path.insert(0, str(SKILL_ROOT / "scripts"))

from llpi import __version__
from llpi.comparator import compare_reports
from llpi.irr import irr, xirr
from llpi.metrics import analyze_product
from llpi.llm_fallback import (
    HTTPJSONLLMFallback,
    LLMFallbackConfig,
    LLMFallbackNotConfigured,
    LLMFallbackResponseError,
)
import llpi.llm_fallback as llm_fallback_module
from llpi.parsers import ConfidenceRouter, parse_file
import llpi.parsers as parser_module
from llpi.validate import validate_product
import llpi.validate as validate_module


def load(path: Path) -> dict:
    with path.open(encoding="utf-8") as handle:
        return json.load(handle)


FIXTURES = SKILL_ROOT / "assets" / "benchmarks"
GOLD = REPO_ROOT / "tests" / "gold" / "leveraged_life"


class LeveragedLifeMetricsTests(unittest.TestCase):
    def assertRate(self, actual, expected):
        self.assertIsNotNone(actual)
        self.assertAlmostEqual(float(actual), float(expected), places=9)

    def test_single_pay_gold_metrics(self):
        report = analyze_product(
            load(FIXTURES / "single-pay-alpha.json"), strict_evidence=True
        )
        self.assertEqual(report["analysis_status"], "complete")
        case = report["case_reports"][0]
        expected = load(GOLD / "alpha_expected.json")
        self.assertEqual(case["case_id"], expected["case_id"])
        self.assertEqual(
            case["fingerprint"]["fingerprint_id"], expected["fingerprint_id"]
        )
        self.assertEqual(
            case["summary"]["guaranteed_breakeven"]["first"]["value"],
            expected["guaranteed_breakeven_year"],
        )
        rows = {str(row["policy_year"]): row for row in case["rows"]}
        for year, gold in expected["rows"].items():
            row = rows[year]["guaranteed"]
            self.assertRate(row["death_leverage"]["value"], gold["death_leverage"])
            self.assertRate(row["death_irr"]["value"], gold["death_irr"])
            self.assertRate(row["cash_value_irr"]["value"], gold["cash_value_irr"])
            self.assertRate(
                row["protection_liquidity_ratio"]["value"],
                gold["protection_liquidity_ratio"],
            )
            self.assertEqual(
                row["inflation_adjusted_death_benefit"]["value"],
                gold["real_death_benefit"],
            )

    def test_three_pay_gold_metrics(self):
        report = analyze_product(
            load(FIXTURES / "three-pay-non-guaranteed.json"), strict_evidence=True
        )
        case = report["case_reports"][0]
        expected = load(GOLD / "three_pay_expected.json")
        self.assertEqual(
            case["fingerprint"]["fingerprint_id"], expected["fingerprint_id"]
        )
        self.assertEqual(case["summary"]["guaranteed_breakeven"]["first"]["value"], 4)
        rows = {str(row["policy_year"]): row for row in case["rows"]}
        for year, gold in expected["rows"].items():
            row = rows[year]
            self.assertEqual(row["cumulative_premium"], gold["cumulative_premium"])
            self.assertRate(
                row["guaranteed"]["death_leverage"]["value"], gold["death_leverage"]
            )
            self.assertRate(row["guaranteed"]["death_irr"]["value"], gold["death_irr"])
            self.assertRate(
                row["guaranteed"]["cash_value_irr"]["value"], gold["cash_value_irr"]
            )
        year_ten = rows["10"]
        gold_ten = expected["rows"]["10"]
        current = year_ten["scenarios"]["current"]
        self.assertRate(
            current["death_non_guaranteed_dependency"]["value"],
            gold_ten["death_non_guaranteed_dependency"],
        )
        self.assertRate(
            current["cash_value_non_guaranteed_dependency"]["value"],
            gold_ten["cash_non_guaranteed_dependency"],
        )
        self.assertRate(
            year_ten["guaranteed"]["protection_liquidity_ratio"]["value"],
            gold_ten["protection_liquidity_ratio"],
        )
        self.assertEqual(
            year_ten["guaranteed"]["inflation_adjusted_death_benefit"]["value"],
            gold_ten["real_death_benefit"],
        )

    def test_leap_year_xirr_is_act_365f(self):
        gold = load(GOLD / "leap_xirr_expected.json")
        cashflows = [
            (date.fromisoformat(item["date"]), Decimal(item["amount"]))
            for item in gold["cashflows"]
        ]
        result = xirr(cashflows)
        self.assertEqual(result.status, "ok")
        self.assertRate(result.to_dict()["value"], gold["xirr"])
        self.assertNotAlmostEqual(result.to_dict()["value"], 0.1, places=5)

    def test_ambiguous_irr_is_not_selected(self):
        result = irr(
            [(0.0, Decimal("-100")), (1.0, Decimal("230")), (2.0, Decimal("-132"))]
        )
        self.assertEqual(result.status, "ambiguous")
        self.assertIsNone(result.rate)

    def test_zero_cash_value_never_serializes_infinity(self):
        data = load(FIXTURES / "single-pay-alpha.json")
        data["cases"][0]["scenario_definitions"] = {}
        for row in data["cases"][0]["projection"]:
            row["death_benefit"]["scenarios"] = {}
            row["cash_surrender_value"]["scenarios"] = {}
        data["cases"][0]["projection"][0]["cash_surrender_value"]["guaranteed"] = "0.00"
        report = analyze_product(data, strict_evidence=True)
        value = report["case_reports"][0]["rows"][0]["guaranteed"][
            "protection_liquidity_ratio"
        ]
        self.assertEqual(value["status"], "undefined")
        self.assertEqual(value["reason"], "zero_liquidity")
        self.assertIsNone(value["value"])
        json.dumps(report, allow_nan=False)

    def test_derived_metrics_cite_timing_and_value_input_families(self):
        report = analyze_product(
            load(FIXTURES / "single-pay-alpha.json"), strict_evidence=True
        )
        case = report["case_reports"][0]
        row = next(item for item in case["rows"] if item["policy_year"] == 10)
        irr_inputs = row["guaranteed"]["death_irr"]["inputs"]
        xirr_inputs = row["guaranteed"]["death_xirr"]["inputs"]
        self.assertIn("/cases/0/premium_cashflows/0/amount", irr_inputs)
        self.assertIn("/cases/0/premium_cashflows/0/time_years", irr_inputs)
        self.assertIn("/cases/0/projection/3/time_years", irr_inputs)
        self.assertIn("/cases/0/premium_cashflows/0/date", xirr_inputs)
        self.assertIn("/cases/0/projection/3/date", xirr_inputs)
        self.assertIn(
            "/cases/0/projection/3/time_years",
            row["guaranteed"]["inflation_adjusted_death_benefit"]["inputs"],
        )
        self.assertTrue(row["cumulative_premium_inputs"])
        self.assertEqual(
            case["summary"]["guaranteed_breakeven"]["first"]["inputs"],
            ["/cases/0/premium_cashflows", "/cases/0/projection"],
        )
        self.assertTrue(case["summary"]["lineage"]["total_scheduled_premium"])

    def test_fingerprint_never_substitutes_sparse_anchor_rows(self):
        data = load(FIXTURES / "single-pay-alpha.json")
        case = data["cases"][0]
        case["case_id"] = "LLPI-DOC-SPARSE-FINGERPRINT-v1"
        case["basis"]["kind"] = "document_illustration"
        case["premium_cashflows"].append(
            {"date": "2046-01-01", "time_years": "20", "amount": "100000.00"}
        )
        case["projection"] = [
            row for row in case["projection"] if row["policy_year"] not in {1, 20}
        ]
        report = analyze_product(data, strict_evidence=True)
        self.assertEqual(report["analysis_status"], "complete")
        fingerprint = report["case_reports"][0]["fingerprint"]
        self.assertEqual(fingerprint["features"]["premium_pattern"], "extended_pay")
        self.assertEqual(
            fingerprint["features"]["initial_guaranteed_death_leverage"],
            "unavailable",
        )
        self.assertEqual(
            fingerprint["features"]["pay_end_liquidity_recovery"], "unavailable"
        )
        self.assertEqual(
            fingerprint["features"]["non_guaranteed_death_dependency_20y"],
            "unavailable",
        )
        self.assertIsNone(fingerprint["raw"]["initial_observation_policy_year"])
        self.assertEqual(fingerprint["raw"]["pay_end_target_policy_year"], 21)
        self.assertIsNone(fingerprint["raw"]["pay_end_observation_policy_year"])
        self.assertIsNone(
            fingerprint["raw"]["non_guaranteed_dependency_observation_policy_year"]
        )

    def test_breakeven_reports_absent_and_sustained_without_interpolation(self):
        never = load(FIXTURES / "single-pay-alpha.json")
        for row in never["cases"][0]["projection"]:
            row["cash_surrender_value"]["guaranteed"] = "90000.00"
            row["cash_surrender_value"]["scenarios"]["current"] = "90000.00"
        never_break = analyze_product(never)["case_reports"][0]["summary"][
            "guaranteed_breakeven"
        ]
        self.assertEqual(never_break["first"]["reason"], "outside_projection_horizon")

        temporary = load(FIXTURES / "single-pay-alpha.json")
        row_by_year = {
            row["policy_year"]: row for row in temporary["cases"][0]["projection"]
        }
        row_by_year[5]["cash_surrender_value"]["guaranteed"] = "90000.00"
        row_by_year[5]["cash_surrender_value"]["scenarios"]["current"] = "90000.00"
        breakeven = analyze_product(temporary)["case_reports"][0]["summary"][
            "guaranteed_breakeven"
        ]
        self.assertEqual(breakeven["first"]["value"], 3)
        self.assertEqual(breakeven["sustained"]["value"], 10)


class LeveragedLifeValidationTests(unittest.TestCase):
    def test_all_benchmarks_pass_strict_evidence_validation(self):
        for path in sorted(FIXTURES.glob("*.json")):
            with self.subTest(path=path.name):
                result = validate_product(load(path), strict_evidence=True)
                self.assertTrue(result.ok, result.to_dict())
                self.assertEqual(result.warnings, [])

    def test_customer_profile_keys_are_rejected(self):
        data = load(FIXTURES / "single-pay-alpha.json")
        data["extensions"] = {
            "customer_profile": {
                "client_age_years": 45,
                "annual_income": 1000000,
                "household_assets": 5000000,
                "family_dependents": 2,
                "desired_risk_level": "high",
                "full_name": "Example Person",
            }
        }
        result = validate_product(data)
        codes = {issue.code for issue in result.errors}
        self.assertIn("customer_data_forbidden", codes)
        self.assertIn("extensions_reserved", codes)

    def test_explicit_customer_data_in_evidence_text_is_rejected(self):
        samples = (
            "customer_name: Alice Secret\nSSN: 123-45-6789",
            "email: alice@example.com",
            "address: 1 Secret Street",
            "passport_number: P1234567",
            "telephone\n13912345678",
            "| telephone |\n| --- |\n| 13912345678 |",
        )
        for raw_text in samples:
            with self.subTest(raw_text=raw_text):
                data = load(FIXTURES / "single-pay-alpha.json")
                data["evidence"][0]["raw_text"] = raw_text
                data["evidence"][0]["content_sha256"] = hashlib.sha256(
                    raw_text.encode("utf-8")
                ).hexdigest()
                result = validate_product(data, strict_evidence=True)
                self.assertIn(
                    "customer_data_forbidden", {item.code for item in result.errors}
                )

    def test_parser_and_validator_share_customer_label_coverage(self):
        for label in sorted(parser_module.CUSTOMER_OR_PII_FIELD_NAMES):
            with self.subTest(label=label):
                self.assertTrue(
                    validate_module._contains_forbidden_client_text(
                        "%s: secret-value" % label
                    )
                )

    def test_labelled_customer_data_is_rejected_outside_evidence_text(self):
        data = load(FIXTURES / "single-pay-alpha.json")
        data["sources"][0]["uri"] = (
            "https://example.invalid/?customer_name=AliceSecret&ssn=123-45-6789"
        )
        pointer = "/product"
        data["provenance"][pointer]["raw_value"] = "email: alice@example.com"
        result = validate_product(data, strict_evidence=True)
        customer_paths = {
            item.path
            for item in result.errors
            if item.code == "customer_data_forbidden"
        }
        self.assertIn("/sources/0/uri", customer_paths)
        self.assertIn("/provenance//product/raw_value", customer_paths)

    def test_long_horizon_nominal_policy_year_accepts_leap_days(self):
        data = load(FIXTURES / "single-pay-alpha.json")
        row = copy.deepcopy(data["cases"][0]["projection"][-1])
        row.update({"policy_year": 40, "date": "2065-12-31", "time_years": "40"})
        data["cases"][0]["projection"].append(row)
        result = validate_product(data, strict_evidence=True)
        self.assertTrue(result.ok, result.to_dict())
        self.assertNotIn("date_time_mismatch", {issue.code for issue in result.issues})

    def test_source_kind_and_evidence_confidence_integrity_are_enforced(self):
        data = load(FIXTURES / "single-pay-alpha.json")
        data["sources"][0]["kind"] = "spreadsheet_from_somewhere"
        data["sources"][0]["title"] = 123
        data["evidence"][0]["confidence"] = 0.0
        incomplete_evidence = copy.deepcopy(data["evidence"][0])
        incomplete_evidence.pop("evidence_id")
        incomplete_evidence.pop("extractor")
        data["evidence"].append(incomplete_evidence)
        result = validate_product(data, strict_evidence=True)
        codes = {issue.code for issue in result.errors}
        self.assertIn("source_kind", codes)
        self.assertIn("required_field", codes)
        self.assertIn("provenance_confidence_exceeds_evidence", codes)
        self.assertIn("critical_provenance_low_confidence", codes)

    def test_product_identity_fields_require_strings(self):
        data = load(FIXTURES / "single-pay-alpha.json")
        data["product"]["product_id"] = 123
        data["product"]["name"] = 456
        data["product"]["jurisdiction"] = 789
        result = validate_product(data, strict_evidence=True)
        codes = {issue.code for issue in result.errors}
        self.assertIn("required_field", codes)
        self.assertIn("jurisdiction_type", codes)

    def test_illustrated_below_guaranteed_is_error(self):
        data = load(FIXTURES / "single-pay-alpha.json")
        data["cases"][0]["projection"][0]["death_benefit"]["scenarios"]["current"] = (
            "499999.99"
        )
        result = validate_product(data)
        self.assertIn(
            "illustrated_below_guaranteed", {issue.code for issue in result.errors}
        )

    def test_dangling_evidence_and_hash_are_errors(self):
        data = load(FIXTURES / "single-pay-alpha.json")
        data["provenance"]["/cases/0/projection"]["evidence_ids"] = ["missing"]
        data["evidence"][0]["raw_text"] = "tampered"
        result = validate_product(data)
        codes = {issue.code for issue in result.errors}
        self.assertIn("dangling_evidence", codes)
        self.assertIn("content_hash", codes)

    def test_malformed_ids_report_errors_instead_of_crashing(self):
        data = load(FIXTURES / "single-pay-alpha.json")
        data["sources"][0]["source_id"] = {"bad": "id"}
        data["evidence"][0]["evidence_id"] = ["bad"]
        data["cases"][0]["case_id"] = {"bad": "id"}
        result = validate_product(data)
        self.assertFalse(result.ok)
        self.assertGreater(len(result.errors), 0)

    def test_death_benefit_below_cash_value_is_warning(self):
        data = load(FIXTURES / "single-pay-alpha.json")
        row = data["cases"][0]["projection"][0]
        row["cash_surrender_value"]["guaranteed"] = "600000.00"
        row["cash_surrender_value"]["scenarios"]["current"] = "600000.00"
        result = validate_product(data)
        self.assertTrue(result.ok)
        self.assertIn(
            "death_benefit_below_cash_value", {issue.code for issue in result.warnings}
        )

    def test_money_scale_and_date_time_sanity_are_enforced(self):
        data = load(FIXTURES / "single-pay-alpha.json")
        data["cases"][0]["amount_scale"] = "ten_thousand"
        data["cases"][0]["premium_cashflows"][0]["amount"] = 100000.0
        data["cases"][0]["projection"][0]["date"] = "2028-12-31"
        result = validate_product(data)
        codes = {issue.code for issue in result.errors}
        self.assertIn("amount_scale", codes)
        self.assertIn("money_string", codes)
        self.assertIn("date_time_mismatch", codes)

    def test_strict_evidence_rejects_low_confidence_critical_facts(self):
        data = load(FIXTURES / "single-pay-alpha.json")
        data["provenance"]["/cases/0/projection"]["confidence"] = 0.84
        permissive = validate_product(data, strict_evidence=False)
        strict = validate_product(data, strict_evidence=True)
        self.assertTrue(permissive.ok)
        self.assertIn(
            "critical_provenance_low_confidence",
            {issue.code for issue in permissive.warnings},
        )
        self.assertFalse(strict.ok)
        self.assertIn(
            "critical_provenance_low_confidence",
            {issue.code for issue in strict.errors},
        )

    def test_committed_json_schema_accepts_gold_when_jsonschema_available(self):
        try:
            import jsonschema
        except ImportError:
            self.skipTest("jsonschema is optional")
        schema = load(SKILL_ROOT / "references" / "canonical-product-1.0.0.schema.json")
        validator = jsonschema.Draft202012Validator(
            schema, format_checker=jsonschema.FormatChecker()
        )
        for path in sorted(FIXTURES.glob("*.json")):
            errors = sorted(
                validator.iter_errors(load(path)), key=lambda item: list(item.path)
            )
            self.assertEqual(errors, [], f"{path.name}: {errors}")


class LeveragedLifeComparatorAndCliTests(unittest.TestCase):
    def setUp(self):
        self.alpha = load(FIXTURES / "single-pay-alpha.json")
        self.beta = load(FIXTURES / "single-pay-beta.json")

    def test_peer_comparison_is_order_independent_and_orientation_is_unranked(self):
        alpha_report = analyze_product(self.alpha, strict_evidence=True)
        beta_report = analyze_product(self.beta, strict_evidence=True)
        first = compare_reports(
            [beta_report, alpha_report], "LLPI-STD-1PAY-100K-v1", [10]
        )
        second = compare_reports(
            [alpha_report, beta_report], "LLPI-STD-1PAY-100K-v1", [10]
        )
        self.assertEqual(first, second)
        self.assertTrue(first["comparable"])
        leverage = first["horizons"][0]["metrics"]["guaranteed_death_leverage"][
            "observations"
        ]
        self.assertEqual(
            [item["product_id"] for item in leverage],
            ["synthetic-alpha", "synthetic-beta"],
        )
        orientation = first["horizons"][0]["metrics"]["protection_liquidity_ratio"]
        self.assertEqual(orientation["direction"], "orientation_only")
        self.assertTrue(
            all(item["rank"] is None for item in orientation["observations"])
        )
        self.assertIn("guaranteed_death_irr", first["horizons"][0]["metrics"])
        self.assertIn("guaranteed_cash_value_irr", first["horizons"][0]["metrics"])
        self.assertIn(
            "guaranteed_cash_value_premium_recovery",
            first["horizons"][0]["metrics"],
        )

    def test_basis_mismatch_refuses_ranking(self):
        alpha = copy.deepcopy(self.alpha)
        beta = copy.deepcopy(self.beta)
        for data in (alpha, beta):
            data["cases"][0]["case_id"] = "LLPI-DOC-BASIS-TEST-v1"
            data["cases"][0]["basis"]["kind"] = "document_illustration"
        beta["cases"][0]["premium_cashflows"][0]["amount"] = "110000.00"
        comparison = compare_reports(
            [analyze_product(alpha), analyze_product(beta)],
            "LLPI-DOC-BASIS-TEST-v1",
            [10],
        )
        self.assertFalse(comparison["comparable"])
        self.assertIn("benchmark_basis_mismatch", comparison["reason_codes"])

    def test_mislabeled_standard_benchmark_is_invalid(self):
        for data in (self.alpha, self.beta):
            data["cases"][0]["premium_cashflows"][0]["amount"] = "110000.00"
        reports = [analyze_product(self.alpha), analyze_product(self.beta)]
        self.assertTrue(
            all(report["analysis_status"] == "invalid" for report in reports)
        )
        comparison = compare_reports(reports, "LLPI-STD-1PAY-100K-v1", [10])
        self.assertFalse(comparison["comparable"])
        self.assertIn("validation_failed", comparison["reason_codes"])

        currency_mismatch = load(FIXTURES / "single-pay-alpha.json")
        currency_mismatch["product"]["currency"] = "USD"
        result = validate_product(currency_mismatch, strict_evidence=True)
        self.assertIn(
            "standard_benchmark_mismatch", {issue.code for issue in result.errors}
        )

    def test_unverified_evidence_and_scenario_semantics_refuse_ranking(self):
        alpha = copy.deepcopy(self.alpha)
        beta = copy.deepcopy(self.beta)
        alpha["provenance"] = {}
        beta["provenance"] = {}
        comparison = compare_reports(
            [analyze_product(alpha), analyze_product(beta)],
            "LLPI-STD-1PAY-100K-v1",
            [10],
        )
        self.assertFalse(comparison["comparable"])
        self.assertIn("critical_evidence_provenance_issue", comparison["reason_codes"])

        beta = copy.deepcopy(self.beta)
        beta["cases"][0]["scenario_definitions"]["current"]["label"] = (
            "Optimistic illustration"
        )
        comparison = compare_reports(
            [analyze_product(self.alpha), analyze_product(beta)],
            "LLPI-STD-1PAY-100K-v1",
            [10],
        )
        self.assertFalse(comparison["comparable"])
        self.assertIn("scenario_definition_mismatch", comparison["reason_codes"])

    def test_comparator_requires_two_unique_valid_product_identities(self):
        alpha_report = analyze_product(self.alpha, strict_evidence=True)
        single = compare_reports([alpha_report], "LLPI-STD-1PAY-100K-v1", [10])
        self.assertEqual(single["reason_codes"], ["insufficient_peers"])

        duplicate = compare_reports(
            [alpha_report, copy.deepcopy(alpha_report)],
            "LLPI-STD-1PAY-100K-v1",
            [10],
        )
        self.assertEqual(duplicate["reason_codes"], ["duplicate_product_id"])

        invalid = load(FIXTURES / "single-pay-alpha.json")
        invalid["product"]["product_id"] = 123
        comparison = compare_reports(
            [analyze_product(invalid), analyze_product(self.beta)],
            "LLPI-STD-1PAY-100K-v1",
            [10],
        )
        self.assertFalse(comparison["comparable"])
        self.assertIn("product_identity_invalid", comparison["reason_codes"])

    def test_amount_scaling_preserves_ratios_irrs_and_peer_order(self):
        def document_case(source):
            data = copy.deepcopy(source)
            data["cases"][0]["case_id"] = "LLPI-DOC-SCALE-TEST-v1"
            data["cases"][0]["basis"]["kind"] = "document_illustration"
            return data

        def scaled(source):
            data = document_case(source)
            case = data["cases"][0]
            for premium in case["premium_cashflows"]:
                premium["amount"] = format(Decimal(premium["amount"]) * 10, "f")
            for row in case["projection"]:
                for field in ("death_benefit", "cash_surrender_value"):
                    row[field]["guaranteed"] = format(
                        Decimal(row[field]["guaranteed"]) * 10, "f"
                    )
                    row[field]["scenarios"] = {
                        name: format(Decimal(value) * 10, "f")
                        for name, value in row[field]["scenarios"].items()
                    }
            return data

        original = compare_reports(
            [
                analyze_product(document_case(self.alpha)),
                analyze_product(document_case(self.beta)),
            ],
            "LLPI-DOC-SCALE-TEST-v1",
            [10],
        )
        scaled_comparison = compare_reports(
            [analyze_product(scaled(self.alpha)), analyze_product(scaled(self.beta))],
            "LLPI-DOC-SCALE-TEST-v1",
            [10],
        )
        for metric_name in (
            "guaranteed_death_leverage",
            "guaranteed_death_irr",
            "guaranteed_death_xirr",
            "guaranteed_cash_value_irr",
            "guaranteed_cash_value_xirr",
            "guaranteed_cash_value_premium_recovery",
            "protection_liquidity_ratio",
        ):
            left = original["horizons"][0]["metrics"][metric_name]["observations"]
            right = scaled_comparison["horizons"][0]["metrics"][metric_name][
                "observations"
            ]
            self.assertEqual(left, right)

    def test_compact_cli_is_one_stable_json_line(self):
        command = [
            sys.executable,
            str(SCRIPT),
            "analyze",
            "--input",
            str(FIXTURES / "single-pay-alpha.json"),
            "--strict-evidence",
        ]
        env_one = dict(os.environ, PYTHONHASHSEED="1", TZ="UTC")
        env_two = dict(os.environ, PYTHONHASHSEED="42", TZ="Asia/Shanghai")
        first = subprocess.run(
            command, check=True, text=True, capture_output=True, env=env_one
        )
        second = subprocess.run(
            command, check=True, text=True, capture_output=True, env=env_two
        )
        self.assertEqual(first.stdout, second.stdout)
        self.assertEqual(first.stderr, "")
        self.assertEqual(first.stdout.count("\n"), 1)
        payload = json.loads(first.stdout)
        self.assertEqual(payload["status"], "complete")

    def test_analyze_cli_is_strict_by_default_with_explicit_exploratory_opt_out(self):
        data = copy.deepcopy(self.alpha)
        data["provenance"] = {}
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "unverified.json"
            source.write_text(json.dumps(data), encoding="utf-8")
            strict = subprocess.run(
                [sys.executable, str(SCRIPT), "analyze", "--input", str(source)],
                check=False,
                text=True,
                capture_output=True,
            )
            exploratory = subprocess.run(
                [
                    sys.executable,
                    str(SCRIPT),
                    "analyze",
                    "--input",
                    str(source),
                    "--allow-unverified-evidence",
                ],
                check=False,
                text=True,
                capture_output=True,
            )
        self.assertEqual(strict.returncode, 2)
        self.assertEqual(json.loads(strict.stdout)["status"], "invalid")
        self.assertEqual(exploratory.returncode, 0)
        self.assertEqual(
            json.loads(exploratory.stdout)["status"], "complete_with_warnings"
        )

    def test_extract_cli_exposes_and_enforces_canonical_readiness(self):
        headers = (
            "currency,policy_year,premium_amount,guaranteed_death_benefit,"
            "guaranteed_cash_surrender_value,unit_scale,guarantee_classification"
        )
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            canonical_bundle = root / "canonical-extraction.json"
            canonical_extract = subprocess.run(
                [
                    sys.executable,
                    str(SCRIPT),
                    "extract",
                    "--input",
                    str(FIXTURES / "single-pay-alpha.json"),
                    "--output",
                    str(canonical_bundle),
                ],
                check=True,
                text=True,
                capture_output=True,
            )
            analyzed = subprocess.run(
                [
                    sys.executable,
                    str(SCRIPT),
                    "analyze",
                    "--input",
                    str(canonical_bundle),
                ],
                check=True,
                text=True,
                capture_output=True,
            )

            csv_source = root / "raw.csv"
            csv_source.write_text(
                headers + "\nCNY,1,100000,500000,80000,元,保证\n",
                encoding="utf-8",
            )
            csv_bundle = root / "csv-extraction.json"
            csv_extract = subprocess.run(
                [
                    sys.executable,
                    str(SCRIPT),
                    "extract",
                    "--input",
                    str(csv_source),
                    "--output",
                    str(csv_bundle),
                ],
                check=True,
                text=True,
                capture_output=True,
            )
            rejected = subprocess.run(
                [
                    sys.executable,
                    str(SCRIPT),
                    "analyze",
                    "--input",
                    str(csv_bundle),
                ],
                check=False,
                text=True,
                capture_output=True,
            )

        self.assertTrue(json.loads(canonical_extract.stdout)["canonical_ready"])
        self.assertEqual(json.loads(analyzed.stdout)["status"], "complete")
        self.assertFalse(json.loads(csv_extract.stdout)["canonical_ready"])
        self.assertEqual(rejected.returncode, 2)
        self.assertIn("not canonical-ready", rejected.stderr)

    def test_version_has_single_public_value(self):
        completed = subprocess.run(
            [sys.executable, str(SCRIPT), "--version"],
            check=True,
            text=True,
            capture_output=True,
        )
        self.assertEqual(__version__, "1.0.0")
        self.assertEqual(completed.stdout.strip(), __version__)
        schema = load(SKILL_ROOT / "references" / "canonical-product-1.0.0.schema.json")
        self.assertEqual(schema["properties"]["schema_version"]["const"], __version__)


class LeveragedLifeParserTests(unittest.TestCase):
    def test_structured_json_route_has_deterministic_content_evidence(self):
        first = parse_file(FIXTURES / "single-pay-alpha.json").to_dict()
        second = parse_file(FIXTURES / "single-pay-alpha.json").to_dict()
        self.assertEqual(first, second)
        self.assertEqual(first["status"], "complete")
        self.assertTrue(first["canonical_ready"])
        self.assertEqual(first["methods"], ["stdlib-json"])
        self.assertTrue(first["evidence"])
        evidence = first["evidence"][0]
        self.assertTrue(evidence["evidence_id"].startswith("ev_"))
        self.assertEqual(len(evidence["content_sha256"]), 64)

    def test_confidence_router_boundaries(self):
        router = ConfidenceRouter(
            accept_threshold=0.85, docling_threshold=0.8, llm_threshold=0.62
        )
        self.assertEqual(router.action(0.85), "accepted")
        self.assertEqual(router.action(0.62), "review_recommended")
        self.assertEqual(router.action(0.619999), "manual_review")
        self.assertTrue(router.should_use_llm(0.619999))
        self.assertFalse(router.should_use_llm(0.62))

    def test_borderless_numeric_table_is_a_camelot_signal(self):
        text = "Policy Year Cash Value Death Benefit\n1 80000 500000\n2 90000 500000\n"
        self.assertTrue(parser_module._looks_like_vector_table(text, drawings=0))

    def test_csv_requires_semantic_coverage_and_never_accepts_customer_or_bad_rows(
        self,
    ):
        headers = (
            "currency,policy_year,premium_amount,guaranteed_death_benefit,"
            "guaranteed_cash_surrender_value,unit_scale,guarantee_classification"
        )
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            good = root / "good.csv"
            good.write_text(
                headers + "\nCNY,1,100000,500000,80000,元,保证\n",
                encoding="utf-8",
            )
            customer = root / "customer.csv"
            customer.write_text(
                "customer_name,annual_income\nAlice,1000000\n", encoding="utf-8"
            )
            overflow = root / "overflow.csv"
            overflow.write_text(
                headers + "\nCNY,1,100000,500000,80000,元,保证,EXTRA\n",
                encoding="utf-8",
            )
            good_result = parse_file(good).to_dict()
            customer_result = parse_file(customer).to_dict()
            overflow_result = parse_file(overflow).to_dict()

        self.assertEqual(good_result["status"], "complete")
        self.assertFalse(good_result["canonical_ready"])
        self.assertEqual(customer_result["status"], "manual_review")
        self.assertNotIn("Alice", json.dumps(customer_result, ensure_ascii=False))
        self.assertNotEqual(overflow_result["status"], "complete")
        self.assertIn("csv_row_width_overflow:1", overflow_result["warnings"])

    def test_csv_rejects_nonsensical_values_and_removes_profile_columns(self):
        headers = (
            "currency,policy_year,premium_amount,guaranteed_death_benefit,"
            "guaranteed_cash_surrender_value,unit_scale,guarantee_classification"
        )
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            nonsense = root / "nonsense.csv"
            nonsense.write_text(
                headers + "\nNOT_A_CURRENCY,year-ten,-100,banana,???,furlongs,maybe\n",
                encoding="utf-8",
            )
            profile = root / "profile.csv"
            profile.write_text(
                headers
                + ",age,gender,health,telephone,notes\n"
                + "CNY,1,100000,500000,80000,元,保证,45,F,secret-condition,"
                + "13912345678,email: alice@example.com\n",
                encoding="utf-8",
            )
            contradiction = root / "contradiction.csv"
            contradiction.write_text(
                headers + "\nCNY,1,100000,500000,80000,元,非保证\n",
                encoding="utf-8",
            )
            absurd = root / "absurd.csv"
            absurd.write_text(
                headers + "\nZZZ,999999,100000000000000000000,0,0,元,保证\n",
                encoding="utf-8",
            )
            nonsense_result = parse_file(nonsense).to_dict()
            profile_result = parse_file(profile).to_dict()
            contradiction_result = parse_file(contradiction).to_dict()
            absurd_result = parse_file(absurd).to_dict()

        self.assertNotEqual(nonsense_result["status"], "complete")
        self.assertFalse(nonsense_result["canonical_ready"])
        self.assertEqual(
            set(nonsense_result["unresolved_fields"]),
            set(parser_module.CRITICAL_FIELD_NAMES),
        )
        self.assertIn("csv_critical_value_error", nonsense_result["route"]["reasons"])
        self.assertEqual(profile_result["status"], "partial")
        self.assertFalse(profile_result["canonical_ready"])
        serialized = json.dumps(profile_result, ensure_ascii=False)
        self.assertNotIn("secret-condition", serialized)
        self.assertNotIn("13912345678", serialized)
        self.assertNotIn("alice@example.com", serialized)
        self.assertIn(
            "csv_customer_or_pii_columns_removed:age,gender,health,telephone",
            profile_result["warnings"],
        )
        self.assertNotEqual(contradiction_result["status"], "complete")
        self.assertIn(
            "csv_guaranteed_columns_classified_non_guaranteed:rows=2",
            contradiction_result["warnings"],
        )
        self.assertNotEqual(absurd_result["status"], "complete")
        self.assertIn("currency", absurd_result["unresolved_fields"])
        self.assertIn("policy_year", absurd_result["unresolved_fields"])
        self.assertIn("premium_amount", absurd_result["unresolved_fields"])
        self.assertIn("guaranteed_death_benefit", absurd_result["unresolved_fields"])

    def test_irrelevant_json_is_manual_review_and_profile_data_is_removed(self):
        with tempfile.TemporaryDirectory() as directory:
            irrelevant = Path(directory) / "irrelevant.json"
            irrelevant.write_text(
                json.dumps(
                    {
                        "hello": "world",
                        "age": 45,
                        "gender": "F",
                        "health": "secret-condition",
                    }
                ),
                encoding="utf-8",
            )
            result = parse_file(irrelevant).to_dict()

        self.assertEqual(result["status"], "manual_review")
        self.assertFalse(result["canonical_ready"])
        self.assertIn("irrelevant_json_manual_review", result["route"]["reasons"])
        serialized = json.dumps(result, ensure_ascii=False)
        self.assertNotIn("secret-condition", serialized)
        self.assertNotIn('"age"', serialized)
        self.assertNotIn('"gender"', serialized)
        self.assertNotIn('"health"', serialized)

    def test_noncanonical_json_requires_nonempty_product_identity(self):
        payload = {
            "product_name": None,
            "currency": "CNY",
            "policy_year": [1],
            "premium_amount": ["100000"],
            "guaranteed_death_benefit": ["500000"],
            "guaranteed_cash_surrender_value": ["80000"],
            "unit_scale": "currency_unit",
            "guarantee_classification": "guaranteed",
        }
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "empty-identity.json"
            source.write_text(json.dumps(payload), encoding="utf-8")
            result = parse_file(source).to_dict()
        self.assertEqual(result["status"], "manual_review")
        self.assertFalse(result["canonical_ready"])
        self.assertIn("irrelevant_json_manual_review", result["route"]["reasons"])

    def test_canonical_json_redacts_evidence_pii_and_is_not_auto_ready(self):
        data = load(FIXTURES / "single-pay-alpha.json")
        raw_text = (
            "customer_name: Alice Secret\nSSN: 123-45-6789\n"
            "email: alice@example.com\naddress: 1 Secret Street\n"
            "passport_number: P1234567\ntelephone\n13912345678\n"
            "| phone_number |\n| --- |\n| 13812345678 |"
        )
        data["evidence"][0]["raw_text"] = raw_text
        data["evidence"][0]["content_sha256"] = hashlib.sha256(
            raw_text.encode("utf-8")
        ).hexdigest()
        data["sources"][0]["uri"] = (
            "https://example.invalid/?customer_name=UriSecret&ssn=987-65-4321"
        )
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "canonical-with-pii.json"
            source.write_text(json.dumps(data), encoding="utf-8")
            result = parse_file(source).to_dict()
        self.assertEqual(result["status"], "partial")
        self.assertFalse(result["canonical_ready"])
        serialized = json.dumps(result, ensure_ascii=False)
        self.assertNotIn("Alice Secret", serialized)
        self.assertNotIn("123-45-6789", serialized)
        self.assertNotIn("13912345678", serialized)
        self.assertNotIn("alice@example.com", serialized)
        self.assertNotIn("1 Secret Street", serialized)
        self.assertNotIn("P1234567", serialized)
        self.assertNotIn("13812345678", serialized)
        self.assertNotIn("UriSecret", serialized)
        self.assertNotIn("987-65-4321", serialized)

    def test_json_customer_profile_is_removed_and_never_auto_accepted(self):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "profile.json"
            source.write_text(
                json.dumps(
                    {
                        "product_name": "Synthetic Product",
                        "customer_profile": {
                            "full_name": "Alice Secret",
                            "annual_income": 1000000,
                        },
                    }
                ),
                encoding="utf-8",
            )
            result = parse_file(source).to_dict()
        self.assertEqual(result["status"], "partial")
        serialized = json.dumps(result, ensure_ascii=False)
        self.assertNotIn("Alice Secret", serialized)
        self.assertIn("json_customer_or_profile_keys_present", result["warnings"])

    def test_conflicting_parser_fields_are_capped_and_unresolved(self):
        digest = "a" * 64
        first_evidence = parser_module.Evidence(
            digest, "pdf:page=1", "pymupdf", 0.9, page=1
        )
        second_evidence = parser_module.Evidence(
            digest, "pdf:page=1", "docling", 0.95, page=1
        )
        fields = {
            "currency": parser_module.ExtractedField("CNY", 0.9, [first_evidence])
        }
        conflicts = parser_module._merge_fields(
            fields,
            {"currency": parser_module.ExtractedField("HKD", 0.95, [second_evidence])},
        )
        self.assertEqual(conflicts, ["currency"])
        self.assertEqual(fields["currency"].confidence, 0.64)
        self.assertIn(
            "currency",
            parser_module._unresolved_field_names(fields, {"currency": [r"Currency"]}),
        )

    def test_missing_optional_pdf_dependencies_degrade_without_network(self):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "fixture.pdf"
            source.write_bytes(b"%PDF-1.4\n% synthetic test only\n")
            with mock.patch(
                "llpi.parsers.importlib.import_module",
                side_effect=ImportError("missing"),
            ):
                result = parse_file(source).to_dict()
        self.assertEqual(result["status"], "manual_review")
        self.assertEqual(result["methods"], [])
        self.assertIn("optional_dependency_missing:pymupdf", result["warnings"])
        self.assertIn("optional_dependency_missing:docling", result["warnings"])
        self.assertIn("llm_fallback_not_configured", result["warnings"])

    def test_layered_pdf_route_uses_pymupdf_camelot_then_docling(self):
        class FakePage:
            def get_text(self, *args, **kwargs):
                return (
                    "保单年度: 1\n1 100000 500000 80000\n"
                    "2 100000 500000 120000\ntelephone: 13912345678"
                )

            def get_drawings(self):
                return [object()] * 8

            def get_images(self, full=True):
                return []

        class FakeDocument:
            needs_pass = False

            def __len__(self):
                return 1

            def __getitem__(self, index):
                return FakePage()

            def close(self):
                return None

        class FakeValues:
            def tolist(self):
                return [
                    [
                        "保单年度",
                        "保费",
                        "保证身故保险金",
                        "保证现金价值",
                        "telephone",
                    ],
                    ["1", "100000", "500000", "80000", "13912345678"],
                ]

        class FakeTable:
            page = 1
            df = SimpleNamespace(values=FakeValues())
            parsing_report = {"accuracy": 95, "whitespace": 5}

        class FakeConvertedDocument:
            def export_to_markdown(self):
                return (
                    "产品名称: 合成产品\n保险公司: 合成公司\n币种: CNY\n"
                    "保证身故保险金: 500000\n保证现金价值: 80000\n"
                    "金额单位: 元\n利益性质: 保证\nSSN: 123-45-6789"
                )

        class FakeConverter:
            def convert(self, path):
                return SimpleNamespace(document=FakeConvertedDocument())

        def fake_import(name):
            if name == "pymupdf":
                return SimpleNamespace(open=lambda path: FakeDocument())
            if name == "camelot":
                return SimpleNamespace(read_pdf=lambda *args, **kwargs: [FakeTable()])
            if name == "docling.document_converter":
                return SimpleNamespace(DocumentConverter=FakeConverter)
            raise ImportError(name)

        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "fixture.pdf"
            source.write_bytes(b"%PDF-1.4\n% synthetic test only\n")
            with mock.patch(
                "llpi.parsers.importlib.import_module", side_effect=fake_import
            ):
                result = parse_file(source).to_dict()
        self.assertEqual(result["dependencies"]["pymupdf"], "used")
        self.assertEqual(result["dependencies"]["camelot"], "used")
        self.assertEqual(result["dependencies"]["docling"], "used")
        self.assertEqual(
            result["route"]["attempted"], ["pymupdf", "camelot", "docling"]
        )
        self.assertIn("guaranteed_death_benefit", result["fields"])
        serialized = json.dumps(result, ensure_ascii=False)
        self.assertNotIn("13912345678", serialized)
        self.assertNotIn("123-45-6789", serialized)
        self.assertTrue(
            any("customer_or_pii" in warning for warning in result["warnings"])
        )

    def test_explicit_llm_fallback_is_bounded_capped_and_filtered(self):
        observed = []

        def transport(request, timeout):
            payload = json.loads(request.data.decode("utf-8"))
            observed.append(payload)
            return {
                "confidence": 1.0,
                "fields": {
                    "currency": {
                        "value": "CNY",
                        "locator": "page 1",
                        "confidence": 1.0,
                    },
                    "customer_income": {
                        "value": "1000000",
                        "locator": "page 1",
                        "confidence": 1.0,
                    },
                },
            }

        fallback = HTTPJSONLLMFallback(
            LLMFallbackConfig(
                endpoint="https://example.invalid/extract",
                model="fake",
                max_input_chars=800,
            ),
            transport=transport,
        )
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "fixture.pdf"
            source.write_bytes(b"%PDF-1.4\n% synthetic test only\n")
            with mock.patch(
                "llpi.parsers.importlib.import_module",
                side_effect=ImportError("missing"),
            ):
                result = parse_file(source, llm_fallback=fallback).to_dict()
        self.assertEqual(len(observed), 1)
        self.assertIn("currency", observed[0]["requested_fields"])
        self.assertNotIn("customer_income", result["fields"])
        self.assertLessEqual(result["fields"]["currency"]["confidence"], 0.69)
        self.assertEqual(result["status"], "partial")
        evidence = result["fields"]["currency"]["evidence"][0]
        self.assertIn("llm_only_candidate", evidence["reason_codes"])
        self.assertTrue(
            any(code.startswith("request_sha256=") for code in evidence["reason_codes"])
        )
        self.assertIn(
            "llm_unrequested_fields_dropped:customer_income", result["warnings"]
        )

    def test_llm_fallback_refuses_redirects_and_bounds_response_size(self):
        request = llm_fallback_module.urllib.request.Request(
            "https://trusted.example/extract",
            headers={"Authorization": "Bearer SECRET"},
        )
        redirected = llm_fallback_module._NoRedirectHandler().redirect_request(
            request,
            None,
            302,
            "Found",
            {},
            "http://attacker.example/collect",
        )
        self.assertIsNone(redirected)

        fallback = HTTPJSONLLMFallback(
            LLMFallbackConfig(
                endpoint="https://example.invalid/extract",
                model="fake",
                max_response_bytes=100,
                max_field_value_chars=20,
            ),
            transport=lambda request, timeout: {
                "fields": {"currency": {"value": "X" * 200}}
            },
        )
        with self.assertRaises(LLMFallbackResponseError):
            fallback.extract(
                text="Currency: CNY",
                source_sha256="a" * 64,
                requested_fields=["currency"],
            )

    def test_llm_fallback_result_serializes_and_enforces_request_and_depth_limits(self):
        fallback = HTTPJSONLLMFallback(
            LLMFallbackConfig(
                endpoint="https://example.invalid/extract",
                model="fake",
                max_fields=1,
                max_json_depth=4,
            ),
            transport=lambda request, timeout: {
                "fields": {
                    "currency": {
                        "value": "CNY",
                        "locator": "page 1",
                        "confidence": 0.6,
                    }
                }
            },
        )
        result = fallback.extract(
            text="Currency: CNY",
            source_sha256="a" * 64,
            requested_fields=["currency"],
        )
        self.assertEqual(result.to_dict()["fields"]["currency"]["value"], "CNY")

        with self.assertRaises(LLMFallbackNotConfigured):
            fallback.build_payload(
                text="Currency: CNY",
                source_sha256="a" * 64,
                requested_fields=["currency", "policy_year"],
            )

        deeply_nested = json.dumps(
            {"fields": {"currency": {"value": {"a": {"b": {"c": "CNY"}}}}}}
        )
        deep_fallback = HTTPJSONLLMFallback(
            LLMFallbackConfig(
                endpoint="https://example.invalid/extract",
                model="fake",
                max_json_depth=4,
            ),
            transport=lambda request, timeout: {"output_text": deeply_nested},
        )
        with self.assertRaises(LLMFallbackResponseError):
            deep_fallback.extract(
                text="Currency: CNY",
                source_sha256="a" * 64,
                requested_fields=["currency"],
            )


if __name__ == "__main__":
    unittest.main()
