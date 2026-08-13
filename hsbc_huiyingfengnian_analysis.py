"""Deprecated product-specific entry point."""


def analyze_hsbc_product() -> dict[str, str]:
    message = (
        "该产品专用旧脚本含固定分红率、推测现金流和综合等级，已停用。"
        "请使用 unified_analysis.py --comparison-case 运行严格分析。"
    )
    print(message)
    return {"status": "disabled", "message": message}


if __name__ == "__main__":
    analyze_hsbc_product()
