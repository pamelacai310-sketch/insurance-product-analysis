"""
集成测试：验证 insurance-clause-insights 与 insurance-product-analysis 的集成
Integration Test: Verify integration between insurance-clause-insights and insurance-product-analysis
"""

import json
from pathlib import Path
from actuarial_bridge import (
    ExtractedProduct,
    load_clause_report,
    convert_to_product_spec,
    extract_premium_from_text,
    extract_period_from_text,
    map_category_to_type,
    calculate_completeness,
)


def test_extract_premium():
    """测试保费提取"""
    assert extract_premium_from_text("10,000元") == 10000.0
    assert extract_premium_from_text("1万元") == 10000.0
    assert extract_premium_from_text("35000元") == 35000.0
    assert extract_premium_from_text("29.03635万元") == 290363.5
    print("✅ 保费提取测试通过")


def test_extract_period():
    """测试期间提取"""
    assert extract_period_from_text("5年缴") == 5
    assert extract_period_from_text("缴费期间10年") == 10
    assert extract_period_from_text("20年期") == 20
    print("✅ 期间提取测试通过")


def test_map_category():
    """测试类别映射"""
    assert map_category_to_type("年金保险") == "annuity"
    assert map_category_to_type("增额终身寿险") == "whole_life"
    assert map_category_to_type("万能险") == "universal"
    print("✅ 类别映射测试通过")


def test_extracted_product():
    """测试产品数据提取"""
    product = ExtractedProduct(
        company="汇丰人寿",
        product_name="汇赢丰年2026",
        category="年金保险",
        pdf_path="/path/to/pdf",
        annual_premium=290363.5,
        sum_assured=35000.0,
        payment_period=5,
        entry_age=40,
        gender="M",
    )

    completeness = calculate_completeness(product)
    assert completeness == 1.0  # 所有参数都完整
    print("✅ 产品完整性计算测试通过")

    # 测试转换
    spec = convert_to_product_spec(product)
    assert spec is not None
    assert spec.product_name == "汇赢丰年2026"
    assert spec.annual_premium == 290363.5
    assert spec.sum_assured == 35000.0
    print("✅ 产品转换测试通过")


def test_incomplete_product():
    """测试不完整产品处理"""
    product = ExtractedProduct(
        company="测试公司",
        product_name="测试产品",
        category="年金保险",
        pdf_path="/path/to/pdf",
        annual_premium=100000.0,
        # 缺少 sum_assured
    )

    completeness = calculate_completeness(product)
    assert completeness < 0.7  # 应该较低
    print("✅ 不完整产品计算测试通过")

    # 转换应该失败
    spec = convert_to_product_spec(product)
    assert spec is None
    print("✅ 不完整产品转换测试通过")


def test_load_sample_report():
    """测试加载示例报告（如果存在）"""
    import glob

    # 查找报告文件
    pattern = "../insurance-clause-insights/outputs/*/reports/comparison_report.json"
    matching_files = glob.glob(pattern)

    if not matching_files:
        print("⚠️  未找到示例报告，跳过测试")
        return

    products = load_clause_report(Path(matching_files[0]))
    print(f"✅ 成功加载报告，找到 {len(products)} 个产品")

    if products:
        # 测试第一个产品
        first_product = products[0]
        print(f"   示例产品: {first_product.company} - {first_product.product_name}")
        print(f"   类别: {first_product.category}")
        print(f"   保费: {first_product.annual_premium}")
        print(f"   保额: {first_product.sum_assured}")


if __name__ == "__main__":
    print("=" * 80)
    print("集成测试开始 | Integration Test Starting")
    print("=" * 80)
    print()

    try:
        test_extract_premium()
        test_extract_period()
        test_map_category()
        test_extracted_product()
        test_incomplete_product()
        test_load_sample_report()

        print()
        print("=" * 80)
        print("✅ 所有测试通过！| All tests passed!")
        print("=" * 80)
    except AssertionError as e:
        print()
        print("=" * 80)
        print(f"❌ 测试失败: {e}")
        print("=" * 80)
        raise
