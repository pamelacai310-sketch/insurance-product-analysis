# 输入规范（Canonical Product JSON）

只保存**不可由代码重新推导的原始事实**。IRR、回本年度、现金价值率、身故杠杆等不要作为输入。

## 最小结构

```json
{
  "schema_version": "1.0",
  "analysis_mode": "core",
  "product": {
    "name": "产品名",
    "product_type": "increasing_whole_life",
    "currency": "CNY",
    "entry_age": 40,
    "gender": "M",
    "underwriting_class": "standard",
    "payment_period_years": 5,
    "premium_frequency": "annual",
    "benefit_option": "standard"
  },
  "premium_schedule": {
    "annual_amount": 200000,
    "years": 5,
    "first_time_years": 0,
    "interval_years": 1
  },
  "policy_values": [
    {
      "year": 5,
      "guaranteed_cash_value": 930000,
      "guaranteed_death_benefit": 1100000,
      "source_ref": "benefit_table"
    }
  ],
  "partial_surrender_rule": {},
  "policy_loan_rule": {},
  "sources": {
    "benefit_table": {
      "file": "illustration.pdf",
      "page": 8,
      "section": "利益演示表"
    }
  }
}
```

## 保费：优先用紧凑结构

规则、等额、等间隔缴费优先使用 `premium_schedule`，可明显减少token：

```json
{"annual_amount":200000,"years":5,"first_time_years":0,"interval_years":1}
```

只有不规则缴费才使用：

```json
"premium_cashflows": [
  {"time_years":0,"amount":300000},
  {"time_years":1,"amount":200000}
]
```

两种形式不得同时出现。

## policy_values

必需：

- `year`
- `guaranteed_cash_value`
- `guaranteed_death_benefit`
- `source_ref`（正式分析应提供）

可选但必须与保证值分离：

- `illustrated_cash_value`
- `illustrated_death_benefit`

### core模式

最少抽取：

1. Y1起逐年，直到首次看到 `保证现金价值 >= 累计已交保费`；
2. Y5、Y10、Y20、Y30（资料存在时）；
3. 最长可用年度。

如果只抽Y1、Y5且Y5已回本，代码不会假装“Y5回本”，而会给回本区间。

### full模式

抽取全部逐年数据。仅在需要完整IRR曲线、IRR稳定年度或细粒度曲线比较时使用。

## 减保规则

推荐字段：

```json
{
  "allowed": true,
  "earliest_year": 5,
  "annual_limit_ratio": null,
  "frequency_per_year": null,
  "minimum_remaining_basic_amount": null,
  "contractual": true,
  "source_ref": "terms_reduction"
}
```

`null` 表示资料未明确，不要猜。

## 保单贷款

推荐字段：

```json
{
  "allowed": true,
  "max_cash_value_ratio": 0.8,
  "rate_rule": "合同/公司公告的原文摘要",
  "term_days": 180,
  "source_ref": "terms_loan"
}
```

## 证据指针

为节约token，重复出现的数据不要把整段原文复制到每一行。使用 `source_ref` 指向 `sources`：

```json
"sources": {
  "benefit_table": {
    "file": "xx利益演示.pdf",
    "page": 8,
    "section": "利益演示表",
    "sha256": "可选"
  }
}
```

只有发生争议或需要解释时才回查原文。
