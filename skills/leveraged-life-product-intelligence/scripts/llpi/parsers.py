"""Layered, auditable file extraction for product-level life-insurance data.

The stdlib-only base routes JSON and CSV directly.  PDFs use PyMuPDF first,
Camelot only when deterministic signals indicate vector tables, Docling for
low-confidence or complex documents, and an LLM only when a configured
fallback client is explicitly supplied.  Optional dependencies are imported
lazily and their absence becomes an auditable warning instead of an import
failure.
"""

from __future__ import annotations

import csv
import hashlib
import importlib
import io
import json
import math
import re
import unicodedata
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import (
    Any,
    Dict,
    Iterable,
    List,
    Mapping,
    Optional,
    Pattern,
    Sequence,
    Tuple,
    Union,
)

from .llm_fallback import HTTPJSONLLMFallback, LLMFallbackError
from .validate import (
    _contains_forbidden_client_text,
    _is_forbidden_client_key,
    validate_product,
)


PARSER_VERSION = "1.0.0"
SUPPORTED_SUFFIXES = {".pdf": "pdf", ".json": "json", ".csv": "csv"}

PatternSpec = Union[str, Pattern[str], Sequence[Union[str, Pattern[str]]]]


DEFAULT_FIELD_PATTERNS: Mapping[str, Sequence[str]] = {
    "product_name": (
        r"(?:保险产品名称|产品名称|保险名称|Product\s+Name)\s*[:：]\s*([^\n|]{2,120})",
        r"(?:条款名称|Policy\s+Name)\s*[:：]\s*([^\n|]{2,120})",
    ),
    "insurer": (
        r"(?:保险公司名称|保险公司|承保公司|Insurer)\s*[:：]\s*([^\n|]{2,120})",
    ),
    "product_type": (
        r"(?:产品类型|险种类型|保险类型|Product\s+Type)\s*[:：]\s*([^\n|]{2,80})",
    ),
    "currency": (
        r"(?:币种|货币单位|Currency)\s*[:：]\s*([A-Za-z]{3}|人民币|港币|美元|欧元|英镑)",
    ),
    "coverage_period": (
        r"(?:保险期间|保障期限|Coverage\s+Period)\s*[:：]\s*([^\n|]{1,80})",
    ),
    "premium_period": (
        r"(?:交费期间|缴费期间|Premium\s+Term)\s*[:：]\s*([^\n|]{1,80})",
    ),
    "policy_year": (r"(?:保单年度|Policy\s+Year)\s*[:：]?\s*([0-9]{1,3})",),
    "premium_amount": (r"(?:保险费|保费|Premium)\s*[:：]?\s*([0-9][0-9,.]*)",),
    "guaranteed_death_benefit": (
        r"(?:保证身故保险金|保证身故金|Guaranteed\s+Death\s+Benefit)\s*[:：]?\s*([0-9][0-9,.]*)",
    ),
    "guaranteed_cash_surrender_value": (
        r"(?:保证现金价值|保证退保价值|Guaranteed\s+(?:Cash|Surrender)\s+Value)\s*[:：]?\s*([0-9][0-9,.]*)",
    ),
    "unit_scale": (
        r"(?:金额单位|单位|Unit)\s*[:：]?\s*(元|千元|万元|人民币元|CNY|HKD|USD)",
    ),
    "guarantee_classification": (
        r"(?:利益性质|保证性质|Guarantee\s+Status)\s*[:：]?\s*(保证|非保证|Guaranteed|Non[- ]Guaranteed)",
    ),
}

CRITICAL_FIELD_NAMES = {
    "currency",
    "policy_year",
    "premium_amount",
    "guaranteed_death_benefit",
    "guaranteed_cash_surrender_value",
    "unit_scale",
    "guarantee_classification",
}

CRITICAL_HEADER_ALIASES: Mapping[str, Sequence[str]] = {
    "currency": (
        "currency",
        "currency_code",
        "币种",
        "货币",
        "货币代码",
    ),
    "policy_year": (
        "policy_year",
        "policyyear",
        "保单年度",
        "保单年",
    ),
    "premium_amount": (
        "premium_amount",
        "premium",
        "annual_premium",
        "single_premium",
        "cumulative_premium",
        "保费",
        "保险费",
        "年交保费",
        "累计保费",
    ),
    "guaranteed_death_benefit": (
        "guaranteed_death_benefit",
        "guaranteeddeathbenefit",
        "guarantee_death_benefit",
        "保证身故保险金",
        "保证身故金",
    ),
    "guaranteed_cash_surrender_value": (
        "guaranteed_cash_surrender_value",
        "guaranteed_cash_value",
        "guaranteed_surrender_value",
        "保证现金价值",
        "保证退保价值",
    ),
    "unit_scale": (
        "unit_scale",
        "amount_unit",
        "monetary_unit",
        "金额单位",
        "金额口径",
        "单位",
    ),
    "guarantee_classification": (
        "guarantee_classification",
        "guarantee_status",
        "guarantee_type",
        "benefit_classification",
        "利益性质",
        "保证性质",
    ),
}

CUSTOMER_OR_PII_FIELD_NAMES = {
    "customer",
    "customer_name",
    "customer_profile",
    "client",
    "client_name",
    "client_profile",
    "user",
    "user_name",
    "user_profile",
    "profile",
    "personal_profile",
    "applicant_name",
    "policyholder_name",
    "insured_person_name",
    "full_name",
    "annual_income",
    "income",
    "household_income",
    "net_worth",
    "assets",
    "liabilities",
    "risk_preference",
    "risk_tolerance",
    "family_responsibility",
    "phone",
    "phone_number",
    "telephone",
    "telephone_number",
    "tel",
    "mobile",
    "mobile_number",
    "email",
    "email_address",
    "address",
    "home_address",
    "id_number",
    "national_id",
    "passport_number",
    "date_of_birth",
    "birth_date",
    "dob",
    "age",
    "insured_age",
    "gender",
    "sex",
    "health",
    "family",
    "dependents",
    "risk_profile",
    "ssn",
    "tax_id",
    "bank_account",
    "account_number",
    "occupation",
    "employer",
    "marital_status",
    "health_status",
    "medical_history",
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

PLAIN_DECIMAL_PATTERN = re.compile(r"^(0|[1-9][0-9]*)(\.[0-9]+)?$")
POSITIVE_INTEGER_PATTERN = re.compile(r"^[1-9][0-9]*$")
MAX_AUTO_ACCEPT_POLICY_YEAR = 200
MAX_AUTO_ACCEPT_MONEY = Decimal("1000000000000000000")

SUPPORTED_CURRENCY_CODES = frozenset(
    {
        "AED",
        "AUD",
        "BHD",
        "BRL",
        "CAD",
        "CHF",
        "CNY",
        "CZK",
        "DKK",
        "EUR",
        "GBP",
        "HKD",
        "HUF",
        "IDR",
        "ILS",
        "INR",
        "JPY",
        "KRW",
        "KWD",
        "MOP",
        "MXN",
        "MYR",
        "NOK",
        "NZD",
        "OMR",
        "PHP",
        "PLN",
        "QAR",
        "RUB",
        "SAR",
        "SEK",
        "SGD",
        "THB",
        "TRY",
        "TWD",
        "USD",
        "VND",
        "ZAR",
    }
)

CURRENCY_VALUE_ALIASES = {
    "RMB": "CNY",
    "人民币": "CNY",
    "人民币元": "CNY",
    "港币": "HKD",
    "港元": "HKD",
    "美元": "USD",
    "美金": "USD",
    "欧元": "EUR",
    "英镑": "GBP",
    "日元": "JPY",
    "新加坡元": "SGD",
}

UNIT_SCALE_VALUE_ALIASES = {
    "元": "1",
    "人民币元": "1",
    "港元": "1",
    "美元": "1",
    "欧元": "1",
    "英镑": "1",
    "cny": "1",
    "hkd": "1",
    "usd": "1",
    "eur": "1",
    "gbp": "1",
    "currency_unit": "1",
    "whole_currency_unit": "1",
    "ones": "1",
    "1": "1",
    "千元": "1000",
    "thousand": "1000",
    "thousands": "1000",
    "1000": "1000",
    "万元": "10000",
    "ten_thousand": "10000",
    "10000": "10000",
    **{code.casefold(): "1" for code in SUPPORTED_CURRENCY_CODES},
}

GUARANTEE_CLASS_VALUE_ALIASES = {
    "保证": "guaranteed",
    "保证利益": "guaranteed",
    "guaranteed": "guaranteed",
    "g": "guaranteed",
    "非保证": "non_guaranteed",
    "非保证利益": "non_guaranteed",
    "演示": "non_guaranteed",
    "演示利益": "non_guaranteed",
    "non_guaranteed": "non_guaranteed",
    "nonguaranteed": "non_guaranteed",
    "illustrated": "non_guaranteed",
}

CANONICAL_JSON_MARKERS = {
    "schema_version",
    "analysis_scope",
    "product",
    "cases",
    "sources",
    "evidence",
    "provenance",
}


class ExtractionError(RuntimeError):
    """Raised when a supported source cannot be decoded or parsed."""


class UnsupportedFileTypeError(ExtractionError):
    """Raised when a source is neither PDF, JSON nor CSV."""


def _reject_json_constant(value: str) -> None:
    raise ValueError("non-finite JSON constant is forbidden: %s" % value)


def _clamp(value: Any, default: float = 0.0) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        number = default
    if not math.isfinite(number):
        number = default
    return round(max(0.0, min(1.0, number)), 6)


def _percentage(value: Any, default: float) -> float:
    try:
        return _clamp(float(value) / 100.0, default)
    except (TypeError, ValueError):
        return _clamp(default)


def _json_safe(value: Any) -> Any:
    """Convert optional-library scalar values into deterministic JSON values."""

    if value is None or isinstance(value, (str, bool, int)):
        return value
    if isinstance(value, float):
        return value if math.isfinite(value) else None
    if isinstance(value, Mapping):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe(item) for item in value]
    item_method = getattr(value, "item", None)
    if callable(item_method):
        try:
            return _json_safe(item_method())
        except (TypeError, ValueError):
            pass
    return str(value)


@dataclass(frozen=True)
class Evidence:
    """Immutable provenance for one page, table, or extracted field."""

    sha256: str
    locator: str
    method: str
    confidence: float
    page: Optional[int] = None
    field: Optional[str] = None
    raw_text: str = ""
    bbox: Optional[Tuple[float, float, float, float]] = None
    reason_codes: Tuple[str, ...] = ()

    @property
    def evidence_id(self) -> str:
        seed = "|".join(
            [
                self.sha256,
                self.locator,
                self.method,
                "" if self.page is None else str(self.page),
                self.field or "",
                self.raw_text[:4000],
            ]
        )
        return "ev_" + hashlib.sha256(seed.encode("utf-8")).hexdigest()[:24]

    def to_dict(self) -> Dict[str, Any]:
        raw_text = self.raw_text[:4000]
        payload: Dict[str, Any] = {
            "evidence_id": self.evidence_id,
            "source_id": "src_" + self.sha256[:24],
            "sha256": self.sha256,
            "document_sha256": self.sha256,
            "locator": self.locator,
            "method": self.method,
            "extractor": self.method,
            "extractor_version": PARSER_VERSION,
            "confidence": _clamp(self.confidence),
        }
        if self.page is not None:
            payload["page"] = self.page
        if self.field:
            payload["field"] = self.field
        if raw_text:
            payload["raw_text"] = raw_text
            payload["content_sha256"] = hashlib.sha256(
                raw_text.encode("utf-8")
            ).hexdigest()
        if self.bbox is not None:
            payload["bbox"] = [round(float(value), 6) for value in self.bbox]
        if self.reason_codes:
            payload["reason_codes"] = sorted(set(self.reason_codes))
        return payload


@dataclass
class ExtractedField:
    """A value and the evidence that supports it."""

    value: Any
    confidence: float
    evidence: List[Evidence]

    def to_dict(self) -> Dict[str, Any]:
        return {
            "value": _json_safe(self.value),
            "confidence": _clamp(self.confidence),
            "evidence": [item.to_dict() for item in self.evidence],
        }


@dataclass
class PageExtraction:
    """Text extracted from a numbered page or whole-document fallback."""

    page: Optional[int]
    text: str
    confidence: float
    method: str
    evidence: Evidence

    def to_dict(self, include_text: bool = True) -> Dict[str, Any]:
        payload: Dict[str, Any] = {
            "confidence": _clamp(self.confidence),
            "method": self.method,
            "evidence": self.evidence.to_dict(),
        }
        if self.page is not None:
            payload["page"] = self.page
        if include_text:
            payload["text"] = self.text
        else:
            payload["chars"] = len(self.text)
        return payload


@dataclass
class TableExtraction:
    """One table returned by Camelot with page-level provenance."""

    page: Optional[int]
    index: int
    rows: List[List[Any]]
    confidence: float
    method: str
    evidence: Evidence

    def to_dict(self, include_rows: bool = True) -> Dict[str, Any]:
        payload: Dict[str, Any] = {
            "index": self.index,
            "confidence": _clamp(self.confidence),
            "method": self.method,
            "evidence": self.evidence.to_dict(),
        }
        if self.page is not None:
            payload["page"] = self.page
        if include_rows:
            payload["rows"] = _json_safe(self.rows)
        else:
            payload["shape"] = [
                len(self.rows),
                max((len(row) for row in self.rows), default=0),
            ]
        return payload


@dataclass(frozen=True)
class RouteDecision:
    """Serializable final decision made from deterministic confidence rules."""

    action: str
    attempted: Tuple[str, ...]
    reasons: Tuple[str, ...]

    def to_dict(self) -> Dict[str, Any]:
        return {
            "action": self.action,
            "attempted": list(self.attempted),
            "reasons": list(self.reasons),
        }


@dataclass
class ExtractionResult:
    """Compact, JSON-serializable output shared by every file route."""

    source: str
    kind: str
    sha256: str
    confidence: float
    fields: Dict[str, ExtractedField]
    route: RouteDecision
    methods: List[str] = field(default_factory=list)
    pages: List[PageExtraction] = field(default_factory=list)
    tables: List[TableExtraction] = field(default_factory=list)
    data: Any = None
    warnings: List[str] = field(default_factory=list)
    dependencies: Dict[str, str] = field(default_factory=dict)
    unresolved_fields: List[str] = field(default_factory=list)
    canonical_ready: bool = False
    parser_version: str = PARSER_VERSION

    @property
    def status(self) -> str:
        """Canonical completion label used by the compact CLI."""

        if self.route.action in ("accepted", "accepted_with_llm"):
            return "complete"
        if self.route.action == "review_recommended":
            return "partial"
        return "manual_review"

    def to_dict(self, include_content: bool = True) -> Dict[str, Any]:
        """Return a stable JSON object; empty optional sections are omitted."""

        payload: Dict[str, Any] = {
            "source": self.source,
            "kind": self.kind,
            "sha256": self.sha256,
            "source_sha256": self.sha256,
            "confidence": _clamp(self.confidence),
            "status": self.status,
            "canonical_ready": bool(self.canonical_ready),
            "parser_version": self.parser_version,
            "methods": list(self.methods),
            "route": self.route.to_dict(),
            "routes": self._route_entries(),
            "fields": {
                name: item.to_dict() for name, item in sorted(self.fields.items())
            },
            "evidence": [item.to_dict() for item in self._all_evidence()],
            "unresolved_fields": sorted(set(self.unresolved_fields)),
        }
        if self.pages:
            payload["pages"] = [
                page.to_dict(include_text=include_content) for page in self.pages
            ]
        if self.tables:
            payload["tables"] = [
                table.to_dict(include_rows=include_content) for table in self.tables
            ]
        if self.data is not None:
            payload["data"] = (
                _json_safe(self.data) if include_content else self._data_summary()
            )
        if self.warnings:
            payload["warnings"] = sorted(set(self.warnings))
        if self.dependencies:
            payload["dependencies"] = dict(sorted(self.dependencies.items()))
        return payload

    def compact_dict(self) -> Dict[str, Any]:
        """Return an audit-friendly stdout form without page text or table rows."""

        return self.to_dict(include_content=False)

    def _data_summary(self) -> Dict[str, Any]:
        if isinstance(self.data, list):
            return {"type": "array", "items": len(self.data)}
        if isinstance(self.data, Mapping):
            return {"type": "object", "keys": len(self.data)}
        return {"type": type(self.data).__name__}

    def _route_entries(self) -> List[Dict[str, str]]:
        entries: List[Dict[str, str]] = []
        for method in self.route.attempted:
            dependency = method.split("-", 1)[0]
            if method.startswith("stdlib-"):
                outcome = "used"
            elif method == "llm-http-json":
                outcome = "used" if method in self.methods else "failed_or_skipped"
            else:
                outcome = self.dependencies.get(dependency, "attempted")
            entries.append({"method": method, "outcome": outcome})
        return entries

    def _all_evidence(self) -> List[Evidence]:
        ordered: List[Evidence] = []
        ordered.extend(page.evidence for page in self.pages)
        ordered.extend(table.evidence for table in self.tables)
        for name in sorted(self.fields):
            ordered.extend(self.fields[name].evidence)
        deduplicated: List[Evidence] = []
        seen: set = set()
        for item in ordered:
            key = (item.sha256, item.locator, item.method, item.page, item.field)
            if key not in seen:
                seen.add(key)
                deduplicated.append(item)
        return deduplicated


@dataclass(frozen=True)
class ConfidenceRouter:
    """Deterministic thresholds that control expensive extraction layers."""

    accept_threshold: float = 0.85
    docling_threshold: float = 0.80
    llm_threshold: float = 0.62
    complex_page_threshold: int = 30

    def __post_init__(self) -> None:
        thresholds = (self.accept_threshold, self.docling_threshold, self.llm_threshold)
        if any(not 0.0 <= value <= 1.0 for value in thresholds):
            raise ValueError("confidence thresholds must be in [0, 1]")
        if self.llm_threshold > self.docling_threshold:
            raise ValueError("llm_threshold must not exceed docling_threshold")
        if self.docling_threshold > self.accept_threshold:
            raise ValueError("docling_threshold must not exceed accept_threshold")
        if self.complex_page_threshold < 1:
            raise ValueError("complex_page_threshold must be positive")

    def local_methods(
        self,
        *,
        primary_confidence: float,
        likely_vector_tables: bool,
        complex_document: bool,
    ) -> Tuple[str, ...]:
        """Choose ordered local enrichments after the mandatory primary pass."""

        methods: List[str] = []
        if likely_vector_tables:
            methods.append("camelot")
        if primary_confidence < self.docling_threshold or complex_document:
            methods.append("docling")
        return tuple(methods)

    def should_use_llm(self, confidence: float) -> bool:
        """Whether local extraction remains below the explicit fallback gate."""

        return _clamp(confidence) < self.llm_threshold

    def action(self, confidence: float, used_llm: bool = False) -> str:
        """Map final confidence to a stable downstream route label."""

        normalized = _clamp(confidence)
        if normalized >= self.accept_threshold:
            return "accepted_with_llm" if used_llm else "accepted"
        if normalized >= self.llm_threshold:
            return "review_recommended"
        return "manual_review"


class FileRouter:
    """Route supported inputs and orchestrate their deterministic parsers."""

    def __init__(
        self,
        confidence_router: Optional[ConfidenceRouter] = None,
        llm_fallback: Optional[HTTPJSONLLMFallback] = None,
        field_patterns: Optional[Mapping[str, PatternSpec]] = None,
    ) -> None:
        self.confidence_router = confidence_router or ConfidenceRouter()
        self.llm_fallback = llm_fallback
        self.field_patterns = _compile_field_patterns(field_patterns)

    def route(self, path: Union[str, Path]) -> str:
        """Return ``pdf``, ``json`` or ``csv`` using suffix then safe sniffing."""

        source = Path(path)
        suffix_kind = SUPPORTED_SUFFIXES.get(source.suffix.lower())
        if suffix_kind:
            return suffix_kind
        try:
            with source.open("rb") as handle:
                head = handle.read(4096)
        except OSError as exc:
            raise ExtractionError("cannot read source: %s" % source) from exc
        if head.startswith(b"%PDF-"):
            return "pdf"
        stripped = head.lstrip(b"\xef\xbb\xbf\x00\t\r\n ")
        if stripped.startswith((b"{", b"[")):
            return "json"
        try:
            sample = head.decode("utf-8-sig")
            dialect = csv.Sniffer().sniff(sample, delimiters=",;\t|")
            if dialect.delimiter:
                return "csv"
        except (UnicodeDecodeError, csv.Error):
            pass
        raise UnsupportedFileTypeError(
            "unsupported source type for %s; expected PDF, JSON, or CSV" % source.name
        )

    def parse(self, path: Union[str, Path]) -> ExtractionResult:
        """Parse one file through the route selected by :meth:`route`."""

        source = Path(path)
        if not source.is_file():
            raise ExtractionError("source file does not exist: %s" % source)
        kind = self.route(source)
        digest = sha256_file(source)
        if kind == "json":
            return self._parse_json(source, digest)
        if kind == "csv":
            return self._parse_csv(source, digest)
        return self._parse_pdf(source, digest)

    def _parse_json(self, source: Path, digest: str) -> ExtractionResult:
        try:
            parsed_data = json.loads(
                source.read_text(encoding="utf-8-sig"),
                parse_constant=_reject_json_constant,
            )
        except (OSError, UnicodeDecodeError, json.JSONDecodeError, ValueError) as exc:
            raise ExtractionError("invalid JSON source: %s" % source.name) from exc

        data, customer_paths = _sanitize_json_customer_keys(parsed_data)
        action, confidence, content_reasons, warnings, unresolved = (
            _assess_json_content(data)
        )
        reason_codes = ["structured_source"] + content_reasons
        canonical_ready = (
            action == "accepted"
            and "canonical_json_runtime_validation_passed" in content_reasons
            and not customer_paths
        )
        if customer_paths:
            reason_codes.append("customer_or_profile_keys_present")
            warnings.append("json_customer_or_profile_keys_present")
            warnings.extend(
                "json_customer_or_profile_key_removed:%s" % path
                for path in customer_paths
            )
            if action in ("accepted", "accepted_with_llm"):
                action = "review_recommended"
            if not _has_meaningful_json_content(data):
                action = "manual_review"
            confidence = min(confidence, 0.84)
        if not canonical_ready:
            reason_codes.append("canonicalization_required")

        evidence = Evidence(
            digest,
            "json:/",
            "stdlib-json",
            confidence,
            raw_text=json.dumps(
                data, ensure_ascii=False, sort_keys=True, separators=(",", ":")
            )[:4000],
            reason_codes=tuple(reason_codes),
        )
        fields: Dict[str, ExtractedField] = {}
        if isinstance(data, Mapping):
            for name, value in data.items():
                field_name = str(name)
                locator = "json:/%s" % _json_pointer_escape(field_name)
                field_evidence = Evidence(
                    digest,
                    locator,
                    "stdlib-json",
                    confidence,
                    field=field_name,
                    raw_text=json.dumps(
                        value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
                    )[:4000],
                    reason_codes=tuple(reason_codes),
                )
                fields[field_name] = ExtractedField(value, confidence, [field_evidence])
        else:
            fields["root"] = ExtractedField(data, confidence, [evidence])
        route = RouteDecision(action, ("stdlib-json",), tuple(reason_codes))
        return ExtractionResult(
            source=str(source),
            kind="json",
            sha256=digest,
            confidence=confidence,
            fields=fields,
            route=route,
            methods=["stdlib-json"],
            data=data,
            warnings=warnings,
            dependencies={"stdlib": "used"},
            unresolved_fields=unresolved,
            canonical_ready=canonical_ready,
        )

    def _parse_csv(self, source: Path, digest: str) -> ExtractionResult:
        try:
            text = source.read_text(encoding="utf-8-sig")
        except (OSError, UnicodeDecodeError) as exc:
            raise ExtractionError("CSV source must be UTF-8: %s" % source.name) from exc
        sample = text[:8192]
        try:
            dialect = csv.Sniffer().sniff(sample, delimiters=",;\t|")
        except csv.Error:
            dialect = csv.excel
        reader = csv.DictReader(io.StringIO(text), dialect=dialect, strict=True)
        if not reader.fieldnames:
            return _invalid_csv_structure_result(
                source,
                digest,
                [],
                ["csv_missing_header"],
            )
        headers = [str(item or "").strip() for item in reader.fieldnames]
        if any(not item for item in headers) or len(set(headers)) != len(headers):
            invalid_warnings: List[str] = []
            if any(not item for item in headers):
                invalid_warnings.append("csv_empty_header")
            duplicates = sorted(
                {header for header in headers if headers.count(header) > 1}
            )
            if duplicates:
                invalid_warnings.append(
                    "csv_duplicate_headers:%s" % ",".join(duplicates)
                )
            return _invalid_csv_structure_result(
                source,
                digest,
                headers,
                invalid_warnings,
            )

        header_pairs = list(zip(headers, reader.fieldnames))
        customer_headers = sorted(
            header for header, _ in header_pairs if _is_customer_or_pii_key(header)
        )
        customer_header_set = set(customer_headers)
        safe_header_pairs = [
            (header, original)
            for header, original in header_pairs
            if header not in customer_header_set
        ]
        safe_headers = [header for header, _ in safe_header_pairs]
        rows: List[Dict[str, Any]] = []
        redacted_value_cells: List[str] = []
        overflow_rows = 0
        truncated_rows = 0
        parse_error: Optional[str] = None
        try:
            for row_number, raw_row in enumerate(reader, start=2):
                if raw_row.get(None) is not None:
                    overflow_rows += 1
                if any(raw_row.get(original) is None for _, original in header_pairs):
                    truncated_rows += 1
                safe_row: Dict[str, Any] = {}
                for header, original in safe_header_pairs:
                    value = raw_row.get(original)
                    if isinstance(value, str) and _contains_forbidden_client_text(
                        value
                    ):
                        safe_row[header] = "[REDACTED]"
                        redacted_value_cells.append("%s@%s" % (header, row_number))
                    else:
                        safe_row[header] = value
                rows.append(safe_row)
        except csv.Error as exc:
            parse_error = _compact_error(exc)
        critical_mapping, ambiguous_mapping = _map_csv_critical_headers(safe_headers)
        invalid_value_fields, inconsistent_value_fields, value_warnings = (
            _validate_csv_critical_values(rows, critical_mapping)
        )
        unresolved_set = CRITICAL_FIELD_NAMES - set(critical_mapping)
        unresolved_set.update(ambiguous_mapping)
        unresolved_set.update(invalid_value_fields)
        if overflow_rows or truncated_rows or not rows or parse_error:
            unresolved_set.update(CRITICAL_FIELD_NAMES)
        unresolved = sorted(unresolved_set)
        structural_errors = bool(
            overflow_rows
            or truncated_rows
            or ambiguous_mapping
            or not rows
            or parse_error
        )
        consistency = (
            1.0
            if not overflow_rows and not truncated_rows
            else max(
                0.5,
                1.0 - (overflow_rows + truncated_rows) / float(max(1, 2 * len(rows))),
            )
        )
        critical_coverage = len(critical_mapping) / float(len(CRITICAL_FIELD_NAMES))
        confidence = _clamp(
            0.50 * (0.90 + 0.09 * consistency) + 0.50 * critical_coverage
        )
        if (
            customer_headers
            or redacted_value_cells
            or structural_errors
            or invalid_value_fields
        ):
            confidence = min(confidence, 0.84)
        fields: Dict[str, ExtractedField] = {}
        for header in safe_headers:
            locator = "csv:column=%s;data_rows=2-%s" % (header, max(2, len(rows) + 1))
            evidence = Evidence(
                digest,
                locator,
                "stdlib-csv",
                confidence,
                field=header,
                raw_text="\n".join(str(row.get(header) or "") for row in rows)[:4000],
                reason_codes=("structured_source",),
            )
            fields[header] = ExtractedField(
                [row.get(header) for row in rows],
                confidence,
                [evidence],
            )
        for canonical_name, source_header in sorted(critical_mapping.items()):
            locator = "csv:column=%s;semantic_field=%s;data_rows=2-%s" % (
                source_header,
                canonical_name,
                max(2, len(rows) + 1),
            )
            evidence = Evidence(
                digest,
                locator,
                "stdlib-csv",
                confidence,
                field=canonical_name,
                raw_text="\n".join(str(row.get(source_header) or "") for row in rows)[
                    :4000
                ],
                reason_codes=(
                    "structured_source",
                    "csv_header_semantic_map",
                    "source_header=%s" % source_header,
                ),
            )
            fields[canonical_name] = ExtractedField(
                [row.get(source_header) for row in rows],
                confidence,
                [evidence],
            )
        table_rows: List[List[Any]] = [safe_headers]
        table_rows.extend(
            [[row.get(header) for header in safe_headers] for row in rows]
        )
        table_evidence = Evidence(
            digest,
            "csv:table=1",
            "stdlib-csv",
            confidence,
            raw_text="\n".join(
                " | ".join(str(cell or "") for cell in row) for row in table_rows
            )[:4000],
            reason_codes=("structured_source",),
        )
        warnings: List[str] = []
        reasons: List[str] = ["structured_source", "canonicalization_required"]
        if unresolved:
            reasons.append("critical_fields_unresolved")
            warnings.append("critical_fields_unresolved:%s" % ",".join(unresolved))
            for name in unresolved:
                if name not in critical_mapping:
                    warnings.append("critical_field_missing:%s" % name)
                elif name in ambiguous_mapping:
                    warnings.append("critical_field_ambiguous:%s" % name)
                elif name in invalid_value_fields:
                    warnings.append("critical_field_invalid_values:%s" % name)
                else:
                    warnings.append("critical_field_structurally_unreliable:%s" % name)
        else:
            reasons.append("critical_headers_semantically_mapped")
        if customer_headers:
            reasons.append("customer_or_pii_columns_present")
            warnings.append(
                "csv_customer_or_pii_columns_removed:%s" % ",".join(customer_headers)
            )
        if redacted_value_cells:
            reasons.append("customer_or_pii_values_present")
            warnings.append(
                "csv_customer_or_pii_values_redacted:%s"
                % ",".join(sorted(redacted_value_cells))
            )
        if overflow_rows or truncated_rows:
            reasons.append("csv_row_width_error")
            warnings.append("csv_inconsistent_row_width")
        if overflow_rows:
            warnings.append("csv_row_width_overflow:%s" % overflow_rows)
        if truncated_rows:
            warnings.append("csv_row_width_truncation:%s" % truncated_rows)
        if not rows:
            reasons.append("csv_no_data_rows")
            warnings.append("csv_no_data_rows")
        if parse_error:
            reasons.append("csv_parse_error")
            warnings.append("csv_parse_error:%s" % parse_error)
        if ambiguous_mapping:
            reasons.append("csv_ambiguous_critical_headers")
            for name, candidates in sorted(ambiguous_mapping.items()):
                warnings.append(
                    "csv_ambiguous_critical_header:%s:%s" % (name, "|".join(candidates))
                )
        if invalid_value_fields:
            reasons.append("csv_critical_value_error")
            warnings.extend(value_warnings)
        if inconsistent_value_fields:
            reasons.append("csv_cross_row_inconsistency")
        if (
            not unresolved
            and not customer_headers
            and not redacted_value_cells
            and not structural_errors
        ):
            action = "accepted"
        elif not rows or not critical_mapping:
            action = "manual_review"
        else:
            action = "review_recommended"
        return ExtractionResult(
            source=str(source),
            kind="csv",
            sha256=digest,
            confidence=confidence,
            fields=fields,
            route=RouteDecision(action, ("stdlib-csv",), tuple(reasons)),
            methods=["stdlib-csv"],
            tables=[
                TableExtraction(
                    None, 1, table_rows, confidence, "stdlib-csv", table_evidence
                )
            ],
            data=rows,
            warnings=warnings,
            dependencies={"stdlib": "used"},
            unresolved_fields=unresolved,
        )

    def _parse_pdf(self, source: Path, digest: str) -> ExtractionResult:
        attempted: List[str] = ["pymupdf"]
        warnings: List[str] = []
        dependencies: Dict[str, str] = {}
        pages, primary_confidence, pdf_signals = _extract_pdf_pymupdf(
            source, digest, warnings, dependencies
        )
        fields = _extract_text_fields(pages, digest, self.field_patterns)
        conflicted_fields = set()
        local_confidence = _semantic_confidence(
            primary_confidence, fields, len(self.field_patterns)
        )
        tables: List[TableExtraction] = []
        likely_tables = bool(pdf_signals.get("likely_vector_tables"))
        complex_document = (
            bool(pdf_signals.get("complex_document"))
            or int(pdf_signals.get("page_count") or 0)
            >= self.confidence_router.complex_page_threshold
        )
        local_methods = self.confidence_router.local_methods(
            primary_confidence=local_confidence,
            likely_vector_tables=likely_tables,
            complex_document=complex_document,
        )
        local_base_confidence = primary_confidence

        if "camelot" in local_methods:
            attempted.append("camelot")
            table_pages = pdf_signals.get("table_pages") or []
            tables = _extract_pdf_camelot(
                source,
                digest,
                table_pages,
                warnings,
                dependencies,
            )
            if tables:
                table_confidence = sum(item.confidence for item in tables) / float(
                    len(tables)
                )
                table_pages = [
                    PageExtraction(
                        table.page,
                        "\n".join(
                            " | ".join(str(cell) for cell in row) for row in table.rows
                        ),
                        table.confidence,
                        table.method,
                        table.evidence,
                    )
                    for table in tables
                ]
                conflicted_fields.update(
                    _merge_fields(
                        fields,
                        _extract_text_fields(table_pages, digest, self.field_patterns),
                    )
                )
                local_base_confidence = max(
                    local_base_confidence,
                    _clamp(0.9 * table_confidence),
                )
                local_confidence = _semantic_confidence(
                    local_base_confidence, fields, len(self.field_patterns)
                )

        docling_text = ""
        docling_confidence = 0.0
        if "docling" in local_methods:
            attempted.append("docling")
            docling_text, docling_confidence = _extract_pdf_docling(
                source, digest, warnings, dependencies
            )
            if docling_text:
                docling_evidence = Evidence(
                    digest,
                    "pdf:document:docling-markdown",
                    "docling",
                    docling_confidence,
                    raw_text=docling_text,
                    bbox=(0.0, 0.0, 1.0, 1.0),
                    reason_codes=("complex_layout_fallback",),
                )
                docling_page = PageExtraction(
                    None,
                    docling_text,
                    docling_confidence,
                    "docling",
                    docling_evidence,
                )
                docling_fields = _extract_text_fields(
                    [docling_page], digest, self.field_patterns
                )
                conflicted_fields.update(_merge_fields(fields, docling_fields))
                if not pages:
                    pages = [docling_page]
                local_base_confidence = max(
                    local_base_confidence, _clamp(0.9 * docling_confidence)
                )
                local_confidence = _semantic_confidence(
                    local_base_confidence, fields, len(self.field_patterns)
                )

        used_llm = False
        fallback = self.llm_fallback
        unresolved = _unresolved_field_names(fields, self.field_patterns)
        critical_unresolved = CRITICAL_FIELD_NAMES & set(unresolved)
        if (
            self.confidence_router.should_use_llm(local_confidence)
            or critical_unresolved
        ):
            if fallback is not None and fallback.configured:
                attempted.append("llm-http-json")
                source_text = _fallback_text(pages, docling_text, unresolved)
                try:
                    llm_result = fallback.extract(
                        text=source_text,
                        source_sha256=digest,
                        existing_fields={
                            name: item.value for name, item in fields.items()
                        },
                        requested_fields=unresolved,
                        context={
                            "source_kind": "pdf",
                            "local_confidence": local_confidence,
                            "instruction": "Extract product facts only; do not infer customer data.",
                        },
                    )
                    for name, item in llm_result.fields.items():
                        if isinstance(
                            item.value, str
                        ) and _contains_forbidden_client_text(item.value):
                            warnings.append(
                                "llm_customer_or_pii_value_dropped:%s" % name
                            )
                            continue
                        llm_confidence = min(
                            item.confidence,
                            llm_result.confidence,
                            0.69,
                        )
                        evidence = Evidence(
                            digest,
                            item.locator,
                            "llm-http-json:%s" % llm_result.model,
                            llm_confidence,
                            field=name,
                            raw_text=json.dumps(
                                item.value,
                                ensure_ascii=False,
                                sort_keys=True,
                                separators=(",", ":"),
                            )[:4000],
                            bbox=(0.0, 0.0, 1.0, 1.0),
                            reason_codes=(
                                "llm_only_candidate",
                                "request_sha256=%s" % llm_result.request_sha256,
                                "response_sha256=%s" % llm_result.response_sha256,
                            ),
                        )
                        candidate = ExtractedField(
                            item.value,
                            llm_confidence,
                            [evidence],
                        )
                        conflicted_fields.update(
                            _merge_fields(fields, {name: candidate})
                        )
                    warnings.extend(llm_result.warnings)
                    local_confidence = max(
                        local_confidence,
                        min(_clamp(llm_result.confidence), 0.69),
                    )
                    used_llm = True
                except LLMFallbackError as exc:
                    warnings.append("llm_fallback_failed:%s" % _compact_error(exc))
            else:
                warnings.append("llm_fallback_not_configured")

        final_unresolved = _unresolved_field_names(fields, self.field_patterns)
        final_critical_unresolved = sorted(CRITICAL_FIELD_NAMES & set(final_unresolved))
        reasons: List[str] = ["canonicalization_required"]
        if likely_tables:
            reasons.append("vector_table_signals")
        if complex_document:
            reasons.append("complex_document")
        if local_confidence < self.confidence_router.accept_threshold:
            reasons.append("confidence_below_auto_accept")
        elif final_critical_unresolved:
            reasons.append("confidence_threshold_met_but_critical_fields_unresolved")
        else:
            reasons.append("confidence_auto_accepted")
        if not pages:
            reasons.append("no_page_text")
        if final_critical_unresolved:
            reasons.append("critical_fields_unresolved")
            warnings.append(
                "critical_fields_unresolved:%s" % ",".join(final_critical_unresolved)
            )
            for name in final_critical_unresolved:
                candidate = fields.get(name)
                if candidate is None:
                    warnings.append("critical_field_missing:%s" % name)
                else:
                    warnings.append(
                        "critical_field_low_confidence:%s:%.6f"
                        % (name, candidate.confidence)
                    )
        warnings.extend(
            "field_conflict:%s" % name for name in sorted(conflicted_fields)
        )
        pii_redacted = any("customer_or_pii" in warning for warning in warnings)
        if pii_redacted:
            reasons.append("customer_or_pii_content_redacted")
            local_confidence = min(local_confidence, 0.84)
        action = self.confidence_router.action(local_confidence, used_llm=used_llm)
        if final_critical_unresolved and action in ("accepted", "accepted_with_llm"):
            action = "review_recommended"
        if pii_redacted and action in ("accepted", "accepted_with_llm"):
            action = "review_recommended"
        methods = _used_methods(attempted, dependencies, used_llm)
        return ExtractionResult(
            source=str(source),
            kind="pdf",
            sha256=digest,
            confidence=local_confidence,
            fields=fields,
            route=RouteDecision(action, tuple(attempted), tuple(reasons)),
            methods=methods,
            pages=pages,
            tables=tables,
            warnings=warnings,
            dependencies=dependencies,
            unresolved_fields=final_unresolved,
        )


def parse_file(
    path: Union[str, Path],
    *,
    llm_fallback: Optional[HTTPJSONLLMFallback] = None,
    field_patterns: Optional[Mapping[str, PatternSpec]] = None,
    router: Optional[ConfidenceRouter] = None,
) -> ExtractionResult:
    """Convenience API for one auditable PDF/JSON/CSV extraction."""

    return FileRouter(
        confidence_router=router,
        llm_fallback=llm_fallback,
        field_patterns=field_patterns,
    ).parse(path)


extract_file = parse_file


def sha256_file(path: Union[str, Path], chunk_size: int = 1024 * 1024) -> str:
    """Hash a source once for every evidence record in its extraction."""

    digest = hashlib.sha256()
    try:
        with Path(path).open("rb") as handle:
            while True:
                chunk = handle.read(chunk_size)
                if not chunk:
                    break
                digest.update(chunk)
    except OSError as exc:
        raise ExtractionError("cannot hash source: %s" % path) from exc
    return digest.hexdigest()


def _compile_field_patterns(
    custom: Optional[Mapping[str, PatternSpec]],
) -> Dict[str, List[Pattern[str]]]:
    combined: Dict[str, PatternSpec] = dict(DEFAULT_FIELD_PATTERNS)
    if custom:
        combined.update(custom)
    compiled: Dict[str, List[Pattern[str]]] = {}
    for name, specification in combined.items():
        values: Iterable[Union[str, Pattern[str]]]
        if isinstance(specification, str) or hasattr(specification, "search"):
            values = [specification]  # type: ignore[list-item]
        else:
            values = specification
        compiled[str(name)] = []
        for value in values:
            if hasattr(value, "search"):
                compiled[str(name)].append(value)  # type: ignore[arg-type]
            else:
                compiled[str(name)].append(re.compile(str(value), flags=re.IGNORECASE))
    return compiled


def _extract_pdf_pymupdf(
    source: Path,
    digest: str,
    warnings: List[str],
    dependencies: Dict[str, str],
) -> Tuple[List[PageExtraction], float, Dict[str, Any]]:
    try:
        pymupdf = importlib.import_module("pymupdf")
    except ImportError:
        dependencies["pymupdf"] = "missing"
        warnings.append("optional_dependency_missing:pymupdf")
        return (
            [],
            0.0,
            {
                "likely_vector_tables": False,
                "complex_document": True,
                "table_pages": [],
                "page_count": 0,
            },
        )

    dependencies["pymupdf"] = "available"
    pages: List[PageExtraction] = []
    table_pages: List[int] = []
    image_heavy_pages = 0
    try:
        document = pymupdf.open(str(source))
        try:
            if getattr(document, "needs_pass", False):
                warnings.append("pdf_encrypted")
                dependencies["pymupdf"] = "failed"
                return (
                    [],
                    0.0,
                    {
                        "likely_vector_tables": False,
                        "complex_document": True,
                        "table_pages": [],
                        "page_count": 0,
                    },
                )
            page_count = len(document)
            for index in range(page_count):
                page = document[index]
                try:
                    text = page.get_text("text", sort=True) or ""
                except TypeError:
                    try:
                        text = page.get_text("text") or ""
                    except Exception as exc:
                        warnings.append(
                            "pymupdf_page_text_failed:page=%s:%s"
                            % (index + 1, _compact_error(exc, limit=80))
                        )
                        text = ""
                except Exception as exc:
                    warnings.append(
                        "pymupdf_page_text_failed:page=%s:%s"
                        % (index + 1, _compact_error(exc, limit=80))
                    )
                    text = ""
                text, redaction_count = _redact_customer_or_pii_text(text)
                if redaction_count:
                    warnings.append(
                        "pymupdf_customer_or_pii_lines_redacted:page=%s:count=%s"
                        % (index + 1, redaction_count)
                    )
                try:
                    drawings = len(page.get_drawings())
                except Exception:
                    drawings = 0
                try:
                    images = len(page.get_images(full=True))
                except Exception:
                    images = 0
                confidence = _text_confidence(text)
                if images and len(text.strip()) < 120:
                    image_heavy_pages += 1
                if _looks_like_vector_table(text, drawings):
                    table_pages.append(index + 1)
                locator = "pdf:page=%s" % (index + 1)
                evidence = Evidence(
                    digest,
                    locator,
                    "pymupdf",
                    confidence,
                    page=index + 1,
                    raw_text=text,
                    bbox=(0.0, 0.0, 1.0, 1.0),
                    reason_codes=("native_pdf_text",),
                )
                pages.append(
                    PageExtraction(index + 1, text, confidence, "pymupdf", evidence)
                )
        finally:
            closer = getattr(document, "close", None)
            if callable(closer):
                try:
                    closer()
                except Exception as exc:
                    warnings.append(
                        "pymupdf_close_failed:%s" % _compact_error(exc, limit=80)
                    )
    except Exception as exc:
        dependencies["pymupdf"] = "failed"
        warnings.append("pymupdf_failed:%s" % _compact_error(exc))
        return (
            [],
            0.0,
            {
                "likely_vector_tables": False,
                "complex_document": True,
                "table_pages": [],
                "page_count": 0,
            },
        )

    dependencies["pymupdf"] = "used"
    nonblank = [page for page in pages if page.text.strip()]
    if nonblank:
        weighted = sum(page.confidence * max(1, len(page.text)) for page in nonblank)
        weight = sum(max(1, len(page.text)) for page in nonblank)
        mean_confidence = weighted / float(weight)
    else:
        mean_confidence = 0.0
    coverage = len(nonblank) / float(max(1, len(pages)))
    document_confidence = _clamp(0.85 * mean_confidence + 0.15 * coverage)
    low_pages = sum(1 for page in pages if page.confidence < 0.55)
    low_ratio = low_pages / float(max(1, len(pages)))
    complex_document = (
        len(pages) >= 30
        or low_ratio >= 0.35
        or image_heavy_pages / float(max(1, len(pages))) >= 0.35
        or len(table_pages) >= 5
    )
    return (
        pages,
        document_confidence,
        {
            "likely_vector_tables": bool(table_pages),
            "complex_document": complex_document,
            "table_pages": table_pages,
            "page_count": len(pages),
        },
    )


def _extract_pdf_camelot(
    source: Path,
    digest: str,
    page_numbers: Sequence[int],
    warnings: List[str],
    dependencies: Dict[str, str],
) -> List[TableExtraction]:
    try:
        camelot = importlib.import_module("camelot")
    except ImportError:
        dependencies["camelot"] = "missing"
        warnings.append("optional_dependency_missing:camelot")
        return []
    dependencies["camelot"] = "available"
    pages_argument = ",".join(str(item) for item in sorted(set(page_numbers))) or "all"
    raw_tables: Any = None
    used_flavor = "lattice"
    lattice_error: Optional[BaseException] = None
    try:
        raw_tables = camelot.read_pdf(
            str(source), pages=pages_argument, flavor="lattice"
        )
    except Exception as exc:
        lattice_error = exc
    if raw_tables is None or len(raw_tables) == 0:
        used_flavor = "stream"
        try:
            raw_tables = camelot.read_pdf(
                str(source), pages=pages_argument, flavor="stream"
            )
        except Exception as exc:
            dependencies["camelot"] = "failed"
            details = _compact_error(exc)
            if lattice_error is not None:
                details = "lattice=%s;stream=%s" % (
                    _compact_error(lattice_error, limit=70),
                    _compact_error(exc, limit=70),
                )
            warnings.append("camelot_failed:%s" % details)
            return []

    extracted: List[TableExtraction] = []
    for index, table in enumerate(raw_tables, start=1):
        try:
            raw_page = getattr(table, "page", None)
            page_number = int(raw_page) if raw_page not in (None, "") else None
        except (TypeError, ValueError):
            page_number = None
        frame = getattr(table, "df", None)
        values = frame.values.tolist() if frame is not None else []
        values, removed_headers, redacted_cells = _sanitize_table_customer_columns(
            values
        )
        if removed_headers:
            warnings.append(
                "camelot_customer_or_pii_columns_removed:table=%s:%s"
                % (index, ",".join(removed_headers))
            )
        if redacted_cells:
            warnings.append(
                "camelot_customer_or_pii_values_redacted:table=%s:count=%s"
                % (index, redacted_cells)
            )
        report = getattr(table, "parsing_report", {}) or {}
        accuracy = _percentage(report.get("accuracy"), 0.5)
        whitespace = _percentage(report.get("whitespace"), 0.5)
        confidence = _clamp(0.55 + 0.40 * accuracy + 0.05 * (1.0 - whitespace))
        method = "camelot-%s" % used_flavor
        locator = "pdf:page=%s;table=%s" % (
            page_number if page_number is not None else "unknown",
            index,
        )
        evidence = Evidence(
            digest,
            locator,
            method,
            confidence,
            page=page_number,
            raw_text=json.dumps(
                _json_safe(values), ensure_ascii=False, separators=(",", ":")
            )[:4000],
            bbox=(0.0, 0.0, 1.0, 1.0),
            reason_codes=("vector_table_candidate",),
        )
        extracted.append(
            TableExtraction(
                page_number,
                index,
                _json_safe(values),
                confidence,
                method,
                evidence,
            )
        )
    dependencies["camelot"] = "used" if extracted else "available"
    if not extracted:
        warnings.append("camelot_no_tables")
    return extracted


def _extract_pdf_docling(
    source: Path,
    digest: str,
    warnings: List[str],
    dependencies: Dict[str, str],
) -> Tuple[str, float]:
    del digest  # Hash is attached by the caller to selected Docling evidence.
    try:
        converter_module = importlib.import_module("docling.document_converter")
        converter_class = getattr(converter_module, "DocumentConverter")
    except (ImportError, AttributeError):
        dependencies["docling"] = "missing"
        warnings.append("optional_dependency_missing:docling")
        return "", 0.0
    dependencies["docling"] = "available"
    try:
        converted = converter_class().convert(str(source))
        document = getattr(converted, "document", converted)
        exporter = getattr(document, "export_to_markdown", None)
        if not callable(exporter):
            raise AttributeError("Docling result has no export_to_markdown")
        text = str(exporter() or "")
        text, redaction_count = _redact_customer_or_pii_text(text)
        if redaction_count:
            warnings.append(
                "docling_customer_or_pii_lines_redacted:count=%s" % redaction_count
            )
    except Exception as exc:
        dependencies["docling"] = "failed"
        warnings.append("docling_failed:%s" % _compact_error(exc))
        return "", 0.0
    confidence = _text_confidence(text)
    dependencies["docling"] = "used" if text.strip() else "available"
    if not text.strip():
        warnings.append("docling_empty_output")
    return text, confidence


def _text_confidence(text: str) -> float:
    stripped = text.strip()
    if not stripped:
        return 0.0
    printable = sum(1 for character in stripped if character.isprintable()) / float(
        len(stripped)
    )
    replacement_ratio = stripped.count("\ufffd") / float(len(stripped))
    tokens = re.findall(r"[A-Za-z0-9\u4e00-\u9fff]+", stripped)
    density = min(1.0, len(stripped) / 300.0)
    token_score = min(1.0, len(tokens) / 45.0)
    line_score = min(
        1.0, len([line for line in stripped.splitlines() if line.strip()]) / 12.0
    )
    confidence = (
        0.15
        + 0.30 * density
        + 0.25 * printable
        + 0.20 * token_score
        + 0.10 * line_score
        - 2.0 * replacement_ratio
    )
    return _clamp(confidence)


def _looks_like_vector_table(text: str, drawings: int) -> bool:
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    numeric_rows = 0
    numeric_total = 0
    for line in lines:
        numeric_tokens = re.findall(r"[-+]?\d[\d,.%]*", line)
        numeric_total += len(numeric_tokens)
        if len(numeric_tokens) >= 3:
            numeric_rows += 1
    keywords = re.search(
        r"现金价值|身故保险金|保单年度|累计保费|红利|cash\s+value|death\s+benefit|policy\s+year",
        text,
        flags=re.IGNORECASE,
    )
    return bool(
        (drawings >= 5 and (numeric_rows >= 2 or numeric_total >= 6))
        or (keywords and numeric_rows >= 2)
    )


def _extract_text_fields(
    pages: Sequence[PageExtraction],
    digest: str,
    patterns: Mapping[str, Sequence[Pattern[str]]],
) -> Dict[str, ExtractedField]:
    fields: Dict[str, ExtractedField] = {}
    for page in pages:
        if not page.text:
            continue
        for name, field_patterns in patterns.items():
            if name in fields:
                continue
            for pattern in field_patterns:
                match = pattern.search(page.text)
                if not match:
                    continue
                value = match.group(1) if match.lastindex else match.group(0)
                value = re.sub(r"\s+", " ", str(value)).strip(" :：|\t\r\n")
                if not value:
                    continue
                page_locator = (
                    "pdf:page=%s" % page.page
                    if page.page is not None
                    else "pdf:document"
                )
                locator = "%s;chars=%s-%s" % (page_locator, match.start(), match.end())
                confidence = _clamp(min(0.94, 0.72 + 0.24 * page.confidence))
                evidence = Evidence(
                    digest,
                    locator,
                    page.method,
                    confidence,
                    page=page.page,
                    field=name,
                    raw_text=match.group(0),
                    bbox=(0.0, 0.0, 1.0, 1.0) if page.page is not None else None,
                    reason_codes=("recognized_field_label",),
                )
                fields[name] = ExtractedField(value, confidence, [evidence])
                break
    return fields


def _merge_fields(
    target: Dict[str, ExtractedField],
    candidates: Mapping[str, ExtractedField],
) -> List[str]:
    conflicts: List[str] = []
    for name, candidate in candidates.items():
        current = target.get(name)
        if current is None:
            target[name] = candidate
        elif current.value != candidate.value:
            conflicts.append(name)
            winner = candidate if candidate.confidence > current.confidence else current
            evidence = current.evidence + candidate.evidence
            target[name] = ExtractedField(
                winner.value, min(winner.confidence, 0.64), evidence
            )
        elif current.value == candidate.value:
            seen = {(item.locator, item.method) for item in current.evidence}
            for item in candidate.evidence:
                if (item.locator, item.method) not in seen:
                    current.evidence.append(item)
            independent = any(
                item.method != current.evidence[0].method
                for item in current.evidence[1:]
            )
            if independent:
                current.confidence = min(
                    0.99, max(current.confidence, candidate.confidence) + 0.05
                )
    return conflicts


def _pages_text(pages: Sequence[PageExtraction]) -> str:
    sections: List[str] = []
    for page in pages:
        label = "document" if page.page is None else "page %s" % page.page
        sections.append("[%s]\n%s" % (label, page.text))
    return "\n\n".join(sections)


def _semantic_confidence(
    base_confidence: float,
    fields: Mapping[str, ExtractedField],
    expected_count: int,
) -> float:
    """Combine extraction mechanics with expected-field coverage.

    A cleanly decoded but semantically irrelevant page must not be accepted
    merely because it contains a lot of printable text.
    """

    accepted_fields = sum(item.confidence >= 0.85 for item in fields.values())
    coverage = accepted_fields / float(max(1, expected_count))
    return _clamp(0.50 * _clamp(base_confidence) + 0.50 * coverage)


def _unresolved_field_names(
    fields: Mapping[str, ExtractedField],
    expected: Mapping[str, Any],
) -> List[str]:
    return sorted(
        name
        for name in expected
        if name not in fields or fields[name].confidence < 0.85
    )


def _fallback_text(
    pages: Sequence[PageExtraction],
    docling_text: str,
    unresolved_fields: Sequence[str],
    limit: int = 12000,
) -> str:
    """Select bounded, domain-relevant snippets for the explicit LLM route."""

    keyword = re.compile(
        r"产品|保险|保费|现金价值|退保|身故|保额|红利|币种|单位|保单年度|"
        r"product|premium|cash|surrender|death|benefit|currency|unit|policy\s+year",
        flags=re.IGNORECASE,
    )
    sections: List[str] = [
        "[unresolved fields] " + ", ".join(sorted(unresolved_fields))
    ]

    def relevant_lines(text: str) -> List[str]:
        lines = [line.strip() for line in text.splitlines() if line.strip()]
        selected = set()
        for index, line in enumerate(lines):
            if keyword.search(line):
                selected.update(range(max(0, index - 1), min(len(lines), index + 2)))
        return [lines[index] for index in sorted(selected)]

    for page in sorted(pages, key=lambda item: (item.page is None, item.page or 0)):
        selected = relevant_lines(page.text)
        if not selected and page.confidence < 0.55:
            selected = [page.text[:800]]
        if selected:
            label = "document" if page.page is None else "page %s" % page.page
            sections.append("[%s]\n%s" % (label, "\n".join(selected)))
        if sum(len(section) for section in sections) >= limit:
            break
    if docling_text:
        selected = relevant_lines(docling_text)
        if selected:
            sections.append("[docling]\n%s" % "\n".join(selected))
    return "\n\n".join(sections)[:limit]


def _used_methods(
    attempted: Sequence[str],
    dependencies: Mapping[str, str],
    used_llm: bool,
) -> List[str]:
    used: List[str] = []
    for method in attempted:
        dependency = method.split("-", 1)[0]
        if method == "llm-http-json":
            if used_llm:
                used.append(method)
        elif dependencies.get(dependency) == "used":
            used.append(method)
    return used


def _invalid_csv_structure_result(
    source: Path,
    digest: str,
    headers: Sequence[str],
    structural_warnings: Sequence[str],
) -> ExtractionResult:
    """Return an auditable manual-review result for unusable CSV headers."""

    unresolved = sorted(CRITICAL_FIELD_NAMES)
    warnings = list(structural_warnings)
    warnings.append("critical_fields_unresolved:%s" % ",".join(unresolved))
    warnings.extend("critical_field_missing:%s" % name for name in unresolved)
    customer_headers = sorted(
        header for header in headers if _is_customer_or_pii_key(header)
    )
    if customer_headers:
        warnings.append(
            "csv_customer_or_pii_columns_removed:%s" % ",".join(customer_headers)
        )
    customer_header_set = set(customer_headers)
    safe_headers = [header for header in headers if header not in customer_header_set]
    reasons = [
        "structured_source",
        "csv_header_structure_error",
        "critical_fields_unresolved",
        "canonicalization_required",
    ]
    if customer_headers:
        reasons.append("customer_or_pii_columns_present")
    evidence = Evidence(
        digest,
        "csv:header",
        "stdlib-csv",
        0.0,
        raw_text=" | ".join(safe_headers)[:4000],
        reason_codes=tuple(reasons),
    )
    return ExtractionResult(
        source=str(source),
        kind="csv",
        sha256=digest,
        confidence=0.0,
        fields={},
        route=RouteDecision("manual_review", ("stdlib-csv",), tuple(reasons)),
        methods=["stdlib-csv"],
        tables=[TableExtraction(None, 1, [safe_headers], 0.0, "stdlib-csv", evidence)],
        data=[],
        warnings=warnings,
        dependencies={"stdlib": "used"},
        unresolved_fields=unresolved,
    )


def _normalize_semantic_key(value: Any) -> str:
    """Normalize a field/header label without translating its meaning."""

    normalized = unicodedata.normalize("NFKC", str(value)).strip().casefold()
    normalized = re.sub(r"[\s./\\:;()\[\]{}\-]+", "_", normalized)
    normalized = re.sub(r"[^\w\u4e00-\u9fff]+", "_", normalized)
    return re.sub(r"_+", "_", normalized).strip("_")


def _is_customer_or_pii_key(value: Any) -> bool:
    """Identify explicit customer/profile/PII fields, not product attributes."""

    if _is_forbidden_client_key(value):
        return True
    normalized = _normalize_semantic_key(value)
    forbidden = {_normalize_semantic_key(item) for item in CUSTOMER_OR_PII_FIELD_NAMES}
    compact = normalized.replace("_", "")
    forbidden_compact = {item.replace("_", "") for item in forbidden}
    if normalized in forbidden or compact in forbidden_compact:
        return True
    if normalized.startswith(
        (
            "customer_",
            "client_",
            "personal_",
            "user_",
            "applicant_",
            "policyholder_",
            "profile_",
        )
    ):
        return True
    if compact.startswith(
        (
            "customer",
            "client",
            "personalprofile",
            "userprofile",
            "applicant",
            "policyholder",
            "profile",
        )
    ):
        return True
    return (
        "客户" in normalized
        or "用户画像" in normalized
        or normalized.startswith("个人画像")
    )


def _redact_customer_or_pii_text(value: str) -> Tuple[str, int]:
    """Redact whole lines containing explicit client/PII labels."""

    lines = value.splitlines()
    if not lines:
        lines = [value]
    redacted = 0
    safe_lines: List[str] = []
    redact_next_value = False
    redact_markdown_table = False
    for line in lines:
        stripped = line.strip()
        if redact_markdown_table:
            if stripped.startswith("|"):
                safe_lines.append("[REDACTED]")
                redacted += 1
                continue
            redact_markdown_table = False
        if redact_next_value:
            safe_lines.append("[REDACTED]")
            redacted += 1
            redact_next_value = False
            continue
        if _contains_forbidden_client_text(line):
            safe_lines.append("[REDACTED]")
            redacted += 1
            if stripped.startswith("|"):
                redact_markdown_table = True
            elif not re.search(r"[:：=#]", line):
                redact_next_value = True
        else:
            safe_lines.append(line)
    return "\n".join(safe_lines), redacted


def _sanitize_table_customer_columns(
    rows: Sequence[Sequence[Any]],
) -> Tuple[List[List[Any]], List[str], int]:
    """Remove explicitly customer-labelled columns from a parsed table."""

    normalized_rows = [list(row) for row in rows]
    if not normalized_rows:
        return normalized_rows, [], 0
    headers = normalized_rows[0]
    removed_indexes = [
        index for index, header in enumerate(headers) if _is_customer_or_pii_key(header)
    ]
    removed = {index for index in removed_indexes}
    safe_rows = [
        [cell for index, cell in enumerate(row) if index not in removed]
        for row in normalized_rows
    ]
    redacted_cells = 0
    for row_index, row in enumerate(safe_rows):
        for column_index, cell in enumerate(row):
            if isinstance(cell, str) and _contains_forbidden_client_text(cell):
                row[column_index] = "[REDACTED]"
                redacted_cells += 1
                if (
                    not re.search(r"[:：=#]", cell)
                    and row_index + 1 < len(safe_rows)
                    and column_index < len(safe_rows[row_index + 1])
                ):
                    safe_rows[row_index + 1][column_index] = "[REDACTED]"
                    redacted_cells += 1
    return (
        safe_rows,
        sorted(str(headers[index]) for index in removed_indexes),
        redacted_cells,
    )


def _sanitize_json_customer_keys(
    value: Any,
    pointer: str = "",
) -> Tuple[Any, List[str]]:
    """Drop explicit customer/profile keys and return sorted JSON pointers."""

    if isinstance(value, Mapping):
        sanitized: Dict[str, Any] = {}
        removed: List[str] = []
        redacted_raw_text = False
        for raw_name, item in value.items():
            name = str(raw_name)
            child_pointer = "%s/%s" % (pointer, _json_pointer_escape(name))
            if _is_customer_or_pii_key(name):
                removed.append(child_pointer or "/")
                continue
            if name == "raw_text" and isinstance(item, str):
                safe_text, redaction_count = _redact_customer_or_pii_text(item)
                if redaction_count:
                    sanitized[name] = safe_text
                    removed.append(child_pointer or "/")
                    redacted_raw_text = True
                    continue
            child, child_removed = _sanitize_json_customer_keys(item, child_pointer)
            sanitized[name] = child
            removed.extend(child_removed)
        if redacted_raw_text and isinstance(sanitized.get("raw_text"), str):
            sanitized["content_sha256"] = hashlib.sha256(
                sanitized["raw_text"].encode("utf-8")
            ).hexdigest()
        return sanitized, sorted(set(removed))
    if isinstance(value, list):
        sanitized_items: List[Any] = []
        removed = []
        for index, item in enumerate(value):
            child, child_removed = _sanitize_json_customer_keys(
                item, "%s/%s" % (pointer, index)
            )
            sanitized_items.append(child)
            removed.extend(child_removed)
        return sanitized_items, sorted(set(removed))
    if isinstance(value, str) and _contains_forbidden_client_text(value):
        return "[REDACTED]", [pointer or "/"]
    return value, []


def _has_meaningful_json_content(value: Any) -> bool:
    if isinstance(value, Mapping):
        return any(_has_meaningful_json_content(item) for item in value.values())
    if isinstance(value, list):
        return any(_has_meaningful_json_content(item) for item in value)
    return value is not None and value != ""


def _assess_json_content(
    data: Any,
) -> Tuple[str, float, List[str], List[str], List[str]]:
    """Route JSON by canonical validation or explicit product semantics."""

    if isinstance(data, Mapping) and set(data) & CANONICAL_JSON_MARKERS:
        validation = validate_product(data, strict_evidence=True)
        warnings = [
            "json_runtime_validation_%s:%s:%s"
            % (issue.severity, issue.code, issue.path or "/")
            for issue in validation.issues
        ]
        if validation.ok:
            return (
                "accepted",
                0.99,
                ["canonical_json_runtime_validation_passed"],
                warnings,
                [],
            )
        sequences = _canonical_json_critical_sequences(data)
        valid_fields, _, semantic_warnings = _valid_json_critical_sequences(sequences)
        unresolved = sorted(CRITICAL_FIELD_NAMES - valid_fields)
        warnings.extend(semantic_warnings)
        if unresolved:
            warnings.append("critical_fields_unresolved:%s" % ",".join(unresolved))
        return (
            "manual_review",
            0.49,
            ["canonical_json_runtime_validation_failed", "critical_fields_unresolved"],
            warnings,
            unresolved,
        )

    sequences = _collect_json_semantic_critical_sequences(data)
    valid_fields, inconsistent_fields, warnings = _valid_json_critical_sequences(
        sequences
    )
    unresolved = sorted(CRITICAL_FIELD_NAMES - valid_fields)
    has_product_identity = _has_noncanonical_product_identity(data)
    coverage = len(valid_fields) / float(len(CRITICAL_FIELD_NAMES))
    if unresolved:
        warnings.append("critical_fields_unresolved:%s" % ",".join(unresolved))
        warnings.extend(
            "critical_field_missing_or_invalid:%s" % name for name in unresolved
        )
    reasons: List[str] = []
    if inconsistent_fields:
        reasons.append("json_cross_value_inconsistency")
    if has_product_identity and not unresolved:
        reasons.append("noncanonical_product_semantics_validated")
        return "accepted", 0.95, reasons, warnings, unresolved
    if has_product_identity:
        reasons.extend(
            ["noncanonical_product_semantics_present", "critical_fields_unresolved"]
        )
        return (
            "review_recommended",
            min(0.84, _clamp(0.40 + 0.44 * coverage)),
            reasons,
            warnings,
            unresolved,
        )
    reasons.extend(["irrelevant_json_manual_review", "critical_fields_unresolved"])
    warnings.append("json_product_semantics_missing")
    return "manual_review", 0.20, reasons, warnings, unresolved


def _canonical_json_critical_sequences(data: Mapping[str, Any]) -> Dict[str, List[Any]]:
    sequences: Dict[str, List[Any]] = {name: [] for name in CRITICAL_FIELD_NAMES}
    product = data.get("product")
    if isinstance(product, Mapping) and product.get("currency") is not None:
        sequences["currency"].append(product.get("currency"))
    cases = data.get("cases")
    if not isinstance(cases, list):
        return sequences
    for case in cases:
        if not isinstance(case, Mapping):
            continue
        if case.get("amount_scale") is not None:
            sequences["unit_scale"].append(case.get("amount_scale"))
        premiums = case.get("premium_cashflows")
        if isinstance(premiums, list):
            for premium in premiums:
                if isinstance(premium, Mapping) and premium.get("amount") is not None:
                    sequences["premium_amount"].append(premium.get("amount"))
        projection = case.get("projection")
        if not isinstance(projection, list):
            continue
        for row in projection:
            if not isinstance(row, Mapping):
                continue
            if row.get("policy_year") is not None:
                sequences["policy_year"].append(row.get("policy_year"))
            death = row.get("death_benefit")
            if isinstance(death, Mapping) and death.get("guaranteed") is not None:
                sequences["guaranteed_death_benefit"].append(death.get("guaranteed"))
                sequences["guarantee_classification"].append("guaranteed")
            cash = row.get("cash_surrender_value")
            if isinstance(cash, Mapping) and cash.get("guaranteed") is not None:
                sequences["guaranteed_cash_surrender_value"].append(
                    cash.get("guaranteed")
                )
                sequences["guarantee_classification"].append("guaranteed")
    return sequences


def _collect_json_semantic_critical_sequences(data: Any) -> Dict[str, List[Any]]:
    sequences: Dict[str, List[Any]] = {name: [] for name in CRITICAL_FIELD_NAMES}

    def visit(value: Any) -> None:
        if isinstance(value, Mapping):
            for raw_name, child in value.items():
                mapping, _ = _map_csv_critical_headers([str(raw_name)])
                for canonical_name in mapping:
                    if isinstance(child, list) and all(
                        not isinstance(item, (Mapping, list)) for item in child
                    ):
                        sequences[canonical_name].extend(child)
                    elif not isinstance(child, (Mapping, list)):
                        sequences[canonical_name].append(child)
                visit(child)
        elif isinstance(value, list):
            for child in value:
                visit(child)

    visit(data)
    return sequences


def _valid_json_critical_sequences(
    sequences: Mapping[str, Sequence[Any]],
) -> Tuple[set, set, List[str]]:
    valid_fields = set()
    inconsistent_fields = set()
    warnings: List[str] = []
    stable_fields = {"currency", "unit_scale", "guarantee_classification"}
    for canonical_name in sorted(CRITICAL_FIELD_NAMES):
        values = list(sequences.get(canonical_name, []))
        if not values:
            continue
        canonical_values = set()
        ordered_values: List[str] = []
        valid = True
        for index, value in enumerate(values, start=1):
            accepted, normalized, reason = _validate_csv_critical_value(
                canonical_name, value
            )
            if not accepted:
                valid = False
                warnings.append(
                    "json_critical_value_invalid:%s:index=%s:%s"
                    % (canonical_name, index, reason)
                )
            elif normalized is not None:
                canonical_values.add(normalized)
                ordered_values.append(normalized)
        if canonical_name in stable_fields and len(canonical_values) > 1:
            valid = False
            inconsistent_fields.add(canonical_name)
            warnings.append(
                "json_critical_value_inconsistent:%s:%s"
                % (canonical_name, "|".join(sorted(canonical_values)))
            )
        if canonical_name == "policy_year" and ordered_values:
            years = [int(item) for item in ordered_values]
            if len(set(years)) != len(years) or any(
                current <= previous for previous, current in zip(years, years[1:])
            ):
                valid = False
                inconsistent_fields.add(canonical_name)
                warnings.append(
                    "json_policy_year_not_unique_strictly_increasing:%s"
                    % "|".join(str(item) for item in years)
                )
        if canonical_name == "premium_amount" and ordered_values:
            premiums = [Decimal(item) for item in ordered_values]
            if not any(item > 0 for item in premiums):
                valid = False
                warnings.append("json_premium_requires_at_least_one_positive_value")
        if canonical_name == "guaranteed_death_benefit" and ordered_values:
            if any(Decimal(item) <= 0 for item in ordered_values):
                valid = False
                warnings.append("json_guaranteed_death_benefit_must_be_positive")
        if valid:
            valid_fields.add(canonical_name)
    if (
        sequences.get("guaranteed_death_benefit")
        and sequences.get("guaranteed_cash_surrender_value")
        and sequences.get("guarantee_classification")
    ):
        classifications = []
        for value in sequences["guarantee_classification"]:
            accepted, normalized, _ = _validate_csv_critical_value(
                "guarantee_classification", value
            )
            if accepted:
                classifications.append(normalized)
        if any(value != "guaranteed" for value in classifications):
            valid_fields.discard("guarantee_classification")
            inconsistent_fields.add("guarantee_classification")
            warnings.append("json_guaranteed_fields_classified_non_guaranteed")
    return valid_fields, inconsistent_fields, warnings


def _has_noncanonical_product_identity(data: Any) -> bool:
    found = set()

    def valid_identity_value(value: Any) -> bool:
        return (
            isinstance(value, str) and bool(value.strip()) and len(value.strip()) <= 300
        )

    def visit(value: Any) -> None:
        if isinstance(value, Mapping):
            for raw_name, child in value.items():
                normalized = _normalize_semantic_key(raw_name)
                compact = normalized.replace("_", "")
                if valid_identity_value(child) and compact in {
                    "productname",
                    "insuranceproductname",
                    "保险产品名称",
                    "产品名称",
                }:
                    found.add("product_name")
                elif valid_identity_value(child) and compact in {
                    "insurer",
                    "insurancecompany",
                    "保险公司",
                }:
                    found.add("insurer")
                elif valid_identity_value(child) and compact in {
                    "producttype",
                    "insurancetype",
                    "产品类型",
                    "险种类型",
                }:
                    found.add("product_type")
                visit(child)
        elif isinstance(value, list):
            for child in value:
                visit(child)

    visit(data)
    return "product_name" in found or {"insurer", "product_type"} <= found


def _map_csv_critical_headers(
    headers: Sequence[str],
) -> Tuple[Dict[str, str], Dict[str, List[str]]]:
    """Map header aliases to canonical critical fields and expose ambiguity."""

    mapping: Dict[str, str] = {}
    ambiguous: Dict[str, List[str]] = {}
    for canonical_name in sorted(CRITICAL_FIELD_NAMES):
        aliases = CRITICAL_HEADER_ALIASES.get(canonical_name, (canonical_name,))
        candidates: List[str] = []
        for header in headers:
            normalized_header = _normalize_semantic_key(header)
            if any(
                _semantic_header_matches(
                    normalized_header,
                    _normalize_semantic_key(alias),
                )
                for alias in aliases
            ):
                candidates.append(header)
        if candidates:
            mapping[canonical_name] = candidates[0]
        if len(candidates) > 1:
            ambiguous[canonical_name] = sorted(candidates)
    return mapping, ambiguous


def _validate_csv_critical_values(
    rows: Sequence[Mapping[str, Any]],
    critical_mapping: Mapping[str, str],
) -> Tuple[set, set, List[str]]:
    """Validate every mapped critical value and stable cross-row dimensions."""

    invalid_fields = set()
    inconsistent_fields = set()
    warnings: List[str] = []
    for canonical_name, source_header in sorted(critical_mapping.items()):
        canonical_values: Dict[str, List[int]] = {}
        ordered_values: List[Tuple[int, str]] = []
        for row_index, row in enumerate(rows, start=2):
            valid, canonical_value, reason = _validate_csv_critical_value(
                canonical_name,
                row.get(source_header),
            )
            if not valid:
                invalid_fields.add(canonical_name)
                warnings.append(
                    "csv_critical_value_invalid:%s:row=%s:%s"
                    % (canonical_name, row_index, reason)
                )
                continue
            normalized = str(canonical_value)
            canonical_values.setdefault(normalized, []).append(row_index)
            ordered_values.append((row_index, normalized))
        if (
            canonical_name
            in {
                "currency",
                "unit_scale",
                "guarantee_classification",
            }
            and len(canonical_values) > 1
        ):
            invalid_fields.add(canonical_name)
            inconsistent_fields.add(canonical_name)
            detail = "|".join(
                "%s@%s" % (value, ",".join(str(item) for item in indexes))
                for value, indexes in sorted(canonical_values.items())
            )
            warnings.append(
                "csv_critical_value_inconsistent:%s:%s" % (canonical_name, detail)
            )
        if canonical_name == "policy_year" and ordered_values:
            years = [(row_index, int(value)) for row_index, value in ordered_values]
            offending_rows = [
                current_row
                for (previous_row, previous), (current_row, current) in zip(
                    years, years[1:]
                )
                if current <= previous
            ]
            if offending_rows:
                invalid_fields.add(canonical_name)
                inconsistent_fields.add(canonical_name)
                warnings.append(
                    "csv_policy_year_not_unique_strictly_increasing:rows=%s:values=%s"
                    % (
                        ",".join(str(item) for item in offending_rows),
                        "|".join(str(value) for _, value in years),
                    )
                )
        if canonical_name == "premium_amount" and ordered_values:
            premiums = [
                (row_index, Decimal(value)) for row_index, value in ordered_values
            ]
            if not any(value > 0 for _, value in premiums):
                invalid_fields.add(canonical_name)
                warnings.append("csv_premium_requires_at_least_one_positive_value")
            if _is_cumulative_premium_header(source_header):
                decreasing_rows = [
                    current_row
                    for (previous_row, previous), (current_row, current) in zip(
                        premiums, premiums[1:]
                    )
                    if current < previous
                ]
                if decreasing_rows:
                    invalid_fields.add(canonical_name)
                    inconsistent_fields.add(canonical_name)
                    warnings.append(
                        "csv_cumulative_premium_decreased:rows=%s:values=%s"
                        % (
                            ",".join(str(item) for item in decreasing_rows),
                            "|".join(format(value, "f") for _, value in premiums),
                        )
                    )
        if canonical_name == "guaranteed_death_benefit" and ordered_values:
            zero_rows = [
                row_index for row_index, value in ordered_values if Decimal(value) <= 0
            ]
            if zero_rows:
                invalid_fields.add(canonical_name)
                warnings.append(
                    "csv_guaranteed_death_benefit_must_be_positive:rows=%s"
                    % ",".join(str(item) for item in zero_rows)
                )

    if {
        "guarantee_classification",
        "guaranteed_death_benefit",
        "guaranteed_cash_surrender_value",
    } <= set(critical_mapping):
        classification_header = critical_mapping["guarantee_classification"]
        contradictory_rows: List[int] = []
        for row_index, row in enumerate(rows, start=2):
            valid, normalized, _ = _validate_csv_critical_value(
                "guarantee_classification", row.get(classification_header)
            )
            if valid and normalized != "guaranteed":
                contradictory_rows.append(row_index)
        if contradictory_rows:
            invalid_fields.add("guarantee_classification")
            inconsistent_fields.add("guarantee_classification")
            warnings.append(
                "csv_guaranteed_columns_classified_non_guaranteed:rows=%s"
                % ",".join(str(item) for item in contradictory_rows)
            )
    return invalid_fields, inconsistent_fields, warnings


def _is_cumulative_premium_header(source_header: str) -> bool:
    """Return whether a mapped premium header denotes a cumulative series."""

    normalized = _normalize_semantic_key(source_header)
    compact = normalized.replace("_", "")
    return (
        normalized == "累计保费"
        or "累计" in normalized
        or compact in {"cumulativepremium", "cumulativepremiumamount"}
    )


def _validate_csv_critical_value(
    canonical_name: str,
    value: Any,
) -> Tuple[bool, Optional[str], str]:
    text = "" if value is None else unicodedata.normalize("NFKC", str(value)).strip()
    if not text:
        return False, None, "missing"
    if canonical_name == "currency":
        alias = CURRENCY_VALUE_ALIASES.get(text.upper()) or CURRENCY_VALUE_ALIASES.get(
            text
        )
        if alias:
            return True, alias, "ok"
        code = text.upper()
        if code in SUPPORTED_CURRENCY_CODES:
            return True, code, "ok"
        return False, None, "currency_not_supported_iso_code_or_known_alias"
    if canonical_name == "policy_year":
        if POSITIVE_INTEGER_PATTERN.fullmatch(text):
            year = int(text)
            if year <= MAX_AUTO_ACCEPT_POLICY_YEAR:
                return True, str(year), "ok"
            return False, None, "policy_year_exceeds_auto_accept_limit"
        return False, None, "policy_year_not_positive_integer"
    if canonical_name in {
        "premium_amount",
        "guaranteed_death_benefit",
        "guaranteed_cash_surrender_value",
    }:
        if not PLAIN_DECIMAL_PATTERN.fullmatch(text):
            return False, None, "not_nonnegative_plain_decimal"
        try:
            number = Decimal(text)
        except InvalidOperation:
            return False, None, "not_nonnegative_plain_decimal"
        if not number.is_finite() or number < 0:
            return False, None, "not_nonnegative_finite_decimal"
        if number > MAX_AUTO_ACCEPT_MONEY:
            return False, None, "money_exceeds_auto_accept_limit"
        return True, format(number, "f"), "ok"
    if canonical_name == "unit_scale":
        normalized = _normalize_semantic_key(text)
        alias = UNIT_SCALE_VALUE_ALIASES.get(normalized)
        if alias:
            return True, alias, "ok"
        return False, None, "unit_scale_not_recognized"
    if canonical_name == "guarantee_classification":
        normalized = _normalize_semantic_key(text)
        compact = normalized.replace("_", "")
        alias = GUARANTEE_CLASS_VALUE_ALIASES.get(normalized)
        if alias is None:
            alias = GUARANTEE_CLASS_VALUE_ALIASES.get(compact)
        if alias:
            return True, alias, "ok"
        return False, None, "guarantee_classification_not_recognized"
    return False, None, "unsupported_critical_field"


def _semantic_header_matches(normalized_header: str, normalized_alias: str) -> bool:
    if not normalized_header or not normalized_alias:
        return False
    return (
        normalized_header == normalized_alias
        or normalized_header.replace("_", "") == normalized_alias.replace("_", "")
        or normalized_header.startswith(normalized_alias + "_")
        or normalized_header.endswith("_" + normalized_alias)
    )


def _compact_error(error: BaseException, limit: int = 160) -> str:
    message = re.sub(r"\s+", " ", str(error)).strip()
    return message[:limit] or error.__class__.__name__


def _json_pointer_escape(value: str) -> str:
    return value.replace("~", "~0").replace("/", "~1")


__all__ = [
    "ConfidenceRouter",
    "DEFAULT_FIELD_PATTERNS",
    "Evidence",
    "ExtractedField",
    "ExtractionError",
    "ExtractionResult",
    "FileRouter",
    "PageExtraction",
    "RouteDecision",
    "TableExtraction",
    "UnsupportedFileTypeError",
    "extract_file",
    "parse_file",
    "sha256_file",
]
