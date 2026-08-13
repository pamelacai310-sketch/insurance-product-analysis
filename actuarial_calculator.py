"""
保险产品逆向精算分析工具库
Insurance Product Reverse Actuarial Analysis Toolkit

用途：从保险条款反推精算参数，量化评估产品优劣势
"""

import numpy as np
import numpy_financial as npf
import pandas as pd
from scipy.optimize import brentq
from dataclasses import dataclass, field
from typing import Optional
import warnings


class UnverifiedAssumptionError(ValueError):
    """Raised when a legacy inferred cash-flow model is requested without opt-in."""


# ─────────────────────────────────────────────
# 数据结构定义
# ─────────────────────────────────────────────

@dataclass
class ProductSpec:
    """从条款提取的产品规格"""
    product_name: str
    product_type: str          # annuity / whole_life / endowment / health / universal
    entry_age: int
    gender: str                # M / F
    payment_period: int        # 趸交=1, 3年缴=3, 5年缴=5
    annual_premium: float
    sum_assured: float         # 基本保险金额
    annuity_start_year: Optional[int] = None   # 首次年金领取保单年度
    terminal_age: int = 105
    dividend_type: Optional[str] = None       # cash / accumulate / reduce_premium / paid_up
    guaranteed_rate: Optional[float] = None   # 保证利率（万能险适用）


@dataclass
class CashFlowModel:
    """产品现金流模型"""
    years: list
    outflows: list     # 保费支出（负值）
    inflows: list      # 保险金收入（正值）
    dividends: list    # 分红（可选，默认0）
    
    def net_cash_flows(self):
        result = []
        max_len = max(len(self.outflows), len(self.inflows), len(self.dividends))
        for i in range(max_len):
            cf = 0
            if i < len(self.outflows):
                cf += self.outflows[i]
            if i < len(self.inflows):
                cf += self.inflows[i]
            if i < len(self.dividends):
                cf += self.dividends[i]
            result.append(cf)
        return result


# ─────────────────────────────────────────────
# IRR 计算
# ─────────────────────────────────────────────

def calculate_irr(cash_flows: list) -> Optional[float]:
    """
    计算内部收益率（IRR）
    
    Args:
        cash_flows: 净现金流列表，支出为负，收入为正
        
    Returns:
        IRR（小数形式），计算失败返回None
    """
    try:
        irr = npf.irr(cash_flows)
        if np.isnan(irr) or np.isinf(irr):
            return None
        return float(irr)
    except Exception:
        return None


def irr_scenario_analysis(
    spec: ProductSpec,
    *,
    allow_unverified_assumptions: bool = False,
) -> dict:
    """
    三情景IRR分析：保守 / 中性 / 乐观
    
    分红假设：
    - 保守：0分红
    - 中性：年金给付额的1%（约为历史均值的低端）
    - 乐观：年金给付额的2.5%（演示利率水平）
    """
    if not allow_unverified_assumptions:
        raise UnverifiedAssumptionError(
            "旧IRR情景会假定领取额、满期金及1%/2.5%分红，正式分析已禁止；"
            "请使用 unified_analysis.py --comparison-case。"
        )
    warnings.warn(
        "正在运行含未核验假设的旧IRR演示，不得用于正式产品比较。",
        RuntimeWarning,
        stacklevel=2,
    )
    base_cfs = build_annuity_cash_flows(
        spec,
        dividend_rate=0.0,
        allow_unverified_assumptions=True,
    )
    
    scenarios = {
        '保守（0分红）': calculate_irr(base_cfs),
        '中性（历史低位分红）': calculate_irr(
            build_annuity_cash_flows(
                spec,
                dividend_rate=0.01,
                allow_unverified_assumptions=True,
            )
        ),
        '乐观（演示分红水平）': calculate_irr(
            build_annuity_cash_flows(
                spec,
                dividend_rate=0.025,
                allow_unverified_assumptions=True,
            )
        )
    }
    return scenarios


def build_annuity_cash_flows(
    spec: ProductSpec,
    dividend_rate: float = 0.0,
    *,
    allow_unverified_assumptions: bool = False,
) -> list:
    """
    构建年金险现金流序列
    
    时间轴（以5年缴、第7年开始领取为例）：
    Year 0: 0
    Year 1-5: -annual_premium
    Year 6: 0（等待期）
    Year 7-N: +annual_annuity + dividend
    Year N: +annual_annuity + maturity_bonus（满期年）
    """
    if not allow_unverified_assumptions:
        raise UnverifiedAssumptionError(
            "旧年金现金流函数包含未核验领取和满期假设；请改用严格逐年给付表。"
        )
    max_years = spec.terminal_age - spec.entry_age + 1
    cash_flows = [0.0] * max_years  # t=0开始
    
    # 保费支出
    for t in range(1, spec.payment_period + 1):
        if t < max_years:
            cash_flows[t] -= spec.annual_premium
    
    # 年金收入（首次领取年度起，至满期前1年）
    annuity_amount = spec.sum_assured
    annual_dividend = annuity_amount * dividend_rate
    
    start = spec.annuity_start_year or (spec.payment_period + 2)
    
    # 领取期年金（不含满期年）
    for t in range(start, max_years - 1):
        cash_flows[t] += annuity_amount + annual_dividend
    
    # 满期保险金 = 已交保费总额 + 基本保险金额（满期年不再给付年金）
    total_premium = spec.annual_premium * spec.payment_period
    cash_flows[-1] += total_premium + spec.sum_assured
    
    return cash_flows


# ─────────────────────────────────────────────
# 年金系数与隐含预定利率反推
# ─────────────────────────────────────────────

# 简化生命表（基于CL2020，可替换为完整表）
# 格式：{年龄: 当年死亡率 qx}
CL2020_MALE_SAMPLE = {
    30: 0.000695, 35: 0.000858, 40: 0.001247, 45: 0.002074,
    50: 0.003542, 55: 0.005881, 60: 0.009582, 65: 0.015234,
    70: 0.024127, 75: 0.038942, 80: 0.062741, 85: 0.099283,
    90: 0.152874, 95: 0.221543, 100: 0.310842, 105: 1.000000
}

CL2020_FEMALE_SAMPLE = {
    30: 0.000342, 35: 0.000425, 40: 0.000624, 45: 0.001087,
    50: 0.001923, 55: 0.003214, 60: 0.005432, 65: 0.008921,
    70: 0.014832, 75: 0.025431, 80: 0.043212, 85: 0.072341,
    90: 0.118432, 95: 0.185321, 100: 0.268432, 105: 1.000000
}


def get_survival_prob(from_age: int, to_age: int, gender: str = 'M') -> float:
    """
    计算从from_age存活到to_age的概率（近似）
    使用线性插值处理非整数步长
    """
    table = CL2020_MALE_SAMPLE if gender == 'M' else CL2020_FEMALE_SAMPLE
    
    survival = 1.0
    for age in range(from_age, to_age):
        # 线性插值
        lower = (age // 5) * 5
        upper = lower + 5
        if lower in table and upper in table:
            ratio = (age - lower) / 5
            qx = table[lower] + ratio * (table[upper] - table[lower])
        else:
            qx = table.get(age, 0.01)
        survival *= (1 - qx)
    
    return survival


def calculate_annuity_factor(
    entry_age: int,
    annuity_start_age: int,
    terminal_age: int = 105,
    discount_rate: float = 0.025,
    gender: str = 'M'
) -> float:
    """
    计算即期年金系数（每元年金的当前价值）
    
    公式：ä = Σ [t_p_x × v^t]
    其中 t_p_x = 从entry_age到annuity_start_age+t的存活概率
         v = 1/(1+i)
    """
    annuity_factor = 0.0
    
    for age in range(annuity_start_age, terminal_age):
        t_from_entry = age - entry_age
        survival = get_survival_prob(entry_age, age, gender)
        discount = (1 + discount_rate) ** (-t_from_entry)
        annuity_factor += survival * discount
    
    return annuity_factor


def reverse_engineer_rate(
    annual_premium: float,
    payment_period: int,
    annual_annuity: float,
    entry_age: int,
    annuity_start_age: int,
    terminal_age: int = 105,
    gender: str = 'M',
    maturity_bonus: float = 0.0,
    *,
    allow_unverified_assumptions: bool = False,
) -> Optional[float]:
    """
    反推产品隐含预定利率
    
    精算等价原理：PV(保费) = PV(年金) + PV(满期金)
    
    Returns:
        隐含预定利率（小数）
    """
    if not allow_unverified_assumptions:
        raise UnverifiedAssumptionError(
            "旧隐含利率函数使用简化生命表，不能作为正式产品精算优势证据；"
            "请在严格comparison-case中使用逐年合同现金流。"
        )

    def actuarial_equation(r):
        # 保费现值
        pv_premiums = 0.0
        for t in range(payment_period):
            pv_premiums += annual_premium * (1 + r) ** (-t)
        
        # 年金现值
        af = calculate_annuity_factor(entry_age, annuity_start_age, terminal_age, r, gender)
        pv_annuities = annual_annuity * af
        
        # 满期金现值（若有）
        t_maturity = terminal_age - entry_age
        survival_maturity = get_survival_prob(entry_age, terminal_age - 1, gender)
        pv_maturity = maturity_bonus * survival_maturity * (1 + r) ** (-t_maturity)
        
        return pv_premiums - pv_annuities - pv_maturity
    
    try:
        rate = brentq(actuarial_equation, 0.001, 0.10)
        return float(rate)
    except ValueError:
        warnings.warn("无法在0.1%-10%区间内求解隐含利率")
        return None


# ─────────────────────────────────────────────
# 现金价值分析
# ─────────────────────────────────────────────

def analyze_cash_value(
    cash_value_by_year: list,
    annual_premium: float,
    payment_period: int
) -> pd.DataFrame:
    """
    现金价值曲线全分析
    
    Args:
        cash_value_by_year: 各保单年度末现金价值列表（第1年起）
        annual_premium: 年缴保费
        payment_period: 交费年数
        
    Returns:
        包含各项指标的DataFrame
    """
    n = len(cash_value_by_year)
    records = []
    
    for year in range(1, n + 1):
        cv = cash_value_by_year[year - 1]
        premium_paid = annual_premium * min(year, payment_period)
        
        loss_rate = max(0, (premium_paid - cv) / premium_paid) if premium_paid > 0 else 0
        cv_growth = None
        if year > 1:
            prev_cv = cash_value_by_year[year - 2]
            cv_growth = (cv - prev_cv) / prev_cv if prev_cv > 0 else None
        
        records.append({
            '保单年度': year,
            '现金价值': cv,
            '已交保费': premium_paid,
            '退保损失额': max(0, premium_paid - cv),
            '退保损失率': f'{loss_rate:.1%}',
            '现金价值增长率': f'{cv_growth:.1%}' if cv_growth else 'N/A',
            '是否回本': '✓' if cv >= premium_paid else '✗'
        })
    
    df = pd.DataFrame(records)
    
    # 关键统计
    breakeven = next((r['保单年度'] for r in records if r['是否回本'] == '✓'), None)
    year3_loss = records[2]['退保损失率'] if n >= 3 else 'N/A'
    year5_loss = records[4]['退保损失率'] if n >= 5 else 'N/A'
    
    print(f"\n📊 现金价值关键指标")
    print(f"  回本年数: {breakeven}年" if breakeven else "  回本年数: 未回本")
    print(f"  第3年退保损失率: {year3_loss}")
    print(f"  第5年退保损失率: {year5_loss}")
    
    return df


# ─────────────────────────────────────────────
# 身故保障杠杆分析
# ─────────────────────────────────────────────

def calculate_death_leverage(
    annual_premium: float,
    payment_period: int,
    sum_assured: float,
    death_benefit_rule: str,  # 'max_premium_csv' / 'sum_assured' / 'N_times'
    leverage_multiple: float = 1.0,
    *,
    allow_unverified_assumptions: bool = False,
) -> pd.DataFrame:
    """
    各保单年度身故保障杠杆比分析
    
    death_benefit_rule选项：
    - 'max_premium_csv': max(已交保费, 现金价值) ← 纯储蓄型
    - 'N_times': 保额×N倍                        ← 有保障型
    - 'sum_assured': 固定保额                     ← 定期寿险型
    """
    if not allow_unverified_assumptions:
        raise UnverifiedAssumptionError(
            "旧身故杠杆函数会简化现金价值和身故责任，正式分析已禁止；"
            "请在严格comparison-case中录入条款公式树。"
        )

    records = []
    
    for year in range(1, min(payment_period * 3, 30) + 1):
        premium_paid = annual_premium * min(year, payment_period)
        
        if death_benefit_rule == 'max_premium_csv':
            # 本产品的身故给付规则
            db = premium_paid  # 简化：假设早期现金价值 < 已交保费
            leverage = 1.0
        elif death_benefit_rule == 'N_times':
            db = sum_assured * leverage_multiple
            leverage = db / premium_paid
        else:
            db = sum_assured
            leverage = db / premium_paid
        
        records.append({
            '保单年度': year,
            '已交保费': premium_paid,
            '身故保险金': db,
            '保障杠杆比': f'{leverage:.1f}x',
            '保障评级': '⭐⭐⭐⭐⭐' if leverage > 5 else
                         '⭐⭐⭐⭐' if leverage > 3 else
                         '⭐⭐⭐' if leverage > 2 else
                         '⭐⭐' if leverage > 1.2 else '⭐（纯储蓄）'
        })
    
    return pd.DataFrame(records)


# ─────────────────────────────────────────────
# 综合评级引擎
# ─────────────────────────────────────────────

def generate_rating(
    irr_conservative: Optional[float],
    irr_neutral: Optional[float],
    breakeven_year: Optional[int],
    death_leverage: float,
    transparency_score: int,   # 1-5
    product_type: str = 'annuity'
) -> dict:
    """Return an audit payload; composite A-D ratings are intentionally disabled."""
    return {
        'status': 'disabled',
        'reason': (
            '固定阈值加权总分无法保证同险种、同投保条件和同证据口径；'
            '请使用 unified_analysis.py 的严格逐项相对比较。'
        ),
        'input_metrics': {
            'irr_conservative': irr_conservative,
            'irr_neutral': irr_neutral,
            'breakeven_year': breakeven_year,
            'death_leverage': death_leverage,
            'transparency_score_legacy_input': transparency_score,
            'product_type': product_type,
        },
        'dimensions': {},
        'total_score': None,
        'grade': None,
    }


# ─────────────────────────────────────────────
# 快速分析入口（示例：汇丰尊享精彩年金险）
# ─────────────────────────────────────────────

def demo_hsbc_annuity():
    """
    示例：汇丰尊享精彩年金保险（分红型）精算快速分析
    假设参数：30岁男性，5年缴，年缴10万，基本保险金额（年金额）2万
    """
    message = (
        "该旧演示含推测现金流和通用分红率，已停用。"
        "请使用 unified_analysis.py --comparison-case。"
    )
    print(message)
    return {"status": "disabled", "message": message}


if __name__ == "__main__":
    demo_hsbc_annuity()
