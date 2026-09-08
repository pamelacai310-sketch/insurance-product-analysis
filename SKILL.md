---
name: insurance-product-analysis
description: 对保险产品进行证据可追溯的精算优势分析。用于同条件比较现金价值、保证退保IRR、身故保险金、年金领取效率、长寿风险转移、合同选择权、分红口径和保证利益压力情景；增额终身寿还支持无需客户财务数据的流动性、保证增长、身故保障、灵活性和Pareto决策数据分析。禁止自动补投保参数、通用分红率、主观综合分及A-D评级。
dependencies:
  python: ">=3.9"
---

# 保险产品精算优势分析

按任务路由到专用规范和确定性计算器：

- 增额终身寿险/增额寿决策数据分析：`skills/analyze-increasing-whole-life/`
- 通用同条件多保险产品精算比较：`skills/compare-insurance-products/`

## 工作流

1. 收集同一版本的正式费率表、现金价值表、条款和利益演示。
2. 锁定相同险种、币种、年龄、性别、体况、交费期、保费、保障方案及比较年度。
3. 记录每个数值的页码、表头、行列、单位、版本与SHA-256。
4. 增额终身寿使用其 `references/input-schema.md` 建立最小结构化JSON；其他通用比较按 `skills/compare-insurance-products/references/input-schema.md`。
5. 先运行对应Skill的 `validate`，再运行 `analyze`/`compare` 或统一入口。
6. 分别报告保证收益、资金回收、身故保障、年金效率、长寿保障、分红、选择权、压力测试和透明度；无客户资料时不得伪造客户适配权重。

通用比较：

```bash
python3 unified_analysis.py --comparison-case case.json --output-dir results
```

增额终身寿：

```bash
python3 skills/analyze-increasing-whole-life/scripts/analyze.py analyze --input product.json --output result.json
```

## 禁止事项

- 不得用默认年龄、默认性别或默认5年交补缺失条件。
- 不得按产品名称猜领取时间、领取金额或满期金。
- 不得把年金给付统一增加1%或2.5%冒充历史/演示分红。
- 不得把演示红利计入保证现金价值或保证退保IRR。
- 不得用随机ALM、VaR、固定准备金或示例公平性评价单一产品。
- 不得把保单贷款、终身保障等功能存在性直接换算成高分。
- 不得跨险种或跨投保条件排名。
- 不得合成主观总分或输出A-D等级。
- 增额寿的身故情景IRR不得表述为投资收益率。

## 综合结论

仅当一只产品在全部声明主要指标中唯一领先，且所有产品资料完整、正式、同条件时，才可称为“综合领先”。其余情况必须写明各维度取舍或“资料不足，无法判断”。增额终身寿优先输出逐项相对优势和Pareto关系，不因缺少客户偏好而人为设置权重。

条款报告本身只能通过 `unified_analysis.py --clause-report` 生成资料准备度审计，不能直接产生正式精算排名。
