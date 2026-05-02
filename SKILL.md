---
name: insurance-product-analysis
description: >
  逆向精算分析技能：从保险产品条款文本反推精算结构，评估产品优劣势。
  当用户上传保险条款PDF、提供条款文本、或询问保险产品分析时，必须使用本技能。
  覆盖场景包括：年金险/寿险/健康险/分红险/万能险的条款解析、IRR测算、
  现金价值分析、分红机制透视、保障杠杆评估、产品横向对比、监管合规分析。
  用户可能使用"分析这个保险"、"这个产品值不值得买"、"帮我看看这个条款"、
  "保险产品精算分析"等表述——只要涉及保险产品评估，就使用本技能。
dependencies:
  python: ">=3.9"
  packages:
    - numpy
    - numpy-financial
    - pandas
    - pdfplumber
    - matplotlib
    - scipy
---

# 保险产品逆向精算分析技能

## 核心理念

**从条款文本反推精算结构**：保险条款是精算假设的法律化表达。每一个条款措辞背后都隐藏着定价逻辑、风险承担结构和利润来源。本技能的目标是将条款语言翻译回精算语言，还原产品的真实经济面貌。

```
条款文本 → 精算参数提取 → 量化指标计算 → 产品优劣评级
```

---

## 第一步：条款结构化解析

### 1.1 必须提取的核心精算参数

拿到任何保险条款，优先提取以下参数，这些是后续所有计算的基础：

| 参数类别 | 具体字段 | 在条款中的位置 |
|---------|---------|-------------|
| **产品基本信息** | 产品类型、保险期间、投保年龄范围 | 第1条、保险期间条款 |
| **保费结构** | 交费方式（趸交/期交）、交费期间 | 保险费条款 |
| **保险金额** | 基本保险金额定义、变更规则 | 保险责任条款 |
| **现金流时间表** | 首次给付日、给付频率、给付金额计算公式 | 保险责任/年金条款 |
| **退出机制** | 犹豫期、退保处理、现金价值规则 | 现金价值/合同解除条款 |
| **分红/利率机制** | 红利类型、分配方式、结算利率机制 | 保单红利条款 |
| **责任免除** | 免责事项列表 | 责任免除条款 |
| **身故保障** | 身故给付计算方式、给付顺序 | 身故保险金条款 |

### 1.2 产品类型识别矩阵

根据条款关键词判断产品类型，决定适用的精算分析框架：

```
关键词                        产品类型          主要分析维度
─────────────────────────────────────────────────────────
"年金"+"首次领取日"           年金险            年金系数、IRR、长寿风险
"分红"+"可分配盈余"           分红险            分红机制透明度、历史兑现率
"万能"+"结算利率"             万能险            实际结算利率vs演示利率
"重大疾病"+"等待期"           重疾险            疾病定义严格度、赔付率
"医疗"+"免赔额"+"报销比例"    医疗险            实际赔付率、续保稳定性
"投资连结"+"投资账户"         投连险            账户费用、实际投资收益
```

---

## 第二步：精算指标量化计算

### 2.1 IRR（内部收益率）测算

IRR是还原产品真实收益率的核心工具，揭穿营销话术。

**标准计算流程：**

```python
import numpy as np
import numpy_financial as npf

def calculate_insurance_irr(
    premium_schedule,      # 保费现金流，支出为负值
    benefit_schedule,      # 给付现金流，收入为正值  
    surrender_value=None,  # 若中途退保，加入退保现金价值
    dividend_schedule=None # 分红现金流（保守估计用0）
):
    """
    计算保险产品IRR
    
    参数设置原则：
    - 保费：负值（现金流出）
    - 年金/保险金：正值（现金流入）
    - 分红：保守情景用0，中性情景用历史均值，乐观情景用演示值
    - 时间单位：年（与保单年度对应）
    """
    cash_flows = []
    
    # 合并所有现金流
    max_years = max(
        len(premium_schedule), 
        len(benefit_schedule),
        len(dividend_schedule) if dividend_schedule else 0
    )
    
    for t in range(max_flows):
        cf = 0
        if t < len(premium_schedule):
            cf += premium_schedule[t]  # 负值
        if t < len(benefit_schedule):
            cf += benefit_schedule[t]  # 正值
        if dividend_schedule and t < len(dividend_schedule):
            cf += dividend_schedule[t]
        cash_flows.append(cf)
    
    if surrender_value:
        cash_flows[-1] += surrender_value
    
    irr = npf.irr(cash_flows)
    return irr

# IRR评级标准（2025年中国市场参考）
def rate_irr(irr, product_type):
    benchmarks = {
        'annuity': {  # 年金险
            'excellent': 0.030,   # IRR > 3.0%：优秀
            'good':      0.025,   # IRR 2.5%-3.0%：良好
            'fair':      0.020,   # IRR 2.0%-2.5%：一般
            'poor':      0.000    # IRR < 2.0%：差
        },
        'endowment': {  # 两全险
            'excellent': 0.035,
            'good':      0.028,
            'fair':      0.022,
            'poor':      0.000
        },
        'whole_life': {  # 终身寿险
            'excellent': 0.040,
            'good':      0.032,
            'fair':      0.025,
            'poor':      0.000
        }
    }
    
    thresholds = benchmarks.get(product_type, benchmarks['annuity'])
    if irr >= thresholds['excellent']:
        return '⭐⭐⭐⭐⭐ 优秀'
    elif irr >= thresholds['good']:
        return '⭐⭐⭐⭐ 良好'
    elif irr >= thresholds['fair']:
        return '⭐⭐⭐ 一般'
    else:
        return '⭐⭐ 较差'
```

**IRR基准比较体系：**
- 3年期国债收益率（当前约2.5%-2.8%）
- 5年期大额存单利率（当前约2.3%-2.6%）
- 货币基金7日年化（当前约1.8%-2.2%）
- 同类产品IRR中位数

### 2.2 年金系数分析（年金险专用）

```python
def calculate_annuity_factor(
    entry_age,          # 投保年龄
    annuity_start_age,  # 首次领取年龄
    terminal_age=105,   # 保障终止年龄
    discount_rate=0.025, # 预定利率（从条款反推）
    mortality_table='CL2020'  # 中国人寿保险业经验生命表2020
):
    """
    年金系数 = 年金给付额现值 / 年金给付额
    反推预定利率：观察条款中的保费/年金给付比，用二分法求解
    """
    # 使用CL2020生命表（2021年起执行）
    # 实际使用时从lifelib加载标准生命表
    
    annuity_factor = 0
    for age in range(annuity_start_age, terminal_age):
        t = age - entry_age  # 距投保的年数
        survival_prob = get_survival_prob(entry_age, age, mortality_table)
        discount = (1 + discount_rate) ** (-t)
        annuity_factor += survival_prob * discount
    
    return annuity_factor

def reverse_engineer_discount_rate(
    annual_premium,     # 年缴保费
    payment_years,      # 交费年数
    annual_annuity,     # 年金给付额
    entry_age,
    annuity_start_age
):
    """
    已知保费和年金额，反推隐含预定利率
    这是检验产品定价是否合理的关键步骤
    """
    from scipy.optimize import brentq
    
    def equation(r):
        pv_premiums = sum(
            annual_premium * (1 + r) ** (-t)
            for t in range(payment_years)
        )
        pv_annuities = annual_annuity * calculate_annuity_factor(
            entry_age, annuity_start_age, discount_rate=r
        )
        return pv_premiums - pv_annuities
    
    implied_rate = brentq(equation, 0.001, 0.10)
    return implied_rate
```

### 2.3 现金价值曲线分析

```python
import pandas as pd
import matplotlib.pyplot as plt

def analyze_cash_value_curve(cash_value_table, premium_paid_table):
    """
    分析现金价值增长曲线，识别"陷阱期"
    
    关键指标：
    1. 回本年数：现金价值首次 >= 已交保费总额的年份
    2. 前N年退保损失率：(已交保费 - 现金价值) / 已交保费
    3. 现金价值增长率：各年度现金价值增速
    """
    df = pd.DataFrame({
        'year': range(1, len(cash_value_table) + 1),
        'cash_value': cash_value_table,
        'premium_paid': premium_paid_table
    })
    
    df['loss_rate'] = (df['premium_paid'] - df['cash_value']) / df['premium_paid']
    df['cv_growth_rate'] = df['cash_value'].pct_change()
    df['breakeven'] = df['cash_value'] >= df['premium_paid']
    
    breakeven_year = df[df['breakeven']].iloc[0]['year'] if df['breakeven'].any() else None
    early_loss = df[df['year'] <= 3]['loss_rate'].mean()
    
    return {
        'breakeven_year': breakeven_year,
        'avg_early_loss_rate': early_loss,
        'year5_loss_rate': df[df['year'] == 5]['loss_rate'].values[0],
        'detail': df
    }
```

### 2.4 身故保障杠杆分析

```python
def calculate_death_benefit_leverage(
    death_benefit_formula,  # 条款中的身故保险金计算公式
    annual_premium,
    policy_year
):
    """
    身故保障杠杆比 = 身故保险金 / 已交保费
    
    评级标准：
    - 杠杆比 > 5倍：高保障，适合家庭保障需求
    - 杠杆比 1-5倍：中等保障
    - 杠杆比 ≈ 1倍：无保障功能（纯储蓄）
    - 杠杆比 < 1倍：负杠杆（极罕见，见于某些责任险）
    """
    premium_paid = annual_premium * policy_year
    
    # 常见身故保险金结构对应的杠杆
    leverage_patterns = {
        'max(premium, csv)': 1.0,        # 纯储蓄型（如本产品）
        'max(premium, csv, N*SA)': 'N',   # 含保障倍数型
        'max(premium*1.X, csv)': 1.0,     # 微弱增强型
        'SA (fixed sum assured)': None    # 需计算SA/premium
    }
    
    return premium_paid, death_benefit_formula
```

---

## 第三步：分红机制深度透视

### 3.1 分红险三差来源分析

```
可分配盈余 = 死差益 + 费差益 + 利差益

死差益：实际死亡率 < 定价死亡率 → 盈余
费差益：实际运营费用 < 定价费用假设 → 盈余  
利差益：实际投资收益 > 预定利率 → 盈余（最主要来源，占70%+）

监管要求：可分配盈余的 ≥ 70% 须分配给保单持有人（原保监发[2009]90号）
```

### 3.2 分红机制红旗识别

分析条款时，标注以下风险信号：

| 红旗信号 | 条款特征 | 精算含义 |
|---------|---------|---------|
| 🔴 不披露预定利率 | 条款中无"预定利率X%"字样 | 消费者无法验证定价公平性 |
| 🔴 红利完全不确定 | 仅写"红利不确定，可能为零" | 演示利率无约束力 |
| 🟡 累积生息利率可变 | "按公司公布利率" | 利率可单方面下调 |
| 🟡 分红计算不透明 | 无三差来源说明 | 信息不对称风险高 |
| 🟢 历史分红信息披露 | 附历年分红实现率 | 透明度较高 |
| 🟢 最低保证利率 | "不低于X%的保证结算利率" | 下行保护较强 |

---

## 第四步：产品综合评级输出

### 4.1 评级维度

生成每个产品的标准化评级报告，包含以下维度：

```python
RATING_DIMENSIONS = {
    'return_quality': {
        'name': '收益质量',
        'weight': 0.30,
        'metrics': ['IRR', '回本年数', '与基准利率对比']
    },
    'transparency': {
        'name': '信息透明度',
        'weight': 0.20,
        'metrics': ['预定利率披露', '现金价值表完整性', '分红机制透明度']
    },
    'protection': {
        'name': '保障功能',
        'weight': 0.20,
        'metrics': ['身故杠杆比', '责任免除合理性', '保障期间']
    },
    'liquidity': {
        'name': '流动性',
        'weight': 0.15,
        'metrics': ['前3年退保损失率', '保单贷款比例', '减保机制']
    },
    'longevity_protection': {
        'name': '长寿保障',
        'weight': 0.15,
        'metrics': ['保障终止年龄', '年金领取期弹性', '通胀对冲能力']
    }
}
```

### 4.2 标准报告结构

每次分析必须输出以下结构的报告：

```
# [产品名称] 精算分析报告

## 一、产品结构图解
[用ASCII图或表格展示现金流时间轴]

## 二、核心精算参数提取
[逐条映射：条款语言 → 精算含义]

## 三、量化指标
- IRR（保守/中性/乐观三情景）
- 回本年数
- 身故保障杠杆比
- 前3/5年退保损失率
- 年金系数（年金险专用）

## 四、风险信号清单
[红旗/黄旗/绿旗分类]

## 五、综合评级
[五维雷达图描述 + 总分]

## 六、适合/不适合人群
[基于精算分析的客观判断]

## 七、与可比产品/资产的对比
[基准比较：国债、大额存单、同类产品]
```

---

## 第五步：数据资源与工具链

### 5.1 推荐开源工具

```python
# 精算建模
import lifelib          # 寿险精算建模，含标准生命表
import numpy_financial  # IRR、NPV计算
from scipy.optimize import brentq  # 反推预定利率

# 数据处理
import pandas as pd
import numpy as np

# 可视化
import matplotlib.pyplot as plt
import matplotlib
matplotlib.rcParams['font.family'] = 'SimHei'  # 中文显示

# PDF条款解析
import pdfplumber       # 从PDF提取条款文本
```

### 5.2 关键监管数据源

- **中国人寿保险业经验生命表（CL2020）**：2021年起执行，用于死亡率假设
- **预定利率监管上限**：2023年9月起为2.5%（普通型），分红险为2.0%
- **万能险最低保证利率**：上限1.5%
- **可分配盈余比例**：保单持有人分配比例≥70%（90号文）
- **偿付能力充足率**：核心偿付能力≥50%，综合偿付能力≥100%（偿二代）

### 5.3 GitHub资源索引

| 项目 | 用途 | 链接 |
|------|------|------|
| `lifelib` | 寿险精算建模，复现定价模型 | actuarialopensource/lifelib |
| `TmVal` | 年金现值、IRR计算 | genedan/TmVal |
| `chainladder-python` | 准备金三角形分析 | chainladder-community/chainladder-python |
| `insurancerating` | R语言GLM费率厘定 | mharinga/insurancerating |
| `InsQABench` | 中文保险条款QA基准 | Spico/InsQABench |

---

## 快速参考：常见产品类型分析重点

### 分红型年金险（如本技能的原始案例）
1. 反推隐含预定利率（目前监管上限2.0%）
2. 计算年金给付期的IRR（含/不含分红两个情景）
3. 检验满期保险金是否真正"额外"给付
4. 分析分红实现方式的复利效应
5. 评估第二投保人等制度创新的实际价值

### 重疾险
1. 对比ICD-10标准与产品疾病定义的严格程度差异
2. 计算赔付率（历史赔付/保费收入）
3. 分析等待期设置的逆选择控制力度
4. 评估保证续保条款的风险承担方

### 增额终身寿险
1. 计算复利增额率的有效年化收益
2. 现金价值曲线斜率分析（识别高手续费阶段）
3. 减保机制的灵活性评估
4. 对比"保额增加"vs"现金价值增加"的实质区别

### 万能险
1. 结算利率历史数据分析（需查询公司官网公告）
2. 初始费用、账户管理费的实际冲击
3. 最低保证利率的下行保护力度
4. 与货币基金、债券基金的净收益对比

---

## 分析质量检查清单

完成分析后，验证以下项目：

- [ ] 是否提取了所有核心精算参数？
- [ ] IRR计算是否覆盖保守/中性/乐观三种情景？
- [ ] 是否识别了所有红旗条款？
- [ ] 现金价值曲线分析是否包含具体数值？
- [ ] 报告是否提供了可比基准（国债等）？
- [ ] 结论是否基于量化数据而非主观判断？
- [ ] 适合/不适合人群的描述是否具体？
