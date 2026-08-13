"""Compatibility shim for the retired synthetic enhanced analyzer."""

from __future__ import annotations

from typing import Any, Dict

from actuarial_calculator import ProductSpec


DISABLED_MESSAGE = (
    "增强版旧入口未接入保险公司真实资产、负债、准备金和经验数据，"
    "其生命表回退、偿付能力示例和随机VaR均已停用。"
    "请使用 unified_analysis.py --comparison-case。"
)


def _disabled_payload(section: str) -> Dict[str, Any]:
    return {
        "status": "disabled",
        "formal_analysis_supported": False,
        "section": section,
        "message": DISABLED_MESSAGE,
        "dimensions": {},
        "total_score": None,
        "grade": None,
    }


class EnhancedProductAnalyzer:
    """Preserve legacy method names while returning no synthetic metrics."""

    def __init__(self, spec: ProductSpec):
        self.spec = spec
        self.analysis_results: Dict[str, Any] = {}

    def analyze_with_lifelib(self) -> Dict[str, Any]:
        return _disabled_payload("lifelib")

    def analyze_company_solvency(self) -> Dict[str, Any]:
        return _disabled_payload("company_solvency")

    def analyze_extreme_risk(self) -> Dict[str, Any]:
        return _disabled_payload("extreme_risk")

    def generate_comprehensive_report(self) -> Dict[str, Any]:
        result = _disabled_payload("comprehensive_report")
        self.analysis_results = result
        print(DISABLED_MESSAGE)
        return result


def demo_enhanced_analysis() -> Dict[str, Any]:
    """Show the migration message instead of running fabricated examples."""
    spec = ProductSpec(
        product_name="旧增强演示（已停用）",
        product_type="annuity",
        entry_age=30,
        gender="M",
        payment_period=5,
        annual_premium=100_000,
        sum_assured=20_000,
    )
    return EnhancedProductAnalyzer(spec).generate_comprehensive_report()


if __name__ == "__main__":
    demo_enhanced_analysis()
