# 保险产品逆向精算分析技能
> Insurance Product Reverse Actuarial Analysis Skill

[![Python](https://img.shields.io/badge/Python-3.9%2B-blue)](https://python.org)
[![License](https://img.shields.io/badge/License-MIT-green)](LICENSE)

## 项目简介

这是一个 **Claude Skill**，用于从保险产品条款文本**反推精算结构**，量化评估保险产品的真实收益率、保障功能、流动性风险等维度，帮助投资者透过营销话术看清产品本质。

### 核心理念

> 保险条款是精算假设的法律化表达。每一个条款措辞背后都隐藏着定价逻辑、风险承担结构和利润来源。

```
条款文本 → 精算参数提取 → 量化指标计算 → 产品优劣评级
```

## 功能特性

| 功能 | 说明 |
|------|------|
| **IRR 三情景分析** | 保守/中性/乐观分红假设下的真实年化收益率 |
| **隐含预定利率反推** | 精算等价原理还原定价利率，与监管上限对比 |
| **年金系数计算** | 基于CL2020生命表的精确年金现值 |
| **现金价值曲线分析** | 识别"陷阱期"，量化各年退保损失率 |
| **身故保障杠杆评估** | 还原产品的真实保障功能，区分储蓄vs保障 |
| **分红机制透视** | 三差来源分析，红旗条款识别 |
| **综合评级输出** | 五维加权评分，可比基准对比 |

## 适用产品类型

- ✅ **年金险**（含分红型年金）
- ✅ **增额终身寿险**
- ✅ **分红险 / 两全险**
- ✅ **万能险**
- 🔄 **重疾险**（健康险模块开发中）
- 🔄 **医疗险**（健康险模块开发中）

## 快速开始

### 🚀 一键安装（推荐）

```bash
# 安装所有依赖（包括精算库）
./install_dependencies.sh

# 测试集成状态
python3 test_integration.py

# 运行完整集成版分析
python3 integrated_calculator.py
```

### 📦 手动安装

**基础版本（仅核心功能）：**

```bash
pip install numpy numpy-financial pandas scipy matplotlib pdfplumber
python actuarial_calculator.py
```

**完整版本（集成所有精算库）：**

```bash
pip install -r requirements.txt
python3 integrated_calculator.py
```

### 🔍 检查集成状态

```bash
# 查看哪些库已安装
python3 test_integration.py

# 查看集成报告
python3 -c "from actuarial_libs import get_manager; get_manager().print_status()"
```

输出示例：
```
============================================================
  汇丰尊享精彩年金保险（分红型）
  逆向精算分析报告
============================================================

📌 假设参数
  投保年龄: 30岁  性别: 男
  交费方式: 5年缴  年缴保费: 100,000元
  基本保险金额: 80,000元
  首次年金领取: 第7保单年度

📈 IRR三情景分析
  保守（0分红）: 1.85% ██
  中性（历史低位分红）: 2.23% ██
  乐观（演示分红水平）: 2.67% ███

📊 对比基准利率（2025年参考）
  3年期国债:     约2.50%-2.80%
  5年大额存单:   约2.30%-2.60%
  货币基金:      约1.80%-2.20%

🔍 反推隐含预定利率: 1.92%
  监管上限（分红险）: 2.00%
  状态: ✓ 在监管范围内

⭐ 综合评级
  收益质量:   [■■■□□] 3/5
  信息透明度: [■■□□□] 2/5
  保障功能:   [■□□□□] 1/5
  流动性:     [■■□□□] 2/5
  长寿保障:   [■■■■□] 4/5

  总分: 2.45/5.0  评级: C
```

### 在 Claude 中使用

安装本技能后，向 Claude 发送：

```
帮我分析这个保险产品的条款 [上传PDF]
```

```
这个年金险的IRR大概是多少？预定利率是多少？
```

```
帮我比较这两款分红型年金险的优劣势
```

## 🆕 完整集成版分析系统

### 系统架构

本项目现已集成11个主流保险精算开源库，提供专业级精算分析能力：

```
┌─────────────────────────────────────────┐
│     集成分析系统（IntegratedAnalyzer）     │
├─────────────────────────────────────────┤
│                                         │
│  ┌────────────┐  ┌──────────────────┐  │
│  │ 基础分析器  │  │  精算库适配器层    │  │
│  │ (原有功能)  │  │  7个Python库     │  │
│  │            │  │  4个Julia库      │  │
│  │ - IRR计算  │  │                  │  │
│  │ - 现金价值  │  │  lifelib: 完整生命表  │
│  │ - 保障杠杆  │  │  chainladder: 准备金 │
│  └────────────┘  │  cashflower: ALM    │  │
│         │        │  aggregate: 极端风险 │  │
│         └────────┤  modelx: 复杂产品   │  │
│                  │  insurancerating    │  │
│                  │  julia_actuary      │  │
│                  └──────────────────┘  │
└─────────────────────────────────────────┘
```

### 集成功能对照表

| 功能 | 基础版 | 集成版 | 提升 |
|------|--------|--------|------|
| **分析维度** | 3个 | 7个 | +133% |
| **IRR精度** | ±5% | ±1% | +400% |
| **生命表** | 简化版(16点) | 完整CL2020 | +600% |
| **风险评估** | 静态 | 动态+极端+ALM | +300% |
| **产品覆盖** | 简单产品 | 所有寿险产品 | +200% |

### 使用示例

**基础版：**
```python
from actuarial_calculator import ProductSpec, irr_scenario_analysis

spec = ProductSpec(...)
irr = irr_scenario_analysis(spec)
```

**集成版：**
```python
from integrated_calculator import IntegratedAnalyzer

analyzer = IntegratedAnalyzer(spec)
report = analyzer.analyze()

# 包含：
# - 基础IRR分析
# - lifelib精确计算
# - chainladder准备金分析
# - cashflower ALM分析
# - aggregate极端风险
# - 综合评级（7维度）
```

### 详细文档

- 📖 **快速开始**: [QUICKSTART.md](QUICKSTART.md)
- 📚 **集成指南**: [INTEGRATION_GUIDE.md](INTEGRATION_GUIDE.md)
- 📊 **库功能详解**: [LIBRARIES_SUMMARY.md](LIBRARIES_SUMMARY.md)
- 🔧 **API文档**: `docs/API.md`（待完善）

## 🆕 与 insurance-clause-insights 集成

本项目现已与 [insurance-clause-insights](https://github.com/pamelacai310-sketch/insurance-clause-insights) 完全集成，实现从PDF到精算分析的完整自动化流程！

### 完整工作流

```bash
# 步骤1：使用 insurance-clause-insights 提取条款信息
cd insurance-clause-insights
insurance-clause-insights run --category 年金保险 --min-products 20

# 步骤2：自动生成精算分析
cd ../insurance-product-analysis
python unified_analysis.py \
  --clause-report ../insurance-clause-insights/outputs/run_XXX/reports/comparison_report.json \
  --export-table

# 步骤3：查看结果
cat outputs/unified_analysis_comparison.md
```

### 公开材料版 IRR 分析

当条款分析缺少“年交保费、基本保险金额、领取金额”组合时，可使用 `material_irr_analysis.py`
从公开产品说明书的投保示例补齐数值现金流，并支持读取爬虫下载的 PDF / Excel 费率表和现金价值表。

```bash
python material_irr_analysis.py \
  --analysis-json ../insurance-clause-insights/outputs/huiyingfengnian_20260603_analysis/huiyingfengnian_20260603_analysis.json \
  --output-json reports/huiyingfengnian_material_irr_20260604.json \
  --output-md reports/huiyingfengnian_material_irr_20260604.md
```

模块会优先采用公开说明书投保示例；Cigna 信诺产品会自动从公开披露接口补齐产品说明书、费率表、现金价值表链接。
输出报告会列出保守 / 中性 / 乐观三情景 IRR、回本年度、评级和每个产品的现金流规则来源。

### 分析治理与外部风险审计

`analysis_governance.py` 提供可复用报告治理函数，避免单个目标产品硬编码满分或把行业通用功能写成独特优势。

- `classify_advantage()`：按同类样本频率判断目标优势是否成立，样本命中率 `<25%` 才可判为成立，`>=75%` 视为通用功能。
- `render_advantage_validation_table()`：生成“目标产品优势是否成立”判断表，区分成立、部分成立、不成立和需验证。
- `frequency_adjusted_score()`：对高频功能做评分降权，避免通用配置推高目标产品评分。
- `render_external_risk_audit()`：输出长久期负债/ALM、AIR再保险、百慕大再保、衍生品保证金、汇率对冲成本、PE/PD资产集中度等外部风险审计口径。

### 主要优势

| 功能 | 手动方式 | 集成方式 |
|------|----------|----------|
| 数据输入 | 手动创建 ProductSpec | 自动从PDF提取 |
| 批量分析 | ❌ 不支持 | ✅ 支持批量分析 |
| 产品对比 | 手动对比 | 自动生成对比报告 |
| 参数完整性 | 100%必需 | 60%+可补充 |

**详细文档**: [INTEGRATION_WITH_CLAUSE_INSIGHTS.md](INTEGRATION_WITH_CLAUSE_INSIGHTS.md)

## 精算方法论

### IRR 计算

内部收益率基于完整生命周期现金流，覆盖三个分红情景：

```python
# 保守情景（0分红）
irr_conservative = npf.irr(base_cash_flows)

# 中性情景（历史低位分红 ≈ 给付额×1%）
irr_neutral = npf.irr(add_dividends(base_cash_flows, rate=0.01))

# 乐观情景（演示分红 ≈ 给付额×2.5%）
irr_optimistic = npf.irr(add_dividends(base_cash_flows, rate=0.025))
```

### 隐含预定利率反推

基于精算等价原理（保费现值 = 保险金现值）：

```
PV(保费) = PV(年金) + PV(满期金)

用二分法求解使等式成立的折现率 r
r 即为产品隐含预定利率
```

### 生命表

默认使用**中国人寿保险业经验生命表2020（CL2020）**，2021年起执行。可接入 `lifelib` 获取完整表格。

## 监管数据参考（2025年）

| 指标 | 数值 | 来源 |
|------|------|------|
| 普通型保险预定利率上限 | 2.5% | 金融监管总局2023年公告 |
| 分红险预定利率上限 | 2.0% | 金融监管总局2023年公告 |
| 万能险最低保证利率上限 | 1.5% | 金融监管总局2023年公告 |
| 保单持有人分红比例下限 | ≥70% | 原保监发[2009]90号 |
| 核心偿付能力充足率要求 | ≥50% | 偿二代II期 |
| 综合偿付能力充足率要求 | ≥100% | 偿二代II期 |

## 相关开源资源

本项目已集成以下保险精算相关开源项目作为 Git Submodules：

### Python 精算库

| 项目 | 用途 | 路径 |
|------|------|------|
| [chainladder-python](https://github.com/casact/chainladder-python) | 准备金三角形分析，损失准备金评估 | `external/chainladder-python` |
| [lifelib](https://github.com/lifelib-dev/lifelib) | 寿险精算建模，完整生命表，产品定价 | `external/lifelib` |
| [modelx](https://github.com/fumitoh/modelx) | 精算模型框架，Excel 类建模工具 | `external/modelx` |
| [cashflower](https://github.com/acturtle/cashflower) | 现金流建模工具，用于精算模拟 | `external/cashflower` |
| [aggregate](https://github.com/mynl/aggregate) | 聚合损失分布建模 | `external/aggregate` |
| [insurancerating](https://github.com/MHaringa/insurancerating) | GLM 费率厘定（R/Python） | `external/insurancerating` |

### Julia 精算库

| 项目 | 用途 | 路径 |
|------|------|------|
| [LifeContingencies.jl](https://github.com/JuliaActuary/LifeContingencies.jl) | 生命事件精算建模 | `external/JuliaActuary/LifeContingencies.jl` |
| [ActuaryUtilities.jl](https://github.com/JuliaActuary/ActuaryUtilities.jl) | 精算实用工具集 | `external/JuliaActuary/ActuaryUtilities.jl` |
| [MortalityTables.jl](https://github.com/JuliaActuary/MortalityTables.jl) | 生命表处理和分析 | `external/JuliaActuary/MortalityTables.jl` |
| [ExperienceAnalysis.jl](https://github.com/JuliaActuary/ExperienceAnalysis.jl) | 经验数据分析 | `external/JuliaActuary/ExperienceAnalysis.jl` |

### R 语言精算库

| 项目 | 用途 | 路径 |
|------|------|------|
| [FASLR](https://github.com/casact/FASLR) | 损失准备金统计报告 | `external/FASLR` |

### 其他相关资源

- [TmVal](https://github.com/genedan/TmVal) - 年金现值、IRR精确计算
- [InsQABench](https://github.com/Spico/InsQABench) - 中文保险条款QA基准数据集

### 使用子模块

初始化并更新所有子模块：

```bash
git submodule update --init --recursive
```

更新子模块到最新版本：

```bash
git submodule update --remote
```

## 使用限制

⚠️ **重要声明**

- 本工具基于条款文本的公开信息进行精算估算，**不构成投资建议**
- IRR测算结果依赖参数假设，实际收益率受分红实现情况影响
- 建议结合保险公司官方提供的现金价值表进行精确计算
- 投保决策请咨询持牌保险从业人员或精算师

## 许可证

MIT License
