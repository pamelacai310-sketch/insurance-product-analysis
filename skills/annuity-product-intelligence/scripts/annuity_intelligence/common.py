from __future__ import annotations

import copy
import hashlib
import json
import math
import re
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation, ROUND_HALF_EVEN
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Set, Tuple


TOOL_VERSION = "1.0.0"
SCHEMA_VERSION = "1.0.0"
FORMULA_VERSION = "1.0.0"


class AnnuityPIError(Exception):
    """Base error carrying a stable process exit status."""

    exit_code = 5


class ValidationError(AnnuityPIError):
    exit_code = 4

    def __init__(self, errors: Sequence[str], warnings: Optional[Sequence[str]] = None):
        self.errors = list(errors)
        self.warnings = list(warnings or [])
        super().__init__("; ".join(self.errors))


class ProhibitedCustomerDataError(AnnuityPIError):
    exit_code = 3

    def __init__(self, findings: Sequence[str]):
        self.findings = list(findings)
        super().__init__("prohibited customer data: " + ", ".join(self.findings))


class ReviewRequiredError(AnnuityPIError):
    exit_code = 2


@dataclass(frozen=True)
class ValidationResult:
    valid: bool
    errors: Tuple[str, ...]
    warnings: Tuple[str, ...]

    def as_dict(self) -> Dict[str, Any]:
        return {
            "schema_version": SCHEMA_VERSION,
            "tool_version": TOOL_VERSION,
            "valid": self.valid,
            "errors": list(self.errors),
            "warnings": list(self.warnings),
        }


DECIMAL_ZERO = Decimal("0")
DECIMAL_ONE = Decimal("1")


def decimal_value(value: Any, path: str = "value") -> Decimal:
    if isinstance(value, bool) or value is None:
        raise ValidationError([f"{path} must be a decimal string or number"])
    try:
        result = Decimal(str(value))
    except (InvalidOperation, ValueError):
        raise ValidationError([f"{path} is not a valid decimal: {value!r}"])
    if not result.is_finite():
        raise ValidationError([f"{path} must be finite"])
    return result


def decimal_string(value: Decimal, places: Optional[int] = None) -> str:
    if places is not None:
        quantum = Decimal("1").scaleb(-places)
        value = value.quantize(quantum, rounding=ROUND_HALF_EVEN)
    if value == 0:
        return "0"
    text = format(value.normalize(), "f")
    if "." in text:
        text = text.rstrip("0").rstrip(".")
    return text


def money_string(value: Decimal) -> str:
    return decimal_string(value, 2)


def stable_json_data(value: Any) -> Any:
    if isinstance(value, Decimal):
        return decimal_string(value)
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, Mapping):
        return {
            str(k): stable_json_data(v)
            for k, v in sorted(value.items(), key=lambda item: str(item[0]))
        }
    if isinstance(value, (list, tuple)):
        return [stable_json_data(v) for v in value]
    return value


def load_json(path: Path) -> Dict[str, Any]:
    try:
        with path.open("r", encoding="utf-8") as handle:
            data = json.load(handle, parse_float=Decimal, parse_int=Decimal)
    except (OSError, json.JSONDecodeError) as exc:
        raise ValidationError([f"cannot read JSON {path}: {exc}"])
    if not isinstance(data, dict):
        raise ValidationError([f"{path} must contain a JSON object"])
    return data


def write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="\n") as handle:
        json.dump(
            stable_json_data(data), handle, ensure_ascii=False, indent=2, sort_keys=True
        )
        handle.write("\n")


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def calculation_hash(data: Any) -> str:
    payload = json.dumps(
        stable_json_data(data),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return sha256_text(payload)


PROHIBITED_KEYS: Set[str] = {
    "applicant_name",
    "beneficiary_name",
    "client",
    "client_age",
    "client_assets",
    "client_income",
    "customer",
    "customer_age",
    "customer_assets",
    "customer_income",
    "customer_name",
    "date_of_birth",
    "dob",
    "expected_lifespan",
    "family_status",
    "health_data",
    "household_assets",
    "household_expenses",
    "identity_number",
    "insurance_needs",
    "personal_goal",
    "personal_goals",
    "personal_income",
    "retirement_expenses",
    "retirement_goal",
    "risk_tolerance",
    "suitability_profile",
    "target_retirement_income",
    "tax_identifier",
    "投保人姓名",
    "客户姓名",
    "客户年龄",
    "客户收入",
    "客户资产",
    "风险承受能力",
    "身份证号",
    "出生日期",
    "退休目标",
    "预期寿命",
}


def _normalized_key(key: Any) -> str:
    text = str(key).strip().lower().replace("-", "_").replace(" ", "_")
    return re.sub(r"_+", "_", text)


def find_prohibited_fields(data: Any, path: str = "$") -> List[str]:
    findings: List[str] = []
    if isinstance(data, Mapping):
        for key, value in data.items():
            normalized = _normalized_key(key)
            if (
                normalized in PROHIBITED_KEYS
                or normalized.startswith("customer_")
                or normalized.startswith("client_")
            ):
                findings.append(f"{path}.{key}")
            findings.extend(find_prohibited_fields(value, f"{path}.{key}"))
    elif isinstance(data, list):
        for index, value in enumerate(data):
            findings.extend(find_prohibited_fields(value, f"{path}[{index}]"))
    return findings


def find_prohibited_value_fields(
    data: Any, path: str = "$", parent_key: str = ""
) -> List[str]:
    findings: List[str] = []
    if isinstance(data, Mapping):
        for key, value in data.items():
            findings.extend(
                find_prohibited_value_fields(
                    value, f"{path}.{key}", _normalized_key(key)
                )
            )
    elif isinstance(data, list):
        for index, value in enumerate(data):
            findings.extend(
                find_prohibited_value_fields(value, f"{path}[{index}]", parent_key)
            )
    elif isinstance(data, str) and not parent_key.endswith("sha256"):
        # Lazy import avoids coupling the standalone extractor to the engine.
        from .extraction import detect_prohibited_customer_data

        if detect_prohibited_customer_data(data):
            findings.append(path)
    elif parent_key == "raw_value" and isinstance(data, (int, Decimal)):
        from .extraction import detect_prohibited_customer_data

        if detect_prohibited_customer_data(str(data)):
            findings.append(path)
    return findings


def enforce_no_customer_data(data: Any) -> None:
    findings = sorted(
        set(find_prohibited_fields(data) + find_prohibited_value_fields(data))
    )
    if findings:
        raise ProhibitedCustomerDataError(findings)


def require_keys(
    obj: Mapping[str, Any], required: Iterable[str], path: str, errors: List[str]
) -> None:
    for key in required:
        if key not in obj:
            errors.append(f"{path}.{key} is required")


def reject_unknown_keys(
    obj: Mapping[str, Any], allowed: Iterable[str], path: str, errors: List[str]
) -> None:
    allowed_set = set(allowed)
    for key in obj:
        if key not in allowed_set:
            errors.append(f"{path}.{key} is not allowed by the closed schema")


def check_unique_ids(
    items: Sequence[Mapping[str, Any]], field: str, path: str, errors: List[str]
) -> None:
    seen: Set[str] = set()
    for index, item in enumerate(items):
        value = item.get(field)
        if not isinstance(value, str) or not value.strip():
            errors.append(f"{path}[{index}].{field} must be a non-empty string")
        elif value in seen:
            errors.append(f"{path}[{index}].{field} duplicates {value!r}")
        else:
            seen.add(value)


def deep_copy_json(value: Any) -> Any:
    return copy.deepcopy(value)


def percentile(values: Sequence[Decimal], probability: Decimal) -> Optional[Decimal]:
    if not values:
        return None
    ordered = sorted(values)
    if len(ordered) == 1:
        return ordered[0]
    position = probability * Decimal(len(ordered) - 1)
    lower = int(position)
    upper = min(lower + 1, len(ordered) - 1)
    fraction = position - Decimal(lower)
    return ordered[lower] * (DECIMAL_ONE - fraction) + ordered[upper] * fraction


def safe_ratio(numerator: Decimal, denominator: Decimal) -> Optional[Decimal]:
    if denominator == 0:
        return None
    return numerator / denominator


def flatten_evidence_refs(*collections: Iterable[str]) -> List[str]:
    values: Set[str] = set()
    for collection in collections:
        for item in collection:
            if item:
                values.add(str(item))
    return sorted(values)


def metric_record(
    value: Any,
    formula_id: str,
    configuration_id: str,
    evidence_refs: Iterable[str],
    calculation_config: Any,
    status: str = "available",
    warnings: Optional[Sequence[str]] = None,
    assumptions: Optional[Sequence[str]] = None,
) -> Dict[str, Any]:
    return {
        "status": status,
        "value": stable_json_data(value) if status == "available" else None,
        "warnings": list(warnings or []),
        "provenance": {
            "formula_id": formula_id,
            "formula_version": FORMULA_VERSION,
            "configuration_id": configuration_id,
            "evidence_refs": sorted(set(evidence_refs)),
            "assumption_refs": list(assumptions or []),
            "calculation_config_sha256": calculation_hash(calculation_config),
        },
    }


def finite_float(value: Decimal) -> float:
    result = float(value)
    if not math.isfinite(result):
        raise ValidationError(
            [f"decimal {value} cannot be represented as a finite float"]
        )
    return result
