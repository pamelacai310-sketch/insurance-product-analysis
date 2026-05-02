"""
完整集成演示
Full Integration Demo

展示如何使用完整集成版分析系统
"""

from actuarial_calculator import ProductSpec
from integrated_calculator import IntegratedAnalyzer


def main():
    """主演示函数"""
    print("="*70)
    print("  保险产品精算分析系统 - 完整集成演示")
    print("  Insurance Product Analysis - Full Integration Demo")
    print("="*70)
    print()

    # 示例1：简单年金险
    print("示例1：年金险产品分析")
    print("-"*70)

    spec1 = ProductSpec(
        product_name="演示年金险产品A",
        product_type="annuity",
        entry_age=30,
        gender='M',
        payment_period=5,
        annual_premium=100_000,
        sum_assured=20_000,
        annuity_start_year=7,
        terminal_age=105,
        dividend_type='accumulate'
    )

    analyzer1 = IntegratedAnalyzer(spec1)
    report1 = analyzer1.analyze()

    print()
    print("分析完成！")
    print(f"评级: {report1['rating']['grade']}")
    print(f"总分: {report1['rating']['total_score']:.2f}/5.0")
    print()

    # 示例2：不同投保年龄对比
    print("="*70)
    print("示例2：不同投保年龄对比分析")
    print("-"*70)

    ages = [25, 30, 35, 40, 45]
    comparison = []

    for age in ages:
        spec = ProductSpec(
            product_name=f"演示年金险（{age}岁投保）",
            product_type="annuity",
            entry_age=age,
            gender='M',
            payment_period=5,
            annual_premium=100_000,
            sum_assured=20_000,
            annuity_start_year=7
        )

        # 简化分析（仅基础IRR）
        from actuarial_calculator import irr_scenario_analysis
        irr_results = irr_scenario_analysis(spec)

        comparison.append({
            'age': age,
            'irr_conservative': irr_results.get('保守（0分红）', 0),
            'irr_neutral': irr_results.get('中性（历史低位分红）', 0),
            'irr_optimistic': irr_results.get('乐观（演示分红水平）', 0)
        })

    # 打印对比表
    print()
    print("投保年龄 vs IRR对比:")
    print("-"*70)
    print(f"{'年龄':<6} {'保守IRR':<12} {'中性IRR':<12} {'乐观IRR':<12}")
    print("-"*70)

    for comp in comparison:
        print(f"{comp['age']:<6} "
              f"{comp['irr_conservative']:>10.2%}  "
              f"{comp['irr_neutral']:>10.2%}  "
              f"{comp['irr_optimistic']:>10.2%}")

    print()

    # 示例3：产品对比
    print("="*70)
    print("示例3：不同公司产品对比")
    print("-"*70)

    products = [
        {
            'name': '产品A（保守型）',
            'premium': 100_000,
            'benefit': 18_000,
            'company_strength': 'strong'
        },
        {
            'name': '产品B（平衡型）',
            'premium': 100_000,
            'benefit': 20_000,
            'company_strength': 'medium'
        },
        {
            'name': '产品C（激进型）',
            'premium': 100_000,
            'benefit': 22_000,
            'company_strength': 'weak'
        }
    ]

    print()
    print("产品对比分析:")
    print("-"*70)

    for prod in products:
        spec = ProductSpec(
            product_name=prod['name'],
            product_type="annuity",
            entry_age=30,
            gender='M',
            payment_period=5,
            annual_premium=prod['premium'],
            sum_assured=prod['benefit'],
            annuity_start_year=7
        )

        from actuarial_calculator import irr_scenario_analysis
        irr_results = irr_scenario_analysis(spec)
        irr_neutral = irr_results.get('中性（历史低位分红）', 0)

        # 模拟公司稳健性评分
        strength_scores = {
            'strong': 5,
            'medium': 3,
            'weak': 1
        }
        strength_score = strength_scores[prod['company_strength']]

        print()
        print(f"产品: {prod['name']}")
        print(f"  年缴保费: {prod['premium']:,.0f}元")
        print(f"  年金额: {prod['benefit']:,.0f}元")
        print(f"  IRR（中性）: {irr_neutral:.2%}")
        print(f"  公司稳健性: {'⭐'*strength_score}")

        # 综合建议
        if irr_neutral > 0.025 and strength_score >= 4:
            print(f"  ✅ 推荐：高收益+强稳健性")
        elif irr_neutral > 0.025 and strength_score <= 2:
            print(f"  ⚠️  谨慎：高收益但公司稳健性弱")
        elif irr_neutral <= 0.020 and strength_score >= 4:
            print(f"  ℹ️  适合：低风险偏好投资者")
        else:
            print(f"  ℹ️  一般：需综合考虑其他因素")

    print()
    print("="*70)
    print("演示完成！")
    print("="*70)
    print()
    print("💡 提示：")
    print("  1. 安装精算库可获得更精确的分析")
    print("     运行: ./install_dependencies.sh")
    print()
    print("  2. 查看完整集成版分析")
    print("     运行: python3 integrated_calculator.py")
    print()
    print("  3. 查看文档")
    print("     - 快速开始: QUICKSTART.md")
    print("     - 集成指南: INTEGRATION_GUIDE.md")
    print("     - 库详解: LIBRARIES_SUMMARY.md")
    print()


if __name__ == "__main__":
    main()
