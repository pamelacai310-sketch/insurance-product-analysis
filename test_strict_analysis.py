import copy
import contextlib
import io
import json
import tempfile
import unittest
from pathlib import Path

from actuarial_calculator import (
    ProductSpec,
    UnverifiedAssumptionError,
    calculate_death_leverage,
    generate_rating,
    irr_scenario_analysis,
    reverse_engineer_rate,
)
from actuarial_libs.adapters import ChainladderAdapter
from actuarial_libs.core import ActuarialLibraryManager
from enhanced_calculator import EnhancedProductAnalyzer
from integrated_calculator import IntegratedAnalyzer
from material_irr_analysis import ScenarioSpec, analyze_scenario, apply_product_rule
from strict_analysis import audit_clause_report_readiness, load_engine, run_strict_comparison
from unified_analysis import main as unified_main


ROOT = Path(__file__).resolve().parent
FIXTURES = ROOT / "skills" / "compare-insurance-products" / "assets" / "fixtures"


class StrictAnalysisTests(unittest.TestCase):
    def test_strict_output_has_no_composite_grade(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            output = run_strict_comparison(
                FIXTURES / "wwa_male_30_10pay.json",
                Path(directory),
            )
            result = output["result"]
            markdown = Path(output["markdown_path"]).read_text(encoding="utf-8")

        self.assertNotIn("grade", result)
        self.assertNotIn("total_score", result)
        self.assertIn("## 年金领取效率", markdown)
        self.assertIn("## 长寿风险转移", markdown)
        self.assertIn("## 合同选择权", markdown)
        self.assertIn("## 可验证压力测试", markdown)

    def test_extended_dimensions_require_explicit_sources(self) -> None:
        engine = load_engine()
        data = engine.load_json(FIXTURES / "ric_female_32_5pay.json")
        data = copy.deepcopy(data)
        data["comparison"]["longevity_test_age"] = 35
        product = data["products"][0]
        product["source_refs"].append(
            {
                "id": "terms",
                "kind": "policy_terms",
                "title": "脱敏条款摘录",
                "location": "fixture://terms",
                "page": 1,
                "row_label": "保证领取与保单贷款",
                "column_label": "合同责任",
                "unit_text": "人民币元",
                "version": "C",
                "fixture": True,
            }
        )
        product["guaranteed_benefits"] = {
            "source_ref": "terms",
            "basis": "absolute",
            "unit_text": "人民币元",
            "values": {"1": 100, "2": 200, "3": 300, "4": 400, "5": 500},
        }
        product["longevity"] = {
            "source_ref": "terms",
            "lifetime_income": True,
            "income_start_policy_year": 1,
            "contract_end_age": 85,
            "guaranteed_payment_years": 20,
        }
        product["contract_options"] = [
            {
                "name": "保单贷款",
                "type": "policy_loan",
                "source_ref": "terms",
                "available": True,
                "max_access_ratio": 0.8,
            }
        ]

        result = engine.calculate_case(data)
        calculated = result["products"][0]

        self.assertEqual(calculated["years"]["5"]["cumulative_guaranteed_benefit"], 1500)
        self.assertEqual(calculated["longevity"]["tail_benefit"], 900)
        self.assertEqual(
            calculated["longevity"]["tail_schedule_status"],
            "calculated_from_partial_explicit_schedule",
        )
        self.assertEqual(
            calculated["contract_options"][0]["quantification_status"],
            "not_quantified",
        )
        self.assertTrue(
            all(not item["non_guaranteed_included"] for item in calculated["stress_tests"])
        )

    def test_clause_report_is_readiness_only_and_never_fills_defaults(self) -> None:
        report = {
            "groups": [
                {
                    "category": "年金保险",
                    "products": [
                        {
                            "company": "测试公司",
                            "product_name": "缺参数产品",
                            "actuarial_params": {
                                "annual_premium": 100000,
                                "sum_assured": 10000,
                                "payment_period": 5,
                            },
                        }
                    ],
                }
            ]
        }
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "clauses.json"
            path.write_text(json.dumps(report, ensure_ascii=False), encoding="utf-8")
            audit = audit_clause_report_readiness(path)

        self.assertFalse(audit["formal_actuarial_analysis"])
        self.assertFalse(audit["products"][0]["strict_ready"])
        self.assertIn("entry_age", audit["products"][0]["missing_fields"])
        self.assertIn("gender", audit["products"][0]["missing_fields"])
        self.assertNotIn("rating", audit["products"][0])

    def test_legacy_default_arguments_are_rejected(self) -> None:
        with contextlib.redirect_stderr(io.StringIO()):
            with self.assertRaises(SystemExit):
                unified_main(
                    [
                        "--comparison-case",
                        str(FIXTURES / "wwa_male_30_10pay.json"),
                        "--default-age",
                        "30",
                    ]
                )

    def test_composite_rating_api_is_disabled(self) -> None:
        rating = generate_rating(0.02, 0.025, 10, 1.5, 4)

        self.assertEqual(rating["status"], "disabled")
        self.assertIsNone(rating["grade"])
        self.assertIsNone(rating["total_score"])

    def test_legacy_assumptions_and_synthetic_adapters_are_blocked(self) -> None:
        spec = ProductSpec(
            product_name="测试年金",
            product_type="annuity",
            entry_age=30,
            gender="M",
            payment_period=5,
            annual_premium=100000,
            sum_assured=10000,
        )
        with self.assertRaises(UnverifiedAssumptionError):
            irr_scenario_analysis(spec)
        with self.assertRaises(UnverifiedAssumptionError):
            reverse_engineer_rate(
                annual_premium=100000,
                payment_period=5,
                annual_annuity=10000,
                entry_age=30,
                annuity_start_age=60,
            )
        with self.assertRaises(UnverifiedAssumptionError):
            calculate_death_leverage(100000, 5, 10000, "sum_assured")

        adapter_result = ChainladderAdapter().analyze(spec)
        self.assertFalse(adapter_result["formal_analysis_supported"])
        self.assertEqual(adapter_result["evidence_quality"], "synthetic_demo")

        legacy_results = [
            IntegratedAnalyzer(spec).analyze(),
            EnhancedProductAnalyzer(spec).analyze_with_lifelib(),
            EnhancedProductAnalyzer(spec).analyze_company_solvency(),
            EnhancedProductAnalyzer(spec).analyze_extreme_risk(),
            ActuarialLibraryManager().analyze_with_available_libs(spec),
        ]
        for result in legacy_results:
            self.assertEqual(result["status"], "disabled")
            self.assertFalse(result["formal_analysis_supported"])

    def test_material_analysis_has_no_generic_product_fallback_or_dividend_guess(self) -> None:
        scenario = ScenarioSpec(
            product_name="未配置规则的年金保险",
            source_quality="公开说明书",
            entry_age=35,
            gender="F",
            payment_period=5,
            annual_premium=100000,
            base_amount=10000,
        )
        self.assertIsNone(apply_product_rule(scenario, "", ""))

        verified = ScenarioSpec(
            product_name="招商信诺岁岁盈定期年金保险（分红型）",
            source_quality="公开说明书",
            entry_age=35,
            gender="F",
            payment_period=3,
            annual_premium=100000,
            base_amount=256857,
            insurance_period=15,
            start_year=5,
            annual_benefit=9000,
            maturity_benefit=256857,
        )
        result = analyze_scenario("测试公司", verified)
        self.assertIsNotNone(result.irr_conservative)
        self.assertIsNone(result.irr_neutral)
        self.assertIsNone(result.irr_optimistic)
        self.assertEqual(result.rating_grade, "")
        self.assertIsNone(result.rating_score)


if __name__ == "__main__":
    unittest.main()
