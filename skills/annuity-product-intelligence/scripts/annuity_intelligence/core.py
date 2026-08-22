from __future__ import annotations

import re
from decimal import Decimal, ROUND_HALF_EVEN, localcontext
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Sequence, Set, Tuple

from .common import (
    DECIMAL_ONE,
    DECIMAL_ZERO,
    SCHEMA_VERSION,
    TOOL_VERSION,
    ReviewRequiredError,
    ValidationError,
    ValidationResult,
    decimal_string,
    decimal_value,
    deep_copy_json,
    enforce_no_customer_data,
    flatten_evidence_refs,
    reject_unknown_keys,
    require_keys,
    sha256_file,
    sha256_text,
    stable_json_data,
)


GUARANTEE_BASES = {"guaranteed", "illustrated", "non_guaranteed"}
EVIDENCE_STATUSES = {"verified", "extracted", "resolved", "unresolved"}
VALUE_STATUSES = {"available", "missing", "not_applicable", "unresolved"}
SOURCE_AUTHORITIES = {
    "contract",
    "rate_table",
    "cash_value_table",
    "illustration",
    "product_summary",
    "benchmark",
    "synthetic_fixture",
}

TOP_LEVEL_KEYS = {
    "schema_version",
    "product",
    "sources",
    "evidence",
    "configurations",
    "analysis_assumptions",
}
PRODUCT_KEYS = {
    "product_id",
    "name",
    "insurer",
    "currency",
    "jurisdiction",
    "document_version",
    "effective_date",
    "product_type",
    "analysis_only",
    "evidence_refs",
}
SOURCE_KEYS = {
    "source_id",
    "path",
    "sha256",
    "document_type",
    "version",
    "effective_date",
    "authority",
    "embedded_fixture",
    "extraction",
}
EVIDENCE_KEYS = {
    "evidence_id",
    "source_id",
    "page",
    "bbox",
    "sheet",
    "cell_range",
    "row_label",
    "column_label",
    "raw_text",
    "raw_value",
    "raw_text_sha256",
    "unit_text",
    "extractor",
    "extractor_version",
    "confidence",
    "status",
    "transformation",
}
CONFIGURATION_KEYS = {
    "configuration_id",
    "dimensions",
    "dimension_evidence_refs",
    "basic_amount",
    "premium_events",
    "annuity_rules",
    "cash_values",
    "death_benefit",
    "maturity_events",
    "loan_terms",
    "notes",
}
DIMENSION_KEYS = {
    "published_issue_age",
    "rate_class",
    "premium_term_months",
    "annuity_start_age",
    "annuity_frequency_per_year",
    "guarantee_option",
    "premium_mode",
    "product_option_code",
    "proportionality_verified",
}
EVENT_KEYS = {
    "policy_month",
    "event_order",
    "amount",
    "guarantee_basis",
    "scenario_id",
    "scenario_composition",
    "status",
    "timing",
    "evidence_refs",
    "contingency",
}
ANNUITY_RULE_KEYS = {
    "rule_id",
    "first_payment_month",
    "frequency_months",
    "payment_timing",
    "amount",
    "annual_growth_rate",
    "growth_interval_months",
    "lifetime",
    "contract_end_age",
    "last_payment_month",
    "payment_count",
    "guaranteed_period_months",
    "guarantee_basis",
    "scenario_id",
    "scenario_composition",
    "rounding",
    "evidence_refs",
    "contingency",
}
DEATH_BENEFIT_KEYS = {
    "guarantee_basis",
    "scenario_id",
    "boundary_order",
    "schedule",
    "lookup",
    "rule",
    "cash_value_timing",
    "beneficiary_continuation",
    "evidence_refs",
}
BENEFICIARY_CONTINUATION_KEYS = {
    "mode",
    "through_policy_month",
    "evidence_refs",
}
LOAN_TERM_KEYS = {
    "available",
    "limit_ratio",
    "eligible_value",
    "interest_rate_status",
    "interest_rate",
    "evidence_refs",
}
ASSUMPTION_KEYS = {
    "target_survival_ages",
    "target_death_ages",
    "inflation_rates",
    "benchmark_selection",
    "analysis_end_age",
}


def _is_int(value: Any) -> bool:
    if isinstance(value, bool):
        return False
    try:
        return Decimal(str(value)) == int(Decimal(str(value)))
    except Exception:
        return False


def find_unresolved_paths(data: Any, path: str = "$") -> List[str]:
    paths: List[str] = []
    if isinstance(data, Mapping):
        for key, value in data.items():
            child_path = f"{path}.{key}"
            if value == "unresolved":
                paths.append(child_path)
            else:
                paths.extend(find_unresolved_paths(value, child_path))
    elif isinstance(data, list):
        for index, value in enumerate(data):
            paths.extend(find_unresolved_paths(value, f"{path}[{index}]"))
    return paths


def _validate_evidence_refs(
    refs: Any,
    evidence_ids: Set[str],
    path: str,
    errors: List[str],
    required: bool = True,
) -> None:
    if refs is None and not required:
        return
    if not isinstance(refs, list) or (required and not refs):
        errors.append(f"{path} must be a non-empty list")
        return
    if len(refs) != len(set(ref for ref in refs if isinstance(ref, str))):
        errors.append(f"{path} must not contain duplicate evidence IDs")
    for index, ref in enumerate(refs):
        if not isinstance(ref, str) or ref not in evidence_ids:
            errors.append(f"{path}[{index}] references unknown evidence {ref!r}")


def _validate_money_spec(spec: Any, path: str, errors: List[str]) -> None:
    if not isinstance(spec, Mapping):
        errors.append(f"{path} must be an explicit money object")
        return
    allowed = {"value", "unit", "basis_kind", "basis_value", "basis_unit", "rounding"}
    reject_unknown_keys(spec, allowed, path, errors)
    require_keys(spec, ("value", "unit"), path, errors)
    try:
        value = decimal_value(spec.get("value"), f"{path}.value")
        if value < 0:
            errors.append(f"{path}.value must be non-negative")
    except ValidationError as exc:
        errors.extend(exc.errors)
    unit = spec.get("unit")
    if not isinstance(unit, str) or not unit.strip():
        errors.append(f"{path}.unit must be explicit")
    if "basis_value" in spec:
        try:
            if decimal_value(spec["basis_value"], f"{path}.basis_value") < 0:
                errors.append(f"{path}.basis_value must be non-negative")
        except ValidationError as exc:
            errors.extend(exc.errors)
    if spec.get("rounding", "none") not in {"none", "cent", "whole"}:
        errors.append(f"{path}.rounding must be none, cent, or whole")


def _validate_event(
    event: Any,
    path: str,
    evidence_ids: Set[str],
    errors: List[str],
    require_amount: bool = True,
) -> None:
    if not isinstance(event, Mapping):
        errors.append(f"{path} must be an object")
        return
    reject_unknown_keys(event, EVENT_KEYS, path, errors)
    require_keys(
        event, ("policy_month", "event_order", "status", "evidence_refs"), path, errors
    )
    if not _is_int(event.get("policy_month")) or int(event.get("policy_month", -1)) < 0:
        errors.append(f"{path}.policy_month must be a non-negative integer")
    if not _is_int(event.get("event_order")):
        errors.append(f"{path}.event_order must be an integer")
    status = event.get("status")
    if status not in VALUE_STATUSES:
        errors.append(f"{path}.status must be one of {sorted(VALUE_STATUSES)}")
    if status == "available" or require_amount:
        if "amount" not in event:
            errors.append(f"{path}.amount is required when status is available")
        else:
            _validate_money_spec(event.get("amount"), f"{path}.amount", errors)
    elif "amount" in event and event["amount"] is not None:
        errors.append(f"{path}.amount must be absent for status {status}")
    guarantee = event.get("guarantee_basis")
    if status == "available" and guarantee not in GUARANTEE_BASES:
        errors.append(f"{path}.guarantee_basis must be explicit")
    scenario_id = event.get("scenario_id", "guaranteed")
    if guarantee == "guaranteed" and scenario_id != "guaranteed":
        errors.append(f"{path}.scenario_id must be guaranteed for guaranteed values")
    if guarantee in {"illustrated", "non_guaranteed"} and scenario_id == "guaranteed":
        errors.append(
            f"{path}.scenario_id must name a separate non-guaranteed scenario"
        )
    composition = event.get("scenario_composition")
    if guarantee in {"illustrated", "non_guaranteed"} and composition not in {
        "total",
        "incremental",
    }:
        errors.append(
            f"{path}.scenario_composition must be total or incremental for non-guaranteed values"
        )
    if guarantee == "guaranteed" and composition not in {None, "total"}:
        errors.append(f"{path}.guaranteed values cannot be incremental")
    _validate_evidence_refs(
        event.get("evidence_refs"), evidence_ids, f"{path}.evidence_refs", errors
    )


def _validate_ast(
    node: Any,
    path: str,
    evidence_ids: Set[str],
    errors: List[str],
    require_money_result: bool = False,
) -> Optional[str]:
    if not isinstance(node, Mapping):
        errors.append(f"{path} must be an AST object")
        return None
    op = node.get("op")
    allowed_ops = {
        "constant",
        "scalar_constant",
        "field",
        "add",
        "subtract",
        "multiply",
        "max",
        "min",
        "floor_zero",
        "if_period",
    }
    if op not in allowed_ops:
        errors.append(f"{path}.op {op!r} is not in the safe grammar")
        return None
    allowed_common = {"op", "evidence_refs"}
    allowed_by_op = {
        "constant": {"amount"},
        "scalar_constant": {"value"},
        "field": {"name"},
        "add": {"args"},
        "subtract": {"left", "right"},
        "multiply": {"args"},
        "max": {"args"},
        "min": {"args"},
        "floor_zero": {"arg"},
        "if_period": {"policy_month_min", "policy_month_max", "then", "else"},
    }
    reject_unknown_keys(node, allowed_common | allowed_by_op[op], path, errors)
    _validate_evidence_refs(
        node.get("evidence_refs"), evidence_ids, f"{path}.evidence_refs", errors
    )
    result_type: Optional[str] = None
    if op == "constant":
        _validate_money_spec(node.get("amount"), f"{path}.amount", errors)
        result_type = "money"
    elif op == "scalar_constant":
        try:
            decimal_value(node.get("value"), f"{path}.value")
        except ValidationError as exc:
            errors.extend(exc.errors)
        result_type = "scalar"
    elif op == "field":
        field_types = {
            "basic_amount": "money",
            "cash_value": "money",
            "cumulative_annuity": "money",
            "cumulative_premium": "money",
            "policy_month": "month",
            "total_premium": "money",
        }
        if node.get("name") not in field_types:
            errors.append(f"{path}.name must be one of {sorted(field_types)}")
        else:
            result_type = field_types[node["name"]]
    elif op in {"add", "multiply", "max", "min"}:
        args = node.get("args")
        if not isinstance(args, list) or len(args) < 2:
            errors.append(f"{path}.args must contain at least two nodes")
        else:
            child_types = [
                _validate_ast(child, f"{path}.args[{index}]", evidence_ids, errors)
                for index, child in enumerate(args)
            ]
            concrete_types = [
                child_type for child_type in child_types if child_type is not None
            ]
            if op == "multiply":
                if any(child_type == "month" for child_type in concrete_types):
                    errors.append(f"{path} cannot multiply a policy-month value")
                elif sum(child_type == "money" for child_type in concrete_types) > 1:
                    errors.append(f"{path} cannot multiply money by money")
                elif concrete_types and len(concrete_types) == len(child_types):
                    result_type = "money" if "money" in concrete_types else "scalar"
            elif concrete_types and len(concrete_types) == len(child_types):
                if len(set(concrete_types)) != 1:
                    errors.append(
                        f"{path} requires operands with the same dimensional type"
                    )
                else:
                    result_type = concrete_types[0]
    elif op == "subtract":
        left_type = _validate_ast(
            node.get("left"), f"{path}.left", evidence_ids, errors
        )
        right_type = _validate_ast(
            node.get("right"), f"{path}.right", evidence_ids, errors
        )
        if left_type is not None and right_type is not None:
            if left_type != right_type:
                errors.append(
                    f"{path} requires operands with the same dimensional type"
                )
            else:
                result_type = left_type
    elif op == "floor_zero":
        result_type = _validate_ast(
            node.get("arg"), f"{path}.arg", evidence_ids, errors
        )
        if result_type == "month":
            errors.append(f"{path} cannot floor a policy-month value as a benefit")
            result_type = None
    elif op == "if_period":
        minimum = node.get("policy_month_min")
        maximum = node.get("policy_month_max")
        if minimum is not None and (not _is_int(minimum) or int(minimum) < 0):
            errors.append(f"{path}.policy_month_min must be a non-negative integer")
        if maximum is not None and (not _is_int(maximum) or int(maximum) < 0):
            errors.append(f"{path}.policy_month_max must be a non-negative integer")
        if minimum is not None and maximum is not None and int(minimum) > int(maximum):
            errors.append(f"{path} has an inverted period")
        then_type = _validate_ast(
            node.get("then"), f"{path}.then", evidence_ids, errors
        )
        else_type = _validate_ast(
            node.get("else"), f"{path}.else", evidence_ids, errors
        )
        if then_type is not None and else_type is not None:
            if then_type != else_type:
                errors.append(
                    f"{path} requires branches with the same dimensional type"
                )
            else:
                result_type = then_type
    if require_money_result and result_type != "money":
        errors.append(f"{path} must evaluate to money")
    return result_type


def _ast_uses_field(node: Any, field_name: str) -> bool:
    if not isinstance(node, Mapping):
        return False
    if node.get("op") == "field" and node.get("name") == field_name:
        return True
    for child in node.get("args", []):
        if _ast_uses_field(child, field_name):
            return True
    return any(
        _ast_uses_field(node.get(key), field_name)
        for key in ("left", "right", "arg", "then", "else")
    )


def validate_product(
    data: Dict[str, Any],
    verify_files: bool = True,
    allow_embedded_fixtures: bool = False,
) -> ValidationResult:
    enforce_no_customer_data(data)
    errors: List[str] = []
    warnings: List[str] = []
    reject_unknown_keys(data, TOP_LEVEL_KEYS, "$", errors)
    require_keys(
        data,
        ("schema_version", "product", "sources", "evidence", "configurations"),
        "$",
        errors,
    )
    if data.get("schema_version") != SCHEMA_VERSION:
        errors.append(f"$.schema_version must equal {SCHEMA_VERSION}")

    product = data.get("product")
    if not isinstance(product, Mapping):
        errors.append("$.product must be an object")
        product = {}
    else:
        reject_unknown_keys(product, PRODUCT_KEYS, "$.product", errors)
        require_keys(
            product,
            (
                "product_id",
                "name",
                "insurer",
                "currency",
                "jurisdiction",
                "document_version",
                "effective_date",
                "product_type",
                "analysis_only",
                "evidence_refs",
            ),
            "$.product",
            errors,
        )
        if product.get("analysis_only") is not True:
            errors.append("$.product.analysis_only must be true")
        currency = product.get("currency")
        if not isinstance(currency, str) or not re.fullmatch(
            r"[A-Z]{3}", currency or ""
        ):
            errors.append("$.product.currency must be an ISO-style three-letter code")
        for key in (
            "product_id",
            "name",
            "insurer",
            "jurisdiction",
            "document_version",
            "effective_date",
            "product_type",
        ):
            if (
                not isinstance(product.get(key), str)
                or not product.get(key, "").strip()
            ):
                errors.append(f"$.product.{key} must be a non-empty string")

    sources = data.get("sources")
    if not isinstance(sources, list) or not sources:
        errors.append("$.sources must be a non-empty list")
        sources = []
    source_ids: Set[str] = set()
    for index, source in enumerate(sources):
        path = f"$.sources[{index}]"
        if not isinstance(source, Mapping):
            errors.append(f"{path} must be an object")
            continue
        reject_unknown_keys(source, SOURCE_KEYS, path, errors)
        require_keys(
            source,
            ("source_id", "path", "sha256", "document_type", "version", "authority"),
            path,
            errors,
        )
        source_id = source.get("source_id")
        if not isinstance(source_id, str) or not source_id.strip():
            errors.append(f"{path}.source_id must be non-empty")
        elif source_id in source_ids:
            errors.append(f"{path}.source_id duplicates {source_id!r}")
        else:
            source_ids.add(source_id)
        digest = source.get("sha256")
        if not isinstance(digest, str) or not re.fullmatch(
            r"[0-9a-f]{64}", digest or ""
        ):
            errors.append(f"{path}.sha256 must be a lowercase SHA-256")
        source_path = source.get("path")
        embedded = source.get("embedded_fixture") is True
        if embedded:
            if not allow_embedded_fixtures:
                errors.append(f"{path} uses an embedded fixture outside self-test mode")
            if not isinstance(source_path, str) or not source_path.startswith(
                "embedded://"
            ):
                errors.append(f"{path}.path must use embedded:// for embedded fixtures")
            warnings.append(f"{path} is synthetic fixture evidence")
        elif not isinstance(source_path, str) or not source_path:
            errors.append(f"{path}.path must identify a local source artifact")
        elif verify_files:
            artifact = Path(source_path).expanduser()
            if not artifact.is_file():
                errors.append(f"{path}.path does not exist: {source_path}")
            elif isinstance(digest, str) and re.fullmatch(r"[0-9a-f]{64}", digest):
                actual = sha256_file(artifact)
                if actual != digest:
                    errors.append(f"{path}.sha256 does not match {source_path}")
        version = source.get("version")
        document_type = source.get("document_type")
        if not isinstance(document_type, str) or not document_type.strip():
            errors.append(f"{path}.document_type must be a non-empty string")
        if source.get("authority") not in SOURCE_AUTHORITIES:
            errors.append(
                f"{path}.authority must be one of {sorted(SOURCE_AUTHORITIES)}"
            )
        if not isinstance(version, str) or not version.strip():
            errors.append(f"{path}.version is required")
        elif product and source.get("authority") in {
            "contract",
            "rate_table",
            "cash_value_table",
            "illustration",
        }:
            if product.get("document_version") != version:
                errors.append(
                    f"{path}.version conflicts with $.product.document_version"
                )

    evidence = data.get("evidence")
    if not isinstance(evidence, list) or not evidence:
        errors.append("$.evidence must be a non-empty list")
        evidence = []
    evidence_ids: Set[str] = set()
    for index, item in enumerate(evidence):
        path = f"$.evidence[{index}]"
        if not isinstance(item, Mapping):
            errors.append(f"{path} must be an object")
            continue
        reject_unknown_keys(item, EVIDENCE_KEYS, path, errors)
        require_keys(
            item,
            (
                "evidence_id",
                "source_id",
                "raw_text_sha256",
                "extractor",
                "extractor_version",
                "confidence",
                "status",
            ),
            path,
            errors,
        )
        evidence_id = item.get("evidence_id")
        if not isinstance(evidence_id, str) or not evidence_id.strip():
            errors.append(f"{path}.evidence_id must be non-empty")
        elif evidence_id in evidence_ids:
            errors.append(f"{path}.evidence_id duplicates {evidence_id!r}")
        else:
            evidence_ids.add(evidence_id)
        if item.get("source_id") not in source_ids:
            errors.append(f"{path}.source_id references an unknown source")
        page_value = item.get("page")
        sheet_value = item.get("sheet")
        if page_value is None and sheet_value is None:
            errors.append(f"{path} must include page/bbox or sheet/cell_range")
        if page_value is not None and (not _is_int(page_value) or int(page_value) < 1):
            errors.append(f"{path}.page must be a positive integer")
        if item.get("bbox") is not None:
            bbox = item.get("bbox")
            if (
                not isinstance(bbox, list)
                or len(bbox) != 4
                or any(
                    isinstance(value, bool)
                    or not isinstance(value, (int, float, Decimal))
                    for value in bbox
                )
            ):
                errors.append(f"{path}.bbox must contain exactly four numbers")
        if sheet_value is not None:
            if not isinstance(sheet_value, str) or not sheet_value.strip():
                errors.append(f"{path}.sheet must be a non-empty string")
            if (
                not isinstance(item.get("cell_range"), str)
                or not item.get("cell_range", "").strip()
            ):
                errors.append(f"{path}.cell_range is required with sheet evidence")
        raw_text = item.get("raw_text")
        raw_value = item.get("raw_value")
        if raw_text is None and raw_value is None:
            errors.append(f"{path} must retain raw_text or raw_value")
        raw_for_hash = str(raw_text if raw_text is not None else raw_value)
        expected_hash = sha256_text(raw_for_hash)
        if item.get("raw_text_sha256") != expected_hash:
            errors.append(
                f"{path}.raw_text_sha256 does not match retained raw evidence"
            )
        if raw_text is not None and not isinstance(raw_text, str):
            errors.append(f"{path}.raw_text must be a string")
        for key in ("extractor", "extractor_version"):
            if not isinstance(item.get(key), str) or not item.get(key, "").strip():
                errors.append(f"{path}.{key} must be a non-empty string")
        try:
            confidence = decimal_value(item.get("confidence"), f"{path}.confidence")
            if confidence < 0 or confidence > 1:
                errors.append(f"{path}.confidence must be between 0 and 1")
            status = item.get("status")
            if status in {"verified", "extracted"} and confidence < Decimal("0.90"):
                errors.append(
                    f"{path}.{status} evidence requires confidence of at least 0.90"
                )
            if status == "resolved" and not Decimal("0.70") <= confidence < Decimal(
                "0.90"
            ):
                errors.append(
                    f"{path}.resolved evidence confidence must be at least 0.70 and below 0.90"
                )
        except ValidationError as exc:
            errors.extend(exc.errors)
        if item.get("status") not in EVIDENCE_STATUSES:
            errors.append(f"{path}.status must be one of {sorted(EVIDENCE_STATUSES)}")

    if product:
        _validate_evidence_refs(
            product.get("evidence_refs"),
            evidence_ids,
            "$.product.evidence_refs",
            errors,
        )

    configurations = data.get("configurations")
    if not isinstance(configurations, list) or not configurations:
        errors.append("$.configurations must be a non-empty list")
        configurations = []
    configuration_ids: Set[str] = set()
    for index, config in enumerate(configurations):
        path = f"$.configurations[{index}]"
        if not isinstance(config, Mapping):
            errors.append(f"{path} must be an object")
            continue
        reject_unknown_keys(config, CONFIGURATION_KEYS, path, errors)
        require_keys(
            config,
            (
                "configuration_id",
                "dimensions",
                "dimension_evidence_refs",
                "premium_events",
                "annuity_rules",
                "cash_values",
            ),
            path,
            errors,
        )
        configuration_id = config.get("configuration_id")
        if not isinstance(configuration_id, str) or not configuration_id.strip():
            errors.append(f"{path}.configuration_id must be non-empty")
        elif configuration_id in configuration_ids:
            errors.append(f"{path}.configuration_id duplicates {configuration_id!r}")
        else:
            configuration_ids.add(configuration_id)
        if config.get("notes") is not None and not isinstance(config.get("notes"), str):
            errors.append(f"{path}.notes must be a string")
        dimensions = config.get("dimensions")
        if not isinstance(dimensions, Mapping):
            errors.append(f"{path}.dimensions must be an object")
            dimensions = {}
        else:
            reject_unknown_keys(
                dimensions, DIMENSION_KEYS, f"{path}.dimensions", errors
            )
            require_keys(
                dimensions,
                (
                    "published_issue_age",
                    "rate_class",
                    "premium_term_months",
                    "annuity_start_age",
                    "annuity_frequency_per_year",
                    "guarantee_option",
                    "premium_mode",
                    "proportionality_verified",
                ),
                f"{path}.dimensions",
                errors,
            )
            for key in (
                "published_issue_age",
                "premium_term_months",
                "annuity_start_age",
            ):
                if not _is_int(dimensions.get(key)) or int(dimensions.get(key, -1)) < 0:
                    errors.append(
                        f"{path}.dimensions.{key} must be a non-negative integer"
                    )
            if (
                not _is_int(dimensions.get("annuity_frequency_per_year"))
                or int(dimensions.get("annuity_frequency_per_year", 0)) <= 0
            ):
                errors.append(
                    f"{path}.dimensions.annuity_frequency_per_year must be a positive integer"
                )
            for key in ("rate_class", "guarantee_option", "premium_mode"):
                if (
                    not isinstance(dimensions.get(key), str)
                    or not dimensions.get(key, "").strip()
                ):
                    errors.append(f"{path}.dimensions.{key} must be a non-empty string")
            if "product_option_code" in dimensions and not isinstance(
                dimensions.get("product_option_code"), str
            ):
                errors.append(f"{path}.dimensions.product_option_code must be a string")
            if dimensions.get("proportionality_verified") not in {True, False}:
                errors.append(
                    f"{path}.dimensions.proportionality_verified must be boolean"
                )
            if (
                _is_int(dimensions.get("published_issue_age"))
                and _is_int(dimensions.get("annuity_start_age"))
                and int(dimensions["annuity_start_age"])
                < int(dimensions["published_issue_age"])
            ):
                errors.append(
                    f"{path}.dimensions.annuity_start_age cannot precede published_issue_age"
                )
        _validate_evidence_refs(
            config.get("dimension_evidence_refs"),
            evidence_ids,
            f"{path}.dimension_evidence_refs",
            errors,
        )
        if "basic_amount" in config:
            _validate_money_spec(
                config.get("basic_amount"), f"{path}.basic_amount", errors
            )
        premiums = config.get("premium_events")
        if not isinstance(premiums, list) or not premiums:
            errors.append(f"{path}.premium_events must be a non-empty list")
        else:
            for event_index, event in enumerate(premiums):
                event_path = f"{path}.premium_events[{event_index}]"
                _validate_event(event, event_path, evidence_ids, errors)
                if isinstance(event, Mapping):
                    if event.get("status") != "available":
                        errors.append(
                            f"{event_path}.status must be available for contractual premiums"
                        )
                    if event.get("guarantee_basis") != "guaranteed":
                        errors.append(
                            f"{event_path}.guarantee_basis must be guaranteed"
                        )
                    if event.get("scenario_id", "guaranteed") != "guaranteed":
                        errors.append(f"{event_path}.scenario_id must be guaranteed")
        rules = config.get("annuity_rules")
        if not isinstance(rules, list) or not rules:
            errors.append(f"{path}.annuity_rules must be a non-empty list")
        else:
            rule_ids: Set[str] = set()
            scenario_compositions: Dict[str, Set[str]] = {}
            for rule_index, rule in enumerate(rules):
                rule_path = f"{path}.annuity_rules[{rule_index}]"
                if not isinstance(rule, Mapping):
                    errors.append(f"{rule_path} must be an object")
                    continue
                reject_unknown_keys(rule, ANNUITY_RULE_KEYS, rule_path, errors)
                require_keys(
                    rule,
                    (
                        "rule_id",
                        "first_payment_month",
                        "frequency_months",
                        "payment_timing",
                        "amount",
                        "annual_growth_rate",
                        "growth_interval_months",
                        "lifetime",
                        "guarantee_basis",
                        "scenario_id",
                        "rounding",
                        "evidence_refs",
                        "contingency",
                    ),
                    rule_path,
                    errors,
                )
                rule_id = rule.get("rule_id")
                if not isinstance(rule_id, str) or not rule_id:
                    errors.append(f"{rule_path}.rule_id must be non-empty")
                elif rule_id in rule_ids:
                    errors.append(f"{rule_path}.rule_id duplicates {rule_id!r}")
                else:
                    rule_ids.add(rule_id)
                first_payment_month = rule.get("first_payment_month")
                if not _is_int(first_payment_month) or int(first_payment_month) < 0:
                    errors.append(
                        f"{rule_path}.first_payment_month must be a non-negative integer"
                    )
                for key in ("frequency_months", "growth_interval_months"):
                    if not _is_int(rule.get(key)) or int(rule.get(key, 0)) <= 0:
                        errors.append(f"{rule_path}.{key} must be a positive integer")
                if rule.get("payment_timing") not in {"advance", "arrears", "explicit"}:
                    errors.append(
                        f"{rule_path}.payment_timing must be advance, arrears, or explicit"
                    )
                if rule.get("rounding") not in {"none", "cent", "whole"}:
                    errors.append(f"{rule_path}.rounding must be none, cent, or whole")
                _validate_money_spec(rule.get("amount"), f"{rule_path}.amount", errors)
                try:
                    if decimal_value(
                        rule.get("annual_growth_rate"),
                        f"{rule_path}.annual_growth_rate",
                    ) <= Decimal("-1"):
                        errors.append(
                            f"{rule_path}.annual_growth_rate must be greater than -1"
                        )
                except ValidationError as exc:
                    errors.extend(exc.errors)
                if rule.get("guarantee_basis") not in GUARANTEE_BASES:
                    errors.append(f"{rule_path}.guarantee_basis must be explicit")
                elif (
                    rule.get("guarantee_basis") == "guaranteed"
                    and rule.get("scenario_id") != "guaranteed"
                ):
                    errors.append(
                        f"{rule_path}.scenario_id must be guaranteed for guaranteed values"
                    )
                elif (
                    rule.get("guarantee_basis") in {"illustrated", "non_guaranteed"}
                    and rule.get("scenario_id") == "guaranteed"
                ):
                    errors.append(
                        f"{rule_path}.scenario_id must name a separate non-guaranteed scenario"
                    )
                composition = rule.get("scenario_composition")
                if rule.get("guarantee_basis") in {
                    "illustrated",
                    "non_guaranteed",
                } and composition not in {
                    "total",
                    "incremental",
                }:
                    errors.append(
                        f"{rule_path}.scenario_composition must be total or incremental for non-guaranteed values"
                    )
                elif rule.get("guarantee_basis") in {"illustrated", "non_guaranteed"}:
                    scenario_compositions.setdefault(
                        str(rule.get("scenario_id")), set()
                    ).add(str(composition))
                if rule.get("guarantee_basis") == "guaranteed" and composition not in {
                    None,
                    "total",
                }:
                    errors.append(
                        f"{rule_path}.guaranteed values cannot be incremental"
                    )
                if (
                    not isinstance(rule.get("scenario_id"), str)
                    or not rule.get("scenario_id", "").strip()
                ):
                    errors.append(f"{rule_path}.scenario_id must be a non-empty string")
                if rule.get("lifetime") not in {True, False}:
                    errors.append(f"{rule_path}.lifetime must be boolean")
                if rule.get("lifetime") is True:
                    if (
                        not _is_int(rule.get("contract_end_age"))
                        or int(rule.get("contract_end_age", -1)) < 0
                    ):
                        errors.append(
                            f"{rule_path}.contract_end_age is required for deterministic lifetime expansion"
                        )
                    elif _is_int(dimensions.get("published_issue_age")) and _is_int(
                        first_payment_month
                    ):
                        contract_end_month = (
                            int(rule["contract_end_age"])
                            - int(dimensions["published_issue_age"])
                        ) * 12
                        if contract_end_month < int(first_payment_month):
                            errors.append(
                                f"{rule_path}.contract_end_age ends before first_payment_month"
                            )
                    if (
                        rule.get("last_payment_month") is not None
                        or rule.get("payment_count") is not None
                    ):
                        errors.append(
                            f"{rule_path} lifetime rules cannot also set last_payment_month or payment_count"
                        )
                elif rule.get("lifetime") is False:
                    termination_fields = sum(
                        rule.get(key) is not None
                        for key in ("last_payment_month", "payment_count")
                    )
                    if termination_fields != 1:
                        errors.append(
                            f"{rule_path} requires exactly one of last_payment_month or payment_count"
                        )
                    if rule.get("contract_end_age") is not None:
                        errors.append(
                            f"{rule_path}.contract_end_age is only valid for lifetime rules"
                        )
                if rule.get("last_payment_month") is not None and (
                    not _is_int(rule.get("last_payment_month"))
                    or int(rule.get("last_payment_month")) < 0
                ):
                    errors.append(
                        f"{rule_path}.last_payment_month must be a non-negative integer"
                    )
                elif (
                    rule.get("last_payment_month") is not None
                    and _is_int(first_payment_month)
                    and int(rule["last_payment_month"]) < int(first_payment_month)
                ):
                    errors.append(
                        f"{rule_path}.last_payment_month cannot precede first_payment_month"
                    )
                if rule.get("payment_count") is not None and (
                    not _is_int(rule.get("payment_count"))
                    or int(rule.get("payment_count")) <= 0
                ):
                    errors.append(
                        f"{rule_path}.payment_count must be a positive integer"
                    )
                if rule.get("guaranteed_period_months") is not None and (
                    not _is_int(rule.get("guaranteed_period_months"))
                    or int(rule.get("guaranteed_period_months")) < 0
                ):
                    errors.append(
                        f"{rule_path}.guaranteed_period_months must be a non-negative integer"
                    )
                _validate_evidence_refs(
                    rule.get("evidence_refs"),
                    evidence_ids,
                    f"{rule_path}.evidence_refs",
                    errors,
                )
            for scenario_id, compositions in sorted(scenario_compositions.items()):
                if len(compositions) > 1:
                    errors.append(
                        f"{path}.annuity_rules scenario {scenario_id!r} mixes total and incremental composition"
                    )
        cash_values = config.get("cash_values")
        if not isinstance(cash_values, list):
            errors.append(f"{path}.cash_values must be a list")
        else:
            cash_value_keys: Set[Tuple[str, int, int]] = set()
            for event_index, event in enumerate(cash_values):
                _validate_event(
                    event,
                    f"{path}.cash_values[{event_index}]",
                    evidence_ids,
                    errors,
                    require_amount=False,
                )
                if isinstance(event, Mapping) and event.get("guarantee_basis") in {
                    "illustrated",
                    "non_guaranteed",
                }:
                    if event.get("scenario_composition") != "total":
                        errors.append(
                            f"{path}.cash_values[{event_index}].scenario_composition must be total"
                        )
                if (
                    isinstance(event, Mapping)
                    and _is_int(event.get("policy_month"))
                    and _is_int(event.get("event_order"))
                ):
                    key = (
                        str(event.get("scenario_id", "guaranteed")),
                        int(event["policy_month"]),
                        int(event["event_order"]),
                    )
                    if key in cash_value_keys:
                        errors.append(
                            f"{path}.cash_values[{event_index}] duplicates scenario/month/order {key!r}"
                        )
                    cash_value_keys.add(key)
        maturities = config.get("maturity_events", [])
        if not isinstance(maturities, list):
            errors.append(f"{path}.maturity_events must be a list")
        else:
            for event_index, event in enumerate(maturities):
                _validate_event(
                    event,
                    f"{path}.maturity_events[{event_index}]",
                    evidence_ids,
                    errors,
                    False,
                )
        death = config.get("death_benefit")
        if death is not None:
            death_path = f"{path}.death_benefit"
            if not isinstance(death, Mapping):
                errors.append(f"{death_path} must be an object")
            else:
                reject_unknown_keys(death, DEATH_BENEFIT_KEYS, death_path, errors)
                require_keys(
                    death,
                    (
                        "guarantee_basis",
                        "scenario_id",
                        "boundary_order",
                        "evidence_refs",
                    ),
                    death_path,
                    errors,
                )
                if ("schedule" in death) == ("rule" in death):
                    errors.append(
                        f"{death_path} must contain exactly one of schedule or rule"
                    )
                if death.get("guarantee_basis") not in GUARANTEE_BASES:
                    errors.append(f"{death_path}.guarantee_basis must be explicit")
                if death.get("boundary_order") not in {
                    "before_annuity",
                    "after_annuity",
                    "unresolved",
                }:
                    errors.append(f"{death_path}.boundary_order is invalid")
                if (
                    death.get("guarantee_basis") == "guaranteed"
                    and death.get("scenario_id") != "guaranteed"
                ):
                    errors.append(
                        f"{death_path}.scenario_id must be guaranteed for guaranteed values"
                    )
                if (
                    death.get("guarantee_basis") in {"illustrated", "non_guaranteed"}
                    and death.get("scenario_id") == "guaranteed"
                ):
                    errors.append(
                        f"{death_path}.scenario_id must name a separate non-guaranteed scenario"
                    )
                if (
                    not isinstance(death.get("scenario_id"), str)
                    or not death.get("scenario_id", "").strip()
                ):
                    errors.append(
                        f"{death_path}.scenario_id must be a non-empty string"
                    )
                if death.get("schedule") is not None:
                    if not isinstance(death.get("schedule"), list):
                        errors.append(f"{death_path}.schedule must be a list")
                    else:
                        death_schedule_keys: Set[Tuple[str, int, int]] = set()
                        for event_index, event in enumerate(death["schedule"]):
                            _validate_event(
                                event,
                                f"{death_path}.schedule[{event_index}]",
                                evidence_ids,
                                errors,
                                False,
                            )
                            if isinstance(event, Mapping) and event.get(
                                "guarantee_basis"
                            ) in {"illustrated", "non_guaranteed"}:
                                if event.get("scenario_composition") != "total":
                                    errors.append(
                                        f"{death_path}.schedule[{event_index}].scenario_composition must be total"
                                    )
                            if (
                                isinstance(event, Mapping)
                                and _is_int(event.get("policy_month"))
                                and _is_int(event.get("event_order"))
                            ):
                                key = (
                                    str(event.get("scenario_id", "guaranteed")),
                                    int(event["policy_month"]),
                                    int(event["event_order"]),
                                )
                                if key in death_schedule_keys:
                                    errors.append(
                                        f"{death_path}.schedule[{event_index}] duplicates scenario/month/order {key!r}"
                                    )
                                death_schedule_keys.add(key)
                if death.get("rule") is not None:
                    _validate_ast(
                        death.get("rule"),
                        f"{death_path}.rule",
                        evidence_ids,
                        errors,
                        require_money_result=True,
                    )
                    if _ast_uses_field(death.get("rule"), "cash_value") and death.get(
                        "cash_value_timing"
                    ) not in {"policy_month_state", "respect_event_order"}:
                        errors.append(
                            f"{death_path}.cash_value_timing is required when the rule uses cash_value"
                        )
                elif death.get("cash_value_timing") is not None:
                    errors.append(
                        f"{death_path}.cash_value_timing is only valid for rule-based benefits"
                    )
                if death.get("lookup", "exact") not in {"exact", "at_or_before"}:
                    errors.append(f"{death_path}.lookup must be exact or at_or_before")
                continuation = death.get("beneficiary_continuation")
                if continuation is not None:
                    continuation_path = f"{death_path}.beneficiary_continuation"
                    if not isinstance(continuation, Mapping):
                        errors.append(f"{continuation_path} must be an object")
                    else:
                        reject_unknown_keys(
                            continuation,
                            BENEFICIARY_CONTINUATION_KEYS,
                            continuation_path,
                            errors,
                        )
                        require_keys(
                            continuation,
                            ("mode", "through_policy_month", "evidence_refs"),
                            continuation_path,
                            errors,
                        )
                        if continuation.get("mode") != "remaining_guaranteed_annuity":
                            errors.append(
                                f"{continuation_path}.mode must be remaining_guaranteed_annuity"
                            )
                        through_month = continuation.get("through_policy_month")
                        if not _is_int(through_month) or int(through_month) < 0:
                            errors.append(
                                f"{continuation_path}.through_policy_month must be a non-negative integer"
                            )
                        _validate_evidence_refs(
                            continuation.get("evidence_refs"),
                            evidence_ids,
                            f"{continuation_path}.evidence_refs",
                            errors,
                        )
                _validate_evidence_refs(
                    death.get("evidence_refs"),
                    evidence_ids,
                    f"{death_path}.evidence_refs",
                    errors,
                )
        loan = config.get("loan_terms")
        if loan is not None:
            loan_path = f"{path}.loan_terms"
            if not isinstance(loan, Mapping):
                errors.append(f"{loan_path} must be an object")
            else:
                reject_unknown_keys(loan, LOAN_TERM_KEYS, loan_path, errors)
                require_keys(loan, ("available", "evidence_refs"), loan_path, errors)
                if loan.get("available") not in {True, False}:
                    errors.append(f"{loan_path}.available must be boolean")
                if loan.get("interest_rate_status") not in {
                    None,
                    "available",
                    "missing",
                    "not_applicable",
                }:
                    errors.append(f"{loan_path}.interest_rate_status is invalid")
                if (
                    loan.get("interest_rate_status") == "available"
                    and loan.get("interest_rate") is None
                ):
                    errors.append(
                        f"{loan_path}.interest_rate is required when its status is available"
                    )
                if loan.get("interest_rate") is not None:
                    try:
                        if decimal_value(
                            loan.get("interest_rate"), f"{loan_path}.interest_rate"
                        ) <= Decimal("-1"):
                            errors.append(
                                f"{loan_path}.interest_rate must be greater than -1"
                            )
                    except ValidationError as exc:
                        errors.extend(exc.errors)
                if loan.get("eligible_value") is not None and not isinstance(
                    loan.get("eligible_value"), str
                ):
                    errors.append(f"{loan_path}.eligible_value must be a string")
                if loan.get("limit_ratio") is not None:
                    try:
                        ratio = decimal_value(
                            loan.get("limit_ratio"), f"{loan_path}.limit_ratio"
                        )
                        if ratio < 0 or ratio > 1:
                            errors.append(
                                f"{loan_path}.limit_ratio must be between 0 and 1"
                            )
                    except ValidationError as exc:
                        errors.extend(exc.errors)
                _validate_evidence_refs(
                    loan.get("evidence_refs"),
                    evidence_ids,
                    f"{loan_path}.evidence_refs",
                    errors,
                )

    assumptions = data.get("analysis_assumptions", {})
    if not isinstance(assumptions, Mapping):
        errors.append("$.analysis_assumptions must be an object")
    else:
        reject_unknown_keys(
            assumptions, ASSUMPTION_KEYS, "$.analysis_assumptions", errors
        )
        for key in ("target_survival_ages", "target_death_ages"):
            values = assumptions.get(key, [])
            if not isinstance(values, list) or any(
                not _is_int(v) or int(v) < 0 for v in values
            ):
                errors.append(
                    f"$.analysis_assumptions.{key} must be a list of non-negative integer ages"
                )
        rates = assumptions.get("inflation_rates", [])
        if not isinstance(rates, list):
            errors.append("$.analysis_assumptions.inflation_rates must be a list")
        else:
            for index, value in enumerate(rates):
                try:
                    if decimal_value(
                        value, f"$.analysis_assumptions.inflation_rates[{index}]"
                    ) <= Decimal("-1"):
                        errors.append(
                            f"$.analysis_assumptions.inflation_rates[{index}] must be greater than -1"
                        )
                except ValidationError as exc:
                    errors.extend(exc.errors)
        if assumptions.get("analysis_end_age") is not None and (
            not _is_int(assumptions.get("analysis_end_age"))
            or int(assumptions.get("analysis_end_age")) < 0
        ):
            errors.append(
                "$.analysis_assumptions.analysis_end_age must be a non-negative integer"
            )
        elif assumptions.get("analysis_end_age") is not None:
            issue_ages = [
                int(config["dimensions"]["published_issue_age"])
                for config in configurations
                if isinstance(config, Mapping)
                and isinstance(config.get("dimensions"), Mapping)
                and _is_int(config["dimensions"].get("published_issue_age"))
            ]
            if issue_ages and int(assumptions["analysis_end_age"]) < max(issue_ages):
                errors.append(
                    "$.analysis_assumptions.analysis_end_age cannot precede a published issue age"
                )
        if assumptions.get("benchmark_selection") is not None and not isinstance(
            assumptions.get("benchmark_selection"), str
        ):
            errors.append("$.analysis_assumptions.benchmark_selection must be a string")

    unresolved_paths = find_unresolved_paths(data)
    if unresolved_paths:
        warnings.append(
            f"semantic/deterministic review remains unresolved at {len(unresolved_paths)} path(s); calculation is blocked"
        )
    if not errors:
        try:
            normalized = _normalize_validated_product(data)
            for index, config in enumerate(normalized["configurations"]):
                if decimal_value(config["calculation_context"]["total_premium"]) <= 0:
                    errors.append(
                        f"$.configurations[{index}].premium_events must produce positive total premium"
                    )
        except ValidationError as exc:
            errors.extend(exc.errors)

    return ValidationResult(not errors, tuple(errors), tuple(sorted(set(warnings))))


def _direct_unit_factor(unit: str, currency: str) -> Optional[Decimal]:
    factors = {
        currency: DECIMAL_ONE,
        f"thousand_{currency}": Decimal("1000"),
        f"ten_thousand_{currency}": Decimal("10000"),
        f"million_{currency}": Decimal("1000000"),
    }
    return factors.get(unit)


def normalize_money(
    spec: Mapping[str, Any], currency: str, context: Mapping[str, Decimal], path: str
) -> Dict[str, Any]:
    if spec.get("normalized") is True:
        if spec.get("currency") != currency or spec.get("unit") != currency:
            raise ValidationError(
                [f"{path} normalized currency conflicts with product currency"]
            )
        decimal_value(spec.get("value"), f"{path}.value")
        return dict(spec)
    raw_value = decimal_value(spec.get("value"), f"{path}.value")
    unit = str(spec.get("unit", ""))
    factor = _direct_unit_factor(unit, currency)
    basis_kind: Optional[str] = None
    basis_value: Optional[Decimal] = None
    if factor is not None:
        unexpected_basis = {
            key
            for key in ("basis_kind", "basis_value", "basis_unit")
            if spec.get(key) is not None
        }
        if unexpected_basis:
            raise ValidationError(
                [
                    f"{path} absolute unit cannot carry basis metadata: {sorted(unexpected_basis)}"
                ]
            )
        result = raw_value * factor
    else:
        suffixes = {
            f"{currency}_per_1000_basic_amount": (
                "basic_amount",
                Decimal("1000"),
                False,
            ),
            f"{currency}_per_1000_annual_premium": (
                "annual_premium",
                Decimal("1000"),
                False,
            ),
            f"{currency}_per_1000_total_premium": (
                "total_premium",
                Decimal("1000"),
                False,
            ),
            "percent_of_basic_amount": ("basic_amount", Decimal("100"), True),
            "percent_of_annual_premium": ("annual_premium", Decimal("100"), True),
            "percent_of_total_premium": ("total_premium", Decimal("100"), True),
            "decimal_of_basic_amount": ("basic_amount", DECIMAL_ONE, True),
            "decimal_of_annual_premium": ("annual_premium", DECIMAL_ONE, True),
            "decimal_of_total_premium": ("total_premium", DECIMAL_ONE, True),
        }
        rule = suffixes.get(unit)
        if rule is None:
            raise ValidationError(
                [
                    f"{path}.unit {unit!r} is unsupported or conflicts with product currency {currency}"
                ]
            )
        expected_basis, divisor, _ = rule
        basis_kind = spec.get("basis_kind")
        if basis_kind != expected_basis:
            raise ValidationError(
                [f"{path}.basis_kind must be {expected_basis!r} for unit {unit!r}"]
            )
        if spec.get("basis_value") is not None:
            basis_unit = spec.get("basis_unit")
            basis_factor = _direct_unit_factor(str(basis_unit), currency)
            if basis_factor is None:
                raise ValidationError(
                    [f"{path}.basis_unit must be an absolute {currency} unit"]
                )
            basis_value = (
                decimal_value(spec.get("basis_value"), f"{path}.basis_value")
                * basis_factor
            )
            if expected_basis in context and context[expected_basis] != basis_value:
                raise ValidationError(
                    [
                        f"{path}.basis_value conflicts with the configuration {expected_basis}"
                    ]
                )
        else:
            if spec.get("basis_unit") is not None:
                raise ValidationError([f"{path}.basis_unit requires basis_value"])
            basis_value = context.get(expected_basis)
        if basis_value is None:
            raise ValidationError([f"{path} cannot resolve basis {expected_basis!r}"])
        factor = basis_value / divisor
        result = raw_value * factor
    rounding = spec.get("rounding", "none")
    if rounding == "cent":
        result = result.quantize(Decimal("0.01"), rounding=ROUND_HALF_EVEN)
    elif rounding == "whole":
        result = result.quantize(Decimal("1"), rounding=ROUND_HALF_EVEN)
    elif rounding != "none":
        raise ValidationError([f"{path}.rounding must be none, cent, or whole"])
    if result < 0:
        raise ValidationError([f"{path} normalizes to a negative amount"])
    normalized = {
        "value": decimal_string(result),
        "unit": currency,
        "currency": currency,
        "normalized": True,
        "source_value": decimal_string(raw_value),
        "source_unit": unit,
        "conversion_factor": decimal_string(factor or DECIMAL_ONE),
    }
    if basis_kind is not None:
        normalized["basis_kind"] = basis_kind
        normalized["basis_value_used"] = decimal_string(basis_value or DECIMAL_ZERO)
    return normalized


def money_value(spec: Mapping[str, Any]) -> Decimal:
    if spec.get("normalized") is not True:
        raise ValidationError(["money value must be normalized before calculation"])
    return decimal_value(spec.get("value"), "normalized money value")


def _normalize_event(
    event: Mapping[str, Any], currency: str, context: Mapping[str, Decimal], path: str
) -> Dict[str, Any]:
    result = dict(event)
    if event.get("status") == "available":
        result["amount"] = normalize_money(
            event["amount"], currency, context, f"{path}.amount"
        )
    return result


def _normalize_ast(
    node: Mapping[str, Any], currency: str, context: Mapping[str, Decimal], path: str
) -> Dict[str, Any]:
    result = dict(node)
    op = node.get("op")
    if op == "constant":
        result["amount"] = normalize_money(
            node["amount"], currency, context, f"{path}.amount"
        )
    elif op in {"add", "multiply", "max", "min"}:
        result["args"] = [
            _normalize_ast(child, currency, context, f"{path}.args[{index}]")
            for index, child in enumerate(node.get("args", []))
        ]
    elif op == "subtract":
        result["left"] = _normalize_ast(node["left"], currency, context, f"{path}.left")
        result["right"] = _normalize_ast(
            node["right"], currency, context, f"{path}.right"
        )
    elif op == "floor_zero":
        result["arg"] = _normalize_ast(node["arg"], currency, context, f"{path}.arg")
    elif op == "if_period":
        result["then"] = _normalize_ast(node["then"], currency, context, f"{path}.then")
        result["else"] = _normalize_ast(node["else"], currency, context, f"{path}.else")
    return result


def _normalize_validated_product(data: Dict[str, Any]) -> Dict[str, Any]:
    result = deep_copy_json(data)
    currency = result["product"]["currency"]
    for config_index, config in enumerate(result["configurations"]):
        path = f"$.configurations[{config_index}]"
        context: Dict[str, Decimal] = {}
        if config.get("basic_amount") is not None:
            config["basic_amount"] = normalize_money(
                config["basic_amount"], currency, context, f"{path}.basic_amount"
            )
            context["basic_amount"] = money_value(config["basic_amount"])
        normalized_premiums: List[Dict[str, Any]] = []
        for event_index, event in enumerate(config["premium_events"]):
            normalized_premiums.append(
                _normalize_event(
                    event, currency, context, f"{path}.premium_events[{event_index}]"
                )
            )
        config["premium_events"] = normalized_premiums
        total_premium = sum(
            (money_value(event["amount"]) for event in normalized_premiums),
            DECIMAL_ZERO,
        )
        annual_premium = sum(
            (
                money_value(event["amount"])
                for event in normalized_premiums
                if int(event["policy_month"]) < 12
            ),
            DECIMAL_ZERO,
        )
        context["total_premium"] = total_premium
        context["annual_premium"] = annual_premium
        config["annuity_rules"] = [
            {
                **rule,
                "amount": normalize_money(
                    rule["amount"],
                    currency,
                    context,
                    f"{path}.annuity_rules[{index}].amount",
                ),
            }
            for index, rule in enumerate(config["annuity_rules"])
        ]
        config["cash_values"] = [
            _normalize_event(event, currency, context, f"{path}.cash_values[{index}]")
            for index, event in enumerate(config["cash_values"])
        ]
        config["maturity_events"] = [
            _normalize_event(
                event, currency, context, f"{path}.maturity_events[{index}]"
            )
            for index, event in enumerate(config.get("maturity_events", []))
        ]
        death = config.get("death_benefit")
        if death:
            if death.get("schedule") is not None:
                death["schedule"] = [
                    _normalize_event(
                        event,
                        currency,
                        context,
                        f"{path}.death_benefit.schedule[{index}]",
                    )
                    for index, event in enumerate(death["schedule"])
                ]
            if death.get("rule") is not None:
                death["rule"] = _normalize_ast(
                    death["rule"], currency, context, f"{path}.death_benefit.rule"
                )
        config["calculation_context"] = {
            "total_premium": decimal_string(total_premium),
            "annual_premium": decimal_string(annual_premium),
            "currency": currency,
        }
    result["normalized_by"] = {
        "tool": "annuity-product-intelligence",
        "version": TOOL_VERSION,
    }
    return result


def normalize_product(
    data: Dict[str, Any],
    verify_files: bool = True,
    allow_embedded_fixtures: bool = False,
) -> Dict[str, Any]:
    validation = validate_product(
        data,
        verify_files=verify_files,
        allow_embedded_fixtures=allow_embedded_fixtures,
    )
    if not validation.valid:
        raise ValidationError(validation.errors, validation.warnings)
    unresolved_paths = find_unresolved_paths(data)
    if unresolved_paths:
        raise ReviewRequiredError(
            f"calculation blocked until unresolved input paths are resolved ({len(unresolved_paths)} path(s))"
        )
    return _normalize_validated_product(data)


def _round_payment(value: Decimal, rounding: str) -> Decimal:
    if rounding == "cent":
        return value.quantize(Decimal("0.01"), rounding=ROUND_HALF_EVEN)
    if rounding == "whole":
        return value.quantize(Decimal("1"), rounding=ROUND_HALF_EVEN)
    return value


def _annual_effective_factor(rate: Decimal, elapsed_months: int) -> Decimal:
    if elapsed_months == 0 or rate == 0:
        return DECIMAL_ONE
    with localcontext() as context:
        context.prec = 50
        return (
            ((DECIMAL_ONE + rate).ln() * Decimal(elapsed_months)) / Decimal(12)
        ).exp()


def expand_annuity_rule(
    rule: Mapping[str, Any], dimensions: Mapping[str, Any], currency: str
) -> List[Dict[str, Any]]:
    first = int(rule["first_payment_month"])
    frequency = int(rule["frequency_months"])
    if rule.get("lifetime") is True:
        issue_age = int(dimensions["published_issue_age"])
        last = (int(rule["contract_end_age"]) - issue_age) * 12
    elif rule.get("last_payment_month") is not None:
        last = int(rule["last_payment_month"])
    else:
        last = first + (int(rule["payment_count"]) - 1) * frequency
    if last < first:
        raise ValidationError(
            [f"annuity rule {rule.get('rule_id')} ends before its first payment"]
        )
    base = money_value(rule["amount"])
    growth = decimal_value(rule.get("annual_growth_rate", "0"), "annual_growth_rate")
    growth_interval = int(rule.get("growth_interval_months", 12))
    events: List[Dict[str, Any]] = []
    month = first
    while month <= last:
        elapsed_growth_months = max(
            0, ((month - first) // growth_interval) * growth_interval
        )
        amount = _round_payment(
            base * _annual_effective_factor(growth, elapsed_growth_months),
            rule.get("rounding", "none"),
        )
        events.append(
            {
                "scenario_id": rule.get("scenario_id", "guaranteed"),
                "policy_month": month,
                "event_order": 30,
                "event_type": "annuity_payment",
                "owner_direction": "inflow",
                "amount": decimal_string(amount),
                "currency": currency,
                "guarantee_basis": rule["guarantee_basis"],
                "scenario_composition": rule.get("scenario_composition", "total"),
                "contingency": rule.get("contingency", "survival"),
                "evidence_refs": list(rule.get("evidence_refs", [])),
                "rule_id": rule.get("rule_id"),
            }
        )
        month += frequency
    return events


def build_cashflows(normalized: Dict[str, Any]) -> Dict[str, Any]:
    currency = normalized["product"]["currency"]
    outputs: List[Dict[str, Any]] = []
    for config in normalized["configurations"]:
        events: List[Dict[str, Any]] = []
        for event in config["premium_events"]:
            events.append(
                {
                    "scenario_id": event.get("scenario_id", "guaranteed"),
                    "policy_month": int(event["policy_month"]),
                    "event_order": int(event["event_order"]),
                    "event_type": "premium",
                    "owner_direction": "outflow",
                    "amount": decimal_string(money_value(event["amount"])),
                    "currency": currency,
                    "guarantee_basis": event.get("guarantee_basis", "guaranteed"),
                    "contingency": event.get("contingency", "contractual"),
                    "evidence_refs": list(event.get("evidence_refs", [])),
                }
            )
        for rule in config["annuity_rules"]:
            events.extend(expand_annuity_rule(rule, config["dimensions"], currency))
        for event in config.get("maturity_events", []):
            if event.get("status") != "available":
                continue
            events.append(
                {
                    "scenario_id": event.get("scenario_id", "guaranteed"),
                    "policy_month": int(event["policy_month"]),
                    "event_order": int(event["event_order"]),
                    "event_type": "maturity_benefit",
                    "owner_direction": "inflow",
                    "amount": decimal_string(money_value(event["amount"])),
                    "currency": currency,
                    "guarantee_basis": event["guarantee_basis"],
                    "scenario_composition": event.get("scenario_composition", "total"),
                    "contingency": event.get("contingency", "survival"),
                    "evidence_refs": list(event.get("evidence_refs", [])),
                }
            )
        events.sort(
            key=lambda item: (
                item["policy_month"],
                item["event_order"],
                item["event_type"],
                item["scenario_id"],
            )
        )
        outputs.append(
            {
                "configuration_id": config["configuration_id"],
                "currency": currency,
                "events": events,
                "cash_values": stable_json_data(config["cash_values"]),
                "death_benefit": stable_json_data(config.get("death_benefit")),
            }
        )
    return {
        "schema_version": SCHEMA_VERSION,
        "tool_version": TOOL_VERSION,
        "product_id": normalized["product"]["product_id"],
        "configurations": outputs,
    }


def scenario_events(
    events: Sequence[Mapping[str, Any]],
    scenario_id: str,
    horizon_month: Optional[int] = None,
) -> List[Dict[str, Any]]:
    scenario_compositions: Dict[str, Set[str]] = {}
    if scenario_id != "guaranteed":
        for event in events:
            if event.get("scenario_id", "guaranteed") == scenario_id:
                event_type = str(event.get("event_type"))
                scenario_compositions.setdefault(event_type, set()).add(
                    str(event.get("scenario_composition", "total"))
                )
    mixed = {
        event_type
        for event_type, values in scenario_compositions.items()
        if len(values) > 1
    }
    if mixed:
        raise ValidationError(
            [
                f"scenario {scenario_id} mixes total and incremental composition for {sorted(mixed)}"
            ]
        )
    selected: List[Dict[str, Any]] = []
    for event in events:
        if horizon_month is not None and int(event["policy_month"]) > horizon_month:
            continue
        event_scenario = event.get("scenario_id", "guaranteed")
        event_type = str(event.get("event_type"))
        composition = next(iter(scenario_compositions.get(event_type, {"none"})))
        if event_scenario == scenario_id or (
            event_scenario == "guaranteed" and composition != "total"
        ):
            selected.append(dict(event))
    return selected


def events_through_boundary(
    events: Sequence[Mapping[str, Any]],
    policy_month: int,
    event_order: int,
    scenario_id: str,
) -> List[Dict[str, Any]]:
    return [
        dict(event)
        for event in scenario_events(events, scenario_id)
        if (int(event["policy_month"]), int(event.get("event_order", 0)))
        <= (policy_month, event_order)
    ]


def cash_value_at(
    config: Mapping[str, Any],
    policy_month: int,
    scenario_id: str = "guaranteed",
    lookup: str = "exact",
    boundary_event_order: Optional[int] = None,
) -> Tuple[str, Optional[Decimal], List[str], Optional[int]]:
    candidates: List[Mapping[str, Any]] = []
    all_values = list(config.get("cash_values", []))
    scenario_values = [
        item
        for item in all_values
        if item.get("scenario_id", "guaranteed") == scenario_id
    ]
    selected_values = (
        scenario_values
        if scenario_id != "guaranteed" and scenario_values
        else [
            item
            for item in all_values
            if item.get("scenario_id", "guaranteed") == "guaranteed"
        ]
    )
    for item in selected_values:
        month = int(item["policy_month"])
        if (
            boundary_event_order is not None
            and month == policy_month
            and int(item.get("event_order", 0)) > boundary_event_order
        ):
            continue
        if month == policy_month or (
            lookup == "at_or_before" and month <= policy_month
        ):
            candidates.append(item)
    if not candidates:
        return "missing", None, [], None
    selected = max(
        candidates,
        key=lambda item: (
            int(item["policy_month"]),
            int(item.get("event_order", 0)),
            item.get("scenario_id", "guaranteed") == scenario_id,
        ),
    )
    status = selected.get("status", "missing")
    if status != "available":
        return (
            status,
            None,
            list(selected.get("evidence_refs", [])),
            int(selected["policy_month"]),
        )
    return (
        "available",
        money_value(selected["amount"]),
        list(selected.get("evidence_refs", [])),
        int(selected["policy_month"]),
    )


def _evaluate_ast(
    node: Mapping[str, Any], context: Mapping[str, Optional[Decimal]]
) -> Tuple[Optional[Decimal], Dict[str, Any]]:
    op = node["op"]
    trace: Dict[str, Any] = {
        "op": op,
        "evidence_refs": list(node.get("evidence_refs", [])),
    }
    if op == "constant":
        value = money_value(node["amount"])
        trace["value"] = decimal_string(value)
        return value, trace
    if op == "scalar_constant":
        value = decimal_value(node["value"])
        trace["value"] = decimal_string(value)
        return value, trace
    if op == "field":
        value = context.get(node["name"])
        trace.update(
            {
                "name": node["name"],
                "value": None if value is None else decimal_string(value),
            }
        )
        return value, trace
    if op == "if_period":
        month_value = context.get("policy_month")
        if month_value is None:
            trace["status"] = "missing_policy_month"
            return None, trace
        month = int(month_value)
        minimum = node.get("policy_month_min")
        maximum = node.get("policy_month_max")
        matched = (minimum is None or month >= int(minimum)) and (
            maximum is None or month <= int(maximum)
        )
        child = node["then"] if matched else node["else"]
        value, child_trace = _evaluate_ast(child, context)
        trace.update({"matched": matched, "child": child_trace})
        return value, trace
    if op == "subtract":
        left, left_trace = _evaluate_ast(node["left"], context)
        right, right_trace = _evaluate_ast(node["right"], context)
        trace["children"] = [left_trace, right_trace]
        if left is None or right is None:
            trace["status"] = "missing_operand"
            return None, trace
        value = left - right
    elif op == "floor_zero":
        child, child_trace = _evaluate_ast(node["arg"], context)
        trace["children"] = [child_trace]
        if child is None:
            trace["status"] = "missing_operand"
            return None, trace
        value = max(child, DECIMAL_ZERO)
    else:
        children = [_evaluate_ast(child, context) for child in node["args"]]
        trace["children"] = [child_trace for _, child_trace in children]
        values = [value for value, _ in children]
        if any(value is None for value in values):
            trace["status"] = "missing_operand"
            return None, trace
        concrete = [value for value in values if value is not None]
        if op == "add":
            value = sum(concrete, DECIMAL_ZERO)
        elif op == "multiply":
            value = DECIMAL_ONE
            for child in concrete:
                value *= child
        elif op == "max":
            value = max(concrete)
        elif op == "min":
            value = min(concrete)
        else:
            raise ValidationError([f"unsupported AST operation {op}"])
    trace["value"] = decimal_string(value)
    return value, trace


def death_benefit_at(
    config: Mapping[str, Any],
    events: Sequence[Mapping[str, Any]],
    policy_month: int,
    scenario_id: str = "guaranteed",
    boundary_event_order: Optional[int] = None,
) -> Dict[str, Any]:
    definition = config.get("death_benefit")
    if not definition:
        return {"status": "missing", "amount": None, "evidence_refs": [], "trace": None}
    definition_scenario = definition.get("scenario_id", "guaranteed")
    if definition_scenario not in {"guaranteed", scenario_id}:
        return {
            "status": "missing",
            "amount": None,
            "evidence_refs": list(definition.get("evidence_refs", [])),
            "trace": {
                "type": "scenario_gate",
                "definition_scenario": definition_scenario,
            },
        }
    if definition.get("schedule") is not None:
        lookup = definition.get("lookup", "exact")
        candidates = []
        all_values = list(definition["schedule"])
        scenario_values = [
            item
            for item in all_values
            if item.get("scenario_id", "guaranteed") == scenario_id
        ]
        selected_values = (
            scenario_values
            if scenario_id != "guaranteed" and scenario_values
            else [
                item
                for item in all_values
                if item.get("scenario_id", "guaranteed") == "guaranteed"
            ]
        )
        for item in selected_values:
            month = int(item["policy_month"])
            if month == policy_month or (
                lookup == "at_or_before" and month <= policy_month
            ):
                candidates.append(item)
        if not candidates:
            return {
                "status": "missing",
                "amount": None,
                "evidence_refs": list(definition.get("evidence_refs", [])),
                "trace": {"type": "schedule", "lookup": lookup, "matched": False},
            }
        selected = max(
            candidates,
            key=lambda item: (
                int(item["policy_month"]),
                int(item.get("event_order", 0)),
                item.get("scenario_id", "guaranteed") == scenario_id,
            ),
        )
        status = selected.get("status", "missing")
        return {
            "status": status,
            "amount": None
            if status != "available"
            else money_value(selected["amount"]),
            "evidence_refs": flatten_evidence_refs(
                definition.get("evidence_refs", []), selected.get("evidence_refs", [])
            ),
            "trace": {
                "type": "schedule",
                "source_policy_month": int(selected["policy_month"]),
                "lookup": lookup,
            },
        }
    if boundary_event_order is None:
        boundary = definition.get("boundary_order")
        if boundary == "before_annuity":
            boundary_event_order = 29
        elif boundary == "after_annuity":
            boundary_event_order = 39
        else:
            return {
                "status": "unresolved",
                "amount": None,
                "evidence_refs": list(definition.get("evidence_refs", [])),
                "trace": {"type": "boundary_gate", "boundary_order": boundary},
            }
    boundary_events = events_through_boundary(
        events,
        policy_month,
        boundary_event_order,
        scenario_id,
    )
    premiums = [event for event in boundary_events if event["event_type"] == "premium"]
    annuities = [
        event for event in boundary_events if event["event_type"] == "annuity_payment"
    ]
    cash_value_boundary = (
        boundary_event_order
        if definition.get("cash_value_timing") == "respect_event_order"
        else None
    )
    cv_status, cash_value, cash_refs, _ = cash_value_at(
        config,
        policy_month,
        scenario_id,
        "at_or_before",
        cash_value_boundary,
    )
    context: Dict[str, Optional[Decimal]] = {
        "basic_amount": money_value(config["basic_amount"])
        if config.get("basic_amount")
        else None,
        "cash_value": cash_value if cv_status == "available" else None,
        "cumulative_annuity": sum(
            (decimal_value(event["amount"]) for event in annuities), DECIMAL_ZERO
        ),
        "cumulative_premium": sum(
            (decimal_value(event["amount"]) for event in premiums), DECIMAL_ZERO
        ),
        "policy_month": Decimal(policy_month),
        "total_premium": decimal_value(config["calculation_context"]["total_premium"]),
    }
    value, trace = _evaluate_ast(definition["rule"], context)
    refs = flatten_evidence_refs(
        definition.get("evidence_refs", []),
        cash_refs,
        _ast_evidence_refs(definition["rule"]),
    )
    if value is not None and value < 0:
        raise ValidationError(
            ["death-benefit rule evaluated to a negative monetary amount"]
        )
    return {
        "status": "available" if value is not None else "missing",
        "amount": value,
        "evidence_refs": refs,
        "trace": trace,
    }


def _ast_evidence_refs(node: Mapping[str, Any]) -> List[str]:
    refs: List[str] = list(node.get("evidence_refs", []))
    for key in ("args",):
        for child in node.get(key, []):
            refs.extend(_ast_evidence_refs(child))
    for key in ("left", "right", "arg", "then", "else"):
        child = node.get(key)
        if isinstance(child, Mapping):
            refs.extend(_ast_evidence_refs(child))
    return sorted(set(refs))


def beneficiary_continuation_events(
    config: Mapping[str, Any],
    events: Sequence[Mapping[str, Any]],
    death_month: int,
    death_event_order: Optional[int] = None,
) -> List[Dict[str, Any]]:
    definition = config.get("death_benefit") or {}
    continuation = definition.get("beneficiary_continuation")
    if not continuation:
        return []
    if continuation.get("mode") != "remaining_guaranteed_annuity":
        raise ValidationError(["unsupported beneficiary continuation mode"])
    guaranteed_annuity_boundaries = [
        (int(event["policy_month"]), int(event.get("event_order", 0)))
        for event in events
        if event["event_type"] == "annuity_payment"
        and event.get("guarantee_basis") == "guaranteed"
    ]
    if not guaranteed_annuity_boundaries:
        return []
    if death_event_order is None:
        boundary = definition.get("boundary_order")
        death_event_order = 29 if boundary == "before_annuity" else 39
    if death_month < min(month for month, _ in guaranteed_annuity_boundaries):
        return []
    through_month = int(continuation["through_policy_month"])
    selected = []
    for event in events:
        if (
            event["event_type"] == "annuity_payment"
            and event.get("guarantee_basis") == "guaranteed"
            and (int(event["policy_month"]), int(event.get("event_order", 0)))
            > (death_month, death_event_order)
            and int(event["policy_month"]) <= through_month
        ):
            copied = dict(event)
            copied["event_type"] = "beneficiary_continuation"
            copied["contingency"] = "guarantee_period_after_death"
            copied["evidence_refs"] = flatten_evidence_refs(
                event.get("evidence_refs", []), continuation.get("evidence_refs", [])
            )
            selected.append(copied)
    return selected
