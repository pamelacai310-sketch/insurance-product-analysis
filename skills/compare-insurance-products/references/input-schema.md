# 输入规范

## 顶层结构

输入为 UTF-8 JSON：

```json
{
  "schema_version": "1.0",
  "comparison": {
    "currency": "CNY",
    "entry_age": 30,
    "gender": "M",
    "underwriting_class": "混合标准体",
    "payment_period_years": 10,
    "annual_premium": 103980,
    "selected_policy_years": [1, 5, 10],
    "primary_policy_year": 10,
    "product_category": "whole_life",
    "death_scenario": "ordinary_death",
    "primary_metrics": ["cash_value", "surrender_irr", "death_benefit"]
  },
  "products": []
}
```

`gender`、`underwriting_class` 和产品方案名称按原表填写。多只产品必须使用同一 `comparison` 条件。产品有任何不同条件时放进另一份输入文件，不能靠脚本“公平化”。

## 产品结构

```json
{
  "name": "示例终身寿险",
  "code": "EXAMPLE",
  "category": "whole_life",
  "source_refs": [
    {
      "id": "rate",
      "kind": "premium_rate_table",
      "title": "保险费率表",
      "location": "/absolute/path/rates.pdf",
      "sha256": "64位十六进制哈希",
      "page": 3,
      "row_label": "男性30周岁、10年交",
      "column_label": "混合标准体",
      "unit_text": "每1000元基本保险金额的年交保险费",
      "version": "2025"
    }
  ],
  "rate": {
    "basis": "premium_per_1000_base",
    "value": 51.99,
    "unit_text": "每1000元基本保险金额的年交保险费",
    "source_ref": "rate"
  },
  "cash_value": {
    "basis": "per_1000_base",
    "unit_text": "每1000元基本保险金额的现金价值",
    "source_ref": "cash",
    "values": {"10": 491.41}
  }
}
```

来源的 `sha256` 在正式分析中必填。脱敏 fixture 可省略，但会产生证据警告。`rate`、`cash_value` 和条款公式必须通过 `source_ref` 指向 `source_refs.id`。

同一产品所有非空 `version` 必须一致。费率表、现金价值表或条款版本不同会阻断计算。

## 费率口径

`rate.basis` 只能取：

| 值 | 原表含义 | 基本保额公式 |
|---|---|---|
| `premium_per_1000_base` | 每千元基本保额对应年交保费 | `年交保费 / 费率 × 1000` |
| `base_per_1000_premium` | 每千元年交保费对应基本保额 | `年交保费 / 1000 × 费率` |
| `absolute_base_amount` | 原表或计划书直接给出基本保额 | `rate.value` |

必须把表头原文写入 `unit_text`。若表头与 `basis` 冲突，复核后可在同一对象添加 `unit_override_reason`；该产品会被标为暂定并退出排名。

## 现金价值口径

`cash_value.basis` 只能取：

| 值 | 现金价值公式 |
|---|---|
| `per_1000_base` | `基本保额 / 1000 × 表值` |
| `per_1000_annual_premium` | `年交保费 / 1000 × 表值` |
| `absolute` | 表值即金额 |

`values` 的键是保单年度字符串，值为该年度表值。未提供的年度会标记为缺失，不插值。

## 身故责任公式

`death_benefit.phases` 按互不重叠的阶段定义：

```json
{
  "age_at_policy_year_end": "entry_age_plus_year_minus_one",
  "source_ref": "terms",
  "phases": [
    {
      "name": "交费期满后",
      "when": {"payment_status": "completed"},
      "expression": {
        "op": "max",
        "args": [
          {"op": "mul", "args": [
            {"op": "field", "name": "paid_premium"},
            {"op": "age_band", "bands": [
              {"max": 40, "value": 1.6},
              {"min": 41, "max": 60, "value": 1.4},
              {"min": 61, "value": 1.2}
            ]}
          ]},
          {"op": "mul", "args": [
            {"op": "field", "name": "base_amount"},
            {"op": "const", "value": 1.5}
          ]},
          {"op": "field", "name": "cash_value"}
        ]
      }
    }
  ]
}
```

`when` 支持 `payment_status`（`during`、`completed`、`any`）、`policy_year_min/max`、`attained_age_min/max`。阶段重叠或所选年度没有匹配阶段均为错误。

允许的表达式操作符：`const`、`field`、`add`、`sub`、`mul`、`max`、`min`、`pow`、`age_band`。允许字段：

- `annual_premium`
- `paid_premium`
- `total_premium`
- `base_amount`
- `cash_value`
- `policy_year`
- `attained_age`
- `effective_base_amount`
- `dividend_cash_value`
- `cumulative_paid_up_amount`

附加意外责任放入 `additive_benefits`，并用 `when.scenario` 声明。脚本只有在 `comparison.death_scenario` 完全匹配时才加入。

## 红利

```json
{
  "dividend": {
    "guaranteed_schedule": {"1": 0, "2": 0},
    "actual_schedule": null,
    "illustrated_scenarios": {}
  }
}
```

`actual_schedule: null` 表示未知，不是 0。演示红利放在 `illustrated_scenarios`，不得写入保证现金价值或保证退保 IRR。
