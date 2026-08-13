#!/usr/bin/env python3
"""Unified, evidence-first actuarial analysis entry point."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from strict_analysis import (
    audit_clause_report_readiness,
    load_engine,
    render_readiness_markdown,
    run_strict_comparison,
)


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="严格同条件保险产品精算分析；不自动补参数，不输出主观综合等级"
    )
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument(
        "--comparison-case",
        type=Path,
        help="符合 compare-insurance-products 输入规范的JSON",
    )
    source.add_argument(
        "--clause-report",
        type=Path,
        help="旧条款报告；仅生成严格分析资料准备度审计",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("outputs/strict_comparison"),
        help="严格comparison.md和comparison.json输出目录",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("outputs/strict_input_readiness.json"),
        help="条款报告准备度JSON输出路径",
    )
    parser.add_argument("--quiet", action="store_true")

    # Kept only to produce an explicit safety error for callers of the old workflow.
    parser.add_argument("--default-age", type=int)
    parser.add_argument("--default-gender", choices=("M", "F"))
    parser.add_argument("--min-completeness", type=float)
    parser.add_argument("--category")
    parser.add_argument("--export-table", action="store_true")
    return parser


def _reject_legacy_inference_options(parser: argparse.ArgumentParser, args: argparse.Namespace) -> None:
    prohibited = {
        "--default-age": args.default_age,
        "--default-gender": args.default_gender,
        "--min-completeness": args.min_completeness,
        "--category": args.category,
        "--export-table": args.export_table,
    }
    used = [name for name, value in prohibited.items() if value not in (None, False)]
    if used:
        parser.error(
            "严格流程禁止默认补值、跨条件筛选后混排或旧评级导出；请移除："
            + ", ".join(used)
        )


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)
    _reject_legacy_inference_options(parser, args)

    if args.clause_report:
        try:
            audit = audit_clause_report_readiness(args.clause_report)
        except (OSError, json.JSONDecodeError, TypeError, ValueError) as exc:
            print(f"资料准备度审计失败：{exc}", file=sys.stderr)
            return 2
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(
            json.dumps(audit, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        markdown_path = args.output.with_suffix(".md")
        markdown_path.write_text(render_readiness_markdown(audit), encoding="utf-8")
        if not args.quiet:
            print(audit["message"])
            print(f"已生成：{args.output}")
            print(f"已生成：{markdown_path}")
        return 0

    engine = load_engine()
    try:
        output = run_strict_comparison(args.comparison_case, args.output_dir)
    except engine.ValidationError as exc:
        print("严格输入验证失败：", file=sys.stderr)
        for error in exc.errors:
            print(f"- {error}", file=sys.stderr)
        return 2
    except (engine.CalculationError, OSError, ValueError) as exc:
        print(f"严格计算失败：{exc}", file=sys.stderr)
        return 3
    if not args.quiet:
        print(output["result"]["conclusion"]["text"])
        print(f"已生成：{output['markdown_path']}")
        print(f"已生成：{output['json_path']}")
        print("正式输出不包含主观总分或A-D等级。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
