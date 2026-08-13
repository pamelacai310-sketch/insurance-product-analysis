"""Safe entry points for the repository's strict comparison engine."""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from types import ModuleType
from typing import Any


ENGINE_PATH = (
    Path(__file__).resolve().parent
    / "skills"
    / "compare-insurance-products"
    / "scripts"
    / "insurance_compare.py"
)


def load_engine() -> ModuleType:
    """Load the portable skill engine without maintaining a second implementation."""
    module_name = "insurance_product_analysis_strict_engine"
    existing = sys.modules.get(module_name)
    if existing is not None:
        return existing
    spec = importlib.util.spec_from_file_location(module_name, ENGINE_PATH)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"无法加载严格比较引擎：{ENGINE_PATH}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


def run_strict_comparison(input_path: Path, output_dir: Path) -> dict[str, Any]:
    engine = load_engine()
    data = engine.load_json(input_path)
    validation = engine.validate_case(data)
    result = engine.calculate_case(data, validation)
    markdown_path, json_path = engine.write_outputs(result, output_dir)
    return {
        "result": result,
        "markdown_path": str(markdown_path),
        "json_path": str(json_path),
    }


def audit_clause_report_readiness(report_path: Path) -> dict[str, Any]:
    """Audit a clause report without inventing inputs or calculating a ranking."""
    payload = json.loads(report_path.read_text(encoding="utf-8"))
    products: list[dict[str, Any]] = []
    for group in payload.get("groups", []):
        for product in group.get("products", []):
            params = product.get("actuarial_params") or {}
            required = {
                "entry_age": params.get("entry_age"),
                "gender": params.get("gender"),
                "payment_period_years": params.get("payment_period"),
                "annual_premium": params.get("annual_premium"),
                "base_amount_or_rate": params.get("sum_assured"),
                "source_refs": product.get("source_refs"),
                "cash_value_table": product.get("cash_value") or product.get("cash_value_table"),
            }
            missing = [name for name, value in required.items() if value in (None, "", [], {})]
            products.append(
                {
                    "company": product.get("company", ""),
                    "product_name": product.get("product_name", ""),
                    "category": group.get("category", ""),
                    "strict_ready": not missing,
                    "missing_fields": missing,
                }
            )
    return {
        "mode": "readiness_only",
        "formal_actuarial_analysis": False,
        "source_clause_report": str(report_path),
        "message": (
            "条款报告不会自动补年龄、性别、交费期、领取规则或满期金，"
            "也不会生成IRR排名或综合等级。请补齐严格comparison-case后再计算。"
        ),
        "total_products": len(products),
        "strict_ready_count": sum(1 for product in products if product["strict_ready"]),
        "products": products,
    }


def render_readiness_markdown(audit: dict[str, Any]) -> str:
    lines = [
        "# 严格精算分析资料准备度审计",
        "",
        audit["message"],
        "",
        f"- 产品数：{audit['total_products']}",
        f"- 资料字段初步齐备：{audit['strict_ready_count']}",
        "- 本报告不包含IRR、排名、总分或A-D等级。",
        "",
        "| 公司 | 产品 | 类别 | 初步齐备 | 缺失字段 |",
        "|---|---|---|---|---|",
    ]
    for product in audit["products"]:
        lines.append(
            f"| {product['company']} | {product['product_name']} | {product['category']} | "
            f"{'是' if product['strict_ready'] else '否'} | {', '.join(product['missing_fields']) or '无'} |"
        )
    lines.extend(
        [
            "",
            "> “初步齐备”只代表字段存在，正式计算仍需通过版本、单位、来源哈希和同条件校验。",
            "",
        ]
    )
    return "\n".join(lines)
