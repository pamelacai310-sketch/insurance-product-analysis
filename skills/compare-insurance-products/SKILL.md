---
name: compare-insurance-products
description: 在相同投保条件下比较多只保险产品的现金价值、累计保费回收率、保证退保 IRR、身故保险金和身故杠杆。用户提供保险费率表、现金价值表、保险条款、产品说明书、投保计划或结构化数据，询问哪个产品现金价值或身故保险金更高、何时回本、IRR 排名、同样保费如何换算基本保额，或要求核查千元口径和表格版本时使用。适用于 compare insurance products、cash value、death benefit、surrender IRR、premium rate table 等英文请求。
---

# 多保险产品精算对比

把表格识别和数值计算分开。模型负责定位可靠证据并生成标准化 JSON；脚本负责单位审计、计算和相对排名。不要凭产品名称、营销材料或经验补齐缺失数字。

## 工作流程

1. 收集每只产品同一版本的费率表、现金价值表和保险条款。PDF 布局重要时先逐页渲染核对，再提取文本。
2. 锁定完全一致的投保条件：险种、币种、年龄、性别、体况、交费期、年交保费、保障方案和比较年度。条件不同不得进入同一排名。
3. 从原表抄录标题、单位、页码、行列标签和文件 SHA-256。不要先换算再记录；证据字段必须保留原文。
4. 阅读 [输入规范](references/input-schema.md)，为每只产品建立规范 JSON。费率和现金价值只能选择规范支持的明确口径。
5. 阅读 [计算规则](references/calculation-rules.md)，特别核对交费时点、年龄分段、身故责任阶段和红利性质。
6. 先验证，再计算：

```bash
python scripts/insurance_compare.py validate --input case.json
python scripts/insurance_compare.py compare --input case.json --output-dir results
```

7. 回查 `comparison.json` 的计算轨迹和 `comparison.md` 的警告。单位冲突、版本冲突或证据不足时，只报告待核验事项，不给正式胜负结论。

## 强制口径

- 首期年交保费在 `t=0`，续期保费在后续保单年度初，年度末现金价值在 `t=year`。
- 保证退保 IRR 只包含实际已交保费和该年度保证现金价值。非保证分红不得混入。
- 身故保险金是或有给付，只比较金额和身故杠杆，不称为投资 IRR。
- 没有正式红利通知或演示表时，保证红利为 0，实际红利为未知。累计增额红利换算系数不等于已分配红利。
- 单位与声明口径不一致时默认阻断。只有原表复核后填写 `unit_override_reason` 才能生成带“暂定”标识的结果；暂定结果不参加排名。
- 不设置固定等级阈值，不合成主观总分。只在同类、同条件产品间逐项相对排名。
- 只有一只产品在声明的全部主要指标上均领先，且所有产品资料完整时，才可写“综合领先”；否则必须说明收益、流动性和保障之间的取舍。

## 输出要求

同时交付：

- `comparison.md`：结论、统一假设、证据与单位审计、现金价值和回收率、保证退保 IRR、身故保险金和杠杆、红利口径、缺失数据与风险提示。
- `comparison.json`：输入快照、来源、基本保额推导、逐年计算轨迹、身故公式取大分支、排名和全部警告。

正式回复必须引用具体表页和行列，展示关键换算公式，并注明结果是保证、非保证、实际还是暂定。输出只用于核算复核，不替代保险公司正式投保计划书或投保建议。

## 自检与案例

运行：

```bash
python scripts/insurance_compare.py self-test
```

`assets/fixtures/` 只包含脱敏结构化案例，不包含客户原始 PDF。WWA 和 RIC 是正向回归案例；PWD 专门验证单位冲突必须被阻断。

## 跨设备与跨模型

复制或解压完整的 `compare-insurance-products` 目录，不要只复制 `SKILL.md`：

- 支持 Skill 目录的模型：把整个目录放入该模型的 Skills 路径后重新加载。
- 不原生支持 Skill 的模型：把 `SKILL.md` 作为系统指令或长期上下文，并允许模型读取同目录的 `references/`、`scripts/` 和 `assets/fixtures/`。
- 计算器只依赖 Python 3.9+ 标准库。迁移后先运行 `python scripts/insurance_compare.py self-test`；自检失败前不要用于正式核算。
