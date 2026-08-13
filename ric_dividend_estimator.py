"""Strict inference utilities for RIC illustrated incremental dividends."""

from __future__ import annotations

import argparse
import csv
import json
import sys
from dataclasses import asdict, dataclass
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Iterable


REFERENCE_DATA = (
    Path(__file__).resolve().parent
    / "reports"
    / "ric_dividend_reference_female45_5pay_105_65.csv"
)
REFERENCE_BASIC_AMOUNT = Decimal("100000")
REFERENCE_ANNUAL_PREMIUM = Decimal("1620250")
REFERENCE_PREMIUM_RATE_PER_1000 = Decimal("16202.5")


class UnsupportedConfigurationError(ValueError):
    """Raised when no official illustration factor exists for a configuration."""


@dataclass(frozen=True)
class RICConfiguration:
    entry_age: int
    gender: str
    payment_years: int
    coverage_to_age: int
    first_annuity_policy_year: int
    extra_annuity_age: int


REFERENCE_CONFIGURATION = RICConfiguration(
    entry_age=45,
    gender="F",
    payment_years=5,
    coverage_to_age=105,
    first_annuity_policy_year=5,
    extra_annuity_age=65,
)


@dataclass(frozen=True)
class DividendReferenceRow:
    policy_year: int
    attained_age: int
    scenario1_annual_increment: Decimal
    scenario2_annual_increment: Decimal
    scenario1_cumulative_increment: Decimal
    scenario2_cumulative_increment: Decimal
    scenario1_terminal_dividend: Decimal
    scenario2_terminal_dividend: Decimal


def _decimal(value: object) -> Decimal:
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError) as exc:
        raise ValueError(f"Invalid decimal value: {value!r}") from exc


def calculate_basic_amount(
    annual_premium: Decimal | int | float | str,
    premium_rate_per_1000: Decimal | int | float | str,
) -> Decimal:
    premium = _decimal(annual_premium)
    rate = _decimal(premium_rate_per_1000)
    if premium <= 0 or rate <= 0:
        raise ValueError("Annual premium and premium rate must be positive")
    return premium / rate * Decimal("1000")


def load_reference_rows(path: Path = REFERENCE_DATA) -> list[DividendReferenceRow]:
    with path.open(encoding="utf-8", newline="") as handle:
        rows = [
            DividendReferenceRow(
                policy_year=int(row["policy_year"]),
                attained_age=int(row["attained_age"]),
                scenario1_annual_increment=_decimal(row["scenario1_annual_increment"]),
                scenario2_annual_increment=_decimal(row["scenario2_annual_increment"]),
                scenario1_cumulative_increment=_decimal(row["scenario1_cumulative_increment"]),
                scenario2_cumulative_increment=_decimal(row["scenario2_cumulative_increment"]),
                scenario1_terminal_dividend=_decimal(row["scenario1_terminal_dividend"]),
                scenario2_terminal_dividend=_decimal(row["scenario2_terminal_dividend"]),
            )
            for row in csv.DictReader(handle)
        ]
    expected_years = list(range(1, 61))
    if [row.policy_year for row in rows] != expected_years:
        raise ValueError("RIC reference data must contain policy years 1 through 60")
    return rows


def validate_reference_rows(
    rows: Iterable[DividendReferenceRow], *, rounding_tolerance: Decimal = Decimal("1")
) -> list[str]:
    warnings: list[str] = []
    previous = Decimal("0")
    for row in rows:
        displayed_delta = row.scenario2_cumulative_increment - previous
        difference = abs(displayed_delta - row.scenario2_annual_increment)
        if difference > rounding_tolerance:
            raise ValueError(
                f"Year {row.policy_year}: cumulative delta differs from annual increment "
                f"by {difference}, above tolerance {rounding_tolerance}"
            )
        if difference:
            warnings.append(
                f"Year {row.policy_year}: displayed annual and cumulative values differ "
                f"by {difference} due to independent rounding"
            )
        previous = row.scenario2_cumulative_increment
    return warnings


def validate_configuration(configuration: RICConfiguration) -> None:
    if configuration != REFERENCE_CONFIGURATION:
        changed = [
            field
            for field, reference_value in asdict(REFERENCE_CONFIGURATION).items()
            if asdict(configuration)[field] != reference_value
        ]
        raise UnsupportedConfigurationError(
            "No official RIC dividend illustration factors are loaded for the requested "
            f"configuration; differing fields: {', '.join(changed)}. "
            "Do not extrapolate across age, gender, payment term, coverage term, first "
            "annuity year, or extra-annuity age."
        )


def estimate_dividends(
    configuration: RICConfiguration,
    basic_amount: Decimal | int | float | str,
    *,
    realization_rate: Decimal | int | float | str | None = None,
    rows: Iterable[DividendReferenceRow] | None = None,
) -> list[dict[str, object]]:
    validate_configuration(configuration)
    amount = _decimal(basic_amount)
    if amount <= 0:
        raise ValueError("Basic amount must be positive")
    rate = None if realization_rate is None else _decimal(realization_rate)
    if rate is not None and not Decimal("0") <= rate <= Decimal("2"):
        raise ValueError("Realization rate must be between 0 and 2")

    scale = amount / REFERENCE_BASIC_AMOUNT
    source_rows = list(rows) if rows is not None else load_reference_rows()
    result: list[dict[str, object]] = []
    for row in source_rows:
        illustrated = row.scenario2_annual_increment * scale
        result.append(
            {
                "policy_year": row.policy_year,
                "attained_age": configuration.entry_age + row.policy_year,
                "scenario1_illustrated_annual_increment": Decimal("0"),
                "scenario2_illustrated_annual_increment": illustrated,
                "historical_rate_adjusted_proxy": (
                    None if rate is None else illustrated * rate
                ),
                "actual_declared_annual_increment": None,
                "confidence": "same_configuration_linear_scale",
            }
        )
    return result


def _json_default(value: object) -> object:
    if isinstance(value, Decimal):
        return float(value)
    raise TypeError(f"Unsupported JSON type: {type(value).__name__}")


def _print_csv(rows: list[dict[str, object]]) -> None:
    writer = csv.DictWriter(sys.stdout, fieldnames=list(rows[0]))
    writer.writeheader()
    for row in rows:
        writer.writerow(row)


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Estimate non-guaranteed RIC illustrated annual incremental dividends"
    )
    parser.add_argument("--basic-amount", type=Decimal)
    parser.add_argument("--annual-premium", type=Decimal)
    parser.add_argument("--premium-rate-per-1000", type=Decimal)
    parser.add_argument("--entry-age", type=int, default=45)
    parser.add_argument("--gender", choices=("F", "M"), default="F")
    parser.add_argument("--payment-years", type=int, default=5)
    parser.add_argument("--coverage-to-age", type=int, default=105)
    parser.add_argument("--first-annuity-policy-year", type=int, default=5)
    parser.add_argument("--extra-annuity-age", type=int, default=65)
    parser.add_argument("--realization-rate", type=Decimal)
    parser.add_argument("--format", choices=("json", "csv"), default="json")
    return parser


def main() -> int:
    parser = _build_parser()
    args = parser.parse_args()
    if args.basic_amount is None:
        if args.annual_premium is None or args.premium_rate_per_1000 is None:
            raise SystemExit(
                "Provide --basic-amount or both --annual-premium and "
                "--premium-rate-per-1000"
            )
        basic_amount = calculate_basic_amount(
            args.annual_premium, args.premium_rate_per_1000
        )
    else:
        if args.annual_premium is not None or args.premium_rate_per_1000 is not None:
            raise SystemExit(
                "Use --basic-amount or premium/rate inputs, not both"
            )
        basic_amount = args.basic_amount

    configuration = RICConfiguration(
        entry_age=args.entry_age,
        gender=args.gender,
        payment_years=args.payment_years,
        coverage_to_age=args.coverage_to_age,
        first_annuity_policy_year=args.first_annuity_policy_year,
        extra_annuity_age=args.extra_annuity_age,
    )
    try:
        rows = estimate_dividends(
            configuration,
            basic_amount,
            realization_rate=args.realization_rate,
        )
    except (UnsupportedConfigurationError, ValueError) as exc:
        parser.error(str(exc))
    if args.format == "csv":
        _print_csv(rows)
    else:
        payload = {
            "product": "RIC",
            "configuration": asdict(configuration),
            "basic_amount": basic_amount,
            "guaranteed_dividend": 0,
            "actual_declared_dividend": None,
            "warning": (
                "All illustrated and realization-rate-adjusted dividends are "
                "non-guaranteed; actual dividends require an insurer declaration."
            ),
            "rows": rows,
        }
        json.dump(payload, sys.stdout, ensure_ascii=False, indent=2, default=_json_default)
        sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
