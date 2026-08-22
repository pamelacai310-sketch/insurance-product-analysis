"""Compact command-line interface for leveraged-life product intelligence."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import sys
import tempfile
from typing import Any, Optional, Sequence

from . import __version__
from .comparator import compare_reports
from .metrics import analyze_product
from .validate import validate_product


def _reject_constant(value: str) -> None:
    raise ValueError(f"Non-finite JSON constant is forbidden: {value}")


def read_json(path: str) -> dict:
    with open(path, "r", encoding="utf-8") as handle:
        value = json.load(handle, parse_constant=_reject_constant)
    if not isinstance(value, dict):
        raise ValueError("JSON root must be an object")
    return value


def read_canonical_input(path: str) -> dict:
    """Read canonical JSON or unwrap a canonical-ready extraction bundle."""

    value = read_json(path)
    if "canonical_ready" not in value:
        return value
    if value.get("canonical_ready") is not True:
        raise ValueError(
            "extraction bundle is not canonical-ready; review and canonicalize it first"
        )
    if value.get("kind") != "json" or not isinstance(value.get("data"), dict):
        raise ValueError("canonical-ready extraction bundle must contain JSON data")
    return value["data"]


def _encoded(value: Any, pretty: bool = False) -> str:
    if pretty:
        return (
            json.dumps(
                value, ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False
            )
            + "\n"
        )
    return (
        json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        )
        + "\n"
    )


def write_json(path: str, value: Any) -> None:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(
        prefix=f".{target.name}.", dir=str(target.parent)
    )
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            handle.write(_encoded(value, pretty=True))
        os.replace(temporary, target)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def emit(value: Any, stream=None) -> None:
    (stream or sys.stdout).write(_encoded(value, pretty=False))


def _analysis_summary(report: dict, output: Optional[str]) -> dict:
    return {
        "command": "analyze",
        "status": report["analysis_status"],
        "version": report["analysis_version"],
        "product_id": report.get("product", {}).get("product_id"),
        "case_ids": [case["case_id"] for case in report.get("case_reports", [])],
        "error_count": report["validation"]["error_count"],
        "warning_count": report["validation"]["warning_count"],
        "output": None if output is None else Path(output).name,
    }


def cmd_validate(args: argparse.Namespace) -> int:
    result = validate_product(
        read_canonical_input(args.input), strict_evidence=args.strict_evidence
    )
    payload = result.to_dict()
    if args.output:
        write_json(args.output, payload)
    emit(
        {
            "command": "validate",
            "status": "ok" if result.ok else "invalid",
            "error_count": len(result.errors),
            "warning_count": len(result.warnings),
            "codes": sorted({issue.code for issue in result.issues}),
            "output": None if not args.output else Path(args.output).name,
        }
    )
    return 0 if result.ok else 2


def cmd_analyze(args: argparse.Namespace) -> int:
    report = analyze_product(
        read_canonical_input(args.input), strict_evidence=args.strict_evidence
    )
    if args.output:
        write_json(args.output, report)
    if args.full_stdout:
        emit(report)
    else:
        emit(_analysis_summary(report, args.output))
    return 0 if report["analysis_status"] != "invalid" else 2


def cmd_compare(args: argparse.Namespace) -> int:
    reports = [
        analyze_product(
            read_canonical_input(path), strict_evidence=args.strict_evidence
        )
        for path in args.inputs
    ]
    invalid = [
        report.get("product", {}).get("product_id")
        for report in reports
        if report["analysis_status"] == "invalid"
    ]
    if invalid:
        emit(
            {
                "command": "compare",
                "status": "invalid_input",
                "invalid_products": sorted(invalid),
            }
        )
        return 2
    horizons = [int(value) for value in args.horizons.split(",") if value.strip()]
    comparison = compare_reports(reports, args.case_id, horizons)
    if args.output:
        write_json(args.output, comparison)
    if args.full_stdout:
        emit(comparison)
    else:
        emit(
            {
                "command": "compare",
                "status": "ok" if comparison["comparable"] else "not_comparable",
                "case_id": args.case_id,
                "products": comparison.get("products", []),
                "horizon_count": len(comparison.get("horizons", [])),
                "reason_codes": comparison.get("reason_codes", []),
                "output": None if not args.output else Path(args.output).name,
            }
        )
    return 0 if comparison["comparable"] else 3


def cmd_extract(args: argparse.Namespace) -> int:
    from .parsers import parse_file

    fallback = None
    if args.allow_llm:
        if not args.llm_endpoint:
            raise ValueError("--allow-llm requires --llm-endpoint")
        from .llm_fallback import HTTPJSONLLMFallback, LLMFallbackConfig

        fallback = HTTPJSONLLMFallback(
            LLMFallbackConfig(
                endpoint=args.llm_endpoint,
                model=args.llm_model,
                api_key_env=args.llm_api_key_env,
                timeout_seconds=args.llm_timeout,
            )
        )
    result = parse_file(args.input, llm_fallback=fallback)
    payload = result.to_dict()
    if args.output:
        write_json(args.output, payload)
    if args.full_stdout:
        emit(payload)
    else:
        emit(
            {
                "command": "extract",
                "status": payload.get("status"),
                "canonical_ready": payload.get("canonical_ready", False),
                "source_sha256": payload.get("source_sha256"),
                "route_count": len(payload.get("routes", [])),
                "evidence_count": len(payload.get("evidence", [])),
                "unresolved_fields": payload.get("unresolved_fields", []),
                "output": None if not args.output else Path(args.output).name,
            }
        )
    return 0 if payload.get("status") in {"complete", "partial"} else 2


def cmd_benchmark(args: argparse.Namespace) -> int:
    skill_root = Path(__file__).resolve().parents[2]
    fixture_dir = skill_root / "assets" / "benchmarks"
    paths = sorted(fixture_dir.glob("*.json"))
    reports = [
        analyze_product(read_canonical_input(str(path)), strict_evidence=True)
        for path in paths
    ]
    invalid = [
        report.get("product", {}).get("product_id")
        for report in reports
        if report["analysis_status"] == "invalid"
    ]
    status = "ok" if not invalid and reports else "failed"
    emit(
        {
            "command": "benchmark",
            "status": status,
            "fixture_count": len(paths),
            "product_ids": sorted(
                report.get("product", {}).get("product_id") for report in reports
            ),
            "invalid_products": sorted(invalid),
        }
    )
    return 0 if status == "ok" else 2


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="llpi",
        description="Evidence-first, product-only leveraged-life economics.",
    )
    parser.add_argument("--version", action="version", version=__version__)
    subparsers = parser.add_subparsers(dest="command", required=True)

    validate_parser = subparsers.add_parser(
        "validate", help="Validate canonical product JSON."
    )
    validate_parser.add_argument("--input", required=True)
    validate_parser.add_argument("--output")
    validate_parser.add_argument("--strict-evidence", action="store_true")
    validate_parser.set_defaults(handler=cmd_validate)

    analyze_parser = subparsers.add_parser(
        "analyze", help="Compute product-only metrics."
    )
    analyze_parser.add_argument("--input", required=True)
    analyze_parser.add_argument("--output")
    analyze_evidence = analyze_parser.add_mutually_exclusive_group()
    analyze_evidence.add_argument(
        "--strict-evidence", dest="strict_evidence", action="store_true"
    )
    analyze_evidence.add_argument(
        "--allow-unverified-evidence",
        dest="strict_evidence",
        action="store_false",
        help="Exploratory only: calculate while reporting unsupported evidence as warnings.",
    )
    analyze_parser.set_defaults(strict_evidence=True)
    analyze_parser.add_argument("--full-stdout", action="store_true")
    analyze_parser.set_defaults(handler=cmd_analyze)

    compare_parser = subparsers.add_parser(
        "compare", help="Compare peers on the same benchmark hash."
    )
    compare_parser.add_argument("--inputs", nargs="+", required=True)
    compare_parser.add_argument("--case-id", required=True)
    compare_parser.add_argument("--horizons", default="1,5,10,20,30")
    compare_parser.add_argument("--output")
    compare_parser.add_argument("--strict-evidence", action="store_true", default=True)
    compare_parser.add_argument("--full-stdout", action="store_true")
    compare_parser.set_defaults(handler=cmd_compare)

    extract_parser = subparsers.add_parser(
        "extract", help="Layered document extraction with evidence."
    )
    extract_parser.add_argument("--input", required=True)
    extract_parser.add_argument("--output")
    extract_parser.add_argument("--full-stdout", action="store_true")
    extract_parser.add_argument("--allow-llm", action="store_true")
    extract_parser.add_argument("--llm-endpoint")
    extract_parser.add_argument("--llm-model", default="unspecified")
    extract_parser.add_argument("--llm-api-key-env", default="LLPI_LLM_API_KEY")
    extract_parser.add_argument("--llm-timeout", type=float, default=30.0)
    extract_parser.set_defaults(handler=cmd_extract)

    benchmark_parser = subparsers.add_parser(
        "benchmark", help="Run shipped synthetic benchmark fixtures."
    )
    benchmark_parser.set_defaults(handler=cmd_benchmark)
    return parser


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return int(args.handler(args))
    except (
        Exception
    ) as exc:  # CLI boundary: deterministic error line, no traceback by default.
        emit(
            {
                "command": getattr(args, "command", None),
                "status": "error",
                "error": str(exc),
            },
            stream=sys.stderr,
        )
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
