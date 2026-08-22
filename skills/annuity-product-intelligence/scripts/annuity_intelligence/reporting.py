from __future__ import annotations

from decimal import Decimal
from typing import Any, Iterable, List, Mapping


STATUS_LABELS = {
    "available": "可用",
    "missing": "缺失",
    "not_applicable": "不适用",
    "unresolved": "待复核",
    "insufficient_cashflows": "现金流不足",
    "no_root": "无有效根",
    "partial_missing": "部分可用（结算缺失）",
    "partial_unresolved": "部分可用（结算待复核）",
}


def _metric_value(record: Mapping[str, Any]) -> Any:
    return record.get("value") if record.get("status") == "available" else None


def _money(record: Mapping[str, Any], currency: str) -> str:
    value = _metric_value(record)
    if value is None:
        status = str(record.get("status", "missing"))
        return f"— ({STATUS_LABELS.get(status, status)})"
    try:
        return f"{Decimal(str(value)):,.2f} {currency}"
    except Exception:
        return str(value)


def _percent(record: Mapping[str, Any]) -> str:
    value = _metric_value(record)
    if value is None:
        status = str(record.get("status", "missing"))
        return f"— ({STATUS_LABELS.get(status, status)})"
    try:
        return f"{Decimal(str(value)) * Decimal('100'):.3f}%"
    except Exception:
        return str(value)


def _irr(record: Mapping[str, Any]) -> str:
    value = _metric_value(record)
    if not isinstance(value, Mapping):
        status = str(record.get("status", "missing"))
        return f"— ({STATUS_LABELS.get(status, status)})"
    status = value.get("status")
    if status == "unique_root":
        return f"{Decimal(str(value['selected_rate'])) * Decimal('100'):.3f}%"
    if status == "multiple_roots":
        roots = ", ".join(
            f"{Decimal(str(root['annual_effective_rate'])) * Decimal('100'):.3f}%"
            for root in value.get("roots", [])
        )
        return f"多根：{roots}"
    return STATUS_LABELS.get(str(status), str(status))


def _number(record: Mapping[str, Any], places: int = 4) -> str:
    value = _metric_value(record)
    if value is None:
        status = str(record.get("status", "missing"))
        return f"— ({STATUS_LABELS.get(status, status)})"
    try:
        return f"{Decimal(str(value)):,.{places}f}"
    except Exception:
        return str(value)


def _boolean(record: Mapping[str, Any]) -> str:
    value = _metric_value(record)
    if value is None:
        status = str(record.get("status", "missing"))
        return f"— ({STATUS_LABELS.get(status, status)})"
    return "是" if value is True else "否"


def _evidence_label(item: Mapping[str, Any]) -> str:
    evidence_id = str(item.get("evidence_id", "unknown"))
    if item.get("page") is not None:
        location = f"第 {int(item['page'])} 页"
        if item.get("bbox"):
            coordinates = ", ".join(
                format(Decimal(str(value)), "f") for value in item["bbox"]
            )
            location += f"，bbox [{coordinates}]"
    else:
        location = f"工作表 {item.get('sheet', 'unknown')}，单元格 {item.get('cell_range', 'unknown')}"
    return f"`{evidence_id}`（{location}）"


def _citations(
    refs: Iterable[str], evidence_index: Mapping[str, Mapping[str, Any]]
) -> str:
    labels = [
        _evidence_label(evidence_index[ref])
        if ref in evidence_index
        else f"`{ref}`（外部基准快照）"
        for ref in sorted(set(str(ref) for ref in refs if ref))
    ]
    return "；".join(labels) if labels else "无可用证据定位"


def _metric_evidence_refs(value: Any) -> List[str]:
    refs: List[str] = []
    if isinstance(value, Mapping):
        provenance = value.get("provenance")
        if isinstance(provenance, Mapping):
            refs.extend(str(ref) for ref in provenance.get("evidence_refs", []))
        for child in value.values():
            refs.extend(_metric_evidence_refs(child))
    elif isinstance(value, list):
        for child in value:
            refs.extend(_metric_evidence_refs(child))
    return sorted(set(refs))


def _money_spec(spec: Mapping[str, Any], currency: str) -> str:
    try:
        return f"{Decimal(str(spec['value'])):,.2f} {currency}"
    except Exception:
        return str(spec.get("value", "—"))


def render_product_report(
    normalized: Mapping[str, Any],
    validation: Mapping[str, Any],
    metrics: Mapping[str, Any],
) -> str:
    product = normalized["product"]
    currency = product["currency"]
    evidence_index = {
        str(item["evidence_id"]): item for item in normalized.get("evidence", [])
    }
    lines = [
        f"# {product['name']} — 年金产品决策数据",
        "",
        "> 本报告只评价产品公开经济结构，不包含客户数据、适配度或投保建议。保证利益与演示/非保证利益严格分列。",
        "",
        "## 产品与审计状态",
        "",
        f"- 产品 ID：`{product['product_id']}`",
        f"- 保险公司：{product['insurer']}",
        f"- 司法辖区 / 币种：{product['jurisdiction']} / {currency}",
        f"- 文件版本 / 生效日：{product['document_version']} / {product['effective_date']}",
        f"- Schema / 工具版本：{normalized['schema_version']} / {metrics['tool_version']}",
        f"- 校验：{'通过' if validation.get('valid') else '未通过'}；配置数：{metrics['summary']['configuration_count']}",
        f"- 产品识别依据：{_citations(product.get('evidence_refs', []), evidence_index)}",
        "",
    ]
    if validation.get("warnings"):
        lines.extend(["### 审计提醒", ""])
        lines.extend(f"- {warning}" for warning in validation["warnings"])
        lines.append("")
    original_sources = [
        source for source in normalized.get("sources", []) if source.get("original_url")
    ]
    if original_sources:
        lines.extend(["### 原始公开资料", ""])
        for source in original_sources:
            lines.append(
                f"- `{source['source_id']}`：[原始文件]({source['original_url']})；"
                f"原始 SHA-256 `{source.get('original_sha256', '未记录')}`；"
                f"页码 `{source.get('original_page_range', '未记录')}`。"
            )
        lines.append("")
    metrics_by_id = {
        item["configuration_id"]: item for item in metrics["configurations"]
    }
    for config in normalized["configurations"]:
        item = metrics_by_id[config["configuration_id"]]
        dimensions = config["dimensions"]
        lines.extend(
            [
                f"## 配置 `{config['configuration_id']}`",
                "",
                f"产品表维度：投保年龄 {dimensions['published_issue_age']}；费率类别 {dimensions['rate_class']}；"
                f"交费期 {dimensions['premium_term_months']} 个月；起领年龄 {dimensions['annuity_start_age']}；"
                f"领取频率 {dimensions['annuity_frequency_per_year']} 次/年；保证选项 {dimensions['guarantee_option']}。",
                f"维度依据：{_citations(config.get('dimension_evidence_refs', []), evidence_index)}",
                "",
                "### 合同现金流结构",
                "",
                "| 类型 | 保单月/区间 | 金额或规则 | 情景基础 | 证据 |",
                "|---|---:|---:|---|---|",
            ]
        )
        for event in config.get("premium_events", []):
            lines.append(
                f"| 保费 | {event['policy_month']} | {_money_spec(event['amount'], currency)} | "
                f"{event.get('guarantee_basis', 'guaranteed')} | "
                f"{_citations(event.get('evidence_refs', []), evidence_index)} |"
            )
        for rule in config.get("annuity_rules", []):
            end = (
                f"至 {rule['last_payment_month']} 月"
                if rule.get("last_payment_month") is not None
                else f"共 {rule['payment_count']} 次"
                if rule.get("payment_count") is not None
                else f"终身扩展至 {rule.get('contract_end_age')} 岁"
            )
            lines.append(
                f"| 年金 | {rule['first_payment_month']} 月起、每 {rule['frequency_months']} 月，{end} | "
                f"首期 {_money_spec(rule['amount'], currency)}；年递增 {Decimal(str(rule.get('annual_growth_rate', 0))) * Decimal('100'):.3f}% | "
                f"{rule.get('guarantee_basis')} / `{rule.get('scenario_id')}` | "
                f"{_citations(rule.get('evidence_refs', []), evidence_index)} |"
            )
        loan = config.get("loan_terms") or {}
        if loan:
            availability = "不可用"
            limit_label = "—"
            if loan.get("limit_ratio") is not None:
                limit_label = (
                    f"{Decimal(str(loan['limit_ratio'])) * Decimal('100'):.2f}%"
                )
            if loan.get("available") is True:
                start = loan.get("availability_start_month", 0)
                end = loan.get("availability_end_month")
                availability = f"保单月 {start} 起" + (
                    "至合同终止" if end is None else f"至 {end}（含）"
                )
            lines.extend(
                [
                    "",
                    "### 保单贷款条款",
                    "",
                    "| 字段 | 合同口径 |",
                    "|---|---|",
                    f"| 可用期间 | {availability} |",
                    f"| 额度上限 | {limit_label}；基数 `{loan.get('eligible_value', '未披露')}` |",
                    f"| 单次最长期限 | {loan.get('maximum_term_months', '未披露')} 个月 |",
                    f"| 利率 | 状态 `{loan.get('interest_rate_status', 'missing')}`；{loan.get('interest_rate_basis', '未披露')} |",
                    f"| 重定价频率 | {loan.get('interest_rate_reset_frequency_months', '未披露')} 个月 |",
                    f"| 还款方式 | {loan.get('repayment_terms', '未披露')} |",
                    f"| 对保险金影响 | {'扣减未偿贷款本息' if loan.get('benefit_deduction') is True else loan.get('annuity_effect', '未披露')} |",
                    f"| 失效触发 | {loan.get('lapse_trigger', '未披露')} |",
                    f"| 证据 | {_citations(loan.get('evidence_refs', []), evidence_index)} |",
                    "",
                ]
            )
        lines.extend(
            [
                "",
                "### 资本效率",
                "",
                "| 指标 | 结果 |",
                "|---|---:|",
                f"| 首次领取保单月 | {_metric_value(item['capital_efficiency']['first_income_month']) or '—'} |",
                f"| 首12个月保证领取 | {_money(item['capital_efficiency']['first_12_month_income'], currency)} |",
                f"| 保证收入转换率 | {_percent(item['capital_efficiency']['income_conversion_rate'])} |",
                f"| 仅靠保证年金累计回本月 | {_metric_value(item['capital_efficiency']['income_only_break_even_month']) or '—'} |",
                f"| 每1元首年收入所需资本 | {_number(item['capital_efficiency']['capital_per_unit_first_income'])} |",
                "",
                f"依据：{_citations(_metric_evidence_refs(item['capital_efficiency']), evidence_index)}",
                "",
            ]
        )
        for scenario_id, scenario in item["scenarios"].items():
            basis_label = (
                "保证" if scenario_id == "guaranteed" else f"演示情景 `{scenario_id}`"
            )
            annual = scenario["annual_decision_table"]
            lines.extend(
                [
                    f"### {basis_label}：完整逐年决策数据",
                    "",
                    "| 保单年 | 累计保费 | 当年保证领取 | 累计保证领取 | 满期金 | 年末现金价值 | CV IRR | 身故结算 | 身故总权益倍数 | 可贷款额 |",
                    "|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
                ]
            )
            for row in annual["rows"]:
                lines.append(
                    f"| {row['policy_year']} | {_money(row['cumulative_premium'], currency)} | "
                    f"{_money(row['annual_guaranteed_annuity'], currency)} | "
                    f"{_money(row['cumulative_guaranteed_annuity'], currency)} | "
                    f"{_money(row['annual_maturity_benefit'], currency)} | "
                    f"{_money(row['cash_value'], currency)} | {_irr(row['cash_value_only_irr'])} | "
                    f"{_money(row['death_settlement'], currency)} | "
                    f"{_number(row['death_wealth_multiple'])} | "
                    f"{_money(row['maximum_policy_loan'], currency)} |"
                )
            lines.extend(
                [
                    "",
                    f"逐年现金价值覆盖完整：{'是' if annual['complete_annual_cash_value_coverage'] else '否'}；"
                    "身故总权益倍数包括身故前已领取、身故结算及保证期剩余领取，并以总计划保费为分母。",
                    "",
                ]
            )
            lines.extend([f"### {basis_label}：流动性与退保", ""])
            curve = scenario["liquidity"]["curve"]
            if curve:
                lines.extend(
                    [
                        "| 保单年/月 | 时点 | 现金价值 | CV/累计保费 | 流动性惩罚 | 锁定比例 | 现金价值IRR | 含既往领取退出IRR | 可贷款额 |",
                        "|---:|---|---:|---:|---:|---:|---:|---:|---:|",
                    ]
                )
                for row in curve:
                    lines.append(
                        f"| {row.get('policy_year', '—')} / {row['policy_month']} | {row.get('timing') or '—'} | "
                        f"{_money(row['cash_value'], currency)} | {_percent(row['cash_value_ratio'])} | "
                        f"{_percent(row['liquidity_penalty'])} | {_percent(row['lock_ratio'])} | "
                        f"{_irr(row['cash_value_only_irr'])} | {_irr(row['total_exit_irr'])} | "
                        f"{_money(row.get('maximum_policy_loan', {}), currency)} |"
                    )
            else:
                lines.append("没有可计算的现金价值点。")
            lines.extend(
                [
                    "",
                    f"- 现金价值回本月：{_metric_value(scenario['liquidity']['cash_value_recovery_month']) or '缺失/未达到'}",
                    f"- 现金价值回本年：{_metric_value(scenario['liquidity']['capital_recovery_year']) or '缺失/未达到'}",
                    f"- 资本锁定年数：{_metric_value(scenario['liquidity']['locked_capital_years']) if _metric_value(scenario['liquidity']['locked_capital_years']) is not None else '缺失'}",
                    f"- 含既往领取的总利益回本月：{_metric_value(scenario['liquidity']['total_benefit_recovery_month']) or '缺失/未达到'}",
                    f"- 依据：{_citations(_metric_evidence_refs(scenario['liquidity']), evidence_index)}",
                    "",
                    f"### {basis_label}：长寿与生存 IRR",
                    "",
                    "| 生存年龄 | 当年保证收入 | 累计年金 | 领取倍数 | 10年长寿杠杆 | 仅领取IRR | 含剩余现金价值IRR |",
                    "|---:|---:|---:|---:|---:|---:|---:|",
                ]
            )
            survival_curve = scenario["survival_longevity_inflation_relative_value"][
                "curve"
            ]
            for row in survival_curve:
                lines.append(
                    f"| {row['target_age']} | {_money(row['annualized_income_at_age'], currency)} | "
                    f"{_money(row['cumulative_annuity'], currency)} | {_number(row['payout_multiple'])} | "
                    f"{_percent(row['longevity_leverage_10y'])} | {_irr(row['income_only_irr'])} | "
                    f"{_irr(row['survival_liquidation_irr'])} |"
                )
            lines.extend(
                [
                    "",
                    f"依据：{_citations(_metric_evidence_refs(survival_curve), evidence_index)}",
                    "",
                    f"### {basis_label}：通胀压力情景",
                    "",
                    "| 生存年龄 | 假设通胀率 | 实际累计年金 | 当年实际年化领取 | 购买力保留率 | 实际领取倍数 | 实际仅领取IRR |",
                    "|---:|---:|---:|---:|---:|---:|---:|",
                ]
            )
            inflation_row_count = 0
            for row in survival_curve:
                for inflation in row.get("inflation_scenarios", []):
                    inflation_row_count += 1
                    lines.append(
                        f"| {row['target_age']} | {Decimal(str(inflation['inflation_rate'])) * Decimal('100'):.2f}% | "
                        f"{_money(inflation['real_cumulative_annuity'], currency)} | "
                        f"{_money(inflation['real_annualized_income_at_age'], currency)} | "
                        f"{_percent(inflation['real_income_retention'])} | "
                        f"{_number(inflation['real_payout_multiple'])} | "
                        f"{_irr(inflation['real_income_only_irr'])} |"
                    )
            if not inflation_row_count:
                lines.append("| — | — | — | — | — | — | — |")
            lines.extend(
                [
                    "",
                    "以上均为固定通胀假设下的实际购买力压力情景，不是预测。",
                    "",
                    f"### {basis_label}：无风险基准相对价值",
                    "",
                    "| 生存年龄 | 选用期限/利率 | 利益PV/保费PV | 条件生存NPV | 唯一IRR利差 |",
                    "|---:|---:|---:|---:|---:|",
                ]
            )
            relative_row_count = 0
            tie_break_used = False
            for row in survival_curve:
                relative = row.get("relative_value")
                if not isinstance(relative, Mapping) or relative.get("status") == "missing":
                    continue
                benchmark = relative.get("benchmark", {})
                relative_row_count += 1
                tie_break_used = (
                    tie_break_used
                    or benchmark.get("selection_tie_break") == "lower_tenor"
                )
                lines.append(
                    f"| {row['target_age']} | {benchmark.get('selected_term_years', '—')} 年 / "
                    f"{Decimal(str(benchmark.get('annual_effective_rate', 0))) * Decimal('100'):.3f}% | "
                    f"{_number(relative['benefit_pv_to_premium_pv'])} | "
                    f"{_money(relative['conditional_survival_npv'], currency)} | "
                    f"{_percent(relative['unique_irr_spread'])} |"
                )
            if not relative_row_count:
                lines.append("| — | 未提供版本化基准 | — | — | — |")
            if tie_break_used:
                lines.extend(["", "等距期限并列时使用较短的已披露期限；不做插值。"])
            lines.extend(["", f"### {basis_label}：早逝合同结果", ""])
            death_curve = scenario["early_death"]["curve"]
            if death_curve:
                lines.extend(
                    [
                        "| 情景 | 身故年龄 | 已交保费 | 身故前已领取 | 身故结算 | 受益人后续领取 | 总保费财富倍数 | 名义回收率 | 条件身故结果IRR |",
                        "|---|---:|---:|---:|---:|---:|---:|---:|---:|",
                    ]
                )
                for row in death_curve:
                    if row.get("status") != "available":
                        status = STATUS_LABELS.get(
                            str(row.get("status")), str(row.get("status"))
                        )
                        lines.append(
                            f"| {row.get('scenario_label', '—')} | {row['target_age']} | {_money(row.get('cumulative_premium_paid', {}), currency)} | "
                            f"{_money(row.get('prior_contract_receipts', {}), currency)} | "
                            f"{_money(row.get('death_settlement', {}), currency)} ({status}) | "
                            f"{_money(row.get('beneficiary_continuation', {}), currency)} | — | — | — |"
                        )
                        continue
                    lines.append(
                        f"| {row.get('scenario_label', '—')} | {row['target_age']} | {_money(row['cumulative_premium_paid'], currency)} | "
                        f"{_money(row['prior_contract_receipts'], currency)} | {_money(row['death_settlement'], currency)} | "
                        f"{_money(row['beneficiary_continuation'], currency)} | {_number(row['death_wealth_multiple'])} | "
                        f"{_percent(row['nominal_recovery_ratio'])} | {_irr(row['conditional_death_outcome_irr'])} |"
                    )
            else:
                lines.append("未提供可计算的身故责任。")
            lines.extend(
                [
                    "",
                    f"依据：{_citations(_metric_evidence_refs(death_curve), evidence_index)}",
                    "",
                ]
            )
    lines.extend(["## 证据定位索引", ""])
    for evidence_id in sorted(evidence_index):
        evidence = evidence_index[evidence_id]
        lines.append(
            f"- {_evidence_label(evidence)}；来源 `{evidence.get('source_id')}`；"
            f"状态 `{evidence.get('status')}`；置信度 {evidence.get('confidence')}。"
        )
    lines.extend(
        [
            "",
            "## 解释边界",
            "",
            "- 身故结果是条件情景，不是必然投资回报；保单贷款是债务，不计入收益现金流。",
            "- 未提供生命表时，不计算死亡概率加权 EPV 或所谓精算价值。",
            "- 未提供版本化市场基准时，相对价值保持缺失；工具不会静默联网补数。",
            "- 通胀情景是假设，不是预测；缺失、不适用和零在数据中保持不同状态。",
            "- 结果用于产品核算复核，不构成保险、法律、税务或投资建议。",
            "",
        ]
    )
    return "\n".join(lines)


def render_comparison_report(comparison: Mapping[str, Any]) -> str:
    lines = [
        "# 年金产品共同配置空间比较",
        "",
        "> 只比较产品共同支持且口径兼容的公开配置；不使用客户数据，不生成主观综合分。",
        "",
        f"产品：{', '.join(comparison['product_ids'])}",
        f"共同配置数：{comparison['common_configuration_count']}",
        "",
    ]
    for index, slice_record in enumerate(comparison["comparison_slices"], start=1):
        lines.extend(
            [f"## 共同配置 {index}", "", f"`{slice_record['dimensions']}`", ""]
        )
        if not slice_record["compatible"]:
            lines.extend(["该配置因总保费不同且未证明线性可缩放而退出排名。", ""])
            continue
        lines.extend([f"标准化方式：`{slice_record['normalization']}`", ""])
        for age_group in slice_record["survival_age_comparisons"]:
            lines.extend(
                [
                    f"### 生存至 {age_group['target_age']} 岁",
                    "",
                    "| 产品 | 累计年金 | 领取倍数 | 唯一含残值IRR |",
                    "|---|---:|---:|---:|",
                ]
            )
            for row in age_group["rows"]:
                lines.append(
                    f"| {row['product_id']} | {row['cumulative_annuity'] or '—'} | "
                    f"{row['payout_multiple'] or '—'} | {row['unique_survival_liquidation_irr'] or '—'} |"
                )
            lines.append("")
    lines.extend(
        [
            "## 边界",
            "",
            "各指标按明确方向独立排名。IRR 多根、资料缺失、币种/时点不兼容或线性缩放未经证明时不排名。",
            "",
        ]
    )
    return "\n".join(lines)
