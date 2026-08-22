from __future__ import annotations

import argparse
import json
import re
import sys
import tempfile
from decimal import Decimal
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Sequence

from .common import (
    SCHEMA_VERSION,
    TOOL_VERSION,
    AnnuityPIError,
    ProhibitedCustomerDataError,
    ReviewRequiredError,
    ValidationError,
    calculation_hash,
    enforce_no_customer_data,
    load_json,
    sha256_file,
    stable_json_data,
    write_json,
)
from .comparison import compare_products
from .core import (
    build_cashflows,
    find_unresolved_paths,
    normalize_product,
    validate_product,
)
from .extraction import inspect_inputs
from .metrics import analyze_product, xirr_all
from .reporting import render_comparison_report, render_product_report
from .resolution import apply_resolutions


def _skill_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="\n") as handle:
        handle.write(text)


def _validate_benchmark(data: Mapping[str, Any], path: Path) -> Dict[str, Any]:
    enforce_no_customer_data(data)
    errors = []
    required = {
        "schema_version",
        "benchmark_id",
        "currency",
        "as_of_date",
        "compounding",
        "day_count",
        "source_sha256",
        "points",
    }
    missing = required - set(data)
    if missing:
        errors.append(f"benchmark is missing fields: {sorted(missing)}")
    unknown = set(data) - required
    if unknown:
        errors.append(f"benchmark contains unsupported fields: {sorted(unknown)}")
    if data.get("schema_version") != SCHEMA_VERSION:
        errors.append(f"benchmark schema_version must equal {SCHEMA_VERSION}")
    if data.get("compounding") != "annual_effective":
        errors.append("benchmark compounding must be annual_effective")
    if (
        not isinstance(data.get("benchmark_id"), str)
        or not data.get("benchmark_id", "").strip()
    ):
        errors.append("benchmark benchmark_id must be a non-empty string")
    if not isinstance(data.get("currency"), str) or not re.fullmatch(
        r"[A-Z]{3}", data.get("currency", "")
    ):
        errors.append("benchmark currency must be a three-letter code")
    if (
        not isinstance(data.get("as_of_date"), str)
        or not data.get("as_of_date", "").strip()
    ):
        errors.append("benchmark as_of_date is required")
    if (
        not isinstance(data.get("day_count"), str)
        or not data.get("day_count", "").strip()
    ):
        errors.append("benchmark day_count is required")
    if not isinstance(data.get("source_sha256"), str) or not re.fullmatch(
        r"[0-9a-f]{64}", data.get("source_sha256", "")
    ):
        errors.append("benchmark source_sha256 must be lowercase SHA-256")
    points = data.get("points")
    if not isinstance(points, list) or not points:
        errors.append("benchmark points must be a non-empty list")
    else:
        terms = set()
        for index, point in enumerate(points):
            if not isinstance(point, Mapping):
                errors.append(f"benchmark point {index} must be an object")
                continue
            point_unknown = set(point) - {
                "term_years",
                "annual_effective_rate",
                "label",
            }
            if point_unknown:
                errors.append(
                    f"benchmark point {index} contains unsupported fields: {sorted(point_unknown)}"
                )
            if not {"term_years", "annual_effective_rate"}.issubset(point):
                errors.append(
                    f"benchmark point {index} is missing term_years or annual_effective_rate"
                )
                continue
            if point.get("label") is not None and not isinstance(
                point.get("label"), str
            ):
                errors.append(f"benchmark point {index} label must be a string")
            try:
                term = Decimal(str(point["term_years"]))
                rate = Decimal(str(point["annual_effective_rate"]))
                if not term.is_finite() or not rate.is_finite():
                    errors.append(f"benchmark point {index} term/rate must be finite")
                    continue
                if term <= 0:
                    errors.append(f"benchmark point {index} term must be positive")
                if rate <= Decimal("-1"):
                    errors.append(
                        f"benchmark point {index} rate must be greater than -1"
                    )
                if term in terms:
                    errors.append(f"benchmark point {index} duplicates tenor {term}")
                terms.add(term)
            except Exception:
                errors.append(f"benchmark point {index} has invalid term/rate")
    if errors:
        raise ValidationError(errors)
    result = dict(data)
    result["snapshot_file_sha256"] = sha256_file(path)
    return result


def load_benchmark(path: Optional[Path]) -> Optional[Dict[str, Any]]:
    if path is None:
        return None
    return _validate_benchmark(load_json(path), path)


def _metric_provenance_index(metrics: Mapping[str, Any]) -> List[Dict[str, Any]]:
    records: List[Dict[str, Any]] = []

    def walk(value: Any, path: str) -> None:
        if isinstance(value, Mapping):
            provenance = value.get("provenance")
            if isinstance(provenance, Mapping):
                records.append({"metric_path": path, **stable_json_data(provenance)})
            for key in sorted(value):
                walk(value[key], f"{path}/{key}")
        elif isinstance(value, list):
            for index, item in enumerate(value):
                walk(item, f"{path}/{index}")

    walk(metrics, "")
    return records


def run_pipeline(
    input_path: Path,
    output_dir: Path,
    benchmark_path: Optional[Path] = None,
    allow_embedded_fixtures: bool = False,
) -> Dict[str, Any]:
    raw = load_json(input_path)
    validation = validate_product(
        raw,
        verify_files=True,
        allow_embedded_fixtures=allow_embedded_fixtures,
    )
    output_dir.mkdir(parents=True, exist_ok=True)
    write_json(output_dir / "validation.json", validation.as_dict())
    if not validation.valid:
        raise ValidationError(validation.errors, validation.warnings)
    unresolved_paths = find_unresolved_paths(raw)
    review_queue = {
        "schema_version": SCHEMA_VERSION,
        "items": [
            {
                "id": calculation_hash(
                    {"path": path, "route": "unresolved_input_block"}
                )[:24],
                "route": "unresolved_input_block",
                "reason": "Resolve this draft field through its original deterministic or semantic inspection task before calculation.",
                "path": path,
            }
            for path in unresolved_paths
        ],
        "llm_called": False,
    }
    write_json(output_dir / "review_queue.json", review_queue)
    if unresolved_paths:
        raise ReviewRequiredError(
            f"calculation blocked until {len(unresolved_paths)} unresolved input path(s) are resolved"
        )
    normalized = normalize_product(
        raw,
        verify_files=True,
        allow_embedded_fixtures=allow_embedded_fixtures,
    )
    cashflows = build_cashflows(normalized)
    benchmark = load_benchmark(benchmark_path)
    metrics = analyze_product(normalized, cashflows, benchmark)
    write_json(output_dir / "product.normalized.json", normalized)
    write_json(output_dir / "cashflows.json", cashflows)
    write_json(output_dir / "metrics.json", metrics)
    report = render_product_report(normalized, validation.as_dict(), metrics)
    _write_text(output_dir / "report.md", report)
    provenance = {
        "schema_version": SCHEMA_VERSION,
        "tool_version": TOOL_VERSION,
        "sources": normalized["sources"],
        "evidence": normalized["evidence"],
        "metric_dependency_index": _metric_provenance_index(metrics),
        "artifact_chain": {
            "input_sha256": sha256_file(input_path),
            "benchmark_input_sha256": None
            if benchmark_path is None
            else sha256_file(benchmark_path),
            "product_normalized_sha256": sha256_file(
                output_dir / "product.normalized.json"
            ),
            "cashflows_sha256": sha256_file(output_dir / "cashflows.json"),
            "metrics_sha256": sha256_file(output_dir / "metrics.json"),
            "report_sha256": sha256_file(output_dir / "report.md"),
        },
    }
    write_json(output_dir / "provenance.json", provenance)
    return {
        "normalized": normalized,
        "validation": validation.as_dict(),
        "cashflows": cashflows,
        "metrics": metrics,
        "provenance": provenance,
        "review_queue": review_queue,
        "report": report,
    }


def run_comparison(
    input_paths: Sequence[Path], output_dir: Path, benchmark_path: Optional[Path]
) -> Dict[str, Any]:
    benchmark = load_benchmark(benchmark_path)
    product_runs = []
    for input_path in input_paths:
        raw = load_json(input_path)
        normalized = normalize_product(
            raw, verify_files=True, allow_embedded_fixtures=False
        )
        cashflows = build_cashflows(normalized)
        metrics = analyze_product(normalized, cashflows, benchmark)
        product_runs.append(
            {"normalized": normalized, "cashflows": cashflows, "metrics": metrics}
        )
    comparison = compare_products(product_runs)
    output_dir.mkdir(parents=True, exist_ok=True)
    write_json(output_dir / "comparison.json", comparison)
    _write_text(output_dir / "comparison.md", render_comparison_report(comparison))
    return comparison


def _run_self_test() -> None:
    skill_root = _skill_root()
    product_path = skill_root / "assets" / "fixtures" / "demo-annuity-product.json"
    benchmark_path = skill_root / "assets" / "fixtures" / "demo-benchmark.json"
    with tempfile.TemporaryDirectory() as temporary_directory:
        output = Path(temporary_directory) / "demo"
        result = run_pipeline(
            product_path, output, benchmark_path, allow_embedded_fixtures=True
        )
        expected_files = {
            "validation.json",
            "product.normalized.json",
            "cashflows.json",
            "metrics.json",
            "provenance.json",
            "review_queue.json",
            "report.md",
        }
        actual_files = {path.name for path in output.iterdir()}
        if expected_files != actual_files:
            raise AssertionError(f"self-test outputs differ: {actual_files}")
        if not result["validation"]["valid"]:
            raise AssertionError("synthetic fixture did not validate")
        config = result["metrics"]["configurations"][0]
        capital = config["capital_efficiency"]
        if capital["income_conversion_rate"]["value"] != "0.06":
            raise AssertionError("income conversion regression")
        if capital["income_only_break_even_month"]["value"] != 432:
            raise AssertionError("income-only break-even regression")
        liquidity = config["scenarios"]["guaranteed"]["liquidity"]
        if liquidity["cash_value_recovery_month"]["value"] != 120:
            raise AssertionError("cash value recovery regression")
        early_death = config["scenarios"]["guaranteed"]["early_death"]
        if early_death["curve"][0]["beneficiary_continuation"]["value"] != "0":
            raise AssertionError("pre-annuitization continuation regression")
        multiple = xirr_all(
            [(0, Decimal("-100")), (12, Decimal("230")), (24, Decimal("-132"))]
        )
        roots = sorted(
            round(float(root["annual_effective_rate"]), 6) for root in multiple["roots"]
        )
        if multiple["status"] != "multiple_roots" or roots != [0.1, 0.2]:
            raise AssertionError(f"multiple-root IRR regression: {multiple}")
        long_horizon = xirr_all([(0, Decimal("-100")), (900, Decimal("200"))])
        if long_horizon["status"] != "unique_root":
            raise AssertionError("long-horizon IRR regression")


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="annuity-pi",
        description="Deterministic, auditable annuity product economics without customer data",
    )
    parser.add_argument(
        "--version", action="version", version=f"%(prog)s {TOOL_VERSION}"
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    inspect_parser = subparsers.add_parser(
        "inspect", help="fingerprint and extract local product materials"
    )
    inspect_parser.add_argument("inputs", nargs="+", type=Path)
    inspect_parser.add_argument("--out", required=True, type=Path)

    validate_parser = subparsers.add_parser(
        "validate", help="validate product schema, evidence, units, and files"
    )
    validate_parser.add_argument("--input", required=True, type=Path)
    validate_parser.add_argument("--output", type=Path)

    normalize_parser = subparsers.add_parser(
        "normalize", help="normalize typed money and product schema"
    )
    normalize_parser.add_argument("--input", required=True, type=Path)
    normalize_parser.add_argument("--output", required=True, type=Path)

    run_parser = subparsers.add_parser(
        "run", help="calculate cashflows, metrics, provenance, and report"
    )
    run_parser.add_argument("--input", required=True, type=Path)
    run_parser.add_argument("--out", required=True, type=Path)
    run_parser.add_argument("--benchmark", type=Path)

    compare_parser = subparsers.add_parser(
        "compare", help="compare only common compatible product configurations"
    )
    compare_parser.add_argument("--input", nargs="+", required=True, type=Path)
    compare_parser.add_argument("--out", required=True, type=Path)
    compare_parser.add_argument("--benchmark", type=Path)

    resolve_parser = subparsers.add_parser(
        "resolve", help="apply a schema-constrained semantic exception patch"
    )
    resolve_parser.add_argument("--input", required=True, type=Path)
    resolve_parser.add_argument("--review-queue", required=True, type=Path)
    resolve_parser.add_argument("--patch", required=True, type=Path)
    resolve_parser.add_argument("--output", required=True, type=Path)

    demo_parser = subparsers.add_parser(
        "demo", help="run the bundled synthetic product fixture"
    )
    demo_parser.add_argument("--out", required=True, type=Path)

    subparsers.add_parser(
        "self-test", help="run deterministic built-in regression checks"
    )
    return parser


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)
    try:
        if args.command == "inspect":
            result = inspect_inputs(args.inputs, args.out)
            routes = {item.get("route") for item in result["review_queue"]["items"]}
            print(
                json.dumps(result["output_files"], ensure_ascii=False, sort_keys=True)
            )
            if "reject_prohibited_customer_data" in routes:
                return 3
            return 2 if routes else 0
        if args.command == "validate":
            result = validate_product(
                load_json(args.input), verify_files=True, allow_embedded_fixtures=False
            )
            if args.output:
                write_json(args.output, result.as_dict())
            else:
                print(
                    json.dumps(
                        result.as_dict(), ensure_ascii=False, indent=2, sort_keys=True
                    )
                )
            return 0 if result.valid else 4
        if args.command == "normalize":
            normalized = normalize_product(
                load_json(args.input), verify_files=True, allow_embedded_fixtures=False
            )
            write_json(args.output, normalized)
            return 0
        if args.command == "run":
            run_pipeline(
                args.input, args.out, args.benchmark, allow_embedded_fixtures=False
            )
            return 0
        if args.command == "compare":
            if len(args.input) < 2:
                raise ValidationError(["compare requires at least two --input files"])
            run_comparison(args.input, args.out, args.benchmark)
            return 0
        if args.command == "resolve":
            resolved = apply_resolutions(
                load_json(args.input),
                load_json(args.review_queue),
                load_json(args.patch),
            )
            validation = validate_product(
                resolved, verify_files=True, allow_embedded_fixtures=False
            )
            if not validation.valid:
                raise ValidationError(validation.errors, validation.warnings)
            write_json(args.output, resolved)
            return 0
        if args.command == "demo":
            skill_root = _skill_root()
            run_pipeline(
                skill_root / "assets" / "fixtures" / "demo-annuity-product.json",
                args.out,
                skill_root / "assets" / "fixtures" / "demo-benchmark.json",
                allow_embedded_fixtures=True,
            )
            return 0
        if args.command == "self-test":
            _run_self_test()
            print("annuity-product-intelligence self-test passed")
            return 0
        parser.error("unknown command")
        return 5
    except ProhibitedCustomerDataError as exc:
        print(str(exc), file=sys.stderr)
        return exc.exit_code
    except ValidationError as exc:
        print("validation failed:", file=sys.stderr)
        for error in exc.errors:
            print(f"- {error}", file=sys.stderr)
        return exc.exit_code
    except AnnuityPIError as exc:
        print(str(exc), file=sys.stderr)
        return exc.exit_code
    except Exception as exc:
        print(f"calculation failed: {exc}", file=sys.stderr)
        return 5


if __name__ == "__main__":
    raise SystemExit(main())
