# 快速开始

## 1. 准备同条件输入

每只产品必须使用相同险种、币种、年龄、性别、体况、交费期、年交保费、保障方案和比较年度。为费率表、现金价值表和条款记录页码、行列、单位、版本与SHA-256。

参考：

- `skills/compare-insurance-products/references/input-schema.md`
- `skills/compare-insurance-products/assets/fixtures/wwa_male_30_10pay.json`

## 2. 先验证

```bash
python3 skills/compare-insurance-products/scripts/insurance_compare.py validate \
  --input case.json
```

单位、版本、来源或责任阶段冲突时必须先修复，不能跳过。

## 3. 正式比较

```bash
python3 unified_analysis.py \
  --comparison-case case.json \
  --output-dir outputs/strict_comparison
```

查看：

```bash
open outputs/strict_comparison/comparison.md
```

报告不输出主观总分或A-D等级，只给逐项排名与取舍。

## 4. 只有条款报告时

```bash
python3 unified_analysis.py \
  --clause-report comparison_report.json \
  --output outputs/strict_input_readiness.json
```

该命令仅检查资料准备度，不自动补年龄、性别、交费期、领取规则或满期金。

## 5. 自检

```bash
python3 -m unittest discover -v
python3 skills/compare-insurance-products/scripts/insurance_compare.py self-test
```
