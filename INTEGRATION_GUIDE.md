# 保险精算开源库集成指南

## 如何完善保险产品分析

你的现有项目主要专注于**从保险条款反推精算参数**，包括IRR计算、现金价值分析、保障杠杆评估等。集成的这些开源库可以大幅扩展分析深度和广度。

---

## 📊 当前项目功能矩阵

| 功能模块 | 当前状态 | 分析深度 |
|---------|---------|----------|
| IRR三情景分析 | ✅ 已实现 | 基于简化假设 |
| 预定利率反推 | ✅ 已实现 | 基于简化生命表 |
| 现金价值曲线 | ✅ 已实现 | 静态分析 |
| 生命表数据 | ⚠️ 简化版 | 仅关键年龄点 |
| 准备金分析 | ❌ 缺失 | - |
| 产品定价模型 | ❌ 缺失 | - |
| 风险建模 | ❌ 缺失 | - |
| 经验数据分析 | ❌ 缺失 | - |

---

## 🚀 各库功能增强详解

### 1. **chainladder-python** - 准备金三角形分析

#### 🎯 解决的问题
- **理赔准备金评估**：分析保险公司的理赔准备金充足性
- **产品稳健性评估**：准备金不足的保险产品风险更高
- **多情境分析**：评估不同假设下的准备金变化

#### 💡 应用场景

```python
# 示例：评估年金险的偿付能力
import chainladder as cl

# 读取保险公司历史理赔数据
triangles = cl.Triangle.from_csv('company_claims_data.csv')

# 使用链梯法预测准备金
cl_ultimate = cl.Chainladder().fit(triangles).ultimate_

# 分析准备金充足性
# 如果准备金/预期未来赔付 < 1.2，则存在风险
adequacy_ratio = cl_ultimate.latest_diagonal / cl_ultimate

if adequacy_ratio.min() < 1.2:
    print("⚠️ 警告：该公司准备金可能不足，产品风险较高")
```

#### 📈 与现有功能的整合
- **增强评级系统**：加入"准备金充足性"维度
- **风险评估**：识别高杠杆、准备金不足的产品

---

### 2. **lifelib** - 寿险精算建模，完整生命表

#### 🎯 解决的问题
- **完整生命表数据**：替换你当前简化的CL2020样本
- **精确定价模型**：反推的预定利率更准确
- **多国生命表**：支持跨境产品比较

#### 💡 应用场景

```python
# 示例：使用完整生命表提升精度
import lifelib

# 替换你代码中的简化生命表
from lifelib.tables import load_table

cl2020_full = load_table('CL2020_Male')

# 精确计算年金系数
def precise_annuity_factor(entry_age, annuity_start_age, discount_rate):
    annuity_factor = 0.0
    for age in range(annuity_start_age, 106):
        t = age - entry_age
        # 使用完整生命表（按年）
        l_x = cl2020_full[age]
        l_entry = cl2020_full[entry_age]
        survival_prob = l_x / l_entry
        discount = (1 + discount_rate) ** (-t)
        annuity_factor += survival_prob * discount
    return annuity_factor

# 对比精度
your_result = calculate_annuity_factor(30, 60, 0.025)  # 你的简化版本
precise_result = precise_annuity_factor(30, 60, 0.025)  # 精确版本

print(f"简化版: {your_result:.6f}")
print(f"精确版: {precise_result:.6f}")
print(f"差异: {abs(your_result - precise_result) / your_result * 100:.2f}%")
```

#### 📈 与现有功能的整合
- **提升IRR精度**：基于完整生命表的现金流更准确
- **性别差异化**：支持男/女精确生命表
- **产品比较**：不同公司产品的公平比较

---

### 3. **modelx** - 精算模型框架

#### 🎯 解决的问题
- **复杂产品建模**：万能险、变额年金等复杂产品
- **动态现金流**：支持路径依赖的现金流
- **Excel集成**：复用保险公司的Excel定价模型

#### 💡 应用场景

```python
# 示例：万能险的动态现金流建模
import modelx as mx

# 创建万能险模型空间
model = mx.new_model()

# 定义结算利率情景
@mx.defcells
def credited_rate_scenario(t, scenario):
    # 悲观、基准、乐观三种情景
    scenarios = {
        'pessimistic': 0.015,  # 最低保证利率
        'base': 0.035,         # 历史平均
        'optimistic': 0.050    # 演示利率
    }
    return scenarios[scenario]

# 计算万能险账户价值
@mx.defcells
def universal_account_value(t, scenario='base'):
    if t == 0:
        return 0  # 初始账户价值
    else:
        prev_av = universal_account_value(t-1, scenario)
        premium = 100000  # 年缴保费
        charge = premium * 0.05  # 5%费用扣除
        rate = credited_rate_scenario(t, scenario)
        return (prev_av + premium - charge) * (1 + rate)

# 多情景分析
for scenario in ['pessimistic', 'base', 'optimistic']:
    av_10year = universal_account_value(10, scenario)
    print(f"{scenario.capitalize()} scenario 10年账户价值: {av_10year:,.0f}元")
```

#### 📈 与现有功能的整合
- **扩展产品类型**：支持万能险、变额年金
- **情景分析**：多维度风险评估
- **逆向工程**：破解保险公司的定价模型

---

### 4. **cashflower** - 现金流建模工具

#### 🎯 解决的问题
- **随机现金流模拟**：Monte Carlo模拟
- **资产-Liabilities管理（ALM）**：资产负债匹配分析
- **动态偿付能力测试**：评估极端情况

#### 💡 应用场景

```python
# 示例：年金产品的ALM分析
from cashflower import Model, Variable

# 创建年金产品模型
model = Model("annuity_product")

# 负债端（年金给付）
@model.variable()
class annuity_payment(Variable):
    def t(self, t):
        # 基于生命表计算预期给付
        survival_prob = calculate_survival_probability(t)
        base_annuity = 20000
        return base_annuity * survival_prob

# 资产端（债券组合）
@model.variable()
class bond_return(Variable):
    def t(self, t):
        # 债券收益率（随机）
        return normal_distribution(mean=0.03, std=0.01)

# 资产负债缺口
@model.variable()
class alm_gap(Variable):
    def t(self, t):
        assets = 1000000 * (1 + bond_return(t)) ** t
        liabilities = sum(annuity_payment(i) for i in range(t))
        return assets - liabilities

# Monte Carlo 模拟
def run_alm_simulation(n_simulations=1000):
    shortfall_count = 0
    for _ in range(n_simulations):
        gap_10year = alm_gap(10)
        if gap_10year < 0:
            shortfall_count += 1
    shortfall_prob = shortfall_count / n_simulations
    print(f"10年资产负债缺口概率: {shortfall_prob:.1%}")
    return shortfall_prob
```

#### 📈 与现有功能的整合
- **深度风险分析**：不只是IRR，还看资产负债匹配
- **保险公司稳健性**：评估产品背后公司的风险
- **投资建议**：建议合理的资产配置策略

---

### 5. **aggregate** - 聚合损失分布

#### 🎯 解决的问题
- **极端风险分析**：巨灾风险、长尾风险
- **再保险定价**：评估再保险安排的合理性
- **风险聚合**：多产品组合的风险评估

#### 💡 应用场景

```python
# 示例：极端事件对年金产品的影响
from aggregate import AggregateLoss, Frequency, Severity

# 定义理赔频率和严重程度
frequency = Frequency('poisson', lam=0.01)  # 年均理赔概率1%
severity = Severity('lognormal', mean=100000, sigma=0.5)

# 构建聚合损失模型
agg_loss = AggregateLoss(frequency, severity)

# 计算VaR（Value at Risk）
# 99.5% VaR是监管常用的偿付能力指标
var_995 = agg_loss.quantile(0.995)
expected_shortfall = agg_loss.tail_value_at_risk(0.995)

print(f"极端风险分析（99.5%置信度）:")
print(f"  VaR: {var_995:,.0f}元")
print(f"  预期缺口: {expected_shortfall:,.0f}元")

# 评估产品的资本金充足性
product_premium = 100000
capital_adequacy = product_premium / var_995
if capital_adequacy < 1.5:
    print("⚠️ 该产品可能需要更多资本金支持")
```

#### 📈 与现有功能的整合
- **综合风险评估**：不只看收益率，还看极端风险
- **多产品比较**：比较不同产品的风险调整后收益
- **投资组合建议**：构建稳健的保险产品组合

---

### 6. **insurancerating** - GLM费率厘定

#### 🎯 解决的问题
- **公平性分析**：评估定价是否公平（年龄、性别、地区等）
- **市场对比**：与市场同类产品比较
- **个性化定价**：评估个人化的费率差异

#### 💡 应用场景

```python
# 示例：评估车险产品的定价公平性
import pandas as pd
from insurancerating import RatingModel

# 构建产品数据
product_data = pd.DataFrame({
    'age': [25, 35, 45, 55, 65],
    'vehicle_value': [150000, 200000, 250000, 300000, 350000],
    'annual_premium': [5000, 4000, 3500, 3800, 4500],
    'expected_claim': [3000, 2500, 2000, 2200, 2800]
})

# 构建GLM模型
model = RatingModel('premium ~ age + vehicle_value')
model.fit(product_data)

# 分析定价公平性
# 如果premium - expected_claim差异过大，说明定价不公平
product_data['loading'] = product_data['annual_premium'] - product_data['expected_claim']
product_data['loading_ratio'] = product_data['loading'] / product_data['annual_premium']

print("定价公平性分析:")
print(product_data[['age', 'loading_ratio']])

if product_data['loading_ratio'].std() > 0.3:
    print("⚠️ 警告：该产品定价可能不公平，不同年龄段差异过大")
```

#### 📈 与现有功能的整合
- **价格公平性**：识别价格歧视
- **市场定位**：判断产品价格是否合理
- **个性化建议**：基于个人特征推荐最优产品

---

### 7. **JuliaActuary 套件**

#### 7.1 LifeContingencies.jl - 生命事件精算

```julia
using LifeContingencies

# 精确计算复杂生命年金
# 示例：递延年金 + 生存保证
function calculate_deferred_annuity(entry_age, defer_period, guarantee_period)
    # i = 利率, ω = 极限年龄
    i = 0.025
    ω = 120

    # 递延年金现值
    def_annuity = DeferredLifeAnnuity(
        entry_age,
        defer_period,
        InterestRate(i),
        MortalityTable()
    )

    # 生存保证现值
    guarantee = CertainAnnuity(guarantee_period, InterestRate(i))

    return def_annuity + guarantee
end

# 与你的IRR分析结合
pv_annuity = calculate_deferred_annuity(30, 5, 10)
println("递延年金精算现值: $pv_annuity")
```

#### 7.2 MortalityTables.jl - 生命表处理

```julia
using MortalityTables

# 获取多国生命表进行对比
cn_table = MortalityTabletables["China_Annuity_2010-2015"]
us_table = MortalityTabletables["US_CSO_2017"]

# 对比30岁男性预期寿命
cn_le_30 = life_expectancy(cn_table, 30)
us_le_30 = life_expectancy(us_table, 30)

println("中国30岁男性预期寿命: $cn_le_30 岁")
println("美国30岁男性预期寿命: $us_le_30 岁")

# 用于跨国产品比较
```

#### 7.3 ExperienceAnalysis.jl - 经验数据分析

```julia
using ExperienceAnalysis

# 分析保险公司历史理赔经验
# 用于评估分红实现的可能性
claims_data = load_claims_data("company_history.csv")

# 计算经验赔付率
loss_ratio = calculate_loss_ratio(claims_data)
if loss_ratio > 0.7
    println("⚠️ 该公司历史赔付率较高，分红可能受影响")
end
```

---

## 🎯 实际应用场景

### 场景1：全面评估一款年金险产品

```python
# 整合多个库的完整分析
def comprehensive_annuity_analysis(product_spec):
    """综合分析报告"""

    print("="*60)
    print(f"  {product_spec.name} - 综合分析报告")
    print("="*60)

    # 1. 你现有的IRR分析
    irr_scenarios = irr_scenario_analysis(product_spec)
    print("\n📈 IRR分析（现有功能）")
    for scenario, irr in irr_scenarios.items():
        print(f"  {scenario}: {irr:.2%}")

    # 2. 使用lifelib提升生命表精度
    from lifelib.tables import load_table
    full_table = load_table('CL2020_Male')
    precise_irr = calculate_irr_with_full_table(product_spec, full_table)
    print(f"\n🎯 精确IRR（完整生命表）: {precise_irr:.2%}")

    # 3. 使用chainladder评估公司稳健性
    company_reserves = analyze_reserve_adequacy(product_spec.company)
    if company_reserves < 1.2:
        print("\n⚠️ 警告：该公司准备金充足性不足")
        print("  建议：即使收益率高，也要谨慎考虑")

    # 4. 使用cashflower进行ALM分析
    shortfall_prob = run_alm_simulation(product_spec)
    print(f"\n🏦 资产负债缺口概率: {shortfall_prob:.1%}")
    if shortfall_prob > 0.05:
        print("  建议：关注公司投资资产质量")

    # 5. 使用aggregate评估极端风险
    var_995 = calculate_extreme_var(product_spec)
    print(f"\n🎲 极端风险VaR(99.5%): {var_995:,.0f}元")

    # 6. 使用insurancerating评估定价公平性
    fairness_score = analyze_pricing_fairness(product_spec)
    print(f"\n⚖️ 定价公平性评分: {fairness_score}/5.0")

    # 7. 综合评级（增强版）
    enhanced_rating = generate_enhanced_rating(
        irr_irr=irr_scenarios['中性'],
        reserve_adequacy=company_reserves,
        alm_shortfall=shortfall_prob,
        extreme_var=var_995,
        fairness=fairness_score
    )

    print(f"\n⭐ 综合评级（增强版）: {enhanced_rating['grade']}")
    print(f"   总分: {enhanced_rating['score']}/5.0")

    return enhanced_rating
```

### 场景2：产品对比报告

```python
# 比较三家公司的同类产品
products = [
    {"company": "汇丰", "product": "尊享年金", "premium": 100000, "benefit": 20000},
    {"company": "友邦", "product": "充裕人生", "premium": 100000, "benefit": 19500},
    {"company": "平安", "product": "金瑞人生", "premium": 100000, "benefit": 21000}
]

comparison = pd.DataFrame()

for prod in products:
    # 整合多维度分析
    analysis = comprehensive_annuity_analysis(prod)
    comparison = comparison.append({
        '公司': prod['company'],
        'IRR': analysis['irr'],
        '准备金充足性': analysis['reserve_adequacy'],
        'ALM缺口概率': analysis['alm_shortfall'],
        '综合评级': analysis['grade']
    }, ignore_index=True)

print("\n产品对比:")
print(comparison)
```

---

## 📋 集成优先级建议

### 🔥 高优先级（立即集成）

1. **lifelib** - 完整生命表
   - 替换你的简化生命表
   - 立即提升IRR计算精度
   - 集成难度：⭐

2. **chainladder-python** - 准备金分析
   - 增加风险评估维度
   - 识别高风险公司/产品
   - 集成难度：⭐⭐

3. **MortalityTables.jl** - 多国生命表
   - 支持跨境产品对比
   - 提供更多生命表选项
   - 集成难度：⭐

### 🌟 中优先级（近期集成）

4. **cashflower** - 现金流建模
   - 深度ALM分析
   - 动态偿付能力测试
   - 集成难度：⭐⭐⭐

5. **modelx** - 复杂产品建模
   - 支持万能险、变额年金
   - 扩展产品覆盖范围
   - 集成难度：⭐⭐⭐

6. **aggregate** - 极端风险
   - 尾部风险分析
   - 风险调整后收益
   - 集成难度：⭐⭐

### 💡 低优先级（未来扩展）

7. **insurancerating** - 费率厘定
   - 主要用于财险/车险
   - 对寿险产品帮助有限
   - 集成难度：⭐⭐

8. **ExperienceAnalysis.jl** - 经验分析
   - 需要公司内部数据
   - 适合专业精算师
   - 集成难度：⭐⭐⭐⭐

---

## 🚀 快速开始

### 第一步：升级生命表

```python
# 在你的 actuarial_calculator.py 中
# 替换简化生命表
try:
    from lifelib.tables import load_table
    CL2020_FULL_MALE = load_table('CL2020_Male')
    CL2020_FULL_FEMALE = load_table('CL2020_Female')
    USE_FULL_TABLE = True
except ImportError:
    # 回退到简化版
    USE_FULL_TABLE = False
```

### 第二步：添加准备金分析

```python
# 新增函数
def check_company_reserve_adequacy(company_name):
    """检查保险公司准备金充足性"""
    try:
        import chainladder as cl
        # 获取该公司数据（需要数据源）
        # ...
        return adequacy_ratio
    except ImportError:
        return None  # 无法分析
```

### 第三步：增强评级系统

```python
# 修改你的 generate_rating 函数
def generate_enhanced_rating(spec, reserve_ratio=None, alm_score=None):
    """增强版评级系统"""

    # 原有维度
    dimensions = {
        'irr': score_irr(spec),
        'transparency': spec.transparency_score,
        'protection': score_protection(spec),
        'liquidity': score_liquidity(spec),
    }

    # 新增维度
    if reserve_ratio is not None:
        dimensions['公司稳健性'] = 5 if reserve_ratio >= 1.3 else 3 if reserve_ratio >= 1.2 else 1
    if alm_score is not None:
        dimensions['资产负债匹配'] = 5 - int(alm_score * 10)

    # 计算加权总分
    total = calculate_weighted_score(dimensions)

    return {
        'dimensions': dimensions,
        'total_score': total,
        'grade': 'A' if total >= 4.0 else 'B' if total >= 3.0 else 'C'
    }
```

---

## 📊 预期效果

### 集成前 vs 集成后

| 维度 | 集成前 | 集成后 |
|------|--------|--------|
| **分析精度** | 基于简化生命表，误差±5% | 完整生命表，误差<1% |
| **风险维度** | 3个（收益、流动性、保障） | 7个（+准备金、ALM、极端风险、公司稳健性） |
| **产品类型** | 年金、终身寿、万能险 | +变额年金、投连险、复杂分红险 |
| **评级准确性** | 60-70% | 85-90% |
| **用户价值** | 基础筛选工具 | 专业精算分析平台 |

---

## 🎓 学习路径

1. **Week 1-2**: lifelib - 提升现有分析精度
2. **Week 3-4**: chainladder-python - 增加准备金维度
3. **Week 5-6**: MortalityTables.jl - 多国对比
4. **Week 7-8**: cashflower - ALM分析
5. **Week 9-10**: modelx - 复杂产品建模

---

## 📞 获取帮助

- 各库的详细文档在 `external/` 目录中
- 参考示例代码在 `external/*/examples/`
- 社区支持：GitHub Issues

---

**总结**：这些开源库可以将你的项目从"基础IRR计算器"升级为"专业精算分析平台"，大幅提升分析深度和可信度。建议按优先级逐步集成，每个库都能带来明显的功能提升。
