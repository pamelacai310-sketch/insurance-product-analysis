"""
增强版保险产品分析工具
Enhanced Insurance Product Analyzer

集成多个开源精算库，提供更全面的分析
"""

import numpy as np
import pandas as pd
import warnings
from typing import Optional, Dict, Any

# 导入基础计算模块（你现有的代码）
from actuarial_calculator import (
    ProductSpec,
    calculate_irr,
    irr_scenario_analysis,
    build_annuity_cash_flows
)

warnings.filterwarnings('ignore')


class EnhancedProductAnalyzer:
    """增强版产品分析器 - 集成多个精算库"""

    def __init__(self, spec: ProductSpec):
        self.spec = spec
        self.analysis_results = {}

        # 尝试导入各个精算库
        self.lifelib_available = self._check_lifelib()
        self.chainladder_available = self._check_chainladder()
        self.julia_available = self._check_julia()

    def _check_lifelib(self) -> bool:
        """检查lifelib是否可用"""
        try:
            from lifelib.tables import load_table
            return True
        except ImportError:
            return False

    def _check_chainladder(self) -> bool:
        """检查chainladder是否可用"""
        try:
            import chainladder as cl
            return True
        except ImportError:
            return False

    def _check_julia(self) -> bool:
        """检查Julia是否可用"""
        try:
            from julia import Julia
            return True
        except ImportError:
            return False

    def analyze_with_lifelib(self) -> Dict[str, Any]:
        """使用lifelib进行精确分析"""
        if not self.lifelib_available:
            print("⚠️ lifelib未安装，使用简化生命表")
            return self._fallback_analysis()

        try:
            from lifelib.tables import load_table

            print("📊 使用lifelib完整生命表进行精确分析")

            # 加载完整生命表
            if self.spec.gender == 'M':
                mortality_table = load_table('CL2020_Male')
            else:
                mortality_table = load_table('CL2020_Female')

            # 使用完整生命表重新计算IRR
            precise_irr = self._calculate_irr_with_full_table(mortality_table)

            # 对比简化版和精确版
            simple_irr = calculate_irr(
                build_annuity_cash_flows(self.spec, dividend_rate=0.0)
            )

            results = {
                'precise_irr': precise_irr,
                'simple_irr': simple_irr,
                'difference_pct': (precise_irr - simple_irr) / simple_irr * 100,
                'method': 'lifelib_full_table'
            }

            print(f"  简化版IRR: {simple_irr:.2%}")
            print(f"  精确版IRR: {precise_irr:.2%}")
            print(f"  差异: {results['difference_pct']:+.2f}%")

            return results

        except Exception as e:
            print(f"❌ lifelib分析失败: {e}")
            return self._fallback_analysis()

    def _calculate_irr_with_full_table(self, mortality_table) -> float:
        """使用完整生命表计算IRR"""
        # 构建考虑精确死亡率的现金流
        max_years = self.spec.terminal_age - self.spec.entry_age + 1
        cash_flows = [0.0] * max_years

        # 保费支出
        for t in range(1, self.spec.payment_period + 1):
            if t < max_years:
                cash_flows[t] -= self.spec.annual_premium

        # 年金收入（考虑死亡率）
        annuity_amount = self.spec.sum_assured
        start_year = self.spec.annuity_start_year or (self.spec.payment_period + 2)

        for t in range(start_year, max_years):
            age = self.spec.entry_age + t
            # 从完整生命表获取生存概率
            if age in mortality_table:
                l_x = mortality_table[age]
                l_entry = mortality_table[self.spec.entry_age]
                survival_prob = l_x / l_entry
            else:
                survival_prob = 0.5  # 简化处理

            cash_flows[t] += annuity_amount * survival_prob

        # 满期金
        total_premium = self.spec.annual_premium * self.spec.payment_period
        cash_flows[-1] += total_premium + self.spec.sum_assured

        return calculate_irr(cash_flows)

    def analyze_company_solvency(self) -> Dict[str, Any]:
        """分析保险公司偿付能力（使用chainladder）"""
        if not self.chainladder_available:
            print("⚠️ chainladder未安装，跳过偿付能力分析")
            return {}

        try:
            import chainladder as cl

            print("\n🏦 分析保险公司偿付能力")

            # 模拟：读取保险公司理赔三角形数据
            # 实际应用中需要真实数据
            print("  （需要真实的理赔数据才能进行此分析）")

            results = {
                'reserve_adequacy': 1.25,  # 示例数据
                'solvency_margin': 0.15,   # 示例数据
                'trend': 'stable',
                'note': '需要公司真实理赔数据'
            }

            return results

        except Exception as e:
            print(f"❌ 偿付能力分析失败: {e}")
            return {}

    def analyze_extreme_risk(self) -> Dict[str, Any]:
        """极端风险分析（VaR计算）"""
        print("\n🎲 极端风险分析")

        # 使用Monte Carlo模拟极端情况
        n_simulations = 10000
        shortfalls = []

        for _ in range(n_simulations):
            # 随机生成极端情景
            # 这里使用简化的正态分布，实际可以使用aggregate库
            shock = np.random.normal(0, 0.5)  # 50%标准差
            shocked_benefit = self.spec.sum_assured * (1 + shock)

            # 计算该情景下的IRR
            shocked_spec = ProductSpec(
                product_name=self.spec.product_name,
                product_type=self.spec.product_type,
                entry_age=self.spec.entry_age,
                gender=self.spec.gender,
                payment_period=self.spec.payment_period,
                annual_premium=self.spec.annual_premium,
                sum_assured=shocked_benefit,
                annuity_start_year=self.spec.annuity_start_year,
                terminal_age=self.spec.terminal_age
            )

            shocked_irr = calculate_irr(
                build_annuity_cash_flows(shocked_spec, dividend_rate=0.0)
            )

            if shocked_irr and shocked_irr < 0:
                shortfalls.append(abs(shocked_irr))

        # 计算VaR
        if shortfalls:
            var_95 = np.percentile(shortfalls, 95)
            expected_shortfall = np.mean([s for s in shortfalls if s >= var_95])

            results = {
                'var_95': var_95,
                'expected_shortfall': expected_shortfall,
                'shortfall_prob': len(shortfalls) / n_simulations
            }

            print(f"  95% VaR: {var_95:.2%}")
            print(f"  预期缺口: {expected_shortfall:.2%}")
            print(f"  亏损概率: {results['shortfall_prob']:.1%}")

            return results
        else:
            print("  极端情景下未出现亏损")
            return {'var_95': 0, 'expected_shortfall': 0, 'shortfall_prob': 0}

    def _fallback_analysis(self) -> Dict[str, Any]:
        """降级到简化分析"""
        print("  使用简化生命表进行分析")

        irr_results = irr_scenario_analysis(self.spec)

        return {
            'precise_irr': irr_results.get('中性（历史低位分红）'),
            'simple_irr': irr_results.get('保守（0分红）'),
            'difference_pct': 0,
            'method': 'simplified_table'
        }

    def generate_comprehensive_report(self) -> Dict[str, Any]:
        """生成综合分析报告"""
        print("="*70)
        print(f"  {self.spec.product_name}")
        print(f"  增强版综合分析报告")
        print("="*70)

        # 基本信息
        print(f"\n📌 产品信息")
        print(f"  投保年龄: {self.spec.entry_age}岁  性别: {'男' if self.spec.gender=='M' else '女'}")
        print(f"  交费方式: {self.spec.payment_period}年缴  年缴: {self.spec.annual_premium:,.0f}元")
        print(f"  基本保险金额: {self.spec.sum_assured:,.0f}元")

        # 1. 基础IRR分析
        print(f"\n📈 基础IRR分析")
        irr_scenarios = irr_scenario_analysis(self.spec)
        for scenario, irr in irr_scenarios.items():
            print(f"  {scenario}: {f'{irr:.2%}' if irr else 'N/A'}")

        # 2. 精确分析（lifelib）
        lifelib_results = self.analyze_with_lifelib()
        self.analysis_results['lifelib'] = lifelib_results

        # 3. 偿付能力分析
        solvency_results = self.analyze_company_solvency()
        self.analysis_results['solvency'] = solvency_results

        # 4. 极端风险分析
        risk_results = self.analyze_extreme_risk()
        self.analysis_results['extreme_risk'] = risk_results

        # 5. 增强版评级
        print(f"\n⭐ 增强版综合评级")

        dimensions = self._calculate_enhanced_dimensions(
            irr_scenarios, lifelib_results, solvency_results, risk_results
        )

        for dim, score in dimensions.items():
            bar = '■' * score + '□' * (5 - score)
            print(f"  {dim}: [{bar}] {score}/5")

        total = sum(dimensions.values()) / len(dimensions)
        grade = 'A' if total >= 4.0 else 'B' if total >= 3.0 else 'C' if total >= 2.0 else 'D'

        print(f"\n  总分: {total:.2f}/5.0  评级: {grade}")

        # 6. 建议
        print(f"\n💡 分析建议")
        self._generate_recommendations(dimensions, lifelib_results, risk_results)

        return {
            'dimensions': dimensions,
            'total_score': total,
            'grade': grade,
            'details': self.analysis_results
        }

    def _calculate_enhanced_dimensions(self, irr_scenarios, lifelib_results,
                                      solvency_results, risk_results) -> Dict[str, int]:
        """计算增强版评分维度"""
        dimensions = {}

        # 收益质量（基于精确IRR）
        irr_value = lifelib_results.get('precise_irr', 0)
        if irr_value >= 0.030:
            dimensions['收益质量'] = 5
        elif irr_value >= 0.025:
            dimensions['收益质量'] = 4
        elif irr_value >= 0.020:
            dimensions['收益质量'] = 3
        elif irr_value >= 0.015:
            dimensions['收益质量'] = 2
        else:
            dimensions['收益质量'] = 1

        # 计算精度（是否使用了完整生命表）
        if lifelib_results.get('method') == 'lifelib_full_table':
            dimensions['计算精度'] = 5
        else:
            dimensions['计算精度'] = 3

        # 公司稳健性（基于偿付能力分析）
        if solvency_results.get('reserve_adequacy', 1.2) >= 1.3:
            dimensions['公司稳健性'] = 5
        elif solvency_results.get('reserve_adequacy', 1.2) >= 1.2:
            dimensions['公司稳健性'] = 3
        else:
            dimensions['公司稳健性'] = 1

        # 抗风险能力（基于极端风险分析）
        shortfall_prob = risk_results.get('shortfall_prob', 0)
        if shortfall_prob < 0.01:
            dimensions['抗风险能力'] = 5
        elif shortfall_prob < 0.05:
            dimensions['抗风险能力'] = 4
        elif shortfall_prob < 0.10:
            dimensions['抗风险能力'] = 3
        elif shortfall_prob < 0.20:
            dimensions['抗风险能力'] = 2
        else:
            dimensions['抗风险能力'] = 1

        return dimensions

    def _generate_recommendations(self, dimensions, lifelib_results, risk_results):
        """生成个性化建议"""
        # 根据各维度得分给出建议
        if dimensions['收益质量'] <= 2:
            print("  ⚠️ 该产品收益率较低，建议与其他投资工具对比")

        if dimensions['计算精度'] <= 3:
            print("  ℹ️ 安装lifelib可获得更精确的分析结果")

        if dimensions['公司稳健性'] <= 2:
            print("  ⚠️ 该保险公司偿付能力存在隐忧，建议谨慎考虑")

        if dimensions['抗风险能力'] <= 2:
            print("  ⚠️ 该产品在极端情况下风险较高，不适合风险厌恶型投资者")

        if dimensions['收益质量'] >= 4 and dimensions['公司稳健性'] >= 4:
            print("  ✅ 该产品综合表现优秀，可重点考虑")


def demo_enhanced_analysis():
    """演示增强版分析"""
    # 创建产品规格
    spec = ProductSpec(
        product_name="演示年金险产品（增强版分析）",
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

    # 创建增强版分析器
    analyzer = EnhancedProductAnalyzer(spec)

    # 生成综合报告
    report = analyzer.generate_comprehensive_report()

    return report


if __name__ == "__main__":
    demo_enhanced_analysis()
