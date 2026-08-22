from __future__ import annotations

import hashlib
import sys
import tempfile
import unittest
from decimal import Decimal
from pathlib import Path


SCRIPTS_DIR = Path(__file__).resolve().parents[1] / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

from annuity_intelligence.common import (  # noqa: E402
    ProhibitedCustomerDataError,
    SCHEMA_VERSION,
    ValidationError,
)
from annuity_intelligence.core import (  # noqa: E402
    beneficiary_continuation_events,
    build_cashflows,
    cash_value_at,
    death_benefit_at,
    expand_annuity_rule,
    normalize_money,
    normalize_product,
    scenario_events,
    validate_product,
)


def _money(value: str, unit: str = "CNY", **extra: object) -> dict:
    return {"value": value, "unit": unit, **extra}


def _event(month: int, amount: str, order: int, **extra: object) -> dict:
    return {
        "policy_month": month,
        "event_order": order,
        "amount": _money(amount),
        "guarantee_basis": "guaranteed",
        "scenario_id": "guaranteed",
        "status": "available",
        "timing": "policy_month_boundary",
        "evidence_refs": ["ev1"],
        "contingency": "contractual",
        **extra,
    }


def make_product(
    product_id: str = "annuity-a",
    premium: str = "100000",
    proportionality_verified: bool = True,
) -> dict:
    raw_text = "Synthetic published annuity table; no customer data."
    return {
        "schema_version": SCHEMA_VERSION,
        "product": {
            "product_id": product_id,
            "name": f"Synthetic {product_id}",
            "insurer": "Example Insurer",
            "currency": "CNY",
            "jurisdiction": "CN",
            "document_version": "v1",
            "effective_date": "2026-01-01",
            "product_type": "annuity",
            "analysis_only": True,
            "evidence_refs": ["ev1"],
        },
        "sources": [
            {
                "source_id": "src1",
                "path": "embedded://synthetic-annuity",
                "sha256": "0" * 64,
                "document_type": "published_product_table",
                "version": "v1",
                "authority": "contract",
                "embedded_fixture": True,
            }
        ],
        "evidence": [
            {
                "evidence_id": "ev1",
                "source_id": "src1",
                "page": 1,
                "bbox": [0, 0, 100, 20],
                "raw_text": raw_text,
                "raw_text_sha256": hashlib.sha256(raw_text.encode("utf-8")).hexdigest(),
                "unit_text": "CNY",
                "extractor": "unittest",
                "extractor_version": "1",
                "confidence": "1",
                "status": "verified",
            }
        ],
        "configurations": [
            {
                "configuration_id": "cfg1",
                "dimensions": {
                    "published_issue_age": 60,
                    "rate_class": "published_unisex",
                    "premium_term_months": 1,
                    "annuity_start_age": 61,
                    "annuity_frequency_per_year": 1,
                    "guarantee_option": "three_payments",
                    "premium_mode": "single",
                    "product_option_code": "A",
                    "proportionality_verified": proportionality_verified,
                },
                "dimension_evidence_refs": ["ev1"],
                "basic_amount": _money("100000"),
                "premium_events": [_event(0, premium, 10)],
                "annuity_rules": [
                    {
                        "rule_id": "income1",
                        "first_payment_month": 12,
                        "frequency_months": 12,
                        "payment_timing": "arrears",
                        "amount": _money("10000"),
                        "annual_growth_rate": "0.10",
                        "growth_interval_months": 12,
                        "lifetime": False,
                        "last_payment_month": 36,
                        "guaranteed_period_months": 36,
                        "guarantee_basis": "guaranteed",
                        "scenario_id": "guaranteed",
                        "rounding": "none",
                        "evidence_refs": ["ev1"],
                        "contingency": "survival",
                    }
                ],
                "cash_values": [
                    _event(12, "80000", 40),
                    _event(24, "85000", 40),
                    {
                        "policy_month": 36,
                        "event_order": 40,
                        "status": "not_applicable",
                        "timing": "after_annuity",
                        "evidence_refs": ["ev1"],
                        "contingency": "contractual",
                    },
                ],
                "death_benefit": {
                    "guarantee_basis": "guaranteed",
                    "scenario_id": "guaranteed",
                    "boundary_order": "after_annuity",
                    "lookup": "exact",
                    "schedule": [
                        _event(12, "90000", 50),
                        _event(24, "80000", 50),
                        _event(36, "70000", 50),
                    ],
                    "evidence_refs": ["ev1"],
                },
            }
        ],
        "analysis_assumptions": {
            "target_survival_ages": [61, 62, 63],
            "target_death_ages": [61, 62, 63],
            "inflation_rates": ["0.10"],
            "analysis_end_age": 63,
        },
    }


def normalize_fixture(data: dict | None = None) -> dict:
    return normalize_product(
        data or make_product(),
        verify_files=True,
        allow_embedded_fixtures=True,
    )


class ProductBoundaryTests(unittest.TestCase):
    def test_extended_loan_terms_are_closed_and_month_ranges_are_validated(self) -> None:
        data = make_product()
        data["configurations"][0]["loan_terms"] = {
            "available": True,
            "limit_ratio": "0.8",
            "eligible_value": "cash_value_net_of_debt",
            "availability_start_month": 24,
            "availability_end_month": 12,
            "maximum_term_months": 6,
            "interest_rate_status": "missing",
            "interest_rate_basis": "published company rate",
            "interest_rate_reset_frequency_months": 6,
            "repayment_terms": "principal and interest at maturity",
            "benefit_deduction": True,
            "lapse_trigger": "debt reaches cash value",
            "annuity_effect": "debt deducted from benefits",
            "evidence_refs": ["ev1"],
        }

        validation = validate_product(data, allow_embedded_fixtures=True)

        self.assertFalse(validation.valid)
        self.assertTrue(
            any("availability_start_month cannot follow" in error for error in validation.errors)
        )

    def test_product_dimensions_are_accepted_without_customer_data(self) -> None:
        validation = validate_product(
            make_product(),
            allow_embedded_fixtures=True,
        )

        self.assertTrue(validation.valid, validation.errors)
        dimensions = make_product()["configurations"][0]["dimensions"]
        self.assertEqual(dimensions["published_issue_age"], 60)
        self.assertEqual(dimensions["rate_class"], "published_unisex")

    def test_customer_fields_are_rejected_recursively(self) -> None:
        data = make_product()
        data["analysis_assumptions"]["customer_age"] = 61

        with self.assertRaises(ProhibitedCustomerDataError) as raised:
            validate_product(data, allow_embedded_fixtures=True)

        self.assertIn("$.analysis_assumptions.customer_age", raised.exception.findings)

    def test_embedded_fixture_requires_explicit_test_mode(self) -> None:
        validation = validate_product(make_product())

        self.assertFalse(validation.valid)
        self.assertTrue(
            any("outside self-test mode" in error for error in validation.errors)
        )

    def test_customer_values_in_evidence_or_notes_are_rejected_without_echo(
        self,
    ) -> None:
        evidence_data = make_product()
        raw_text = "客户姓名：张三"
        evidence_data["evidence"][0]["raw_text"] = raw_text
        evidence_data["evidence"][0]["raw_text_sha256"] = hashlib.sha256(
            raw_text.encode()
        ).hexdigest()
        with self.assertRaises(ProhibitedCustomerDataError) as evidence_error:
            validate_product(evidence_data, allow_embedded_fixtures=True)
        self.assertNotIn("张三", str(evidence_error.exception))

        notes_data = make_product()
        notes_data["configurations"][0]["notes"] = "Customer name: Jane Doe"
        with self.assertRaises(ProhibitedCustomerDataError) as notes_error:
            validate_product(notes_data, allow_embedded_fixtures=True)
        self.assertNotIn("Jane Doe", str(notes_error.exception))

    def test_low_confidence_evidence_cannot_be_labeled_extracted(self) -> None:
        data = make_product()
        data["evidence"][0]["status"] = "extracted"
        data["evidence"][0]["confidence"] = "0.1"

        validation = validate_product(data, allow_embedded_fixtures=True)

        self.assertFalse(validation.valid)
        self.assertTrue(any("at least 0.90" in error for error in validation.errors))


class SourceIntegrityTests(unittest.TestCase):
    def test_missing_source_file_is_a_validation_error(self) -> None:
        data = make_product()
        source = data["sources"][0]
        source.pop("embedded_fixture")
        source["path"] = "/definitely/not/present/annuity.pdf"

        validation = validate_product(data)

        self.assertFalse(validation.valid)
        self.assertTrue(
            any("path does not exist" in error for error in validation.errors)
        )

    def test_wrong_source_hash_is_a_validation_error(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            artifact = Path(temporary_directory) / "annuity.txt"
            artifact.write_text("official product table", encoding="utf-8")
            data = make_product()
            source = data["sources"][0]
            source.pop("embedded_fixture")
            source["path"] = str(artifact)
            source["sha256"] = "0" * 64

            validation = validate_product(data)

        self.assertFalse(validation.valid)
        self.assertTrue(
            any("sha256 does not match" in error for error in validation.errors)
        )


class UnitNormalizationTests(unittest.TestCase):
    def test_premiums_must_be_available_guaranteed_and_positive(self) -> None:
        missing = make_product()
        missing["configurations"][0]["premium_events"][0]["status"] = "missing"
        illustrated = make_product()
        illustrated["configurations"][0]["premium_events"][0].update(
            {
                "guarantee_basis": "illustrated",
                "scenario_id": "illustrated_premium",
                "scenario_composition": "total",
            }
        )
        zero = make_product(premium="0")

        for case in (missing, illustrated, zero):
            with self.subTest(case=case):
                self.assertFalse(
                    validate_product(case, allow_embedded_fixtures=True).valid
                )

    def test_validate_rejects_unsupported_units_and_basis_metadata_on_absolute_units(
        self,
    ) -> None:
        unsupported = make_product()
        unsupported["configurations"][0]["premium_events"][0]["amount"]["unit"] = (
            "bananas"
        )
        validation = validate_product(unsupported, allow_embedded_fixtures=True)
        self.assertFalse(validation.valid)
        self.assertTrue(any("unsupported" in error for error in validation.errors))

        absolute_with_basis = make_product()
        absolute_with_basis["configurations"][0]["annuity_rules"][0]["amount"][
            "basis_kind"
        ] = "total_premium"
        validation = validate_product(absolute_with_basis, allow_embedded_fixtures=True)
        self.assertFalse(validation.valid)
        self.assertTrue(any("basis metadata" in error for error in validation.errors))

    def test_custom_validator_enforces_closed_runtime_enums(self) -> None:
        mutations = (
            (
                lambda data: data["sources"][0].__setitem__("authority", "bogus"),
                "authority",
            ),
            (
                lambda data: data["configurations"][0]["annuity_rules"][0].__setitem__(
                    "payment_timing", "bogus"
                ),
                "payment_timing",
            ),
            (
                lambda data: data["configurations"][0]["annuity_rules"][0].__setitem__(
                    "rounding", "bogus"
                ),
                "rounding",
            ),
            (
                lambda data: data["configurations"][0]["dimensions"].__setitem__(
                    "annuity_frequency_per_year", 0
                ),
                "annuity_frequency",
            ),
        )
        for mutate, label in mutations:
            with self.subTest(label=label):
                data = make_product()
                mutate(data)
                self.assertFalse(
                    validate_product(data, allow_embedded_fixtures=True).valid
                )

    def test_absolute_scales_and_per_1000_basis_are_explicit(self) -> None:
        scaled = normalize_money(
            _money("2", "thousand_CNY"),
            "CNY",
            {},
            "$.amount",
        )
        per_thousand = normalize_money(
            _money(
                "5",
                "CNY_per_1000_basic_amount",
                basis_kind="basic_amount",
            ),
            "CNY",
            {"basic_amount": Decimal("100000")},
            "$.amount",
        )

        self.assertEqual(scaled["value"], "2000")
        self.assertEqual(per_thousand["value"], "500")
        self.assertEqual(per_thousand["basis_value_used"], "100000")

    def test_absolute_currency_and_per_1000_masquerade_conflicts_block(self) -> None:
        with self.assertRaises(ValidationError):
            normalize_money(_money("5", "USD"), "CNY", {}, "$.amount")
        with self.assertRaises(ValidationError):
            normalize_money(
                {
                    "value": "5",
                    "unit": "CNY_per_1000_basic_amount",
                    "currency": "CNY",
                    "normalized": True,
                },
                "CNY",
                {"basic_amount": Decimal("100000")},
                "$.amount",
            )


class CashflowAndFormulaTests(unittest.TestCase):
    def test_first_payment_month_zero_is_valid(self) -> None:
        data = make_product()
        data["configurations"][0]["annuity_rules"][0]["first_payment_month"] = 0

        validation = validate_product(data, allow_embedded_fixtures=True)

        self.assertTrue(validation.valid, validation.errors)

    def test_beneficiary_continuation_has_closed_schema(self) -> None:
        data = make_product()
        data["configurations"][0]["death_benefit"]["beneficiary_continuation"] = {
            "mode": "remaining_guaranteed_annuity",
            "through_policy_month": 36,
            "evidence_refs": ["ev1"],
            "unsupported": True,
        }

        validation = validate_product(data, allow_embedded_fixtures=True)

        self.assertFalse(validation.valid)
        self.assertTrue(any("unsupported" in error for error in validation.errors))

    def test_continuation_does_not_start_before_annuitization(self) -> None:
        data = make_product()
        data["configurations"][0]["death_benefit"]["beneficiary_continuation"] = {
            "mode": "remaining_guaranteed_annuity",
            "through_policy_month": 36,
            "evidence_refs": ["ev1"],
        }
        normalized = normalize_fixture(data)
        config = normalized["configurations"][0]
        events = build_cashflows(normalized)["configurations"][0]["events"]

        self.assertEqual(beneficiary_continuation_events(config, events, 11), [])
        self.assertEqual(
            [
                event["policy_month"]
                for event in beneficiary_continuation_events(config, events, 12, 29)
            ],
            [12, 24, 36],
        )
        self.assertEqual(
            [
                event["policy_month"]
                for event in beneficiary_continuation_events(config, events, 12, 39)
            ],
            [24, 36],
        )

    def test_scenario_specific_schedule_overrides_guaranteed_at_same_month(
        self,
    ) -> None:
        data = make_product()
        config = data["configurations"][0]
        illustrated = _event(
            12,
            "95000",
            40,
            guarantee_basis="illustrated",
            scenario_id="illustrated_base",
            scenario_composition="total",
        )
        config["cash_values"].append(illustrated)
        config["death_benefit"]["schedule"].append(dict(illustrated))
        normalized = normalize_fixture(data)
        normalized_config = normalized["configurations"][0]
        events = build_cashflows(normalized)["configurations"][0]["events"]

        self.assertEqual(
            cash_value_at(normalized_config, 12, "illustrated_base")[1],
            Decimal("95000"),
        )
        self.assertEqual(
            death_benefit_at(normalized_config, events, 12, "illustrated_base")[
                "amount"
            ],
            Decimal("95000"),
        )

    def test_cash_value_respects_same_month_death_boundary(self) -> None:
        normalized = normalize_fixture()
        config = normalized["configurations"][0]

        before = cash_value_at(config, 12, boundary_event_order=29)
        after = cash_value_at(config, 12, boundary_event_order=40)

        self.assertEqual(before[:2], ("missing", None))
        self.assertEqual(after[:2], ("available", Decimal("80000")))

    def test_death_rule_uses_same_boundary_for_cumulative_annuity(self) -> None:
        data = make_product()
        config = data["configurations"][0]
        config["death_benefit"] = {
            "guarantee_basis": "guaranteed",
            "scenario_id": "guaranteed",
            "boundary_order": "before_annuity",
            "cash_value_timing": "policy_month_state",
            "rule": {
                "op": "subtract",
                "left": {
                    "op": "field",
                    "name": "total_premium",
                    "evidence_refs": ["ev1"],
                },
                "right": {
                    "op": "field",
                    "name": "cumulative_annuity",
                    "evidence_refs": ["ev1"],
                },
                "evidence_refs": ["ev1"],
            },
            "evidence_refs": ["ev1"],
        }
        normalized = normalize_fixture(data)
        normalized_config = normalized["configurations"][0]
        events = build_cashflows(normalized)["configurations"][0]["events"]

        before = death_benefit_at(
            normalized_config, events, 12, boundary_event_order=29
        )
        after = death_benefit_at(normalized_config, events, 12, boundary_event_order=39)

        self.assertEqual(before["amount"], Decimal("100000"))
        self.assertEqual(after["amount"], Decimal("90000"))

    def test_scenario_specific_annuity_is_total_not_added_to_guaranteed(self) -> None:
        normalized = normalize_fixture()
        events = build_cashflows(normalized)["configurations"][0]["events"]
        illustrated = dict(
            next(event for event in events if event["event_type"] == "annuity_payment")
        )
        illustrated.update(
            {
                "amount": "15000",
                "guarantee_basis": "illustrated",
                "scenario_id": "illustrated_base",
            }
        )

        selected = scenario_events([*events, illustrated], "illustrated_base")
        month_12 = [
            event
            for event in selected
            if event["event_type"] == "annuity_payment" and event["policy_month"] == 12
        ]

        self.assertEqual([event["amount"] for event in month_12], ["15000"])

    def test_incremental_annuity_scenario_keeps_guaranteed_schedule(self) -> None:
        normalized = normalize_fixture()
        events = build_cashflows(normalized)["configurations"][0]["events"]
        bonus = dict(
            next(event for event in events if event["event_type"] == "annuity_payment")
        )
        bonus.update(
            {
                "amount": "5000",
                "guarantee_basis": "illustrated",
                "scenario_id": "illustrated_bonus",
                "scenario_composition": "incremental",
            }
        )

        selected = scenario_events([*events, bonus], "illustrated_bonus")
        annuities = [
            event for event in selected if event["event_type"] == "annuity_payment"
        ]

        self.assertEqual(
            [(event["policy_month"], event["amount"]) for event in annuities],
            [(12, "10000"), (24, "11000"), (36, "12100"), (12, "5000")],
        )

    def test_mixed_scenario_composition_is_rejected_during_validation(self) -> None:
        data = make_product()
        base = dict(data["configurations"][0]["annuity_rules"][0])
        total = {
            **base,
            "rule_id": "illustrated-total",
            "guarantee_basis": "illustrated",
            "scenario_id": "illustrated_base",
            "scenario_composition": "total",
        }
        incremental = {
            **base,
            "rule_id": "illustrated-incremental",
            "guarantee_basis": "illustrated",
            "scenario_id": "illustrated_base",
            "scenario_composition": "incremental",
        }
        data["configurations"][0]["annuity_rules"].extend([total, incremental])

        validation = validate_product(data, allow_embedded_fixtures=True)

        self.assertFalse(validation.valid)
        self.assertTrue(
            any("mixes total and incremental" in error for error in validation.errors)
        )

    def test_illustrated_death_rule_is_not_used_in_guaranteed_scenario(self) -> None:
        data = make_product()
        data["configurations"][0]["death_benefit"] = {
            "guarantee_basis": "illustrated",
            "scenario_id": "illustrated_base",
            "boundary_order": "after_annuity",
            "rule": {
                "op": "constant",
                "amount": _money("123456"),
                "evidence_refs": ["ev1"],
            },
            "evidence_refs": ["ev1"],
        }
        normalized = normalize_fixture(data)
        config = normalized["configurations"][0]
        events = build_cashflows(normalized)["configurations"][0]["events"]

        self.assertEqual(
            death_benefit_at(config, events, 12, "guaranteed")["status"], "missing"
        )
        self.assertEqual(
            death_benefit_at(config, events, 12, "illustrated_base")["amount"],
            Decimal("123456"),
        )

    def test_ast_dimensional_errors_and_negative_death_benefits_are_blocked(
        self,
    ) -> None:
        invalid = make_product()
        invalid["configurations"][0]["death_benefit"]["schedule"] = None
        invalid["configurations"][0]["death_benefit"].pop("schedule")
        invalid["configurations"][0]["death_benefit"]["rule"] = {
            "op": "add",
            "args": [
                {"op": "field", "name": "cash_value", "evidence_refs": ["ev1"]},
                {"op": "field", "name": "policy_month", "evidence_refs": ["ev1"]},
            ],
            "evidence_refs": ["ev1"],
        }
        invalid["configurations"][0]["death_benefit"]["cash_value_timing"] = (
            "policy_month_state"
        )
        validation = validate_product(invalid, allow_embedded_fixtures=True)
        self.assertFalse(validation.valid)
        self.assertTrue(any("dimensional type" in error for error in validation.errors))

        negative = make_product()
        negative["configurations"][0]["death_benefit"].pop("schedule")
        negative["configurations"][0]["death_benefit"]["rule"] = {
            "op": "subtract",
            "left": {"op": "constant", "amount": _money("1"), "evidence_refs": ["ev1"]},
            "right": {
                "op": "constant",
                "amount": _money("2"),
                "evidence_refs": ["ev1"],
            },
            "evidence_refs": ["ev1"],
        }
        normalized = normalize_fixture(negative)
        config = normalized["configurations"][0]
        events = build_cashflows(normalized)["configurations"][0]["events"]
        with self.assertRaisesRegex(ValidationError, "negative"):
            death_benefit_at(config, events, 12)

    def test_zero_missing_and_not_applicable_remain_distinct(self) -> None:
        data = make_product()
        data["configurations"][0]["cash_values"] = [
            _event(12, "0", 40),
            {
                "policy_month": 24,
                "event_order": 40,
                "status": "missing",
                "timing": "after_annuity",
                "evidence_refs": ["ev1"],
                "contingency": "contractual",
            },
            {
                "policy_month": 36,
                "event_order": 40,
                "status": "not_applicable",
                "timing": "after_annuity",
                "evidence_refs": ["ev1"],
                "contingency": "contractual",
            },
        ]
        config = normalize_fixture(data)["configurations"][0]

        zero = cash_value_at(config, 12)
        missing = cash_value_at(config, 24)
        not_applicable = cash_value_at(config, 36)

        self.assertEqual(zero[:2], ("available", Decimal("0")))
        self.assertEqual(missing[:2], ("missing", None))
        self.assertEqual(not_applicable[:2], ("not_applicable", None))

    def test_duplicate_state_schedule_points_are_rejected(self) -> None:
        cash_duplicate = make_product()
        cash_duplicate["configurations"][0]["cash_values"].append(
            dict(cash_duplicate["configurations"][0]["cash_values"][0])
        )
        death_duplicate = make_product()
        death_duplicate["configurations"][0]["death_benefit"]["schedule"].append(
            dict(death_duplicate["configurations"][0]["death_benefit"]["schedule"][0])
        )

        for case in (cash_duplicate, death_duplicate):
            with self.subTest(case=case):
                validation = validate_product(case, allow_embedded_fixtures=True)
                self.assertFalse(validation.valid)
                self.assertTrue(
                    any(
                        "duplicates scenario/month/order" in error
                        for error in validation.errors
                    )
                )

    def test_annuity_timing_and_growth_expand_deterministically(self) -> None:
        normalized = normalize_fixture()
        config = normalized["configurations"][0]

        events = expand_annuity_rule(
            config["annuity_rules"][0],
            config["dimensions"],
            "CNY",
        )

        self.assertEqual([event["policy_month"] for event in events], [12, 24, 36])
        self.assertEqual(
            [event["amount"] for event in events], ["10000", "11000", "12100"]
        )
        self.assertTrue(all(event["event_order"] == 30 for event in events))

    def test_invalid_annuity_horizons_are_rejected_before_cashflow_build(self) -> None:
        start_before_issue = make_product()
        start_before_issue["configurations"][0]["dimensions"]["annuity_start_age"] = 59
        lifetime_ends_early = make_product()
        lifetime_ends_early["configurations"][0]["annuity_rules"][0][
            "contract_end_age"
        ] = 60
        ambiguous_termination = make_product()
        rule = ambiguous_termination["configurations"][0]["annuity_rules"][0]
        rule.update(
            {
                "lifetime": False,
                "last_payment_month": 36,
                "payment_count": 3,
            }
        )

        for case in (start_before_issue, lifetime_ends_early, ambiguous_termination):
            with self.subTest(case=case):
                self.assertFalse(
                    validate_product(case, allow_embedded_fixtures=True).valid
                )

    def test_unavailable_maturity_event_is_not_emitted_as_zero_cashflow(self) -> None:
        data = make_product()
        data["configurations"][0]["maturity_events"] = [
            {
                "policy_month": 120,
                "event_order": 40,
                "status": "missing",
                "timing": "policy_month_boundary",
                "guarantee_basis": "guaranteed",
                "scenario_id": "guaranteed",
                "contingency": "survival",
                "evidence_refs": ["ev1"],
            }
        ]

        normalized = normalize_fixture(data)
        events = build_cashflows(normalized)["configurations"][0]["events"]

        self.assertFalse(
            any(event["event_type"] == "maturity_benefit" for event in events)
        )

    def test_annual_growth_rate_is_converted_for_monthly_intervals(self) -> None:
        normalized = normalize_fixture()
        rule = dict(normalized["configurations"][0]["annuity_rules"][0])
        rule.update(
            {
                "first_payment_month": 0,
                "frequency_months": 1,
                "growth_interval_months": 1,
                "annual_growth_rate": "0.12",
                "last_payment_month": 12,
            }
        )

        events = expand_annuity_rule(
            rule, normalized["configurations"][0]["dimensions"], "CNY"
        )

        self.assertEqual(events[0]["amount"], "10000")
        self.assertAlmostEqual(float(events[-1]["amount"]), 11200.0, places=6)

    def test_ast_missing_operand_propagates_missing_instead_of_zero(self) -> None:
        data = make_product()
        config = data["configurations"][0]
        config["cash_values"] = []
        config["death_benefit"] = {
            "guarantee_basis": "guaranteed",
            "scenario_id": "guaranteed",
            "boundary_order": "after_annuity",
            "cash_value_timing": "policy_month_state",
            "rule": {
                "op": "add",
                "args": [
                    {"op": "field", "name": "cash_value", "evidence_refs": ["ev1"]},
                    {
                        "op": "constant",
                        "amount": _money("1000"),
                        "evidence_refs": ["ev1"],
                    },
                ],
                "evidence_refs": ["ev1"],
            },
            "evidence_refs": ["ev1"],
        }
        normalized = normalize_fixture(data)
        cashflows = build_cashflows(normalized)

        result = death_benefit_at(
            normalized["configurations"][0],
            cashflows["configurations"][0]["events"],
            24,
        )

        self.assertEqual(result["status"], "missing")
        self.assertIsNone(result["amount"])
        self.assertEqual(result["trace"]["status"], "missing_operand")


if __name__ == "__main__":
    unittest.main()
