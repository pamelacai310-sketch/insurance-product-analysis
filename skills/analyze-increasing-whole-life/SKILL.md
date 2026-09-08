---
name: analyze-increasing-whole-life
description: 对增额终身寿险/增额寿进行无需客户财务数据的客观决策数据分析。基于正式利益演示、现金价值表和条款，计算回本、退保资金缺口、保证现金价值IRR、身故情景IRR、身故/现金价值比、减保与保单贷款约束；支持同投保场景下的多产品逐项排名和Pareto分析。禁止补默认投保参数、混合保证与非保证利益、跨场景排名、主观总分。
---

# 增额终身寿险决策数据分析

目标：判断产品本身擅长解决什么需求、短板在哪里；不要求客户收入、资产、风险偏好等个人数据。

## 工作流

1. **只抽最小原始数据**：产品场景、保费现金流、关键年度保证现金价值/身故利益、减保规则、保单贷款规则及证据指针。不要人工填写已可计算的IRR/回本指标。
2. 默认 `analysis_mode=core`：抽取早期年度直到首次可证明回本，再取Y5/Y10/Y20/Y30与最长可用年度。只有用户要求完整收益曲线或IRR稳定年度时才用 `full` 并抽取逐年数据。
3. 先读 [输入规范](references/input-schema.md)。字段定位困难时再读 [抽取地图](references/extraction-map.md)；只有解释方法论时读 [方法论](references/methodology.md)。
4. 先验证，再计算；任何数值计算都交给脚本：

```bash
python3 scripts/analyze.py validate --input product.json
python3 scripts/analyze.py analyze --input product.json --output result.json
```

多产品比较：

```bash
python3 scripts/analyze.py compare --inputs a.json b.json c.json --output comparison.json
```

5. 比较前必须通过 comparability gate：币种、投保年龄、性别、核保等级、交费期、缴费频率、保障方案和保费现金流必须一致。未通过时只做单品分析，不排名。
6. 解释时优先报告：流动性、保证增长、身故保障、灵活性、确定性；不得合成主观总分或A-D评级。

## 强制口径

- 首期保费必须有明确现金流时点；不得默认年龄、性别或5年交。
- 保证现金价值IRR只使用实际保费现金流和该年度保证现金价值。
- `death_benefit_irr` 仅表示“假设该年度身故”的现金流IRR，不得表述为投资收益率。
- 保证与演示/非保证利益必须分列；不得把红利、万能结算或演示值混入保证IRR。
- 回本年度只有在从Y1到首次回本年度的数据连续齐全时才输出精确年份；否则输出区间并明确证据不足。
- IRR稳定年度默认定义为：连续5年保证现金价值IRR与最长可用年度IRR差异均不超过10bp；稀疏 `core` 数据不得推断稳定年度。
- 减保、保单贷款只审计合同权利与限制，不因为“存在”就自动计为优势。
- Pareto只有配置的主要指标在全部可比产品上均完整时才生成；否则停止而不是用缺失指标凑排名。

## 输出结论边界

允许：逐项领先、各维度取舍、Pareto前沿、被另一产品严格支配、资料缺失/不可比。

禁止：跨场景“综合第一”、主观100分、把非保证演示当保证、把身故情景IRR称为投资回报。

## 自检

```bash
python3 scripts/analyze.py self-test
```

自检失败前不得用于正式产品核算。
