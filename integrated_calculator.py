"""Compatibility shim for the retired synthetic integration workflow."""

from __future__ import annotations

from typing import Any, Dict

from actuarial_calculator import ProductSpec


DISABLED_MESSAGE = (
    "该旧集成入口依赖示例现金流、模拟ALM/VaR和固定评分，已停止用于正式产品分析。"
    "请改用 unified_analysis.py --comparison-case；正式输出只做有来源的逐项比较。"
)


def _disabled_payload() -> Dict[str, Any]:
    return {
        "status": "disabled",
        "formal_analysis_supported": False,
        "message": DISABLED_MESSAGE,
        "rating": {
            "status": "disabled",
            "dimensions": {},
            "total_score": None,
            "grade": None,
        },
    }


class IntegratedAnalyzer:
    """Retain the historical API without exposing synthetic analysis results."""

    def __init__(self, spec: ProductSpec):
        self.spec = spec
        self.results: Dict[str, Any] = {}

    def analyze(self) -> Dict[str, Any]:
        self.results = _disabled_payload()
        print(DISABLED_MESSAGE)
        return self.results

    def _generate_integrated_rating(self) -> Dict[str, Any]:
        self.results["rating"] = _disabled_payload()["rating"]
        return self.results["rating"]


def demo_integrated_analysis() -> Dict[str, Any]:
    """Show the migration message instead of running fabricated examples."""
    spec = ProductSpec(
        product_name="旧集成演示（已停用）",
        product_type="annuity",
        entry_age=30,
        gender="M",
        payment_period=5,
        annual_premium=100_000,
        sum_assured=20_000,
    )
    return IntegratedAnalyzer(spec).analyze()


if __name__ == "__main__":
    demo_integrated_analysis()
