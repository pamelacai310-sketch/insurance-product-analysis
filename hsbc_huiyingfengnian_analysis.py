"""
HSBC汇丰汇赢丰年2026年金保险（分红型）精算分析
HSBC Huiying Fengnian 2026 Participating Annuity Analysis
"""

from actuarial_calculator import ProductSpec, irr_scenario_analysis
from integrated_calculator import IntegratedAnalyzer
import numpy as np


def analyze_hsbc_product():
    """分析HSBC汇赢丰年2026产品"""

    print("=" * 80)
    print("汇丰汇赢丰年2026年金保险（分红型）- 精算优势分析报告")
    print("HSBC Huiying Fengnian 2026 Participating Annuity - Actuarial Analysis Report")
    print("=" * 80)
    print()

    # 根据产品建议书创建产品规格
    # Product specification based on the proposal illustration
    spec = ProductSpec(
        product_name="汇丰汇赢丰年2026年金保险（分红型）",
        product_type="annuity_participating",
        entry_age=40,          # 40岁男性
        gender='M',
        payment_period=5,       # 5年交
        annual_premium=290_363.50,  # 首期保费
        sum_assured=35_000,     # 基本保险金额（年金额）
        annuity_start_year=5,   # 第5个保单周年日开始领
        terminal_age=105,       # 至105岁
        dividend_type='accumulate'  # 分红购买交清增额保险
    )

    print("📋 产品基本信息")
    print("-" * 80)
    print(f"产品名称: {spec.product_name}")
    print(f"投保年龄: {spec.entry_age}岁  性别: {'男' if spec.gender == 'M' else '女'}")
    print(f"交费方式: {spec.payment_period}年缴  首年保费: {spec.annual_premium:,.2f}元")
    print(f"基本保险金额: {spec.sum_assured:,.2f}元")
    print(f"首次年金领取: 第{spec.annuity_start_year}个保单年度")
    print(f"保险期间: 至{spec.terminal_age}周岁")
    print(f"总保费投入: {spec.annual_premium * spec.payment_period:,.2f}元")
    print()

    # IRR情景分析
    print("📊 一、IRR三情景分析")
    print("-" * 80)

    irr_results = irr_scenario_analysis(spec)

    print(f"保守情景（0分红）: {irr_results.get('保守（0分红）', 0):.2%}")
    print(f"中性情景（历史低位分红≈1%）: {irr_results.get('中性（历史低位分红）', 0):.2%}")
    print(f"乐观情景（演示分红≈2.5%）: {irr_results.get('乐观（演示分红水平）', 0):.2%}")
    print()

    # 与市场利率对比
    print("📈 二、与市场基准利率对比（2025年参考）")
    print("-" * 80)
    print(f"3年期国债: 约2.50%-2.80%")
    print(f"5年大额存单: 约2.30%-2.60%")
    print(f"货币基金: 约1.80%-2.20%")
    print(f"本产品中性IRR: {irr_results.get('中性（历史低位分红）', 0):.2%}")
    print()

    # 使用集成分析器进行完整分析
    print("🔍 三、完整集成分析")
    print("-" * 80)

    analyzer = IntegratedAnalyzer(spec)
    report = analyzer.analyze()

    # 提取关键指标
    rating = report['rating']
    scores = report.get('dimension_scores', {})

    print(f"综合评级: {rating['grade']}")
    print(f"总分: {rating['total_score']:.2f}/5.0")
    print()

    if scores:
        print("📊 七维度评分:")
        print("-" * 80)
        for dimension, score in scores.items():
            bar = "█" * int(score * 2)
            print(f"{dimension:12s}: [{bar:<10}] {score:.1f}/5.0")
        print()

    # 精算优势分析
    print("🌟 四、产品精算优势分析")
    print("-" * 80)

    advantages = []

    # 优势1: 分红机制
    advantages.append({
        "优势": "分红机制 - 购买交清增额保险",
        "说明": "红利用于购买交清增额保险，自动增加基本保险金额，实现复利增长",
        "精算价值": "提升长期IRR约0.3-0.7个百分点",
        "风险": "红利不保证，实际分红取决于公司经营状况"
    })

    # 优势2: 保险期间长
    advantages.append({
        "优势": "超长保险期间 - 至105岁",
        "说明": "覆盖整个退休期，提供长达65年的年金现金流",
        "精算价值": "有效应对长寿风险，提供终身收入保障",
        "风险": "通胀可能侵蚀长期购买力"
    })

    # 优势3: 身故保障
    advantages.append({
        "优势": "身故保障 - 已交保费扣除年金与现金价值取大",
        "说明": "身故时给付已交保费扣除已领年金或现金价值的较大者",
        "精算价值": "保证保费不损失，提供身故保障",
        "风险": "早期身故可能损失保费时间价值"
    })

    # 优势4: 灵活性
    advantages.append({
        "优势": "年金领取方式灵活",
        "说明": "可选择自动转账、申请领取或购买交清增额保险",
        "精算价值": "适应不同流动性需求",
        "风险": "不同选择影响长期收益"
    })

    # 优势5: 退保保护
    advantages.append({
        "优势": "退保保护 - 增加退保给付",
        "说明": "退保时额外给付交清增额保险减少部分对应的现金价值",
        "精算价值": "减少退保损失",
        "风险": "犹豫期后退保仍有损失"
    })

    # 优势6: 保单贷款
    advantages.append({
        "优势": "保单贷款功能",
        "说明": "可申请保单贷款，提供流动性支持",
        "精算价值": "提高资金使用灵活性",
        "风险": "贷款会影响保单价值和收益"
    })

    for i, adv in enumerate(advantages, 1):
        print(f"\n优势{i}: {adv['优势']}")
        print(f"  说明: {adv['说明']}")
        print(f"  精算价值: {adv['精算价值']}")
        print(f"  风险: {adv['风险']}")

    print()

    # 精算建议
    print("💡 五、精算建议")
    print("-" * 80)

    suggestions = [
        "适合40岁左右、有一定资金实力、希望补充养老金储备的人群",
        "适合风险偏好较低、希望获得稳定现金流的人群",
        "建议作为养老规划的补充工具，而非主要投资工具",
        "关注汇丰人寿历史分红实现率，选择分红稳定的公司",
        "长期持有至满期可获得最佳收益，避免早期退保",
        "可考虑增加定期寿险补充早期身故保障",
        "注意通胀风险，建议搭配其他投资工具分散风险"
    ]

    for i, suggestion in enumerate(suggestions, 1):
        print(f"{i}. {suggestion}")

    print()

    # 风险提示
    print("⚠️ 六、风险提示")
    print("-" * 80)

    risks = [
        "分红不确定: 实际分红可能低于演示水平，甚至为零",
        "流动性风险: 犹豫期后退保可能遭受较大损失",
        "通胀风险: 固定金额年金可能被通胀侵蚀购买力",
        "利率风险: 市场利率上升时，固定收益产品吸引力下降",
        "保险公司风险: 依赖保险公司长期经营稳定性",
        "早期身故风险: 投保后短期内身故可能损失保费时间价值"
    ]

    for i, risk in enumerate(risks, 1):
        print(f"{i}. {risk}")

    print()

    # 总结
    print("📝 七、总结")
    print("-" * 80)

    irr_neutral = irr_results.get('中性（历史低位分红）', 0)

    print(f"汇丰汇赢丰年2026年金保险是一款分红型年金产品，")
    print(f"总保费投入{spec.annual_premium * spec.payment_period:,.0f}元，")
    print(f"从第{spec.annuity_start_year}年开始每年领取{spec.sum_assured:,.0f}元至{spec.terminal_age}岁，")
    print(f"中性情景下IRR约为{irr_neutral:.2%}。")
    print()

    if irr_neutral > 0.025:
        print(f"✅ 中性IRR高于当前市场利率水平，具有一定竞争力")
    elif irr_neutral > 0.020:
        print(f"⚠️ 中性IRR接近市场利率水平，竞争力一般")
    else:
        print(f"❌ 中性IRR低于市场利率水平，建议谨慎考虑")

    print()
    print("该产品的主要优势在于:")
    print("  • 分红机制提供参与盈余分配的机会")
    print("  • 超长的保险期间有效应对长寿风险")
    print("  • 身故保障保证保费本金安全")
    print("  • 灵活的年金领取方式和流动性功能")
    print()
    print("投资者应根据自身风险偏好、流动性需求和养老规划，")
    print("结合产品的长期收益特征，理性评估投资价值。")
    print()

    print("=" * 80)
    print("报告完成")
    print("=" * 80)


if __name__ == "__main__":
    analyze_hsbc_product()
