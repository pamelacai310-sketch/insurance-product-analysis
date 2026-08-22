from __future__ import annotations

import sys
import unittest
from pathlib import Path


SCRIPTS_DIR = Path(__file__).resolve().parents[1] / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

from annuity_intelligence.common import SCHEMA_VERSION, ValidationError  # noqa: E402
from annuity_intelligence.resolution import apply_resolutions  # noqa: E402


def draft_document() -> dict:
    return {
        "product": {"name": "Synthetic annuity"},
        "configurations": [
            {
                "dimensions": {
                    "guarantee_option": "unresolved",
                    "premium_mode": "single",
                    "product_option_code": "A",
                },
                "annuity_rules": [{"rule_id": "income1"}],
                "death_benefit": {"rule": {"op": "field", "name": "cash_value"}},
            }
        ],
    }


def review_queue() -> dict:
    return {
        "items": [
            {
                "id": "task1",
                "route": "llm_semantic_resolution",
                "record_id": "record1",
                "snippet": "The guaranteed period is 10 years and the factor is 1.2.",
            },
            {
                "id": "manual-only",
                "route": "manual_verification",
                "record_id": "record2",
                "snippet": "Not eligible for an LLM patch.",
            },
        ]
    }


def patch_for(**overrides: object) -> dict:
    resolution = {
        "task_id": "task1",
        "target_path": "/configurations/0/dimensions/guarantee_option",
        "value": "10_year",
        "source_record_id": "record1",
        "candidate_confidence": "medium",
        "rationale": "Directly stated in the bounded evidence snippet.",
    }
    resolution.update(overrides)
    return {"schema_version": SCHEMA_VERSION, "resolutions": [resolution]}


class SemanticResolutionTests(unittest.TestCase):
    def test_valid_bounded_resolution_updates_only_the_allowed_target(self) -> None:
        original = draft_document()

        resolved = apply_resolutions(original, review_queue(), patch_for())

        self.assertEqual(
            resolved["configurations"][0]["dimensions"]["guarantee_option"],
            "10_year",
        )
        self.assertEqual(
            original["configurations"][0]["dimensions"]["guarantee_option"],
            "unresolved",
        )

    def test_target_outside_allowlist_is_rejected(self) -> None:
        with self.assertRaisesRegex(
            ValidationError, "outside the semantic resolution allowlist"
        ):
            apply_resolutions(
                draft_document(),
                review_queue(),
                patch_for(target_path="/product/name", value="Changed"),
            )

    def test_unanchored_numeric_value_is_rejected(self) -> None:
        with self.assertRaisesRegex(ValidationError, "not anchored"):
            apply_resolutions(
                draft_document(),
                review_queue(),
                patch_for(value="20_year"),
            )

    def test_llm_cannot_claim_high_confidence(self) -> None:
        with self.assertRaisesRegex(ValidationError, "cannot be high confidence"):
            apply_resolutions(
                draft_document(),
                review_queue(),
                patch_for(candidate_confidence="high"),
            )

    def test_source_record_must_match_review_evidence(self) -> None:
        with self.assertRaisesRegex(ValidationError, "must match"):
            apply_resolutions(
                draft_document(),
                review_queue(),
                patch_for(source_record_id="record2"),
            )

    def test_non_llm_task_cannot_be_patched(self) -> None:
        with self.assertRaisesRegex(ValidationError, "not an unresolved semantic task"):
            apply_resolutions(
                draft_document(),
                review_queue(),
                patch_for(task_id="manual-only", source_record_id="record2"),
            )

    def test_patch_schema_is_closed_and_requires_rationale(self) -> None:
        with self.assertRaisesRegex(ValidationError, "unsupported fields"):
            apply_resolutions(
                draft_document(),
                review_queue(),
                {**patch_for(), "extra": True},
            )
        missing = patch_for()
        missing["resolutions"][0].pop("rationale")
        with self.assertRaisesRegex(ValidationError, "missing required"):
            apply_resolutions(draft_document(), review_queue(), missing)


if __name__ == "__main__":
    unittest.main()
