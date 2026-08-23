#!/usr/bin/env python3
"""Deterministic same-scenario comparison for insurance product values."""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import math
import re
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple


SCHEMA_VERSION = "1.0"
RATE_BASES = {
    "premium_per_1000_base",
    "base_per_1000_premium",
    "absolute_base_amount",
}
CASH_BASES = {"per_1000_base", "per_1000_annual_premium", "absolute"}
EXPRESSION_OPS = {"const", "field", "add", "sub", "mul", "max", "min", "pow", "age_band"}
EXPRESSION_FIELDS = {
    "annual_premium",
    "paid_premium",
    "total_premium",
    "base_amount",
    "cash_value",
    "policy_year",
    "attained_age",
    "effective_base_amount",
    "dividend_cash_value",
    "cumulative_paid_up_amount",
}
SCENARIO_FIELDS = (
    "currency",
    "entry_age",
    "gender",
    "underwriting_class",
    "payment_period_years",
    "annual_premium",
    "benefit_option",
    "coverage_option",
    "annuity_start_age",
    "annuity_frequency",
    "death_scenario",
)
METRIC_FIELDS = {
    "cash_value": "cash_value",
    "recovery_ratio": "recovery_ratio",
    "surrender_irr": "surrender_irr",
    "death_benefit": "death_benefit",
    "death_leverage": "death_leverage",
    "guaranteed_benefit": "guaranteed_benefit",
    "cumulative_guaranteed_benefit": "cumulative_guaranteed_benefit",
    "guaranteed_benefit_recovery_ratio": "guaranteed_benefit_recovery_ratio",
    "guaranteed_income_irr": "guaranteed_income_irr",
}
OPTION_TYPES = {
    "policy_loan",
    "partial_surrender",
    "paid_up",
    "annuity_conversion",
    "beneficiary_change",
    "policyholder_change",
    "insured_change",
    "second_policyholder",
    "other",
}


class ValidationError(Exception):
    def __init__(self, errors: Sequence[str], warnings: Optional[Sequence[str]] = None):
        self.errors = list(errors)
        self.warnings = list(warnings or [])
        super().__init__("; ".join(self.errors))


class CalculationError(Exception):
    pass


def load_json(path: Path) -> Dict[str, Any]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValidationError([f"无法读取 JSON：{exc}"]) from exc
    if not isinstance(data, dict):
        raise ValidationError(["输入顶层必须是 JSON 对象"])
    return data


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _is_number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(float(value))


def _money(value: float) -> float:
    return round(float(value) + 1e-10, 2)


def _ratio(value: float) -> float:
    return round(float(value), 10)


def _plain_number(value: float) -> str:
    return f"{float(value):.10f}".rstrip("0").rstrip(".")


def _normalize_unit(text: str) -> str:
    return re.sub(r"[\s,，。.:：()（）/\-]", "", str(text).lower()).replace("一千", "1000").replace("千元", "1000元")


def _unit_matches(basis: str, unit_text: str, component: str) -> bool:
    if basis in {"absolute_base_amount", "absolute"}:
        return True
    text = _normalize_unit(unit_text)
    has_thousand = "每1000" in text or "1000元" in text
    base_tokens = ("基本保险金额", "基本保额")
    premium_tokens = ("年交保险费", "年缴保险费", "年交保费", "年缴保费", "保险费", "保费")
    base_positions = [text.find(token) for token in base_tokens if token in text]
    premium_positions = [text.find(token) for token in premium_tokens if token in text]
    base_pos = min(base_positions) if base_positions else -1
    premium_pos = min(premium_positions) if premium_positions else -1
    if not has_thousand:
        return False
    if component == "rate":
        if base_pos < 0 or premium_pos < 0:
            return False
        if basis == "premium_per_1000_base":
            return base_pos < premium_pos
        return premium_pos < base_pos
    if basis == "per_1000_base":
        return base_pos >= 0 and premium_pos < 0
    return premium_pos >= 0 and base_pos < 0


def _validate_expression(expr: Any, path: str, errors: List[str]) -> None:
    if _is_number(expr):
        return
    if not isinstance(expr, dict):
        errors.append(f"{path} 必须是数字或公式对象")
        return
    op = expr.get("op")
    if op not in EXPRESSION_OPS:
        errors.append(f"{path}.op 不受支持：{op!r}")
        return
    if op == "const":
        if not _is_number(expr.get("value")):
            errors.append(f"{path}.value 必须是有限数字")
        return
    if op == "field":
        if expr.get("name") not in EXPRESSION_FIELDS:
            errors.append(f"{path}.name 不受支持：{expr.get('name')!r}")
        return
    if op == "age_band":
        bands = expr.get("bands")
        if not isinstance(bands, list) or not bands:
            errors.append(f"{path}.bands 必须是非空数组")
            return
        for index, band in enumerate(bands):
            band_path = f"{path}.bands[{index}]"
            if not isinstance(band, dict) or not _is_number(band.get("value")):
                errors.append(f"{band_path} 必须包含数值 value")
                continue
            if "min" in band and not _is_number(band["min"]):
                errors.append(f"{band_path}.min 必须是数字")
            if "max" in band and not _is_number(band["max"]):
                errors.append(f"{band_path}.max 必须是数字")
            if "min" in band and "max" in band and band["min"] > band["max"]:
                errors.append(f"{band_path} 的 min 不得大于 max")
        for left in range(len(bands)):
            if not isinstance(bands[left], dict):
                continue
            left_low = float(bands[left]["min"]) if _is_number(bands[left].get("min")) else -math.inf
            left_high = float(bands[left]["max"]) if _is_number(bands[left].get("max")) else math.inf
            for right in range(left + 1, len(bands)):
                if not isinstance(bands[right], dict):
                    continue
                right_low = float(bands[right]["min"]) if _is_number(bands[right].get("min")) else -math.inf
                right_high = float(bands[right]["max"]) if _is_number(bands[right].get("max")) else math.inf
                if max(left_low, right_low) <= min(left_high, right_high):
                    errors.append(f"{path}.bands[{left}] 与 bands[{right}] 年龄范围重叠")
        return
    args = expr.get("args")
    if not isinstance(args, list):
        errors.append(f"{path}.args 必须是数组")
        return
    required = 2 if op in {"sub", "pow"} else 1
    if len(args) < required or (op in {"sub", "pow"} and len(args) != 2):
        errors.append(f"{path}.args 数量不符合 {op} 要求")
    for index, arg in enumerate(args):
        _validate_expression(arg, f"{path}.args[{index}]", errors)


def _condition_interval(condition: Dict[str, Any], minimum: str, maximum: str) -> Tuple[float, float]:
    low_value = condition.get(minimum)
    high_value = condition.get(maximum)
    low = float(low_value) if _is_number(low_value) else -math.inf
    high = float(high_value) if _is_number(high_value) else math.inf
    return low, high


def _conditions_overlap(left: Dict[str, Any], right: Dict[str, Any]) -> bool:
    left_status = left.get("payment_status", "any")
    right_status = right.get("payment_status", "any")
    status_overlap = left_status == "any" or right_status == "any" or left_status == right_status
    if not status_overlap:
        return False
    for minimum, maximum in (("policy_year_min", "policy_year_max"), ("attained_age_min", "attained_age_max")):
        left_low, left_high = _condition_interval(left, minimum, maximum)
        right_low, right_high = _condition_interval(right, minimum, maximum)
        if max(left_low, right_low) > min(left_high, right_high):
            return False
    return True


def _attained_age(entry_age: int, policy_year: int, convention: str) -> int:
    if convention == "entry_age_plus_year_minus_one":
        return entry_age + policy_year - 1
    if convention == "entry_age_plus_year":
        return entry_age + policy_year
    raise CalculationError(f"不支持的到达年龄口径：{convention}")


def _condition_matches(condition: Dict[str, Any], context: Dict[str, float], payment_period: int) -> bool:
    year = int(context["policy_year"])
    status = "during" if year < payment_period else "completed"
    required_status = condition.get("payment_status", "any")
    if required_status not in {"any", status}:
        return False
    checks = (
        ("policy_year_min", year, lambda value, boundary: value >= boundary),
        ("policy_year_max", year, lambda value, boundary: value <= boundary),
        ("attained_age_min", context["attained_age"], lambda value, boundary: value >= boundary),
        ("attained_age_max", context["attained_age"], lambda value, boundary: value <= boundary),
    )
    return all(
        key not in condition or (_is_number(condition[key]) and test(value, float(condition[key])))
        for key, value, test in checks
    )


def _product_scenario(comparison: Dict[str, Any], product: Dict[str, Any]) -> Dict[str, Any]:
    scenario = {field: comparison.get(field) for field in SCENARIO_FIELDS}
    overrides = product.get("scenario_overrides", {})
    if isinstance(overrides, dict):
        for field in SCENARIO_FIELDS:
            if field in overrides:
                scenario[field] = overrides[field]
    scenario["category"] = product.get("category")
    return scenario


def _scenario_key(scenario: Dict[str, Any]) -> str:
    return json.dumps(scenario, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _validate_nonnegative_schedule(
    schedule: Any,
    path: str,
    errors: List[str],
) -> Dict[str, Any]:
    if not isinstance(schedule, dict):
        errors.append(f"{path} 必须是对象")
        return {}
    for year_text, value in schedule.items():
        if not str(year_text).isdigit() or int(year_text) <= 0 or not _is_number(value) or value < 0:
            errors.append(f"{path}[{year_text!r}] 必须是非负数且年度为正整数")
    return schedule


def validate_case(data: Dict[str, Any]) -> Dict[str, Any]:
    errors: List[str] = []
    warnings: List[str] = []
    provisional: Dict[str, List[str]] = {}

    if data.get("schema_version") != SCHEMA_VERSION:
        errors.append(f"schema_version 必须为 {SCHEMA_VERSION}")
    comparison = data.get("comparison")
    if not isinstance(comparison, dict):
        errors.append("comparison 必须是对象")
        comparison = {}
    for key in ("currency", "entry_age", "gender", "underwriting_class", "payment_period_years", "annual_premium", "selected_policy_years", "product_category"):
        if key not in comparison:
            errors.append(f"comparison 缺少 {key}")
    if not isinstance(comparison.get("entry_age"), int) or comparison.get("entry_age", -1) < 0:
        errors.append("comparison.entry_age 必须是非负整数")
    if not isinstance(comparison.get("payment_period_years"), int) or comparison.get("payment_period_years", 0) <= 0:
        errors.append("comparison.payment_period_years 必须是正整数")
    if not _is_number(comparison.get("annual_premium")) or comparison.get("annual_premium", 0) <= 0:
        errors.append("comparison.annual_premium 必须是正数")
    years = comparison.get("selected_policy_years")
    if not isinstance(years, list) or not years or any(not isinstance(year, int) or year <= 0 for year in years):
        errors.append("comparison.selected_policy_years 必须是非空正整数数组")
        years = []
    elif len(set(years)) != len(years):
        errors.append("comparison.selected_policy_years 不得重复")
    primary_year = comparison.get("primary_policy_year", max(years) if years else None)
    if primary_year not in years:
        errors.append("comparison.primary_policy_year 必须包含在 selected_policy_years 中")
    primary_metrics = comparison.get("primary_metrics", ["cash_value", "surrender_irr", "death_benefit"])
    if not isinstance(primary_metrics, list) or not primary_metrics or any(metric not in METRIC_FIELDS for metric in primary_metrics):
        errors.append(f"comparison.primary_metrics 只能使用：{', '.join(sorted(METRIC_FIELDS))}")
    longevity_test_age = comparison.get("longevity_test_age")
    if longevity_test_age is not None and (
        not isinstance(longevity_test_age, int) or longevity_test_age <= 0
    ):
        errors.append("comparison.longevity_test_age 必须是正整数或省略")

    products = data.get("products")
    if not isinstance(products, list) or not products:
        errors.append("products 必须是非空数组")
        products = []
    product_keys: set = set()
    for index, product in enumerate(products):
        path = f"products[{index}]"
        if not isinstance(product, dict):
            errors.append(f"{path} 必须是对象")
            continue
        name = product.get("name")
        code = str(product.get("code") or name or index)
        if not isinstance(name, str) or not name.strip():
            errors.append(f"{path}.name 必须是非空字符串")
        key = (str(name), code)
        if key in product_keys:
            errors.append(f"{path} 产品名称和代码重复")
        product_keys.add(key)
        if not product.get("category"):
            errors.append(f"{path}.category 必填")
        elif comparison.get("product_category") and product.get("category") != comparison.get("product_category"):
            warnings.append(f"{name}：产品类别与 comparison.product_category 不同，将退出同组排名")

        overrides = product.get("scenario_overrides", {})
        if not isinstance(overrides, dict):
            errors.append(f"{path}.scenario_overrides 必须是对象")
            overrides = {}
        scenario = _product_scenario(comparison, {**product, "scenario_overrides": overrides})
        if overrides:
            changed = [field for field in SCENARIO_FIELDS if field in overrides and overrides[field] != comparison.get(field)]
            if changed:
                warnings.append(f"{name}：覆盖了投保条件 {', '.join(changed)}，只与完全相同条件的产品排名")
        if not isinstance(scenario.get("entry_age"), int) or scenario.get("entry_age", -1) < 0:
            errors.append(f"{path} 的投保年龄必须是非负整数")
        if not isinstance(scenario.get("payment_period_years"), int) or scenario.get("payment_period_years", 0) <= 0:
            errors.append(f"{path} 的交费期间必须是正整数")
        if not _is_number(scenario.get("annual_premium")) or scenario.get("annual_premium", 0) <= 0:
            errors.append(f"{path} 的年交保费必须是正数")

        refs = product.get("source_refs")
        if not isinstance(refs, list) or not refs:
            errors.append(f"{path}.source_refs 必须是非空数组")
            refs = []
        ref_ids: set = set()
        versions: set = set()
        for ref_index, ref in enumerate(refs):
            ref_path = f"{path}.source_refs[{ref_index}]"
            if not isinstance(ref, dict) or not ref.get("id"):
                errors.append(f"{ref_path}.id 必填")
                continue
            for required_field in ("kind", "title", "location", "page", "row_label", "column_label", "unit_text"):
                if ref.get(required_field) in (None, ""):
                    errors.append(f"{ref_path}.{required_field} 必填")
            if ref["id"] in ref_ids:
                errors.append(f"{ref_path}.id 重复：{ref['id']}")
            ref_ids.add(ref["id"])
            if ref.get("version"):
                versions.add(str(ref["version"]).strip())
            digest = ref.get("sha256")
            if digest:
                if not re.fullmatch(r"[0-9a-fA-F]{64}", str(digest)):
                    errors.append(f"{ref_path}.sha256 必须是64位十六进制字符串")
                else:
                    location = Path(str(ref.get("location", ""))).expanduser()
                    if location.is_file():
                        actual_digest = _sha256(location)
                        if actual_digest.lower() != str(digest).lower():
                            errors.append(f"{ref_path}.sha256 与本地文件实际哈希不一致")
            elif ref.get("fixture") is True:
                warnings.append(f"{name}：{ref.get('id')} 是脱敏测试证据，未附原文件哈希")
            else:
                errors.append(f"{ref_path}.sha256 正式分析必填")
        if len(versions) > 1:
            errors.append(f"{name}：费率表、现金价值表或条款版本不一致：{sorted(versions)}")

        for component_name, allowed_bases in (("rate", RATE_BASES), ("cash_value", CASH_BASES)):
            component = product.get(component_name)
            if not isinstance(component, dict):
                errors.append(f"{path}.{component_name} 必须是对象")
                continue
            basis = component.get("basis")
            if basis not in allowed_bases:
                errors.append(f"{path}.{component_name}.basis 不受支持：{basis!r}")
            unit_text = component.get("unit_text")
            if not isinstance(unit_text, str) or not unit_text.strip():
                errors.append(f"{path}.{component_name}.unit_text 必填")
            elif basis in allowed_bases and not _unit_matches(basis, unit_text, "rate" if component_name == "rate" else "cash"):
                reason = component.get("unit_override_reason")
                message = f"{name}：{component_name} 声明口径 {basis} 与表头“{unit_text}”冲突"
                if isinstance(reason, str) and reason.strip():
                    provisional.setdefault(code, []).append(f"{message}；暂定覆盖原因：{reason.strip()}")
                    warnings.append(provisional[code][-1])
                else:
                    errors.append(message)
            if component.get("source_ref") not in ref_ids:
                errors.append(f"{path}.{component_name}.source_ref 未指向有效 source_refs.id")
            else:
                selected_ref = next(ref for ref in refs if isinstance(ref, dict) and ref.get("id") == component.get("source_ref"))
                ref_unit = selected_ref.get("unit_text")
                if isinstance(unit_text, str) and isinstance(ref_unit, str) and _normalize_unit(unit_text) != _normalize_unit(ref_unit):
                    errors.append(f"{path}.{component_name}.unit_text 与所引用证据的 unit_text 不一致")
        rate = product.get("rate") if isinstance(product.get("rate"), dict) else {}
        if not _is_number(rate.get("value")) or rate.get("value", 0) <= 0:
            errors.append(f"{path}.rate.value 必须是正数")
        cash = product.get("cash_value") if isinstance(product.get("cash_value"), dict) else {}
        if cash.get("value_type") != "guaranteed":
            errors.append(f"{path}.cash_value.value_type 必须明确为 guaranteed")
        values = cash.get("values")
        if not isinstance(values, dict):
            errors.append(f"{path}.cash_value.values 必须是对象")
            values = {}
        else:
            for year_text, value in values.items():
                if not str(year_text).isdigit() or int(year_text) <= 0 or not _is_number(value) or value < 0:
                    errors.append(f"{path}.cash_value.values[{year_text!r}] 必须是非负数且年度为正整数")
        for year in years:
            if str(year) not in values:
                warnings.append(f"{name}：缺少第{year}保单年度现金价值，不参与该年度相关排名")

        death = product.get("death_benefit")
        if death is not None:
            if not isinstance(death, dict):
                errors.append(f"{path}.death_benefit 必须是对象")
            else:
                if death.get("source_ref") not in ref_ids:
                    errors.append(f"{path}.death_benefit.source_ref 未指向有效 source_refs.id")
                convention = death.get("age_at_policy_year_end", "entry_age_plus_year_minus_one")
                if convention not in {"entry_age_plus_year_minus_one", "entry_age_plus_year"}:
                    errors.append(f"{path}.death_benefit.age_at_policy_year_end 不受支持")
                phases = death.get("phases")
                if not isinstance(phases, list) or not phases:
                    errors.append(f"{path}.death_benefit.phases 必须是非空数组")
                    phases = []
                conditions: List[Dict[str, Any]] = []
                for phase_index, phase in enumerate(phases):
                    phase_path = f"{path}.death_benefit.phases[{phase_index}]"
                    if not isinstance(phase, dict):
                        errors.append(f"{phase_path} 必须是对象")
                        continue
                    condition = phase.get("when", {})
                    if not isinstance(condition, dict):
                        errors.append(f"{phase_path}.when 必须是对象")
                        condition = {}
                    status = condition.get("payment_status", "any")
                    if status not in {"during", "completed", "any"}:
                        errors.append(f"{phase_path}.when.payment_status 不受支持")
                    for boundary in ("policy_year_min", "policy_year_max", "attained_age_min", "attained_age_max"):
                        if boundary in condition and not _is_number(condition[boundary]):
                            errors.append(f"{phase_path}.when.{boundary} 必须是数字")
                    conditions.append(condition)
                    _validate_expression(phase.get("expression"), f"{phase_path}.expression", errors)
                for left in range(len(conditions)):
                    for right in range(left + 1, len(conditions)):
                        if _conditions_overlap(conditions[left], conditions[right]):
                            errors.append(f"{path}.death_benefit 阶段 {left} 与 {right} 条件重叠")
                scenario_entry_age = scenario.get("entry_age")
                scenario_payment_period = scenario.get("payment_period_years")
                if (
                    convention in {"entry_age_plus_year_minus_one", "entry_age_plus_year"}
                    and isinstance(scenario_entry_age, int)
                    and scenario_entry_age >= 0
                    and isinstance(scenario_payment_period, int)
                    and scenario_payment_period > 0
                ):
                    for year in years:
                        context = {"policy_year": float(year), "attained_age": float(_attained_age(scenario_entry_age, year, convention))}
                        matches = [condition for condition in conditions if _condition_matches(condition, context, scenario_payment_period)]
                        if len(matches) != 1:
                            errors.append(f"{name}：第{year}年度必须且只能匹配一个身故责任阶段，实际为{len(matches)}个")
                additive = death.get("additive_benefits", [])
                if not isinstance(additive, list):
                    errors.append(f"{path}.death_benefit.additive_benefits 必须是数组")
                else:
                    for add_index, benefit in enumerate(additive):
                        add_path = f"{path}.death_benefit.additive_benefits[{add_index}]"
                        if not isinstance(benefit, dict) or not isinstance(benefit.get("when"), dict) or not benefit["when"].get("scenario"):
                            errors.append(f"{add_path} 必须声明 when.scenario")
                            continue
                        _validate_expression(benefit.get("expression"), f"{add_path}.expression", errors)

        dividend = product.get("dividend")
        if dividend is None:
            warnings.append(f"{name}：未提供红利数据；保证红利按0，实际红利标记为未知")
        elif not isinstance(dividend, dict):
            errors.append(f"{path}.dividend 必须是对象")
        else:
            actual = dividend.get("actual_schedule")
            if actual is not None and not isinstance(actual, dict):
                errors.append(f"{path}.dividend.actual_schedule 必须是对象或 null")
            for schedule_name in ("guaranteed_schedule", "actual_schedule"):
                schedule = dividend.get(schedule_name)
                if isinstance(schedule, dict):
                    for year_text, value in schedule.items():
                        if not str(year_text).isdigit() or not _is_number(value) or value < 0:
                            errors.append(f"{path}.dividend.{schedule_name}[{year_text!r}] 无效")

        guaranteed_benefits = product.get("guaranteed_benefits")
        if guaranteed_benefits is not None:
            if not isinstance(guaranteed_benefits, dict):
                errors.append(f"{path}.guaranteed_benefits 必须是对象")
            else:
                if guaranteed_benefits.get("source_ref") not in ref_ids:
                    errors.append(f"{path}.guaranteed_benefits.source_ref 未指向有效 source_refs.id")
                if guaranteed_benefits.get("basis") != "absolute":
                    errors.append(f"{path}.guaranteed_benefits.basis 必须为 absolute")
                unit_text = guaranteed_benefits.get("unit_text")
                if not isinstance(unit_text, str) or not unit_text.strip():
                    errors.append(f"{path}.guaranteed_benefits.unit_text 必填")
                elif guaranteed_benefits.get("source_ref") in ref_ids:
                    selected_ref = next(
                        ref
                        for ref in refs
                        if isinstance(ref, dict)
                        and ref.get("id") == guaranteed_benefits.get("source_ref")
                    )
                    ref_unit = selected_ref.get("unit_text")
                    if isinstance(ref_unit, str) and _normalize_unit(unit_text) != _normalize_unit(ref_unit):
                        errors.append(
                            f"{path}.guaranteed_benefits.unit_text 与所引用证据的 unit_text 不一致"
                        )
                _validate_nonnegative_schedule(
                    guaranteed_benefits.get("values"),
                    f"{path}.guaranteed_benefits.values",
                    errors,
                )
        elif product.get("category") == "annuity":
            warnings.append(f"{name}：未提供逐年保证领取表，年金效率和长寿尾部给付不可量化")

        longevity = product.get("longevity")
        if longevity is not None:
            if not isinstance(longevity, dict):
                errors.append(f"{path}.longevity 必须是对象")
            else:
                if longevity.get("source_ref") not in ref_ids:
                    errors.append(f"{path}.longevity.source_ref 未指向有效 source_refs.id")
                if not isinstance(longevity.get("lifetime_income"), bool):
                    errors.append(f"{path}.longevity.lifetime_income 必须是布尔值")
                start_year = longevity.get("income_start_policy_year")
                if not isinstance(start_year, int) or start_year <= 0:
                    errors.append(f"{path}.longevity.income_start_policy_year 必须是正整数")
                end_age = longevity.get("contract_end_age")
                if end_age is not None and (not isinstance(end_age, int) or end_age <= 0):
                    errors.append(f"{path}.longevity.contract_end_age 必须是正整数或 null")
                guaranteed_years = longevity.get("guaranteed_payment_years")
                if guaranteed_years is not None and (
                    not isinstance(guaranteed_years, int) or guaranteed_years < 0
                ):
                    errors.append(f"{path}.longevity.guaranteed_payment_years 必须是非负整数或 null")
                convention = longevity.get("age_at_policy_year_end", "entry_age_plus_year_minus_one")
                if convention not in {"entry_age_plus_year_minus_one", "entry_age_plus_year"}:
                    errors.append(f"{path}.longevity.age_at_policy_year_end 不受支持")

        options = product.get("contract_options", [])
        if not isinstance(options, list):
            errors.append(f"{path}.contract_options 必须是数组")
        else:
            option_keys: set = set()
            for option_index, option in enumerate(options):
                option_path = f"{path}.contract_options[{option_index}]"
                if not isinstance(option, dict):
                    errors.append(f"{option_path} 必须是对象")
                    continue
                option_type = option.get("type")
                if option_type not in OPTION_TYPES:
                    errors.append(f"{option_path}.type 不受支持：{option_type!r}")
                option_name = str(option.get("name") or option_type or option_index)
                if option_name in option_keys:
                    errors.append(f"{option_path}.name 重复：{option_name}")
                option_keys.add(option_name)
                if option.get("source_ref") not in ref_ids:
                    errors.append(f"{option_path}.source_ref 未指向有效 source_refs.id")
                if not isinstance(option.get("available"), bool):
                    errors.append(f"{option_path}.available 必须是布尔值")
                for ratio_field in ("max_access_ratio", "known_cost_rate"):
                    ratio = option.get(ratio_field)
                    if ratio is not None and (
                        not _is_number(ratio)
                        or ratio < 0
                        or (ratio_field == "max_access_ratio" and ratio > 1)
                    ):
                        errors.append(f"{option_path}.{ratio_field} 数值无效")
                scenario_value = option.get("quantified_scenario")
                if scenario_value is not None:
                    if not isinstance(scenario_value, dict):
                        errors.append(f"{option_path}.quantified_scenario 必须是对象")
                    else:
                        discount_rate = scenario_value.get("discount_rate")
                        if not _is_number(discount_rate) or discount_rate <= -1:
                            errors.append(f"{option_path}.quantified_scenario.discount_rate 必须大于-1")
                        flows = scenario_value.get("incremental_cash_flows")
                        if not isinstance(flows, dict) or not flows:
                            errors.append(f"{option_path}.quantified_scenario.incremental_cash_flows 必须是非空对象")
                        else:
                            for time_text, value in flows.items():
                                if not str(time_text).isdigit() or int(time_text) < 0 or not _is_number(value):
                                    errors.append(
                                        f"{option_path}.quantified_scenario.incremental_cash_flows[{time_text!r}] 无效"
                                    )

    if errors:
        raise ValidationError(errors, warnings)
    return {"warnings": warnings, "provisional_products": provisional}


def _calculate_base_amount(rate: Dict[str, Any], annual_premium: float) -> Tuple[float, str]:
    value = float(rate["value"])
    basis = rate["basis"]
    if basis == "premium_per_1000_base":
        amount = annual_premium / value * 1000.0
        formula = f"{_plain_number(annual_premium)} / {_plain_number(value)} × 1000"
    elif basis == "base_per_1000_premium":
        amount = annual_premium / 1000.0 * value
        formula = f"{_plain_number(annual_premium)} / 1000 × {_plain_number(value)}"
    elif basis == "absolute_base_amount":
        amount = value
        formula = f"直接基本保额 {_plain_number(value)}"
    else:
        raise CalculationError(f"不支持的费率口径：{basis}")
    return _money(amount), formula


def _calculate_cash_value(cash: Dict[str, Any], year: int, base_amount: float, annual_premium: float) -> Tuple[Optional[float], Optional[str]]:
    raw = cash.get("values", {}).get(str(year))
    if raw is None:
        return None, None
    value = float(raw)
    basis = cash["basis"]
    if basis == "per_1000_base":
        amount = base_amount / 1000.0 * value
        formula = f"{_plain_number(base_amount)} / 1000 × {_plain_number(value)}"
    elif basis == "per_1000_annual_premium":
        amount = annual_premium / 1000.0 * value
        formula = f"{_plain_number(annual_premium)} / 1000 × {_plain_number(value)}"
    elif basis == "absolute":
        amount = value
        formula = f"直接金额 {_plain_number(value)}"
    else:
        raise CalculationError(f"不支持的现金价值口径：{basis}")
    return _money(amount), formula


def _evaluate(expr: Any, context: Dict[str, float]) -> Tuple[float, Dict[str, Any]]:
    if _is_number(expr):
        value = float(expr)
        return value, {"op": "const", "value": value}
    op = expr["op"]
    if op == "const":
        value = float(expr["value"])
        return value, {"op": op, "value": value}
    if op == "field":
        name = expr["name"]
        value = context.get(name)
        if value is None:
            raise CalculationError(f"公式字段 {name} 在当前年度没有可用值")
        return float(value), {"op": op, "field": name, "value": float(value)}
    if op == "age_band":
        age = float(context["attained_age"])
        matches = [
            (index, band)
            for index, band in enumerate(expr["bands"])
            if age >= float(band.get("min", -math.inf)) and age <= float(band.get("max", math.inf))
        ]
        if len(matches) != 1:
            raise CalculationError(f"到达年龄 {age:g} 必须且只能匹配一个 age_band，实际为{len(matches)}个")
        index, band = matches[0]
        value = float(band["value"])
        return value, {"op": op, "attained_age": age, "selected_band": index, "value": value}
    evaluated = [_evaluate(arg, context) for arg in expr["args"]]
    values = [item[0] for item in evaluated]
    traces = [item[1] for item in evaluated]
    trace: Dict[str, Any] = {"op": op, "arguments": traces}
    if op == "add":
        value = sum(values)
    elif op == "sub":
        value = values[0] - values[1]
    elif op == "mul":
        value = math.prod(values)
    elif op == "pow":
        value = math.pow(values[0], values[1])
    elif op in {"max", "min"}:
        value = max(values) if op == "max" else min(values)
        selected = next(index for index, candidate in enumerate(values) if math.isclose(candidate, value, rel_tol=1e-12, abs_tol=1e-9))
        trace["selected_index"] = selected
    else:
        raise CalculationError(f"不支持的公式操作符：{op}")
    if not math.isfinite(value):
        raise CalculationError(f"公式 {op} 计算结果不是有限数字")
    trace["value"] = value
    return value, trace


def _irr(cash_flows: Sequence[float]) -> Optional[float]:
    if not cash_flows or not any(value < 0 for value in cash_flows) or not any(value > 0 for value in cash_flows):
        return None

    def npv(rate: float) -> float:
        return sum(value / math.pow(1.0 + rate, index) for index, value in enumerate(cash_flows))

    low = -0.999999
    high = 1.0
    low_value = npv(low)
    high_value = npv(high)
    while low_value * high_value > 0 and high < 1_000_000:
        high *= 2.0
        high_value = npv(high)
    if low_value * high_value > 0:
        return None
    for _ in range(240):
        middle = (low + high) / 2.0
        middle_value = npv(middle)
        if abs(middle_value) < 1e-10 or high - low < 1e-13:
            return middle
        if low_value * middle_value > 0:
            low = middle
            low_value = middle_value
        else:
            high = middle
    return (low + high) / 2.0


def _surrender_irr(annual_premium: float, payment_period: int, year: int, cash_value: Optional[float]) -> Tuple[Optional[float], List[float]]:
    if cash_value is None:
        return None, []
    cash_flows = [0.0 for _ in range(year + 1)]
    for time in range(min(payment_period, year)):
        cash_flows[time] -= annual_premium
    cash_flows[year] += cash_value
    result = _irr(cash_flows)
    return (None if result is None else _ratio(result)), [_money(value) for value in cash_flows]


def _guaranteed_income_cash_flows(
    annual_premium: float,
    payment_period: int,
    horizon: int,
    benefit_schedule: Dict[str, Any],
) -> List[float]:
    cash_flows = [0.0 for _ in range(horizon + 1)]
    for time in range(min(payment_period, horizon)):
        cash_flows[time] -= annual_premium
    for year_text, value in benefit_schedule.items():
        year = int(year_text)
        if 0 < year <= horizon:
            cash_flows[year] += float(value)
    return [_money(value) for value in cash_flows]


def _income_breakeven_year(
    annual_premium: float,
    payment_period: int,
    benefit_schedule: Dict[str, Any],
) -> Optional[int]:
    if not benefit_schedule:
        return None
    horizon = max(payment_period, max(int(year) for year in benefit_schedule))
    running = 0.0
    cumulative: List[float] = []
    for value in (
        _guaranteed_income_cash_flows(
            annual_premium,
            payment_period,
            horizon,
            benefit_schedule,
        )
    ):
        running += value
        cumulative.append(running)
    for year in range(1, len(cumulative)):
        if cumulative[year] >= 0 and min(cumulative[year:]) >= 0:
            return year
    return None


def _calculate_option(option: Dict[str, Any]) -> Dict[str, Any]:
    result = {
        "name": option.get("name") or option.get("type"),
        "type": option.get("type"),
        "available": option.get("available"),
        "source_ref": option.get("source_ref"),
        "max_access_ratio": option.get("max_access_ratio"),
        "known_cost_rate": option.get("known_cost_rate"),
        "quantification_status": "not_quantified",
        "scenario_npv": None,
        "scenario_cash_flows": None,
    }
    scenario = option.get("quantified_scenario")
    if not isinstance(scenario, dict):
        return result
    rate = float(scenario["discount_rate"])
    flows = {
        int(time): float(value)
        for time, value in scenario["incremental_cash_flows"].items()
    }
    npv = sum(value / math.pow(1.0 + rate, time) for time, value in flows.items())
    result.update(
        {
            "quantification_status": "explicit_scenario",
            "scenario_name": scenario.get("name") or "未命名显式情景",
            "scenario_assumption": scenario.get("assumption") or "",
            "discount_rate": _ratio(rate),
            "scenario_npv": _money(npv),
            "scenario_cash_flows": {str(time): _money(value) for time, value in sorted(flows.items())},
        }
    )
    return result


def _calculate_longevity(
    product: Dict[str, Any],
    scenario: Dict[str, Any],
    benefit_schedule: Dict[str, Any],
    total_premium: float,
    longevity_test_age: Optional[int],
) -> Dict[str, Any]:
    longevity = product.get("longevity")
    if not isinstance(longevity, dict):
        return {
            "status": "missing",
            "reason": "未提供有来源的长寿责任字段",
            "tail_benefit": None,
            "tail_benefit_ratio": None,
        }
    convention = longevity.get("age_at_policy_year_end", "entry_age_plus_year_minus_one")
    entry_age = int(scenario["entry_age"])
    start_year = int(longevity["income_start_policy_year"])
    start_age = _attained_age(entry_age, start_year, convention)
    test_age = longevity_test_age
    tail_benefit: Optional[float] = None
    tail_ratio: Optional[float] = None
    completeness = "not_requested"
    schedule_coverage_end_age: Optional[int] = None
    if test_age is not None:
        schedule_ages = {
            _attained_age(entry_age, int(year), convention): float(value)
            for year, value in benefit_schedule.items()
        }
        contract_end_age = longevity.get("contract_end_age")
        schedule_coverage_end_age = max(schedule_ages) if schedule_ages else None
        if contract_end_age is not None and int(contract_end_age) < int(test_age):
            tail_benefit = 0.0
            tail_ratio = 0.0
            completeness = "contract_ends_before_test_age"
        elif int(test_age) in schedule_ages:
            tail_benefit = _money(
                sum(value for age, value in schedule_ages.items() if age >= test_age)
            )
            tail_ratio = None if total_premium <= 0 else _ratio(tail_benefit / total_premium)
            if contract_end_age is not None and schedule_coverage_end_age >= int(contract_end_age):
                completeness = "calculated_from_complete_explicit_schedule"
            else:
                completeness = "calculated_from_partial_explicit_schedule"
        else:
            completeness = "schedule_incomplete_for_test_age"
    return {
        "status": "documented",
        "source_ref": longevity.get("source_ref"),
        "lifetime_income": longevity.get("lifetime_income"),
        "income_start_policy_year": start_year,
        "income_start_age": start_age,
        "contract_end_age": longevity.get("contract_end_age"),
        "guaranteed_payment_years": longevity.get("guaranteed_payment_years"),
        "longevity_test_age": test_age,
        "schedule_coverage_end_age": schedule_coverage_end_age,
        "tail_schedule_status": completeness,
        "tail_benefit": tail_benefit,
        "tail_benefit_ratio": tail_ratio,
    }


def _schedule_value(schedule: Any, year: int, default: Optional[float]) -> Optional[float]:
    if not isinstance(schedule, dict):
        return default
    value = schedule.get(str(year), default)
    return default if value is None else _money(float(value))


def _select_phase(phases: Sequence[Dict[str, Any]], context: Dict[str, float], payment_period: int) -> Dict[str, Any]:
    matches = [phase for phase in phases if _condition_matches(phase.get("when", {}), context, payment_period)]
    if len(matches) != 1:
        raise CalculationError(f"身故责任阶段匹配数量应为1，实际为{len(matches)}")
    return matches[0]


def _rank_values(entries: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    ordered = sorted(entries, key=lambda item: (-float(item["value"]), item["product"]))
    rank = 0
    previous: Optional[float] = None
    for index, item in enumerate(ordered):
        value = float(item["value"])
        if previous is None or not math.isclose(value, previous, rel_tol=1e-10, abs_tol=1e-8):
            rank = index + 1
        item["rank"] = rank
        previous = value
    return ordered


def calculate_case(data: Dict[str, Any], validation: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    validation = validation or validate_case(data)
    comparison = data["comparison"]
    years = sorted(comparison["selected_policy_years"])
    products_output: List[Dict[str, Any]] = []
    runtime_warnings = list(validation["warnings"])
    provisional_codes = validation["provisional_products"]

    for product in data["products"]:
        name = product["name"]
        code = str(product.get("code") or name)
        scenario = _product_scenario(comparison, product)
        annual_premium = float(scenario["annual_premium"])
        payment_period = int(scenario["payment_period_years"])
        entry_age = int(scenario["entry_age"])
        base_amount, base_formula = _calculate_base_amount(product["rate"], annual_premium)
        product_result: Dict[str, Any] = {
            "name": name,
            "code": code,
            "category": product["category"],
            "scenario": scenario,
            "scenario_key": _scenario_key(scenario),
            "provisional": code in provisional_codes,
            "provisional_reasons": provisional_codes.get(code, []),
            "base_amount": base_amount,
            "base_amount_formula": base_formula,
            "source_refs": copy.deepcopy(product["source_refs"]),
            "years": {},
        }
        guaranteed_benefits = product.get("guaranteed_benefits") or {}
        benefit_schedule = guaranteed_benefits.get("values", {})
        total_premium = _money(annual_premium * payment_period)
        positive_benefit_years = sorted(
            int(year)
            for year, value in benefit_schedule.items()
            if float(value) > 0
        )
        first_income_year = positive_benefit_years[0] if positive_benefit_years else None
        first_income_amount = (
            _money(float(benefit_schedule[str(first_income_year)]))
            if first_income_year is not None
            else None
        )
        product_result["annuity_efficiency"] = {
            "status": "calculated_from_explicit_schedule" if benefit_schedule else "missing",
            "source_ref": guaranteed_benefits.get("source_ref"),
            "first_income_policy_year": first_income_year,
            "first_income_amount": first_income_amount,
            "first_income_to_total_premium_ratio": (
                None
                if first_income_amount is None or total_premium <= 0
                else _ratio(first_income_amount / total_premium)
            ),
            "income_breakeven_policy_year": _income_breakeven_year(
                annual_premium,
                payment_period,
                benefit_schedule,
            ),
        }
        product_result["longevity"] = _calculate_longevity(
            product,
            scenario,
            benefit_schedule,
            total_premium,
            comparison.get("longevity_test_age"),
        )
        product_result["contract_options"] = [
            _calculate_option(option)
            for option in product.get("contract_options", [])
        ]
        product_result["stress_tests"] = []
        dividend = product.get("dividend") or {}
        actual_schedule = dividend.get("actual_schedule")
        product_result["dividend_status"] = {
            "guaranteed": "provided" if isinstance(dividend.get("guaranteed_schedule"), dict) else "assumed_zero",
            "actual": "provided" if isinstance(actual_schedule, dict) else "unknown",
            "illustrated_scenarios": sorted((dividend.get("illustrated_scenarios") or {}).keys()),
        }
        for year in years:
            paid_premium = _money(annual_premium * min(year, payment_period))
            cash_value, cash_formula = _calculate_cash_value(product["cash_value"], year, base_amount, annual_premium)
            irr, cash_flows = _surrender_irr(annual_premium, payment_period, year, cash_value)
            guaranteed_benefit = _money(float(benefit_schedule.get(str(year), 0.0))) if benefit_schedule else None
            cumulative_guaranteed_benefit = (
                _money(
                    sum(
                        float(value)
                        for benefit_year, value in benefit_schedule.items()
                        if int(benefit_year) <= year
                    )
                )
                if benefit_schedule
                else None
            )
            guaranteed_income_cash_flows = (
                _guaranteed_income_cash_flows(
                    annual_premium,
                    payment_period,
                    year,
                    benefit_schedule,
                )
                if benefit_schedule
                else []
            )
            guaranteed_income_irr = (
                _irr(guaranteed_income_cash_flows)
                if guaranteed_income_cash_flows
                else None
            )
            guaranteed_dividend = _schedule_value(dividend.get("guaranteed_schedule"), year, 0.0)
            actual_dividend = _schedule_value(actual_schedule, year, None)
            convention = (product.get("death_benefit") or {}).get("age_at_policy_year_end", "entry_age_plus_year_minus_one")
            attained_age = _attained_age(entry_age, year, convention)
            effective_schedule = product.get("effective_base_amount", {}).get("values", {}) if isinstance(product.get("effective_base_amount"), dict) else {}
            paid_up_schedule = product.get("cumulative_paid_up_amount", {}).get("values", {}) if isinstance(product.get("cumulative_paid_up_amount"), dict) else {}
            context = {
                "annual_premium": annual_premium,
                "paid_premium": paid_premium,
                "total_premium": total_premium,
                "base_amount": base_amount,
                "cash_value": cash_value,
                "policy_year": float(year),
                "attained_age": float(attained_age),
                "effective_base_amount": float(effective_schedule.get(str(year), base_amount)),
                "dividend_cash_value": float(actual_dividend or 0.0),
                "cumulative_paid_up_amount": float(paid_up_schedule.get(str(year), 0.0)),
            }
            death_amount: Optional[float] = None
            death_trace: Optional[Dict[str, Any]] = None
            phase_name: Optional[str] = None
            death = product.get("death_benefit")
            if death:
                try:
                    phase = _select_phase(death["phases"], context, payment_period)
                    phase_name = phase.get("name") or "未命名阶段"
                    base_death, base_trace = _evaluate(phase["expression"], context)
                    additions: List[Dict[str, Any]] = []
                    death_amount_raw = base_death
                    for benefit in death.get("additive_benefits", []):
                        if benefit.get("when", {}).get("scenario") == scenario.get("death_scenario", "ordinary_death"):
                            amount, trace = _evaluate(benefit["expression"], context)
                            death_amount_raw += amount
                            additions.append({"name": benefit.get("name"), "amount": _money(amount), "trace": trace})
                    death_amount = _money(death_amount_raw)
                    death_trace = {"phase": phase_name, "base": base_trace, "additions": additions, "value": death_amount}
                except CalculationError as exc:
                    runtime_warnings.append(f"{name}：第{year}年度身故保险金无法计算：{exc}")
            year_result = {
                "policy_year": year,
                "attained_age": attained_age,
                "payment_status": "during" if year < payment_period else "completed",
                "paid_premium": paid_premium,
                "cash_value": cash_value,
                "cash_value_formula": cash_formula,
                "recovery_ratio": None if cash_value is None or paid_premium == 0 else _ratio(cash_value / paid_premium),
                "surrender_irr": irr,
                "surrender_cash_flows": cash_flows,
                "guaranteed_benefit": guaranteed_benefit,
                "cumulative_guaranteed_benefit": cumulative_guaranteed_benefit,
                "guaranteed_benefit_recovery_ratio": (
                    None
                    if cumulative_guaranteed_benefit is None or total_premium <= 0
                    else _ratio(cumulative_guaranteed_benefit / total_premium)
                ),
                "guaranteed_income_irr": (
                    None if guaranteed_income_irr is None else _ratio(guaranteed_income_irr)
                ),
                "guaranteed_income_cash_flows": guaranteed_income_cash_flows,
                "death_benefit": death_amount,
                "death_leverage": None if death_amount is None or paid_premium == 0 else _ratio(death_amount / paid_premium),
                "death_phase": phase_name,
                "death_trace": death_trace,
                "guaranteed_dividend": guaranteed_dividend,
                "actual_dividend": actual_dividend,
            }
            product_result["years"][str(year)] = year_result
            product_result["stress_tests"].append(
                {
                    "name": "保证利益/零分红提前退出",
                    "policy_year": year,
                    "evidence_basis": "guaranteed_cash_value",
                    "non_guaranteed_included": False,
                    "paid_premium": paid_premium,
                    "exit_value": cash_value,
                    "loss_amount": (
                        None if cash_value is None else _money(max(0.0, paid_premium - cash_value))
                    ),
                    "recovery_ratio": year_result["recovery_ratio"],
                    "surrender_irr": irr,
                }
            )
        products_output.append(product_result)

    ranking_rows: List[Dict[str, Any]] = []
    for year in years:
        groups: Dict[str, List[Dict[str, Any]]] = {}
        for product in products_output:
            groups.setdefault(product["scenario_key"], []).append(product)
        for group_key, group_products in sorted(groups.items()):
            if len(group_products) < 2:
                continue
            for metric, field in METRIC_FIELDS.items():
                entries = []
                for product in group_products:
                    value = product["years"][str(year)].get(field)
                    if value is not None and not product["provisional"]:
                        entries.append({"product": product["name"], "code": product["code"], "value": value})
                if len(entries) < 2:
                    continue
                for entry in _rank_values(entries):
                    ranking_rows.append({"policy_year": year, "metric": metric, "scenario_key": group_key, **entry})

    conclusion = _build_conclusion(comparison, products_output, ranking_rows)
    return {
        "schema_version": SCHEMA_VERSION,
        "comparison": copy.deepcopy(comparison),
        "conclusion": conclusion,
        "products": products_output,
        "rankings": ranking_rows,
        "warnings": sorted(set(runtime_warnings)),
        "disclaimer": "结果用于核算复核，不替代保险公司正式投保计划书，也不构成保险、法律或投资建议。",
    }


def _build_conclusion(comparison: Dict[str, Any], products: List[Dict[str, Any]], rankings: List[Dict[str, Any]]) -> Dict[str, Any]:
    if len(products) < 2:
        return {"status": "single_product", "text": "仅有一只可比产品，不生成相对胜负结论。", "leader": None}
    keys = {product["scenario_key"] for product in products}
    if len(keys) != 1:
        return {"status": "scenario_mismatch", "text": "产品类别或投保条件不完全一致，不生成同窗口胜负结论。", "leader": None}
    if any(product["provisional"] for product in products):
        return {"status": "provisional_data", "text": "存在单位覆盖后的暂定数据，不生成同窗口胜负结论。", "leader": None}
    year = comparison.get("primary_policy_year", max(comparison["selected_policy_years"]))
    metrics = comparison.get("primary_metrics", ["cash_value", "surrender_irr", "death_benefit"])
    group_key = products[0]["scenario_key"]
    leaders: List[set] = []
    for metric in metrics:
        rows = [row for row in rankings if row["policy_year"] == year and row["metric"] == metric and row["scenario_key"] == group_key]
        if len(rows) != len(products):
            return {"status": "incomplete", "text": f"第{year}保单年度末主要指标资料不完整，无法判断该窗口领先者。", "leader": None, "policy_year": year, "metrics": metrics}
        leaders.append({row["product"] for row in rows if row["rank"] == 1})
    common = set.intersection(*leaders) if leaders else set()
    if len(common) == 1:
        leader = next(iter(common))
        return {
            "status": "window_leader",
            "text": f"{leader}仅在第{year}保单年度末及声明的主要指标窗口内均列第一；该结论不得外推为全周期综合领先。",
            "leader": leader,
            "policy_year": year,
            "metrics": metrics,
            "overall_winner": None,
        }
    return {
        "status": "tradeoff",
        "text": f"第{year}保单年度末的声明指标存在取舍，未形成同窗口单一领先者；不生成全周期综合胜负结论。",
        "leader": None,
        "policy_year": year,
        "metrics": metrics,
        "overall_winner": None,
    }


def _fmt_money(value: Optional[float]) -> str:
    return "缺数据" if value is None else f"{value:,.2f}"


def _fmt_percent(value: Optional[float]) -> str:
    return "缺数据" if value is None else f"{value * 100:.4f}%"


def _rank_lookup(result: Dict[str, Any]) -> Dict[Tuple[int, str, str], int]:
    return {(row["policy_year"], row["metric"], row["code"]): row["rank"] for row in result["rankings"]}


def _death_trace_summary(trace: Optional[Dict[str, Any]]) -> Optional[str]:
    if not trace:
        return None
    base = trace.get("base", {})
    op = base.get("op")
    if op in {"max", "min"}:
        arguments = base.get("arguments", [])
        values = [argument.get("value") for argument in arguments]
        rendered = ", ".join(
            f"分支{index + 1}={_fmt_money(value)}" for index, value in enumerate(values)
        )
        selected = base.get("selected_index")
        selected_text = "未知" if selected is None else str(int(selected) + 1)
        return f"`{op}`({rendered})，选择分支{selected_text}，基础给付{_fmt_money(base.get('value'))}"
    return f"`{op}` 计算基础给付{_fmt_money(base.get('value'))}"


def render_markdown(result: Dict[str, Any]) -> str:
    comparison = result["comparison"]
    ranks = _rank_lookup(result)
    lines = [
        "# 多保险产品精算对比报告",
        "",
        "## 结论",
        "",
        result["conclusion"]["text"],
        "",
        "## 统一投保条件",
        "",
        "| 项目 | 条件 |",
        "|---|---|",
        f"| 币种 | {comparison.get('currency')} |",
        f"| 投保年龄 | {comparison.get('entry_age')}周岁 |",
        f"| 性别 | {comparison.get('gender')} |",
        f"| 体况 | {comparison.get('underwriting_class')} |",
        f"| 交费期间 | {comparison.get('payment_period_years')}年 |",
        f"| 年交保费 | {_fmt_money(float(comparison.get('annual_premium')))} |",
        f"| 比较年度 | {', '.join(str(year) for year in comparison.get('selected_policy_years', []))} |",
        f"| 身故情景 | {comparison.get('death_scenario', 'ordinary_death')} |",
        "",
        "## 证据与单位审计",
        "",
        "| 产品 | 基本保额 | 状态 | 材料版本 | 来源数 |",
        "|---|---:|---|---|---:|",
    ]
    for product in result["products"]:
        versions = sorted({str(ref.get("version")) for ref in product["source_refs"] if ref.get("version")})
        fixture = all(ref.get("fixture") is True for ref in product["source_refs"])
        status = "暂定" if product["provisional"] else ("脱敏测试" if fixture else "已校验")
        lines.append(f"| {product['name']} | {_fmt_money(product['base_amount'])} | {status} | {', '.join(versions) or '未标注'} | {len(product['source_refs'])} |")
        lines.append("")
        lines.append(f"- **{product['name']}基本保额推导**：`{product['base_amount_formula']}`。")
        for ref in product["source_refs"]:
            location = ref.get("location", "未提供")
            page = ref.get("page", "未标注")
            row = ref.get("row_label", "未标注")
            column = ref.get("column_label", "未标注")
            lines.append(f"- **{product['name']} / {ref.get('id')}**：{ref.get('title', ref.get('kind'))}；位置 `{location}`；第{page}页；行“{row}”；列“{column}”；单位“{ref.get('unit_text', '未标注')}”。")
    lines.extend(["", "## 现金价值与保证退保 IRR", ""])
    for year in comparison["selected_policy_years"]:
        lines.extend([
            f"### 第{year}保单年度末",
            "",
            "| 产品 | 累计保费 | 现金价值 | 回收率 | 保证退保IRR | 现金价值排名 | IRR排名 |",
            "|---|---:|---:|---:|---:|---:|---:|",
        ])
        for product in result["products"]:
            values = product["years"][str(year)]
            cash_rank = ranks.get((year, "cash_value", product["code"]))
            irr_rank = ranks.get((year, "surrender_irr", product["code"]))
            lines.append(
                f"| {product['name']} | {_fmt_money(values['paid_premium'])} | {_fmt_money(values['cash_value'])} | "
                f"{_fmt_percent(values['recovery_ratio'])} | {_fmt_percent(values['surrender_irr'])} | "
                f"{cash_rank or '不排名'} | {irr_rank or '不排名'} |"
            )
            if values["cash_value_formula"]:
                lines.append("")
                lines.append(f"- **{product['name']}第{year}年现金价值**：`{values['cash_value_formula']}`。IRR现金流：`{values['surrender_cash_flows']}`。")
        lines.append("")
    lines.extend(["## 年金领取效率", ""])
    lines.extend([
        "| 产品 | 首次保证领取年度 | 首次保证领取额 | 首次领取/总保费 | 仅靠保证领取回本年度 |",
        "|---|---:|---:|---:|---:|",
    ])
    for product in result["products"]:
        efficiency = product["annuity_efficiency"]
        lines.append(
            f"| {product['name']} | {efficiency.get('first_income_policy_year') or '缺数据'} | "
            f"{_fmt_money(efficiency.get('first_income_amount'))} | "
            f"{_fmt_percent(efficiency.get('first_income_to_total_premium_ratio'))} | "
            f"{efficiency.get('income_breakeven_policy_year') or '未回本/缺数据'} |"
        )
    lines.append("")
    for year in comparison["selected_policy_years"]:
        lines.extend([
            f"### 第{year}保单年度末保证领取",
            "",
            "| 产品 | 当年保证领取 | 累计保证领取 | 累计领取/总保费 | 保证领取现金流IRR |",
            "|---|---:|---:|---:|---:|",
        ])
        for product in result["products"]:
            values = product["years"][str(year)]
            lines.append(
                f"| {product['name']} | {_fmt_money(values['guaranteed_benefit'])} | "
                f"{_fmt_money(values['cumulative_guaranteed_benefit'])} | "
                f"{_fmt_percent(values['guaranteed_benefit_recovery_ratio'])} | "
                f"{_fmt_percent(values['guaranteed_income_irr'])} |"
            )
        lines.append("")

    lines.extend(["## 长寿风险转移", ""])
    lines.extend([
        "| 产品 | 终身领取 | 首次领取年龄 | 合同终止年龄 | 保证领取年数 | 长寿测试年龄 | 测试年龄后保证领取/总保费 | 状态 |",
        "|---|---|---:|---:|---:|---:|---:|---|",
    ])
    for product in result["products"]:
        longevity = product["longevity"]
        lifetime = "是" if longevity.get("lifetime_income") is True else ("否" if longevity.get("lifetime_income") is False else "缺数据")
        lines.append(
            f"| {product['name']} | {lifetime} | {longevity.get('income_start_age') or '缺数据'} | "
            f"{longevity.get('contract_end_age') or '终身/缺数据'} | "
            f"{longevity.get('guaranteed_payment_years') if longevity.get('guaranteed_payment_years') is not None else '缺数据'} | "
            f"{longevity.get('longevity_test_age') or '未指定'} | "
            f"{_fmt_percent(longevity.get('tail_benefit_ratio'))} | {longevity.get('tail_schedule_status') or longevity.get('reason')} |"
        )
    lines.extend([
        "",
        "长寿尾部指标只使用输入中逐年列明的保证领取，不用生命表或未披露假设补齐。",
        "",
        "## 合同选择权",
        "",
        "| 产品 | 选择权 | 是否可用 | 最大可动用比例 | 已知成本率 | 量化状态 | 显式情景NPV |",
        "|---|---|---|---:|---:|---|---:|",
    ])
    option_rows = 0
    for product in result["products"]:
        for option in product["contract_options"]:
            option_rows += 1
            lines.append(
                f"| {product['name']} | {option.get('name')} | {'是' if option.get('available') else '否'} | "
                f"{_fmt_percent(option.get('max_access_ratio'))} | {_fmt_percent(option.get('known_cost_rate'))} | "
                f"{option.get('quantification_status')} | {_fmt_money(option.get('scenario_npv'))} |"
            )
    if not option_rows:
        lines.append("| 全部产品 | 缺少有来源的合同选择权数据 | 缺数据 | 缺数据 | 缺数据 | 不量化 | 缺数据 |")
    lines.extend([
        "",
        "未提供显式增量现金流和折现率时，只确认选择权存在，不把功能存在性换算成分数。",
        "",
        "## 可验证压力测试",
        "",
        "| 产品 | 保单年度 | 情景 | 累计保费 | 保证退出价值 | 损失额 | 回收率 | 保证退保IRR |",
        "|---|---:|---|---:|---:|---:|---:|---:|",
    ])
    for product in result["products"]:
        for stress in product["stress_tests"]:
            lines.append(
                f"| {product['name']} | {stress['policy_year']} | {stress['name']} | "
                f"{_fmt_money(stress['paid_premium'])} | {_fmt_money(stress['exit_value'])} | "
                f"{_fmt_money(stress['loss_amount'])} | {_fmt_percent(stress['recovery_ratio'])} | "
                f"{_fmt_percent(stress['surrender_irr'])} |"
            )
    lines.extend([
        "",
        "压力测试仅采用正式保证现金价值并排除全部非保证红利；不使用随机ALM、VaR或公司资产假设冒充产品证据。",
        "",
        "## 身故保险金与保障杠杆",
        "",
    ])
    for year in comparison["selected_policy_years"]:
        lines.extend([
            f"### 第{year}保单年度末",
            "",
            "| 产品 | 到达年龄 | 责任阶段 | 身故保险金 | 身故杠杆 | 身故金额排名 |",
            "|---|---:|---|---:|---:|---:|",
        ])
        for product in result["products"]:
            values = product["years"][str(year)]
            death_rank = ranks.get((year, "death_benefit", product["code"]))
            leverage_text = "缺数据" if values["death_leverage"] is None else f"{values['death_leverage']:.4f}倍"
            lines.append(
                f"| {product['name']} | {values['attained_age']} | {values['death_phase'] or '缺数据'} | "
                f"{_fmt_money(values['death_benefit'])} | "
                f"{leverage_text} | {death_rank or '不排名'} |"
            )
            trace_summary = _death_trace_summary(values["death_trace"])
            if trace_summary:
                lines.append("")
                lines.append(f"- **{product['name']}第{year}年身故责任轨迹**：{trace_summary}。")
        lines.append("")
    lines.extend(["## 红利口径", "", "| 产品 | 保证红利 | 实际红利 | 演示情景 |", "|---|---|---|---|"])
    for product in result["products"]:
        status = product["dividend_status"]
        guarantee = "已提供" if status["guaranteed"] == "provided" else "未提供，按0"
        actual = "已提供" if status["actual"] == "provided" else "未知"
        scenarios = ", ".join(status["illustrated_scenarios"]) or "无"
        lines.append(f"| {product['name']} | {guarantee} | {actual} | {scenarios} |")
    lines.extend(["", "## 缺失数据与警告", ""])
    if result["warnings"]:
        lines.extend(f"- {warning}" for warning in result["warnings"])
    else:
        lines.append("- 无。")
    lines.extend(["", "> " + result["disclaimer"], ""])
    return "\n".join(lines)


def write_outputs(result: Dict[str, Any], output_dir: Path) -> Tuple[Path, Path]:
    output_dir.mkdir(parents=True, exist_ok=True)
    json_path = output_dir / "comparison.json"
    markdown_path = output_dir / "comparison.md"
    json_path.write_text(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    markdown_path.write_text(render_markdown(result), encoding="utf-8")
    return markdown_path, json_path


def _assert_close(actual: Optional[float], expected: float, label: str, tolerance: float = 0.01) -> None:
    if actual is None or not math.isclose(actual, expected, rel_tol=0.0, abs_tol=tolerance):
        raise AssertionError(f"{label}: expected {expected}, got {actual}")


def run_self_test() -> None:
    fixtures = Path(__file__).resolve().parent.parent / "assets" / "fixtures"
    checks: List[str] = []

    male_data = load_json(fixtures / "wwa_male_30_10pay.json")
    male = calculate_case(male_data)
    male_product = male["products"][0]
    _assert_close(male_product["base_amount"], 2_000_000, "WWA male base")
    _assert_close(male_product["years"]["10"]["cash_value"], 982_820, "WWA male CV10")
    _assert_close(male_product["years"]["10"]["death_benefit"], 3_000_000, "WWA male death10")
    checks.append("WWA男性案例")

    female_data = load_json(fixtures / "wwa_female_40_10pay.json")
    female = calculate_case(female_data)
    female_product = female["products"][0]
    _assert_close(female_product["base_amount"], 1_900_000, "WWA female base")
    _assert_close(female_product["years"]["10"]["cash_value"], 983_364, "WWA female CV10")
    _assert_close(female_product["years"]["10"]["death_benefit"], 2_850_000, "WWA female death10")
    checks.append("WWA女性案例")

    ric_data = load_json(fixtures / "ric_female_32_5pay.json")
    ric = calculate_case(ric_data)
    expected_ric = [23_690.40, 57_001.50, 92_709.30, 130_906.20, 171_688.50]
    for year, expected in enumerate(expected_ric, 1):
        _assert_close(ric["products"][0]["years"][str(year)]["cash_value"], expected, f"RIC CV{year}")
    if ric["products"][0]["dividend_status"]["actual"] != "unknown":
        raise AssertionError("RIC actual dividend must remain unknown")
    checks.append("RIC现金价值与红利案例")

    advantage_data = copy.deepcopy(ric_data)
    advantage_data["comparison"]["longevity_test_age"] = 35
    advantage_data["comparison"]["primary_metrics"] = [
        "cash_value",
        "guaranteed_benefit_recovery_ratio",
    ]
    advantage_product = advantage_data["products"][0]
    advantage_product["source_refs"].append(
        {
            "id": "terms",
            "kind": "policy_terms",
            "title": "RIC保证领取与合同选择权（脱敏摘录）",
            "location": "fixture://ric-terms",
            "page": 1,
            "row_label": "保证领取、长寿责任与保单贷款",
            "column_label": "合同责任",
            "unit_text": "人民币元",
            "version": "C",
            "fixture": True,
        }
    )
    advantage_product["guaranteed_benefits"] = {
        "source_ref": "terms",
        "basis": "absolute",
        "unit_text": "人民币元",
        "values": {"1": 100, "2": 200, "3": 300, "4": 400, "5": 500},
    }
    advantage_product["longevity"] = {
        "source_ref": "terms",
        "lifetime_income": True,
        "income_start_policy_year": 1,
        "contract_end_age": 85,
        "guaranteed_payment_years": 20,
    }
    advantage_product["contract_options"] = [
        {
            "name": "保单贷款",
            "type": "policy_loan",
            "source_ref": "terms",
            "available": True,
            "max_access_ratio": 0.8,
            "known_cost_rate": 0.05,
            "quantified_scenario": {
                "name": "第5年借款并于第6年偿还",
                "assumption": "仅用于验证显式情景NPV",
                "discount_rate": 0.03,
                "incremental_cash_flows": {"5": 1000, "6": -1050},
            },
        }
    ]
    advantage = calculate_case(advantage_data)
    advantage_result = advantage["products"][0]
    if advantage_result["annuity_efficiency"]["first_income_policy_year"] != 1:
        raise AssertionError("Annuity efficiency must use the explicit benefit schedule")
    if advantage_result["years"]["5"]["cumulative_guaranteed_benefit"] != 1500:
        raise AssertionError("Cumulative guaranteed benefits are incorrect")
    if advantage_result["longevity"]["tail_benefit"] != 900:
        raise AssertionError("Longevity tail benefit must be based on explicit scheduled values")
    if advantage_result["longevity"]["tail_schedule_status"] != "calculated_from_partial_explicit_schedule":
        raise AssertionError("A partial schedule must not be described as complete longevity coverage")
    if advantage_result["contract_options"][0]["quantification_status"] != "explicit_scenario":
        raise AssertionError("Contract option must remain unquantified without an explicit scenario")
    if any(item["non_guaranteed_included"] for item in advantage_result["stress_tests"]):
        raise AssertionError("Guaranteed stress tests must exclude non-guaranteed benefits")
    if "grade" in advantage or "total_score" in advantage:
        raise AssertionError("Strict comparison must not emit a composite grade or score")
    checks.append("年金效率、长寿、选择权与保证压力测试")

    pwd_data = load_json(fixtures / "pwd_unit_conflict.json")
    try:
        validate_case(pwd_data)
    except ValidationError as exc:
        if not any("冲突" in error for error in exc.errors):
            raise AssertionError("PWD fixture did not report unit conflict")
    else:
        raise AssertionError("PWD unit conflict must block validation")
    checks.append("PWD单位冲突阻断")

    invalid_ast = copy.deepcopy(male_data)
    invalid_ast["products"][0]["death_benefit"]["phases"][0]["expression"]["op"] = "eval"
    try:
        validate_case(invalid_ast)
    except ValidationError:
        pass
    else:
        raise AssertionError("Unknown AST operator must be rejected")
    invalid_field = copy.deepcopy(male_data)
    invalid_field["products"][0]["death_benefit"]["phases"][0]["expression"] = {"op": "field", "name": "__import__"}
    try:
        validate_case(invalid_field)
    except ValidationError:
        pass
    else:
        raise AssertionError("Unknown AST field must be rejected")
    checks.append("安全公式操作符与字段白名单")

    age_expr = {"op": "age_band", "bands": [{"max": 40, "value": 1.6}, {"min": 41, "value": 1.4}]}
    _assert_close(_evaluate(age_expr, {"attained_age": 40})[0], 1.6, "age 40 band", 1e-12)
    _assert_close(_evaluate(age_expr, {"attained_age": 41})[0], 1.4, "age 41 band", 1e-12)
    checks.append("年龄分界")

    during = {"payment_status": "during"}
    completed = {"payment_status": "completed"}
    year_nine = {"policy_year": 9.0, "attained_age": 38.0}
    year_ten = {"policy_year": 10.0, "attained_age": 39.0}
    if not _condition_matches(during, year_nine, 10) or _condition_matches(completed, year_nine, 10):
        raise AssertionError("Policy year 9 must be during payment")
    if not _condition_matches(completed, year_ten, 10) or _condition_matches(during, year_ten, 10):
        raise AssertionError("Policy year 10 must be payment completed")
    checks.append("交费完成边界")

    irr_value, flows = _surrender_irr(100.0, 1, 1, 110.0)
    _assert_close(irr_value, 0.1, "IRR timing", 1e-9)
    if flows != [-100.0, 110.0]:
        raise AssertionError(f"Unexpected cash flow timing: {flows}")
    checks.append("IRR现金流时点")

    override_data = copy.deepcopy(pwd_data)
    override_data["products"][0]["cash_value"]["unit_override_reason"] = "仅用于测试：已人工回查原表脚注"
    override_validation = validate_case(override_data)
    override_result = calculate_case(override_data, override_validation)
    if not override_result["products"][0]["provisional"]:
        raise AssertionError("Unit override must remain provisional")
    checks.append("单位覆盖保持暂定")

    version_data = copy.deepcopy(male_data)
    version_data["products"][0]["source_refs"][1]["version"] = "2026"
    try:
        validate_case(version_data)
    except ValidationError as exc:
        if not any("版本不一致" in error for error in exc.errors):
            raise AssertionError("Version mismatch did not produce the expected error")
    else:
        raise AssertionError("Material version mismatch must block validation")
    checks.append("材料版本冲突阻断")

    hash_data = copy.deepcopy(male_data)
    hash_data["products"][0]["source_refs"][0]["location"] = str(fixtures / "wwa_male_30_10pay.json")
    hash_data["products"][0]["source_refs"][0]["sha256"] = "0" * 64
    try:
        validate_case(hash_data)
    except ValidationError as exc:
        if not any("实际哈希不一致" in error for error in exc.errors):
            raise AssertionError("Local source hash mismatch did not produce the expected error")
    else:
        raise AssertionError("Local source hash mismatch must block validation")
    checks.append("本地材料哈希核验")

    ranking_data = copy.deepcopy(male_data)
    challenger = copy.deepcopy(ranking_data["products"][0])
    challenger["name"] = "对照产品"
    challenger["code"] = "CONTROL"
    challenger["cash_value"]["values"]["10"] = 450.0
    challenger["death_benefit"]["phases"][0]["expression"] = {"op": "const", "value": 2_500_000}
    ranking_data["products"].append(challenger)
    ranked = calculate_case(ranking_data)
    if ranked["conclusion"]["status"] != "window_leader" or ranked["conclusion"]["leader"] != male_product["name"]:
        raise AssertionError("Relative window leader logic failed")
    if ranked["conclusion"].get("overall_winner") is not None:
        raise AssertionError("A horizon-scoped result must not create an overall winner")
    checks.append("同条件同窗口相对排名")

    mismatch_data = copy.deepcopy(ranking_data)
    mismatch_data["products"][1]["category"] = "annuity"
    mismatch = calculate_case(mismatch_data)
    if mismatch["conclusion"]["status"] != "scenario_mismatch":
        raise AssertionError("Cross-category products must not receive an overall ranking")
    checks.append("跨险种禁止综合排名")

    first = json.dumps(calculate_case(male_data), ensure_ascii=False, sort_keys=True)
    second = json.dumps(calculate_case(male_data), ensure_ascii=False, sort_keys=True)
    first_markdown = render_markdown(calculate_case(male_data))
    second_markdown = render_markdown(calculate_case(male_data))
    if first != second or first_markdown != second_markdown:
        raise AssertionError("Output must be deterministic")
    checks.append("Markdown与JSON稳定重复输出")

    print(f"自检通过：{len(checks)}项")
    for check in checks:
        print(f"- {check}")


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="同条件比较多只保险产品的现金价值、身故保险金和保证IRR")
    subparsers = parser.add_subparsers(dest="command", required=True)
    validate_parser = subparsers.add_parser("validate", help="验证输入、来源、版本和单位")
    validate_parser.add_argument("--input", required=True, type=Path)
    compare_parser = subparsers.add_parser("compare", help="计算并输出Markdown与JSON报告")
    compare_parser.add_argument("--input", required=True, type=Path)
    compare_parser.add_argument("--output-dir", required=True, type=Path)
    subparsers.add_parser("self-test", help="运行内置脱敏回归案例")
    return parser


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = _build_parser().parse_args(argv)
    if args.command == "self-test":
        try:
            run_self_test()
        except (AssertionError, CalculationError, ValidationError) as exc:
            print(f"自检失败：{exc}", file=sys.stderr)
            return 3
        return 0
    try:
        data = load_json(args.input)
        validation = validate_case(data)
    except ValidationError as exc:
        print("验证失败：", file=sys.stderr)
        for error in exc.errors:
            print(f"- {error}", file=sys.stderr)
        if exc.warnings:
            print("同时发现警告：", file=sys.stderr)
            for warning in exc.warnings:
                print(f"- {warning}", file=sys.stderr)
        return 2
    if args.command == "validate":
        print("验证通过")
        for warning in validation["warnings"]:
            print(f"- 警告：{warning}")
        return 0
    try:
        result = calculate_case(data, validation)
        markdown_path, json_path = write_outputs(result, args.output_dir)
    except (CalculationError, OSError, ValueError) as exc:
        print(f"计算失败：{exc}", file=sys.stderr)
        return 3
    print(f"已生成：{markdown_path}")
    print(f"已生成：{json_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
