"""
完整集成版保险产品分析器
Fully Integrated Insurance Product Analyzer

集成了所有精算开源库的完整分析系统
"""

import sys
import numpy as np
import pandas as pd
from typing import Dict, Any, Optional
from dataclasses import dataclass, field

# 导入基础模块
from actuarial_calculator import (
    ProductSpec,
    calculate_irr,
    irr_scenario_analysis,
    build_annuity_cash_flows,
    generate_rating
)

# 导入集成系统
from actuarial_libs import get_manager


class IntegratedAnalyzer:
    """完整集成版分析器"""

    def __init__(self, spec: ProductSpec):
        self.spec = spec
        self.manager = get_manager()
        self.results = {}

        # 打印集成状态
        self.manager.print_status()
        print()

    def analyze(self) -> Dict[str, Any]:
        """执行完整分析"""
        print("="*70)
        print(f"  {self.spec.product_name}")
        print(f"  完整集成版精算分析报告")
        print("="*70)
        print()

        # 1. 基本信息
        self._print_basic_info()

        # 2. 基础IRR分析
        self._analyze_basic_irr()

        # 3. 增强分析（使用所有可用库）
        self._analyze_with_libraries()

        # 4. 生成综合评级
        self._generate_integrated_rating()

        # 5. 生成建议
        self._generate_recommendations()

        return self.results

    def _print_basic_info(self):
        """打印基本信息"""
        print("📌 产品信息")
        print(f"  投保年龄: {self.spec.entry_age}岁")
        print(f"  性别: {'男' if self.spec.gender=='M' else '女'}")
        print(f"  交费方式: {self.spec.payment_period}年缴")
        print(f"  年缴保费: {self.spec.annual_premium:,.0f}元")
        print(f"  基本保险金额: {self.spec.sum_assured:,.0f}元")
        if self.spec.annuity_start_year:
            print(f"  首次年金领取: 第{self.spec.annuity_start_year}保单年度")
        print()

    def _analyze_basic_irr(self):
        """基础IRR分析"""
        print("📈 基础IRR分析")
        print("-" * 40)

        irr_scenarios = irr_scenario_analysis(self.spec)

        for scenario, irr in irr_scenarios.items():
            if irr:
                bar = '█' * int(irr * 100)
                print(f"  {scenario}: {irr:.2%} {bar}")
            else:
                print(f"  {scenario}: N/A")

        print()

        # 对比基准
        print("📊 市场基准利率（2025年参考）")
        print("  3年期国债:     约2.50%-2.80%")
        print("  5年大额存单:   约2.30%-2.60%")
        print("  货币基金:      约1.80%-2.20%")
        print()

        self.results['basic_irr'] = irr_scenarios

    def _analyze_with_libraries(self):
        """使用所有可用库进行分析"""
        print("🔬 增强分析（集成精算库）")
        print("-" * 40)

        available_libs = self.manager.get_available_libraries()

        if not available_libs:
            print("  ⚠️ 未安装任何精算库，使用基础分析")
            print("  提示：运行 ./install_dependencies.sh 安装库")
            print()
            return

        print(f"  已集成 {len(available_libs)} 个精算库")
        print()

        # 逐个库分析
        for lib_name in available_libs:
            adapter = self.manager.get_adapter(lib_name)
            if adapter:
                try:
                    print(f"  📚 {lib_name.upper()}")
                    lib_results = adapter.analyze(self.spec)

                    if 'error' in lib_results:
                        print(f"    ❌ {lib_results['error']}")
                    else:
                        # 打印结果
                        self._print_lib_results(lib_name, lib_results)

                    self.results[lib_name] = lib_results
                    print()

                except Exception as e:
                    print(f"    ❌ 分析失败: {e}")
                    print()

    def _print_lib_results(self, lib_name: str, results: Dict[str, Any]):
        """打印库分析结果"""
        if lib_name == 'lifelib':
            irr = results.get('precise_irr', 0)
            if irr:
                print(f"    ✅ 精确IRR: {irr:.2%} ({results.get('method', 'N/A')})")
            else:
                print(f"    ✅ 使用完整生命表分析")

        elif lib_name == 'chainladder':
            adequacy = results.get('reserve_adequacy', 0)
            print(f"    ✅ 准备金充足率: {adequacy:.2f}")
            if adequacy >= 1.3:
                print(f"       状态: 优秀")
            elif adequacy >= 1.2:
                print(f"       状态: 良好")
            else:
                print(f"       状态: 需关注")

        elif lib_name == 'cashflower':
            prob = results.get('alm_shortfall_probability', 0)
            print(f"    ✅ ALM缺口概率: {prob:.1%}")
            if prob < 0.05:
                print(f"       状态: 低风险")
            elif prob < 0.10:
                print(f"       状态: 中等风险")
            else:
                print(f"       状态: 高风险")

        elif lib_name == 'aggregate':
            var = results.get('var_95', 0)
            es = results.get('expected_shortfall', 0)
            print(f"    ✅ 95% VaR: {var:,.0f}元")
            print(f"    ✅ 预期缺口: {es:,.0f}元")

        elif lib_name == 'modelx':
            scenarios = results.get('scenarios', {})
            print(f"    ✅ 支持复杂产品建模")
            for scenario, data in scenarios.items():
                print(f"       {scenario}: 利率{data['rate']:.1%}, IRR{data['irr']:.1%}")

        elif lib_name == 'insurancerating':
            score = results.get('fairness_score', 0)
            print(f"    ✅ 定价公平性评分: {score:.1f}/5.0")

        elif lib_name == 'julia_actuary':
            factor = results.get('precise_annuity_factor', 0)
            print(f"    ✅ Julia精确年金系数: {factor:.4f}")

        else:
            for key, value in results.items():
                if key != 'error' and key != 'description':
                    print(f"    ✅ {key}: {value}")

        desc = results.get('description', '')
        if desc:
            print(f"    📝 {desc}")

    def _generate_integrated_rating(self):
        """生成集成版评级"""
        print("⭐ 综合评级（集成版）")
        print("-" * 40)

        dimensions = self._calculate_integrated_dimensions()

        for dim, score in dimensions.items():
            bar = '■' * score + '□' * (5 - score)
            print(f"  {dim}: [{bar}] {score}/5")

        print()

        # 计算总分
        total = sum(dimensions.values()) / len(dimensions)
        grade = self._get_grade(total)

        print(f"  总分: {total:.2f}/5.0")
        print(f"  评级: {grade}")
        print()

        self.results['rating'] = {
            'dimensions': dimensions,
            'total_score': total,
            'grade': grade
        }

    def _calculate_integrated_dimensions(self) -> Dict[str, int]:
        """计算集成版评分维度"""
        dimensions = {}

        # 1. 收益质量（基于IRR）
        basic_irr = self.results.get('basic_irr', {})
        neutral_irr = basic_irr.get('中性（历史低位分红）', 0) or \
                    basic_irr.get('保守（0分红）', 0) or 0

        if neutral_irr >= 0.030:
            dimensions['收益质量'] = 5
        elif neutral_irr >= 0.025:
            dimensions['收益质量'] = 4
        elif neutral_irr >= 0.020:
            dimensions['收益质量'] = 3
        elif neutral_irr >= 0.015:
            dimensions['收益质量'] = 2
        else:
            dimensions['收益质量'] = 1

        # 2. 计算精度（是否使用了lifelib）
        if 'lifelib' in self.results:
            dimensions['计算精度'] = 5
        else:
            dimensions['计算精度'] = 3

        # 3. 公司稳健性（chainladder）
        if 'chainladder' in self.results:
            adequacy = self.results['chainladder'].get('reserve_adequacy', 1.2)
            if adequacy >= 1.3:
                dimensions['公司稳健性'] = 5
            elif adequacy >= 1.2:
                dimensions['公司稳健性'] = 3
            else:
                dimensions['公司稳健性'] = 1
        else:
            dimensions['公司稳健性'] = 3  # 默认中等

        # 4. 资产负债匹配（cashflower）
        if 'cashflower' in self.results:
            shortfall_prob = self.results['cashflower'].get('alm_shortfall_probability', 0.05)
            if shortfall_prob < 0.03:
                dimensions['资产负债匹配'] = 5
            elif shortfall_prob < 0.07:
                dimensions['资产负债匹配'] = 4
            elif shortfall_prob < 0.10:
                dimensions['资产负债匹配'] = 3
            elif shortfall_prob < 0.15:
                dimensions['资产负债匹配'] = 2
            else:
                dimensions['资产负债匹配'] = 1
        else:
            dimensions['资产负债匹配'] = 3

        # 5. 抗风险能力（aggregate）
        if 'aggregate' in self.results:
            var = self.results['aggregate'].get('var_95', 0)
            # VaR越小，风险越小
            if var < self.spec.annual_premium * 0.1:
                dimensions['抗风险能力'] = 5
            elif var < self.spec.annual_premium * 0.2:
                dimensions['抗风险能力'] = 4
            elif var < self.spec.annual_premium * 0.3:
                dimensions['抗风险能力'] = 3
            elif var < self.spec.annual_premium * 0.5:
                dimensions['抗风险能力'] = 2
            else:
                dimensions['抗风险能力'] = 1
        else:
            dimensions['抗风险能力'] = 3

        # 6. 产品复杂性支持（modelx）
        if 'modelx' in self.results:
            dimensions['产品支持'] = 5
        else:
            dimensions['产品支持'] = 3

        # 7. 定价公平性（insurancerating）
        if 'insurancerating' in self.results:
            fairness = self.results['insurancerating'].get('fairness_score', 3.0)
            dimensions['定价公平性'] = int(fairness)
        else:
            dimensions['定价公平性'] = 3

        return dimensions

    def _get_grade(self, score: float) -> str:
        """根据分数获取等级"""
        if score >= 4.5:
            return 'A+'
        elif score >= 4.0:
            return 'A'
        elif score >= 3.5:
            return 'B+'
        elif score >= 3.0:
            return 'B'
        elif score >= 2.5:
            return 'C+'
        elif score >= 2.0:
            return 'C'
        else:
            return 'D'

    def _generate_recommendations(self):
        """生成个性化建议"""
        print("💡 分析建议")
        print("-" * 40)

        rating = self.results.get('rating', {})
        dimensions = rating.get('dimensions', {})

        # 收益建议
        if dimensions.get('收益质量', 3) <= 2:
            print("  ⚠️ 收益率较低，建议对比其他投资工具")
            print("     - 考虑国债、大额存单等低风险产品")
            print("     - 或风险等级更高的理财产品")

        # 公司稳健性建议
        if dimensions.get('公司稳健性', 3) <= 2:
            print("  ⚠️ 保险公司偿付能力存在隐忧")
            print("     - 查看公司最新偿付能力报告")
            print("     - 考虑分散投保多家公司")

        # 资产负债匹配建议
        if dimensions.get('资产负债匹配', 3) <= 2:
            print("  ⚠️ 产品存在资产负债错配风险")
            print("     - 关注公司投资资产质量")
            print("     - 了解再保险安排")

        # 抗风险能力建议
        if dimensions.get('抗风险能力', 3) <= 2:
            print("  ⚠️ 极端情况下风险较高")
            print("     - 不适合风险厌恶型投资者")
            print("     - 建议配置保底资产")

        # 定价公平性建议
        if dimensions.get('定价公平性', 3) <= 2:
            print("  ⚠️ 产品定价可能存在不公平")
            print("     - 对比其他公司同类产品")
            print("     - 注意年龄、性别差异")

        # 正面建议
        if dimensions.get('收益质量', 3) >= 4 and dimensions.get('公司稳健性', 3) >= 4:
            print("  ✅ 该产品综合表现优秀")
            print("     - 收益率良好")
            print("     - 公司稳健性强")
            print("     - 可重点考虑")

        print()


def demo_integrated_analysis():
    """演示完整集成版分析"""
    # 创建产品规格
    spec = ProductSpec(
        product_name="演示年金险产品（完整集成版分析）",
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

    # 创建完整集成版分析器
    analyzer = IntegratedAnalyzer(spec)

    # 执行完整分析
    report = analyzer.analyze()

    return report


if __name__ == "__main__":
    demo_integrated_analysis()
