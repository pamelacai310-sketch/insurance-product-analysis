# 保险产品精算优势分析

本项目以“同险种、同投保条件、同现金流时点、同证据标准”为前提，对保险产品进行可复核的逐项比较。正式流程不自动补年龄、性别、交费期、领取规则或满期金，不使用通用分红率推测实际利益，也不输出主观综合分或A-D等级。

```text
正式费率表/现金价值表/条款/利益演示
                    ↓
         版本、来源、单位和条件审计
                    ↓
              确定性逐项计算
                    ↓
          相对排名、取舍与资料缺口
```

## 精算优势维度

| 维度 | 正式流程的量化口径 |
|---|---|
| 保证收益 | 指定年度保证现金价值、保证退保IRR |
| 资金回收 | 现金价值/累计保费、损失额、回本年度 |
| 身故保障 | 普通身故保险金、条款取大分支、身故杠杆 |
| 年金效率 | 首次保证领取、累计保证领取、保证领取现金流IRR |
| 长寿保障 | 终身领取、保证领取年数、显式测试年龄后的保证给付 |
| 分红质量 | 保证、演示和实际红利分列；未知不按0处理 |
| 合同选择权 | 贷款、减保、减额交清等条款存在性及显式情景NPV |
| 不利情景 | 零分红、按保证现金价值提前退出的损失和IRR |
| 材料透明度 | 页码、表头、行列、单位、版本及SHA-256审计 |

只有一只产品在全部声明的主要指标中均列第一，且所有产品资料完整时，报告才会写“综合领先”；否则只展示各维度取舍。

## 快速开始

严格计算器只依赖Python 3.9+标准库：

```bash
python3 unified_analysis.py \
  --comparison-case case.json \
  --output-dir outputs/strict_comparison
```

也可以直接调用可移植Skill：

```bash
python3 skills/compare-insurance-products/scripts/insurance_compare.py validate \
  --input case.json

python3 skills/compare-insurance-products/scripts/insurance_compare.py compare \
  --input case.json \
  --output-dir outputs/strict_comparison
```

输入规范见[输入结构](skills/compare-insurance-products/references/input-schema.md)，计算规则见[计算与审计规则](skills/compare-insurance-products/references/calculation-rules.md)。

## 年金产品决策数据 Skill

[`annuity-product-intelligence v1.0.0`](skills/annuity-product-intelligence/README.md) 是独立的产品经济分析工具，不读取或索取客户年龄、资产、收入、目标、风险偏好等适配数据。它对公开产品配置空间执行确定性 PDF/表格抽取、Schema 与单位归一化、显式保单月现金流、完整 IRR 根集、流动性、长寿、早逝、通胀、资本效率、相对价值、provenance 与 confidence routing。

```bash
python3 skills/annuity-product-intelligence/scripts/annuity_product_intelligence.py self-test

python3 skills/annuity-product-intelligence/scripts/annuity_product_intelligence.py demo \
  --out outputs/annuity_demo
```

只有条款语义仍存在歧义时才生成最小化 LLM review packet；数值冲突、OCR 和表格冲突仍走确定性或人工复核路线。保证与演示/非保证利益始终分列，不输出客户适配建议或主观综合分。

## 条款报告衔接

`insurance-clause-insights` 生成的条款报告只能先做资料准备度审计：

```bash
python3 unified_analysis.py \
  --clause-report ../insurance-clause-insights/outputs/run_x/reports/comparison_report.json \
  --output outputs/strict_input_readiness.json
```

该模式不会计算IRR、生成排名或填补缺失参数。补齐同版本费率表、现金价值表、条款来源和统一投保条件后，再建立严格 `comparison-case`。

## 输出内容

正式流程同时生成：

- `comparison.md`：结论、统一条件、证据和单位审计、现金价值、保证退保IRR、年金效率、长寿风险转移、合同选择权、压力测试、身故保障及红利口径。
- `comparison.json`：标准化输入、计算公式、现金流、身故责任分支、逐项排名、缺失数据和警告。

资料缺失、版本冲突、单位冲突或投保条件不一致时，对应产品退出排名；不会用估算值补位。

## 公开材料准备

`material_irr_analysis.py` 保留用于公开材料抽取和保证现金流准备度审计。它不再使用统一的1%/2.5%分红假设，不采用“按基本保额年领”的通用兜底，不跨不同投保案例排名，也不输出综合等级。

费率表相关能力包括：

- `premium_table_ref`：记录匹配标题、URL/路径、版本、内容哈希和置信度。
- `formal_plan_input`：检查正式计划所需年龄、性别、交费期、保费和基本金额。
- `material_version_refs` / `version_changes`：识别条款、费率表和现金价值表版本变化。

## RIC增额红利

`ric_dividend_estimator.py` 只允许对“女性45岁、5年交、保障至105岁、65岁起额外年金”的正式利益演示案例按基本保险金额线性缩放。年龄、性别、交费期、保障期限或领取安排变化时会停止计算。

```bash
python3 ric_dividend_estimator.py --basic-amount 100000 --format csv
python3 ric_dividend_estimator.py --basic-amount 100000 \
  --realization-rate 0.857 --format json
```

历史红利实现率只作为敏感性代理，不能视为实际已分配红利或未来保证。完整说明见[RIC推测方法与边界](reports/ric_annual_incremental_dividend_inference_20260730.md)。

## 已停用入口

以下旧入口包含示例现金流、固定分红率或模拟公司风险数据，现仅保留源码参考，并会拒绝生成正式综合评级：

- `integrated_calculator.py`
- `enhanced_calculator.py`
- `hsbc_huiyingfengnian_analysis.py`
- `actuarial_calculator.generate_rating()`

安装某个精算库不等于拥有保险公司真实资产、负债、准备金或再保险数据。随机ALM、VaR和固定准备金示例不得作为单一保险产品优势证据。

## 验证

```bash
python3 -m unittest discover -v
python3 skills/compare-insurance-products/scripts/insurance_compare.py self-test
```

结果仅用于产品核算复核，不替代保险公司正式投保计划书，也不构成保险、法律或投资建议。
