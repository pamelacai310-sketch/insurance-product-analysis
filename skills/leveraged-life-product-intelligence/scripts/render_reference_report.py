#!/usr/bin/env python3
"""Render the shipped WWA/WWB/Allianz reference comparison."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys


SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))

from llpi.comparator import compare_reports  # noqa: E402
from llpi.metrics import analyze_product  # noqa: E402


REFERENCE_ORDER = [
    "wwa-fortune-life-2025.json",
    "wwb-bonjour-2025-plan-1.json",
    "wwb-bonjour-2025-plan-2.json",
    "allianz-prosperous-legacy-c-5-grade-a.json",
    "allianz-prosperous-legacy-c-5-grade-b.json",
    "allianz-prosperous-legacy-c-5-grade-c.json",
    "allianz-prosperous-legacy-c-5-grade-d.json",
    "allianz-prosperous-legacy-c-5-grade-e.json",
]
CASE_ID = "LLPI-STD-10PAY-100K-v1"


def read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def metric_value(item: dict | None) -> float | None:
    if not item or item.get("status") != "ok" or item.get("value") is None:
        return None
    return float(item["value"])


def fmt_money(value: str | float | None) -> str:
    if value is None:
        return "缺失"
    return f"{float(value):,.0f}"


def fmt_pct(value: float | None, digits: int = 2) -> str:
    if value is None:
        return "未达到/不可计算"
    return f"{value:.{digits}%}"


def fmt_ratio(value: float | None) -> str:
    if value is None:
        return "不可计算"
    return f"{value:.2f}x"


def find_case(report: dict, case_id: str) -> dict:
    return next(case for case in report["case_reports"] if case["case_id"] == case_id)


def find_row(case: dict, policy_year: int) -> dict:
    return next(row for row in case["rows"] if row["policy_year"] == policy_year)


def year10_table(reports: list[dict]) -> list[str]:
    lines = [
        "| 产品/方案 | 保证现金价值 | 保证CV IRR | 普通身故金 | 条件身故IRR | DeathBenefit/CV |",
        "|---|---:|---:|---:|---:|---:|",
    ]
    for report in reports:
        row = find_row(find_case(report, CASE_ID), 10)
        guaranteed = row["guaranteed"]
        lines.append(
            "| {name} | {cash} | {cash_irr} | {death} | {death_irr} | {ratio} |".format(
                name=report["product"]["name"],
                cash=fmt_money(guaranteed["cash_surrender_value"]),
                cash_irr=fmt_pct(metric_value(guaranteed["cash_value_irr"])),
                death=fmt_money(guaranteed["death_benefit"]),
                death_irr=fmt_pct(
                    metric_value(guaranteed["conditional_death_irr"])
                ),
                ratio=fmt_ratio(metric_value(guaranteed["death_benefit_cv_ratio"])),
            )
        )
    return lines


def breakeven_table(reports: list[dict]) -> list[str]:
    lines = [
        "| 产品/方案 | CV回本年 | CV IRR>=1% | CV IRR>=2% | CV IRR>=3% |",
        "|---|---:|---:|---:|---:|",
    ]
    for report in reports:
        summary = find_case(report, CASE_ID)["summary"]
        thresholds = summary["guaranteed_cash_value_irr_breakeven"]
        values = []
        for threshold in ("0.01", "0.02", "0.03"):
            value = thresholds[threshold]["first"].get("value")
            values.append("未达到" if value is None else f"第{value}年")
        recovery = summary["guaranteed_breakeven"]["first"].get("value")
        lines.append(
            f"| {report['product']['name']} | "
            f"{'未回本' if recovery is None else f'第{recovery}年'} | "
            f"{values[0]} | {values[1]} | {values[2]} |"
        )
    return lines


def inflation_table(reports: list[dict], policy_year: int = 30) -> list[str]:
    lines = [
        f"| 产品/方案 | 第{policy_year}年名义身故金 | 0%实际值 | 2%实际值 | 3%实际值 | 4%实际值 |",
        "|---|---:|---:|---:|---:|---:|",
    ]
    for report in reports:
        guaranteed = find_row(find_case(report, CASE_ID), policy_year)["guaranteed"]
        stress = guaranteed["death_benefit_purchasing_power_stress"]
        lines.append(
            "| {name} | {nominal} | {r0} | {r2} | {r3} | {r4} |".format(
                name=report["product"]["name"],
                nominal=fmt_money(guaranteed["death_benefit"]),
                r0=fmt_money(stress["0.00"]["real_amount"]),
                r2=fmt_money(stress["0.02"]["real_amount"]),
                r3=fmt_money(stress["0.03"]["real_amount"]),
                r4=fmt_money(stress["0.04"]["real_amount"]),
            )
        )
    return lines


def illustration_table(reports: list[dict]) -> list[str]:
    lines = [
        "| WWB正式演示 | 年度 | 保证身故 | 演示身故 | 身故NGR | 保证退保 | 演示退保 | 退保NGR | 保证CV IRR | 演示CV IRR |",
        "|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for report in reports:
        product_id = report["product"]["product_id"]
        if not product_id.startswith("wwb-"):
            continue
        case = next(
            case
            for case in report["case_reports"]
            if case["case_id"].startswith("WWB-DOC-")
        )
        for policy_year in (10, 20, 30, 40, 50, 65):
            row = find_row(case, policy_year)
            guaranteed = row["guaranteed"]
            illustrated = row["scenarios"]["illustrated"]
            lines.append(
                "| {name} | {year} | {gd} | {idb} | {dngr} | {gc} | {ic} | {cngr} | {girr} | {iirr} |".format(
                    name=report["product"]["name"],
                    year=policy_year,
                    gd=fmt_money(guaranteed["death_benefit"]),
                    idb=fmt_money(illustrated["death_benefit"]),
                    dngr=fmt_pct(metric_value(illustrated["death_ngr"]), 1),
                    gc=fmt_money(guaranteed["cash_surrender_value"]),
                    ic=fmt_money(illustrated["cash_surrender_value"]),
                    cngr=fmt_pct(metric_value(illustrated["cash_value_ngr"]), 1),
                    girr=fmt_pct(metric_value(guaranteed["cash_value_irr"])),
                    iirr=fmt_pct(metric_value(illustrated["cash_value_irr"])),
                )
            )
    return lines


def render(reports: list[dict], manifest: dict) -> str:
    standard_counts = manifest["annual_value_counts"]
    lines = [
        "# 杠杆寿险产品决策数据参考报告",
        "",
        "> 版本：`leveraged-life-product-intelligence v1.0.0` 增强版。标准实验为年交10万元、连续10年，总保费100万元；仅用于产品经济结构比较，不构成客户建议。",
        "",
        "## 结论口径",
        "",
        "本报告不设置“综合领先”产品。每项排序只在同一保费实验、同一保单年度、同一保证/演示口径和同一指标内成立；不同年度的现金价值、条件身故IRR、身故杠杆与流动性方向可能冲突。WWB 的计划一/二及安联 A-E 费率等级均作为产品内部方案敏感性保留，不能把某一等级自动等同于汇丰的核保分类。",
        "",
        "## 数据完整性",
        "",
        f"- WWA 官网定价行导入 {standard_counts['wwa']} 个连续保单年度。",
        f"- WWB 计划一、计划二各导入 {standard_counts['wwb_plan_1']} 和 {standard_counts['wwb_plan_2']} 个连续保单年度。",
        f"- 安联 A-E 五个费率等级各导入 {standard_counts['allianz_grade_a']} 个连续保单年度。",
        "- WWB 计划一、计划二正式利益演示各导入 65 个年度，保证与情景2非保证利益分列。",
        "- WWA 为非分红产品，无 NGR；本地官方资料未包含与同一标准实验匹配的安联正式利益演示，因此安联不参与演示曲线/NGR比较。",
        "",
        "## 第10年决策数据",
        "",
        *year10_table(reports),
        "",
        "条件身故IRR假定对应保单年度末发生身故，仅衡量该条件现金流，不含死亡概率，也不是投资收益承诺。`DeathBenefit/CV` 高表示更偏身故保障、低表示更偏退保流动性，不存在统一的越高越好。",
        "",
        "## 回本与IRR门槛",
        "",
        *breakeven_table(reports),
        "",
        "门槛年份采用首次观察到的完整保单年度，不做年度间插值；“未达到”只表示在官网披露窗口内未达到。",
        "",
        "## 通胀购买力",
        "",
        *inflation_table(reports),
        "",
        "## 正式利益演示与NGR",
        "",
        "`NGR = (演示总利益 - 保证利益) / 演示总利益`。NGR 越高，演示结果对非保证红利的依赖越大；它不是红利实现概率。",
        "",
        *illustration_table(reports),
        "",
        "## 使用边界",
        "",
        "现金价值表和费率表可生成保证曲线；分红产品的演示曲线必须来自正式利益演示，缺少正式演示时保持未知，不能根据保证表或历史分红反推。安联 A-E 等级属于费率敏感性，只有正式核保对应关系明确后，才能选定单一等级与汇丰方案作一对一决策。",
        "",
    ]
    return "\n".join(lines)


def parse_args() -> argparse.Namespace:
    skill_root = SCRIPT_DIR.parent
    repository_root = skill_root.parents[1]
    parser = argparse.ArgumentParser(description="Render LLPI reference report")
    parser.add_argument(
        "--reference-dir",
        type=Path,
        default=skill_root / "assets" / "reference-products",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=repository_root
        / "reports"
        / "leveraged_life_product_intelligence_v1_0_0",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    canonical = [read_json(args.reference_dir / name) for name in REFERENCE_ORDER]
    reports = [analyze_product(item, strict_evidence=True) for item in canonical]
    if any(report["analysis_status"] == "invalid" for report in reports):
        raise ValueError("Reference input failed strict analysis")
    comparison = compare_reports(
        reports,
        CASE_ID,
        horizons=[1, 5, 10, 20, 30, 40, 50, 60, 70],
    )
    if not comparison["comparable"]:
        raise ValueError(f"Reference inputs are not comparable: {comparison}")
    args.output_dir.mkdir(parents=True, exist_ok=True)
    (args.output_dir / "decision_data.md").write_text(
        render(reports, read_json(args.reference_dir / "manifest.json")),
        encoding="utf-8",
    )
    (args.output_dir / "comparison.json").write_text(
        json.dumps(comparison, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(
        json.dumps(
            {
                "status": "ok",
                "output_dir": str(args.output_dir.resolve()),
                "overall_winner": comparison["decision_scope"]["overall_winner"],
            },
            ensure_ascii=False,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
