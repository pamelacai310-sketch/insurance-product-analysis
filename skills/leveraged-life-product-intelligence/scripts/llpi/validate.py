"""Canonical-product validation and evidence/provenance sanity checks."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal, InvalidOperation
import hashlib
import json
import re
import urllib.parse
from typing import Any, Dict, Iterable, List, Optional


FORBIDDEN_CLIENT_KEYS = {
    "age",
    "assets",
    "client",
    "client_id",
    "customer",
    "customer_id",
    "address",
    "account_number",
    "bank_account",
    "birth_date",
    "date_of_birth",
    "dob",
    "email",
    "email_address",
    "family",
    "family_responsibility",
    "employer",
    "gender",
    "health",
    "income",
    "liabilities",
    "net_worth",
    "occupation",
    "passport",
    "passport_number",
    "personal_name",
    "phone",
    "phone_number",
    "mobile",
    "mobile_number",
    "national_id",
    "id_number",
    "marital_status",
    "medical_history",
    "risk_appetite",
    "risk_preference",
    "risk_profile",
    "risk_tolerance",
    "sex",
    "ssn",
    "tax_id",
    "tel",
    "telephone",
    "telephone_number",
}

FORBIDDEN_CLIENT_TOKENS = {
    "applicant",
    "account",
    "address",
    "asset",
    "assets",
    "beneficiary",
    "bank",
    "client",
    "customer",
    "debt",
    "dependent",
    "dependents",
    "earnings",
    "employer",
    "email",
    "family",
    "health",
    "household",
    "income",
    "insured",
    "liabilities",
    "liability",
    "mortgage",
    "medical",
    "mobile",
    "occupation",
    "passport",
    "phone",
    "policyholder",
    "personal",
    "profile",
    "salary",
    "tax",
    "ssn",
    "telephone",
    "user",
    "wealth",
}

FORBIDDEN_CLIENT_KEYS_ZH = {
    "客户",
    "客户姓名",
    "客户画像",
    "用户画像",
    "姓名",
    "投保人姓名",
    "被保险人姓名",
    "年收入",
    "家庭收入",
    "净资产",
    "资产",
    "负债",
    "风险偏好",
    "风险承受能力",
    "家庭责任",
    "手机号",
    "电话号码",
    "联系电话",
    "手机号码",
    "邮箱",
    "电子邮箱",
    "地址",
    "通讯地址",
    "身份证号",
    "护照号",
    "出生日期",
    "年龄",
    "投保年龄",
    "被保险人年龄",
    "性别",
    "健康",
    "健康资料",
    "家庭",
    "家庭成员",
    "扶养人数",
    "风险画像",
    "银行账号",
    "职业",
    "雇主",
    "婚姻状况",
    "健康状况",
    "病史",
}

HIGH_RISK_STANDALONE_CLIENT_LABELS = {
    "address",
    "customer_name",
    "client_name",
    "date_of_birth",
    "dob",
    "email",
    "email_address",
    "full_name",
    "id_number",
    "mobile",
    "mobile_number",
    "national_id",
    "passport",
    "passport_number",
    "phone",
    "phone_number",
    "ssn",
    "tax_id",
    "bank_account",
    "account_number",
    "tel",
    "telephone",
    "telephone_number",
    "medical_history",
    "employer",
    "marital_status",
}

HIGH_RISK_STANDALONE_CLIENT_LABELS_ZH = {
    "姓名",
    "客户姓名",
    "投保人姓名",
    "被保险人姓名",
    "身份证号",
    "护照号",
    "手机号",
    "手机号码",
    "电话号码",
    "联系电话",
    "邮箱",
    "电子邮箱",
    "地址",
    "通讯地址",
}

FORBIDDEN_CLIENT_TEXT_LABELS = {
    "姓名",
    "客户姓名",
    "投保人姓名",
    "被保险人姓名",
    "身份证号",
    "护照号",
    "手机号",
    "手机号码",
    "电话号码",
    "联系电话",
    "出生日期",
    "年龄",
    "性别",
    "健康状况",
    "病史",
    "年收入",
    "家庭收入",
    "净资产",
    "风险偏好",
}

STANDARD_BENCHMARKS = {
    "LLPI-STD-1PAY-100K-v1": {
        "benchmark_version": "1.0.0",
        "currency": "CNY",
        "issue_date": "2026-01-01",
        "amount_scale": "currency_unit",
        "inflation_rate": "0.02",
        "premium_cashflows": [
            {"date": "2026-01-01", "time_years": "0", "amount": "100000.00"}
        ],
    },
    "LLPI-STD-3PAY-100K-v1": {
        "benchmark_version": "1.0.0",
        "currency": "CNY",
        "issue_date": "2026-01-01",
        "amount_scale": "currency_unit",
        "inflation_rate": "0.02",
        "premium_cashflows": [
            {"date": "2026-01-01", "time_years": "0", "amount": "100000.00"},
            {"date": "2027-01-01", "time_years": "1", "amount": "100000.00"},
            {"date": "2028-01-01", "time_years": "2", "amount": "100000.00"},
        ],
    },
    "LLPI-STD-10PAY-100K-v1": {
        "benchmark_version": "1.0.0",
        "currency": "CNY",
        "issue_date": "2026-01-01",
        "amount_scale": "currency_unit",
        "inflation_rate": "0.02",
        "premium_cashflows": [
            {
                "date": f"{2026 + index}-01-01",
                "time_years": str(index),
                "amount": "100000.00",
            }
            for index in range(10)
        ],
    },
}

ROOT_KEYS = {
    "schema_version",
    "analysis_scope",
    "product",
    "sources",
    "evidence",
    "cases",
    "provenance",
    "extensions",
}

PRODUCT_KEYS = {
    "product_id",
    "name",
    "insurer",
    "currency",
    "product_type",
    "jurisdiction",
    "participating",
}
SOURCE_KEYS = {"source_id", "title", "kind", "version", "uri", "document_sha256"}
EVIDENCE_KEYS = {
    "evidence_id",
    "source_id",
    "document_sha256",
    "page",
    "bbox",
    "locator",
    "raw_text",
    "content_sha256",
    "extractor",
    "extractor_version",
    "confidence",
    "reason_codes",
}
CASE_KEYS = {
    "case_id",
    "label",
    "basis",
    "timing",
    "amount_scale",
    "inflation_rate",
    "premium_cashflows",
    "scenario_definitions",
    "projection",
}
BASIS_KEYS = {"kind", "benchmark_version", "pricing_basis_digest"}
TIMING_KEYS = {"issue_date", "premium_timing", "benefit_timing"}
PREMIUM_KEYS = {"date", "time_years", "amount"}
PROJECTION_KEYS = {
    "policy_year",
    "date",
    "time_years",
    "death_benefit",
    "cash_surrender_value",
}
BENEFIT_KEYS = {"guaranteed", "scenarios"}
SCENARIO_DEFINITION_KEYS = {"label", "guaranteed"}
PROVENANCE_KEYS = {
    "evidence_ids",
    "extractor",
    "extractor_version",
    "confidence",
    "status",
    "raw_value",
    "reason_codes",
}
SHA256_PATTERN = re.compile(r"^[a-f0-9]{64}$")
MONEY_PATTERN = re.compile(r"^(0|[1-9][0-9]*)(\.[0-9]+)?$")


@dataclass(frozen=True)
class ValidationIssue:
    severity: str
    code: str
    path: str
    message: str

    def to_dict(self) -> dict:
        return {
            "severity": self.severity,
            "code": self.code,
            "path": self.path,
            "message": self.message,
        }


class ValidationResult:
    def __init__(self, issues: Iterable[ValidationIssue]):
        self.issues = sorted(
            issues, key=lambda item: (item.severity, item.path, item.code)
        )

    @property
    def errors(self) -> List[ValidationIssue]:
        return [issue for issue in self.issues if issue.severity == "error"]

    @property
    def warnings(self) -> List[ValidationIssue]:
        return [issue for issue in self.issues if issue.severity == "warning"]

    @property
    def ok(self) -> bool:
        return not self.errors

    def to_dict(self) -> dict:
        return {
            "ok": self.ok,
            "error_count": len(self.errors),
            "warning_count": len(self.warnings),
            "issues": [issue.to_dict() for issue in self.issues],
        }


def _issue(
    issues: List[ValidationIssue], severity: str, code: str, path: str, message: str
) -> None:
    issues.append(ValidationIssue(severity, code, path, message))


def _is_nonempty_string(value: Any) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _unknown_keys(
    value: Any,
    allowed: set,
    path: str,
    issues: List[ValidationIssue],
) -> None:
    if not isinstance(value, dict):
        return
    for key in sorted(set(value) - allowed):
        _issue(
            issues,
            "error",
            "unknown_field",
            f"{path}/{key}",
            "Unknown core field; schema 1.0.0 is closed.",
        )


def _walk_keys(value: Any, path: str = "") -> Iterable[tuple]:
    if isinstance(value, dict):
        for key, child in value.items():
            child_path = f"{path}/{key}"
            yield key, child_path
            yield from _walk_keys(child, child_path)
    elif isinstance(value, list):
        for index, child in enumerate(value):
            yield from _walk_keys(child, f"{path}/{index}")


def _walk_string_values(value: Any, path: str = "") -> Iterable[tuple]:
    if isinstance(value, str):
        yield value, path
    elif isinstance(value, dict):
        for key, child in value.items():
            yield from _walk_string_values(child, f"{path}/{key}")
    elif isinstance(value, list):
        for index, child in enumerate(value):
            yield from _walk_string_values(child, f"{path}/{index}")


def _normalized_key(value: Any) -> str:
    text = re.sub(r"([a-z0-9])([A-Z])", r"\1_\2", str(value))
    return re.sub(r"[^a-z0-9]+", "_", text.lower()).strip("_")


def _is_forbidden_client_key(value: Any) -> bool:
    if str(value).strip() in FORBIDDEN_CLIENT_KEYS_ZH:
        return True
    normalized = _normalized_key(value)
    tokens = set(normalized.split("_"))
    if normalized in FORBIDDEN_CLIENT_KEYS:
        return True
    if tokens & FORBIDDEN_CLIENT_TOKENS:
        return True
    if normalized in {"full_name", "net_worth", "personal_details", "user_profile"}:
        return True
    return "risk" in tokens and bool(
        tokens & {"appetite", "desired", "level", "preference", "profile", "tolerance"}
    )


def _contains_forbidden_client_text(value: Any) -> bool:
    """Detect explicitly labelled customer/profile facts in evidence text.

    Product facts such as ``product_name`` and ``issue_age_range`` are not
    rejected. The detector intentionally requires an explicit client/PII label
    instead of guessing whether an arbitrary number or personal-looking name is
    sensitive.
    """

    if not isinstance(value, str) or not value.strip():
        return False
    decoded = urllib.parse.unquote_plus(value)
    if decoded != value and _contains_forbidden_client_text(decoded):
        return True
    for line in value.splitlines() or [value]:
        cells = [
            cell.strip(" \t\"'{}[],")
            for cell in re.split(r"[|\t]", line.strip().strip("|"))
            if cell.strip(" \t\"'{}[],")
        ]
        for cell in cells:
            if (
                _normalized_key(cell) in HIGH_RISK_STANDALONE_CLIENT_LABELS
                or cell in HIGH_RISK_STANDALONE_CLIENT_LABELS_ZH
            ):
                return True
        candidates = re.findall(r"[\"']([^\"']{1,100})[\"']\s*[:：=]", line)
        prefix = re.match(r"^\s*([^:：=]{1,100})\s*[:：=]", line)
        if prefix:
            candidates.append(prefix.group(1).strip(" \t\"'{}[],"))
        for candidate in candidates:
            if candidate in FORBIDDEN_CLIENT_TEXT_LABELS or _is_forbidden_client_key(
                candidate
            ):
                return True
        if re.search(
            r"(?i)(?:^|\b)(?:ssn|social\s+security\s+number|telephone(?:\s+number)?|"
            r"phone(?:\s+number)?|email(?:\s+address)?|address|"
            r"passport(?:\s+number)?|national\s+id)\s*[:#=]",
            line,
        ):
            return True
        if re.search(
            r"(?i)(?:^|\b)(?:ssn|social\s+security\s+number|"
            r"telephone(?:\s+number)?|phone(?:\s+number)?)\s+\+?[0-9]",
            line,
        ):
            return True
        if re.search(
            r"(?i)(?:^|\b)(?:passport(?:\s+number)?|national\s+id)\s+[A-Z0-9]",
            line,
        ):
            return True
        if any(
            re.search(r"(?:^|[\s,;])%s\s*[:：=]" % re.escape(label), line)
            for label in FORBIDDEN_CLIENT_TEXT_LABELS
        ):
            return True
    return False


def _decimal(
    value: Any, path: str, issues: List[ValidationIssue], nonnegative: bool = True
) -> Optional[Decimal]:
    if isinstance(value, bool):
        _issue(
            issues, "error", "invalid_decimal", path, "Boolean is not a money value."
        )
        return None
    try:
        result = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        _issue(
            issues, "error", "invalid_decimal", path, "Expected a finite decimal value."
        )
        return None
    if not result.is_finite():
        _issue(issues, "error", "non_finite", path, "NaN and infinity are forbidden.")
        return None
    if nonnegative and result < 0:
        _issue(
            issues,
            "error",
            "negative_value",
            path,
            "Contract values must be non-negative.",
        )
    return result


def _money_decimal(
    value: Any, path: str, issues: List[ValidationIssue]
) -> Optional[Decimal]:
    if not isinstance(value, str) or not MONEY_PATTERN.fullmatch(value):
        _issue(
            issues,
            "error",
            "money_string",
            path,
            "Money must be a non-negative plain decimal string.",
        )
        return None
    return _decimal(value, path, issues)


def _date(value: Any, path: str, issues: List[ValidationIssue]) -> Optional[date]:
    try:
        return date.fromisoformat(str(value))
    except (TypeError, ValueError):
        _issue(
            issues, "error", "invalid_date", path, "Expected an ISO 8601 calendar date."
        )
        return None


def _calendar_anniversary(issue_date: date, years: int) -> date:
    try:
        return issue_date.replace(year=issue_date.year + years)
    except ValueError:
        # A 29 February issue date uses 28 February in a non-leap anniversary year.
        return issue_date.replace(month=2, day=28, year=issue_date.year + years)


def _date_time_consistent(
    issue_date: date, event_date: date, time_years: Decimal
) -> bool:
    """Accept nominal whole policy years and ACT/365F fractional coordinates.

    Periodic IRR uses nominal policy-year coordinates while XIRR uses exact
    dates. Comparing a 40-year anniversary directly with days/365 would
    incorrectly accumulate every leap day as an input error.
    """

    integral = time_years.to_integral_value()
    if time_years == integral:
        expected = _calendar_anniversary(issue_date, int(integral))
        return abs((event_date - expected).days) <= 7
    actual_time = Decimal((event_date - issue_date).days) / Decimal("365")
    return abs(actual_time - time_years) <= Decimal("0.02")


def _standard_benchmark_matches(case: dict, registered: dict, currency: Any) -> bool:
    basis = case.get("basis") if isinstance(case.get("basis"), dict) else {}
    timing = case.get("timing") if isinstance(case.get("timing"), dict) else {}
    if basis.get("benchmark_version") != registered["benchmark_version"]:
        return False
    if currency != registered["currency"]:
        return False
    if timing.get("issue_date") != registered["issue_date"]:
        return False
    if case.get("amount_scale") != registered["amount_scale"]:
        return False
    if timing.get("premium_timing") != "explicit_dates":
        return False
    if timing.get("benefit_timing") != "projection_date":
        return False
    try:
        if Decimal(str(case.get("inflation_rate"))) != Decimal(
            registered["inflation_rate"]
        ):
            return False
    except (InvalidOperation, TypeError, ValueError):
        return False
    actual_flows = case.get("premium_cashflows")
    expected_flows = registered["premium_cashflows"]
    if not isinstance(actual_flows, list) or len(actual_flows) != len(expected_flows):
        return False
    for actual, expected in zip(actual_flows, expected_flows):
        if not isinstance(actual, dict) or actual.get("date") != expected["date"]:
            return False
        try:
            if Decimal(str(actual.get("time_years"))) != Decimal(
                expected["time_years"]
            ) or Decimal(str(actual.get("amount"))) != Decimal(expected["amount"]):
                return False
        except (InvalidOperation, TypeError, ValueError):
            return False
    return True


def _json_pointer_exists(document: Any, pointer: str) -> bool:
    if pointer == "":
        return True
    if not isinstance(pointer, str) or not pointer.startswith("/"):
        return False
    current = document
    for raw_part in pointer[1:].split("/"):
        part = raw_part.replace("~1", "/").replace("~0", "~")
        if isinstance(current, dict) and part in current:
            current = current[part]
        elif isinstance(current, list) and part.isdigit() and int(part) < len(current):
            current = current[int(part)]
        else:
            return False
    return True


def _has_provenance(provenance: Dict[str, Any], path: str) -> bool:
    if path in provenance:
        return True
    parts = path.split("/")
    return any(
        "/".join(parts[:index]) in provenance for index in range(len(parts) - 1, 0, -1)
    )


def _provenance_record(provenance: Dict[str, Any], path: str) -> Optional[dict]:
    if isinstance(provenance.get(path), dict):
        return provenance[path]
    parts = path.split("/")
    for index in range(len(parts) - 1, 0, -1):
        candidate = provenance.get("/".join(parts[:index]))
        if isinstance(candidate, dict):
            return candidate
    return None


def _critical_paths(data: dict) -> Iterable[str]:
    yield "/product/currency"
    for case_index, case in enumerate(data.get("cases", [])):
        if not isinstance(case, dict):
            continue
        yield f"/cases/{case_index}/basis"
        yield f"/cases/{case_index}/timing"
        yield f"/cases/{case_index}/amount_scale"
        if case.get("inflation_rate") is not None:
            yield f"/cases/{case_index}/inflation_rate"
        yield f"/cases/{case_index}/scenario_definitions"
        for premium_index, _ in enumerate(case.get("premium_cashflows", [])):
            yield f"/cases/{case_index}/premium_cashflows/{premium_index}/amount"
            yield f"/cases/{case_index}/premium_cashflows/{premium_index}/date"
            yield f"/cases/{case_index}/premium_cashflows/{premium_index}/time_years"
        for row_index, row in enumerate(case.get("projection", [])):
            if not isinstance(row, dict):
                continue
            yield f"/cases/{case_index}/projection/{row_index}/policy_year"
            yield f"/cases/{case_index}/projection/{row_index}/date"
            yield f"/cases/{case_index}/projection/{row_index}/time_years"
            yield f"/cases/{case_index}/projection/{row_index}/death_benefit/guaranteed"
            yield f"/cases/{case_index}/projection/{row_index}/cash_surrender_value/guaranteed"
            death = row.get("death_benefit")
            death = death if isinstance(death, dict) else {}
            cash = row.get("cash_surrender_value")
            cash = cash if isinstance(cash, dict) else {}
            death_scenarios = death.get("scenarios")
            death_scenarios = (
                death_scenarios if isinstance(death_scenarios, dict) else {}
            )
            cash_scenarios = cash.get("scenarios")
            cash_scenarios = cash_scenarios if isinstance(cash_scenarios, dict) else {}
            for scenario_id in death_scenarios:
                yield f"/cases/{case_index}/projection/{row_index}/death_benefit/scenarios/{scenario_id}"
            for scenario_id in cash_scenarios:
                yield f"/cases/{case_index}/projection/{row_index}/cash_surrender_value/scenarios/{scenario_id}"


def validate_product(data: Any, strict_evidence: bool = False) -> ValidationResult:
    """Validate core schema invariants without requiring jsonschema at runtime."""

    issues: List[ValidationIssue] = []
    if not isinstance(data, dict):
        return ValidationResult(
            [ValidationIssue("error", "root_type", "", "Root must be an object.")]
        )

    unknown = sorted(set(data) - ROOT_KEYS)
    for key in unknown:
        _issue(
            issues,
            "error",
            "unknown_root_field",
            f"/{key}",
            "Unknown core field; schema 1.0.0 is closed.",
        )
    if data.get("schema_version") != "1.0.0":
        _issue(
            issues,
            "error",
            "schema_version",
            "/schema_version",
            "Expected schema version 1.0.0.",
        )
    if data.get("analysis_scope") != "product_only":
        _issue(
            issues,
            "error",
            "scope",
            "/analysis_scope",
            "Only product_only analysis is supported.",
        )

    extensions = data.get("extensions")
    if extensions is not None and (not isinstance(extensions, dict) or extensions):
        _issue(
            issues,
            "error",
            "extensions_reserved",
            "/extensions",
            "extensions is reserved and must be an empty object in schema 1.0.0.",
        )

    for key, path in _walk_keys(data):
        if _is_forbidden_client_key(key):
            _issue(
                issues,
                "error",
                "customer_data_forbidden",
                path,
                "Customer/profile data is outside this tool's scope.",
            )
    for value, path in _walk_string_values(data):
        if _contains_forbidden_client_text(value):
            _issue(
                issues,
                "error",
                "customer_data_forbidden",
                path,
                "Explicitly labelled customer/profile data is outside this tool's scope.",
            )

    product = data.get("product")
    if not isinstance(product, dict):
        _issue(
            issues,
            "error",
            "product_required",
            "/product",
            "Product metadata is required.",
        )
        product = {}
    _unknown_keys(product, PRODUCT_KEYS, "/product", issues)
    for field in ("product_id", "name", "insurer", "currency", "product_type"):
        if (
            not isinstance(product.get(field), str)
            or not product.get(field, "").strip()
        ):
            _issue(
                issues,
                "error",
                "required_field",
                f"/product/{field}",
                "Required product field must be a non-empty string.",
            )
    currency = product.get("currency", "")
    if (
        isinstance(currency, str)
        and currency
        and not re.fullmatch(r"[A-Z]{3}", currency)
    ):
        _issue(
            issues,
            "error",
            "currency",
            "/product/currency",
            "Currency must be a three-letter uppercase code.",
        )
    if "participating" in product and not isinstance(
        product.get("participating"), bool
    ):
        _issue(
            issues,
            "error",
            "participating_type",
            "/product/participating",
            "participating must be boolean.",
        )
    if "jurisdiction" in product and not isinstance(product.get("jurisdiction"), str):
        _issue(
            issues,
            "error",
            "jurisdiction_type",
            "/product/jurisdiction",
            "jurisdiction must be a string.",
        )

    sources = data.get("sources", [])
    evidence = data.get("evidence", [])
    provenance = data.get("provenance", {})
    if (
        not isinstance(sources, list)
        or not isinstance(evidence, list)
        or not isinstance(provenance, dict)
    ):
        _issue(
            issues,
            "error",
            "evidence_shape",
            "/",
            "sources/evidence must be arrays and provenance must be an object.",
        )
        sources, evidence, provenance = [], [], {}
    source_ids = [
        item.get("source_id") if isinstance(item.get("source_id"), str) else None
        for item in sources
        if isinstance(item, dict)
    ]
    evidence_ids = [
        item.get("evidence_id") if isinstance(item.get("evidence_id"), str) else None
        for item in evidence
        if isinstance(item, dict)
    ]
    if len(source_ids) != len(set(source_ids)):
        _issue(
            issues,
            "error",
            "duplicate_source_id",
            "/sources",
            "Source IDs must be unique.",
        )
    if len(evidence_ids) != len(set(evidence_ids)):
        _issue(
            issues,
            "error",
            "duplicate_evidence_id",
            "/evidence",
            "Evidence IDs must be unique.",
        )
    source_id_set, evidence_id_set = set(source_ids), set(evidence_ids)
    source_hashes = {}
    source_kinds: Dict[str, str] = {}
    for index, item in enumerate(sources):
        path = f"/sources/{index}"
        if not isinstance(item, dict):
            _issue(issues, "error", "source_item", path, "Source must be an object.")
            continue
        _unknown_keys(item, SOURCE_KEYS, path, issues)
        for field in ("source_id", "title", "kind", "document_sha256"):
            if not _is_nonempty_string(item.get(field)):
                _issue(
                    issues,
                    "error",
                    "required_field",
                    f"{path}/{field}",
                    "Required source field must be a non-empty string.",
                )
        for field in ("version", "uri"):
            if field in item and not isinstance(item.get(field), str):
                _issue(
                    issues,
                    "error",
                    "source_string",
                    f"{path}/{field}",
                    f"{field} must be a string.",
                )
        if item.get("kind") not in {
            "contract",
            "illustration",
            "cash_value_table",
            "rate_table",
            "structured_input",
            "synthetic_benchmark",
        }:
            _issue(
                issues,
                "error",
                "source_kind",
                f"{path}/kind",
                "Unsupported source kind.",
            )
        document_hash = item.get("document_sha256")
        if not isinstance(document_hash, str) or not SHA256_PATTERN.fullmatch(
            document_hash
        ):
            _issue(
                issues,
                "error",
                "document_hash",
                f"{path}/document_sha256",
                "Expected lowercase SHA-256.",
            )
        if isinstance(item.get("source_id"), str) and item.get("source_id"):
            source_hashes[item.get("source_id")] = document_hash
            if isinstance(item.get("kind"), str):
                source_kinds[item["source_id"]] = item["kind"]
    evidence_confidence_by_id: Dict[str, float] = {}
    evidence_source_by_id: Dict[str, str] = {}
    for index, item in enumerate(evidence):
        path = f"/evidence/{index}"
        if not isinstance(item, dict):
            _issue(
                issues, "error", "evidence_item", path, "Evidence must be an object."
            )
            continue
        _unknown_keys(item, EVIDENCE_KEYS, path, issues)
        for field in ("evidence_id", "source_id", "extractor"):
            if not _is_nonempty_string(item.get(field)):
                _issue(
                    issues,
                    "error",
                    "required_field",
                    f"{path}/{field}",
                    "Required evidence field must be a non-empty string.",
                )
        if "extractor_version" in item and not isinstance(
            item.get("extractor_version"), str
        ):
            _issue(
                issues,
                "error",
                "evidence_string",
                f"{path}/extractor_version",
                "extractor_version must be a string.",
            )
        locator = item.get("locator")
        if locator is not None and not isinstance(locator, dict):
            _issue(
                issues,
                "error",
                "evidence_locator",
                f"{path}/locator",
                "locator must be an object.",
            )
        reason_codes = item.get("reason_codes")
        if reason_codes is not None and (
            not isinstance(reason_codes, list)
            or any(not isinstance(code, str) for code in reason_codes)
            or len(reason_codes) != len(set(reason_codes))
        ):
            _issue(
                issues,
                "error",
                "reason_codes",
                f"{path}/reason_codes",
                "reason_codes must be a unique array of strings.",
            )
        evidence_source_id = item.get("source_id")
        if (
            not isinstance(evidence_source_id, str)
            or evidence_source_id not in source_id_set
        ):
            _issue(
                issues,
                "error",
                "dangling_source",
                f"{path}/source_id",
                "Evidence source_id does not resolve.",
            )
        evidence_hash = item.get("document_sha256")
        if not isinstance(evidence_hash, str) or not SHA256_PATTERN.fullmatch(
            evidence_hash
        ):
            _issue(
                issues,
                "error",
                "document_hash",
                f"{path}/document_sha256",
                "Expected lowercase SHA-256.",
            )
        elif source_hashes.get(evidence_source_id) != evidence_hash:
            _issue(
                issues,
                "error",
                "source_hash_mismatch",
                f"{path}/document_sha256",
                "Evidence hash differs from its source document hash.",
            )
        page_number = item.get("page")
        if (
            not isinstance(page_number, int)
            or isinstance(page_number, bool)
            or page_number < 1
        ):
            _issue(
                issues,
                "error",
                "evidence_page",
                f"{path}/page",
                "Evidence page must be a 1-based integer.",
            )
        bbox = item.get("bbox")
        if bbox is not None:
            valid_bbox = (
                isinstance(bbox, list)
                and len(bbox) == 4
                and all(
                    isinstance(value, (int, float))
                    and not isinstance(value, bool)
                    and 0 <= value <= 1
                    for value in bbox
                )
                and bbox[0] <= bbox[2]
                and bbox[1] <= bbox[3]
            )
            if not valid_bbox:
                _issue(
                    issues,
                    "error",
                    "evidence_bbox",
                    f"{path}/bbox",
                    "bbox must be four ordered normalized coordinates.",
                )
        confidence = item.get("confidence")
        if (
            not isinstance(confidence, (int, float))
            or isinstance(confidence, bool)
            or not 0 <= confidence <= 1
        ):
            _issue(
                issues,
                "error",
                "confidence",
                f"{path}/confidence",
                "Confidence must be between 0 and 1.",
            )
        else:
            evidence_id = item.get("evidence_id")
            if isinstance(evidence_id, str) and evidence_id:
                evidence_confidence_by_id[evidence_id] = float(confidence)
                if isinstance(evidence_source_id, str):
                    evidence_source_by_id[evidence_id] = evidence_source_id
            extractor = str(item.get("extractor", "")).lower()
            if extractor.startswith("llm") and confidence > 0.69:
                _issue(
                    issues,
                    "error",
                    "llm_confidence_cap",
                    f"{path}/confidence",
                    "LLM-only evidence confidence cannot exceed 0.69.",
                )
        raw_text = item.get("raw_text")
        content_hash = item.get("content_sha256")
        if not isinstance(raw_text, str) or len(raw_text) > 4000:
            _issue(
                issues,
                "error",
                "evidence_text",
                f"{path}/raw_text",
                "Evidence raw_text must be a string of at most 4000 characters.",
            )
        if not isinstance(content_hash, str) or not SHA256_PATTERN.fullmatch(
            content_hash
        ):
            _issue(
                issues,
                "error",
                "content_hash",
                f"{path}/content_sha256",
                "Expected lowercase SHA-256.",
            )
        if raw_text is not None and content_hash:
            actual = hashlib.sha256(str(raw_text).encode("utf-8")).hexdigest()
            if actual != content_hash:
                _issue(
                    issues,
                    "error",
                    "content_hash",
                    f"{path}/content_sha256",
                    "Evidence content hash does not match raw_text.",
                )
    for pointer, record in provenance.items():
        path = f"/provenance/{pointer}"
        if not _json_pointer_exists(data, pointer):
            _issue(
                issues,
                "error",
                "dangling_pointer",
                path,
                "Provenance JSON pointer does not resolve.",
            )
        if not isinstance(record, dict):
            _issue(
                issues,
                "error",
                "provenance_record",
                path,
                "Provenance record must be an object.",
            )
            continue
        _unknown_keys(record, PROVENANCE_KEYS, path, issues)
        evidence_refs = record.get("evidence_ids")
        if not isinstance(evidence_refs, list) or not evidence_refs:
            _issue(
                issues,
                "error",
                "provenance_evidence",
                f"{path}/evidence_ids",
                "Provenance requires at least one evidence ID.",
            )
        elif any(
            not isinstance(evidence_id, str) for evidence_id in evidence_refs
        ) or len(evidence_refs) != len(set(evidence_refs)):
            _issue(
                issues,
                "error",
                "provenance_evidence",
                f"{path}/evidence_ids",
                "Provenance evidence_ids must be a unique array of strings.",
            )
        for evidence_id in evidence_refs if isinstance(evidence_refs, list) else []:
            if not isinstance(evidence_id, str) or evidence_id not in evidence_id_set:
                _issue(
                    issues,
                    "error",
                    "dangling_evidence",
                    path,
                    "Provenance evidence_id does not resolve.",
                )
        confidence = record.get("confidence")
        if (
            not isinstance(confidence, (int, float))
            or isinstance(confidence, bool)
            or not 0 <= confidence <= 1
        ):
            _issue(
                issues,
                "error",
                "confidence",
                f"{path}/confidence",
                "Confidence must be between 0 and 1.",
            )
        else:
            supported_confidences = [
                evidence_confidence_by_id[evidence_id]
                for evidence_id in evidence_refs
                if isinstance(evidence_refs, list)
                and isinstance(evidence_id, str)
                and evidence_id in evidence_confidence_by_id
            ]
            if supported_confidences and confidence > max(supported_confidences):
                _issue(
                    issues,
                    "error",
                    "provenance_confidence_exceeds_evidence",
                    f"{path}/confidence",
                    "Provenance confidence cannot exceed its strongest referenced evidence.",
                )
        if record.get("status") not in {"accepted", "needs_review", "rejected"}:
            _issue(
                issues,
                "error",
                "provenance_status",
                f"{path}/status",
                "Unknown provenance status.",
            )
        if not _is_nonempty_string(record.get("extractor")):
            _issue(
                issues,
                "error",
                "provenance_extractor",
                f"{path}/extractor",
                "Extractor is required.",
            )
        if "extractor_version" in record and not isinstance(
            record.get("extractor_version"), str
        ):
            _issue(
                issues,
                "error",
                "provenance_string",
                f"{path}/extractor_version",
                "extractor_version must be a string.",
            )
        reason_codes = record.get("reason_codes")
        if reason_codes is not None and (
            not isinstance(reason_codes, list)
            or any(not isinstance(code, str) for code in reason_codes)
            or len(reason_codes) != len(set(reason_codes))
        ):
            _issue(
                issues,
                "error",
                "reason_codes",
                f"{path}/reason_codes",
                "reason_codes must be a unique array of strings.",
            )

    cases = data.get("cases")
    if not isinstance(cases, list) or not cases:
        _issue(
            issues,
            "error",
            "cases_required",
            "/cases",
            "At least one benchmark/document case is required.",
        )
        cases = []
    case_ids = []
    for case_index, case in enumerate(cases):
        case_path = f"/cases/{case_index}"
        if not isinstance(case, dict):
            _issue(issues, "error", "case_item", case_path, "Case must be an object.")
            continue
        _unknown_keys(case, CASE_KEYS, case_path, issues)
        if "label" in case and not isinstance(case.get("label"), str):
            _issue(
                issues,
                "error",
                "case_label",
                f"{case_path}/label",
                "Case label must be a string.",
            )
        case_id = case.get("case_id")
        case_ids.append(case_id if isinstance(case_id, str) else None)
        if not _is_nonempty_string(case_id):
            _issue(
                issues,
                "error",
                "case_id",
                f"{case_path}/case_id",
                "case_id must be a non-empty string.",
            )
        basis = case.get("basis", {})
        if not isinstance(basis, dict) or basis.get("kind") not in {
            "standard_benchmark",
            "document_illustration",
        }:
            _issue(
                issues,
                "error",
                "basis_kind",
                f"{case_path}/basis/kind",
                "Unsupported case basis.",
            )
            basis = {} if not isinstance(basis, dict) else basis
        _unknown_keys(basis, BASIS_KEYS, f"{case_path}/basis", issues)
        if not _is_nonempty_string(basis.get("benchmark_version")):
            _issue(
                issues,
                "error",
                "benchmark_version",
                f"{case_path}/basis/benchmark_version",
                "Benchmark version must be a non-empty string.",
            )
        pricing_digest = basis.get("pricing_basis_digest")
        if pricing_digest is not None and (
            not isinstance(pricing_digest, str)
            or not SHA256_PATTERN.fullmatch(pricing_digest)
        ):
            _issue(
                issues,
                "error",
                "pricing_basis_digest",
                f"{case_path}/basis/pricing_basis_digest",
                "Expected lowercase SHA-256.",
            )
        if basis.get("kind") == "standard_benchmark":
            registered = (
                STANDARD_BENCHMARKS.get(case_id) if isinstance(case_id, str) else None
            )
            if registered is None:
                _issue(
                    issues,
                    "error",
                    "unknown_standard_benchmark",
                    f"{case_path}/case_id",
                    "standard_benchmark case_id is not registered in engine 1.0.0.",
                )
            elif not _standard_benchmark_matches(
                case, registered, product.get("currency")
            ):
                _issue(
                    issues,
                    "error",
                    "standard_benchmark_mismatch",
                    case_path,
                    "Standard benchmark timing, inflation, or premium schedule differs from its registered definition.",
                )
        timing = case.get("timing", {})
        if not isinstance(timing, dict):
            _issue(
                issues,
                "error",
                "timing",
                f"{case_path}/timing",
                "Timing must be an object.",
            )
            timing = {}
        _unknown_keys(timing, TIMING_KEYS, f"{case_path}/timing", issues)
        issue_date = _date(
            timing.get("issue_date"), f"{case_path}/timing/issue_date", issues
        )
        if timing.get("premium_timing") != "explicit_dates":
            _issue(
                issues,
                "error",
                "premium_timing",
                f"{case_path}/timing/premium_timing",
                "Only explicit_dates is supported.",
            )
        if timing.get("benefit_timing") != "projection_date":
            _issue(
                issues,
                "error",
                "benefit_timing",
                f"{case_path}/timing/benefit_timing",
                "Only projection_date is supported.",
            )
        if case.get("amount_scale") != "currency_unit":
            _issue(
                issues,
                "error",
                "amount_scale",
                f"{case_path}/amount_scale",
                "Canonical money must be normalized to one currency unit.",
            )
        inflation = case.get("inflation_rate")
        if inflation is None:
            _issue(
                issues,
                "warning",
                "inflation_missing",
                f"{case_path}/inflation_rate",
                "Real death benefit will be unavailable.",
            )
        else:
            parsed_inflation = _decimal(
                inflation, f"{case_path}/inflation_rate", issues, nonnegative=False
            )
            if parsed_inflation is not None and (
                parsed_inflation <= -1 or parsed_inflation > Decimal("1")
            ):
                _issue(
                    issues,
                    "error",
                    "inflation_range",
                    f"{case_path}/inflation_rate",
                    "Inflation must be greater than -100% and no more than 100%.",
                )

        premiums = case.get("premium_cashflows", [])
        projections = case.get("projection", [])
        if not isinstance(premiums, list) or not premiums:
            _issue(
                issues,
                "error",
                "premiums_required",
                f"{case_path}/premium_cashflows",
                "At least one premium is required.",
            )
            premiums = []
        premium_dates = []
        premium_times = []
        for premium_index, premium in enumerate(premiums):
            path = f"{case_path}/premium_cashflows/{premium_index}"
            if not isinstance(premium, dict):
                _issue(
                    issues, "error", "premium_item", path, "Premium must be an object."
                )
                continue
            _unknown_keys(premium, PREMIUM_KEYS, path, issues)
            premium_dates.append(_date(premium.get("date"), f"{path}/date", issues))
            premium_times.append(
                _decimal(premium.get("time_years"), f"{path}/time_years", issues)
            )
            amount = _money_decimal(premium.get("amount"), f"{path}/amount", issues)
            if amount == 0:
                _issue(
                    issues,
                    "error",
                    "zero_premium",
                    f"{path}/amount",
                    "Premium amount must be positive.",
                )
        valid_dates = [value for value in premium_dates if value is not None]
        valid_times = [value for value in premium_times if value is not None]
        if valid_dates != sorted(valid_dates) or valid_times != sorted(valid_times):
            _issue(
                issues,
                "error",
                "premium_order",
                f"{case_path}/premium_cashflows",
                "Premium cashflows must be ordered.",
            )
        if issue_date is not None:
            for premium_index, (flow_date, flow_time) in enumerate(
                zip(premium_dates, premium_times)
            ):
                if flow_date is None or flow_time is None:
                    continue
                if not _date_time_consistent(issue_date, flow_date, flow_time):
                    _issue(
                        issues,
                        "error",
                        "date_time_mismatch",
                        f"{case_path}/premium_cashflows/{premium_index}",
                        "date does not match the nominal policy-year or ACT/365F time coordinate.",
                    )

        if not isinstance(projections, list) or not projections:
            _issue(
                issues,
                "error",
                "projection_required",
                f"{case_path}/projection",
                "At least one projection row is required.",
            )
            projections = []
        years, projection_dates, projection_times = [], [], []
        scenario_defs = case.get("scenario_definitions", {})
        if not isinstance(scenario_defs, dict):
            _issue(
                issues,
                "error",
                "scenario_definitions",
                f"{case_path}/scenario_definitions",
                "Scenario definitions must be an object.",
            )
            scenario_defs = {}
        for scenario_id, definition in scenario_defs.items():
            scenario_path = f"{case_path}/scenario_definitions/{scenario_id}"
            if not isinstance(definition, dict):
                _issue(
                    issues,
                    "error",
                    "scenario_definition",
                    scenario_path,
                    "Scenario definition must be an object.",
                )
                continue
            _unknown_keys(definition, SCENARIO_DEFINITION_KEYS, scenario_path, issues)
            if not _is_nonempty_string(definition.get("label")):
                _issue(
                    issues,
                    "error",
                    "scenario_label",
                    f"{scenario_path}/label",
                    "Scenario label must be a non-empty string.",
                )
            if definition.get("guaranteed") is not False:
                _issue(
                    issues,
                    "error",
                    "scenario_guarantee",
                    f"{scenario_path}/guaranteed",
                    "Named scenarios are non-guaranteed; guaranteed values use the dedicated field.",
                )
        for row_index, row in enumerate(projections):
            path = f"{case_path}/projection/{row_index}"
            if not isinstance(row, dict):
                _issue(
                    issues,
                    "error",
                    "projection_item",
                    path,
                    "Projection row must be an object.",
                )
                continue
            _unknown_keys(row, PROJECTION_KEYS, path, issues)
            year = row.get("policy_year")
            if not isinstance(year, int) or isinstance(year, bool) or year < 1:
                _issue(
                    issues,
                    "error",
                    "policy_year",
                    f"{path}/policy_year",
                    "policy_year must be a positive integer.",
                )
            else:
                years.append(year)
            row_date = _date(row.get("date"), f"{path}/date", issues)
            row_time = _decimal(row.get("time_years"), f"{path}/time_years", issues)
            projection_dates.append(row_date)
            projection_times.append(row_time)
            if (
                row_time is not None
                and isinstance(year, int)
                and not isinstance(year, bool)
                and abs(row_time - Decimal(year)) > Decimal("0.05")
            ):
                _issue(
                    issues,
                    "error",
                    "policy_year_time_mismatch",
                    path,
                    "policy_year and time_years differ by more than 0.05 years.",
                )
            if issue_date is not None and row_date is not None and row_time is not None:
                if not _date_time_consistent(issue_date, row_date, row_time):
                    _issue(
                        issues,
                        "error",
                        "date_time_mismatch",
                        path,
                        "date does not match the nominal policy-year or ACT/365F time coordinate.",
                    )
            guaranteed_values = {}
            for value_name in ("death_benefit", "cash_surrender_value"):
                value = row.get(value_name)
                value_path = f"{path}/{value_name}"
                if not isinstance(value, dict):
                    _issue(
                        issues,
                        "error",
                        "benefit_shape",
                        value_path,
                        "Expected guaranteed and scenarios object.",
                    )
                    continue
                _unknown_keys(value, BENEFIT_KEYS, value_path, issues)
                guaranteed = _money_decimal(
                    value.get("guaranteed"), f"{value_path}/guaranteed", issues
                )
                guaranteed_values[value_name] = guaranteed
                scenarios = value.get("scenarios", {})
                if not isinstance(scenarios, dict):
                    _issue(
                        issues,
                        "error",
                        "scenario_values",
                        f"{value_path}/scenarios",
                        "Scenario values must be an object.",
                    )
                    continue
                for scenario_id, scenario_value in scenarios.items():
                    parsed = _money_decimal(
                        scenario_value, f"{value_path}/scenarios/{scenario_id}", issues
                    )
                    if scenario_id not in scenario_defs:
                        _issue(
                            issues,
                            "error",
                            "unknown_scenario",
                            f"{value_path}/scenarios/{scenario_id}",
                            "Scenario has no definition.",
                        )
                    if (
                        parsed is not None
                        and guaranteed is not None
                        and parsed < guaranteed
                    ):
                        _issue(
                            issues,
                            "error",
                            "illustrated_below_guaranteed",
                            f"{value_path}/scenarios/{scenario_id}",
                            "Illustrated total cannot be below guaranteed.",
                        )
            guaranteed_death = guaranteed_values.get("death_benefit")
            guaranteed_cash = guaranteed_values.get("cash_surrender_value")
            if (
                guaranteed_death is not None
                and guaranteed_cash is not None
                and guaranteed_death < guaranteed_cash
            ):
                _issue(
                    issues,
                    "warning",
                    "death_benefit_below_cash_value",
                    path,
                    "Guaranteed death benefit is below guaranteed surrender value; verify the contract benefit rule and table basis.",
                )
        if years != sorted(set(years)):
            _issue(
                issues,
                "error",
                "projection_year_order",
                f"{case_path}/projection",
                "Policy years must be unique and strictly increasing.",
            )
        valid_projection_dates = [
            value for value in projection_dates if value is not None
        ]
        valid_projection_times = [
            value for value in projection_times if value is not None
        ]
        if valid_projection_dates != sorted(
            valid_projection_dates
        ) or valid_projection_times != sorted(valid_projection_times):
            _issue(
                issues,
                "error",
                "projection_order",
                f"{case_path}/projection",
                "Projection dates/times must be ordered.",
            )

    if len(case_ids) != len(set(case_ids)):
        _issue(
            issues,
            "error",
            "duplicate_case_id",
            "/cases",
            "Case IDs must be unique within a product.",
        )

    missing_severity = "error" if strict_evidence else "warning"
    for path in _critical_paths(data):
        record = _provenance_record(provenance, path)
        if record is None:
            _issue(
                issues,
                missing_severity,
                "missing_provenance",
                path,
                "Critical source fact has no provenance record.",
            )
            continue
        confidence = record.get("confidence")
        evidence_refs = record.get("evidence_ids", [])
        supported_confidences = [
            evidence_confidence_by_id[evidence_id]
            for evidence_id in evidence_refs
            if isinstance(evidence_refs, list)
            and isinstance(evidence_id, str)
            and evidence_id in evidence_confidence_by_id
        ]
        supported_confidence = max(supported_confidences, default=None)
        effective_confidence = (
            min(float(confidence), supported_confidence)
            if isinstance(confidence, (int, float))
            and not isinstance(confidence, bool)
            and supported_confidence is not None
            else None
        )
        if (
            record.get("status") != "accepted"
            or effective_confidence is None
            or effective_confidence < 0.85
        ):
            _issue(
                issues,
                missing_severity,
                "critical_provenance_low_confidence",
                path,
                "Critical source fact requires accepted provenance with confidence of at least 0.85.",
            )

    for case_index, case in enumerate(cases):
        if not isinstance(case, dict):
            continue
        basis = case.get("basis", {})
        if not isinstance(basis, dict) or basis.get("kind") != "document_illustration":
            continue
        case_prefix = f"/cases/{case_index}/"
        for path in _critical_paths(data):
            if not path.startswith(case_prefix) or "/scenarios/" not in path:
                continue
            record = _provenance_record(provenance, path)
            evidence_refs = (
                record.get("evidence_ids", []) if isinstance(record, dict) else []
            )
            supporting_kinds = {
                source_kinds.get(evidence_source_by_id.get(evidence_id, ""))
                for evidence_id in evidence_refs
                if isinstance(evidence_id, str)
            }
            if "illustration" not in supporting_kinds:
                _issue(
                    issues,
                    missing_severity,
                    "scenario_requires_illustration_source",
                    path,
                    "A document-illustration scenario must be supported by evidence from a source whose kind is illustration.",
                )

    try:
        json.dumps(data, allow_nan=False)
    except (TypeError, ValueError):
        _issue(issues, "error", "non_json", "/", "Canonical data must be finite JSON.")
    return ValidationResult(issues)
