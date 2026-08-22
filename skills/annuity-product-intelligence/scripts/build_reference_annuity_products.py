#!/usr/bin/env python3
"""Build three auditable, product-only annuity reference inputs."""

from __future__ import annotations

import hashlib
import json
from decimal import Decimal, ROUND_HALF_EVEN, getcontext
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, Optional


getcontext().prec = 40

SKILL_ROOT = Path(__file__).resolve().parents[1]
EXTRACT_ROOT = SKILL_ROOT / "assets" / "reference-products" / "source-extracts"
PRODUCT_ROOT = SKILL_ROOT / "assets" / "reference-products" / "products"
ANNUAL_PREMIUM = Decimal("200000")
TOTAL_PREMIUM = Decimal("1000000")

DAO_CASH = [
    "3639.84", "8107.37", "14147.09", "21612.06", "30284.36",
    "30083.44", "29876.85", "29664.48", "29446.22", "29222.00",
    "28991.73", "28755.33", "28512.74", "28263.90", "28008.72",
    "27747.17", "27479.18", "27204.73", "26923.82", "26636.47",
    "26341.48", "26038.37", "25726.92", "25406.91", "25078.10",
    "24740.25", "24393.11", "24036.42", "23669.92", "23293.34",
    "22906.41", "22508.83", "22100.33", "21680.59", "21249.30",
    "20806.16", "20350.83", "19882.97", "19402.26", "18908.32",
    "18400.80", "17879.32", "17343.50", "16792.95", "16227.25",
    "15646.00", "15048.77", "14435.11", "13804.57", "13156.70",
    "12491.01", "11807.01", "11104.20", "10382.07", "9640.08",
    "8877.68", "8094.31", "7289.41", "6462.37", "5612.58",
    "4739.43", "3842.26", "2920.42", "1973.24", "1000.00",
]

PIA_CASH = [
    "1605.39", "3575.91", "5821.96", "8362.97", "11094.49",
    "11506.87", "11934.55", "12378.09", "12838.10", "13315.23",
    "13810.15", "14323.58", "14856.26", "15408.99", "15982.57",
    "16577.86", "17195.73", "17837.12", "18503.00", "19194.41",
] + ["0.00"] * 45

ALLIANZ_CASH = [
    "349.03", "777.33", "1265.39", "1817.40", "2410.61", "2499.40",
    "2591.46", "2686.91", "2785.87", "2888.49", "2994.90", "3105.26",
    "3219.71", "3338.42", "3461.57", "3589.33", "3721.91", "3859.50",
    "4002.33", "4017.60", "4033.30", "4049.42", "4065.96", "4082.94",
    "4100.36", "4118.21", "4136.50", "4155.21", "4174.33", "4193.83",
    "4213.71", "4233.97", "4254.58", "4275.51", "4296.69", "4318.01",
    "4339.35", "4360.56", "4381.52", "4402.12", "4422.26", "4441.88",
    "4460.96", "4479.49", "4497.47", "4514.92", "4531.88", "4548.37",
    "4564.44", "4580.13", "4595.50", "4610.64", "4625.65", "4640.67",
    "4655.88", "4671.54", "4687.95", "4705.53", "4724.88", "4746.90",
    "4773.01", "4805.48", "4848.14", "4896.91", "4947.50", "5000.00",
]


def _decimal_text(value: Decimal) -> str:
    text = format(value.normalize(), "f")
    return text.rstrip("0").rstrip(".") if "." in text else text


def _sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _write_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _money(value: str, unit: str = "CNY", **extra: Any) -> Dict[str, Any]:
    return {"value": value, "unit": unit, **extra}


def _event(
    month: int,
    amount: Optional[Mapping[str, Any]],
    evidence_refs: Iterable[str],
    *,
    order: int = 90,
    status: str = "available",
    timing: str = "anniversary_end",
) -> Dict[str, Any]:
    result: Dict[str, Any] = {
        "policy_month": month,
        "event_order": order,
        "guarantee_basis": "guaranteed",
        "scenario_id": "guaranteed",
        "status": status,
        "timing": timing,
        "evidence_refs": list(evidence_refs),
    }
    if amount is not None:
        result["amount"] = dict(amount)
    return result


def _premium_events(evidence_ref: str) -> List[Dict[str, Any]]:
    return [
        {
            **_event(
                month,
                _money(_decimal_text(ANNUAL_PREMIUM)),
                [evidence_ref],
                order=10 if month == 0 else 50,
                timing="issue" if month == 0 else "anniversary_advance",
            ),
            "contingency": "contractual",
        }
        for month in (0, 12, 24, 36, 48)
    ]


def _field(name: str, evidence_ref: str) -> Dict[str, Any]:
    return {"op": "field", "name": name, "evidence_refs": [evidence_ref]}


def _floor_zero(node: Mapping[str, Any], evidence_ref: str) -> Dict[str, Any]:
    return {"op": "floor_zero", "arg": dict(node), "evidence_refs": [evidence_ref]}


def _subtract(left: Mapping[str, Any], right: Mapping[str, Any], evidence_ref: str) -> Dict[str, Any]:
    return {
        "op": "subtract",
        "left": dict(left),
        "right": dict(right),
        "evidence_refs": [evidence_ref],
    }


def _multiply_money(name: str, scalar: str, evidence_ref: str) -> Dict[str, Any]:
    return {
        "op": "multiply",
        "args": [
            _field(name, evidence_ref),
            {"op": "scalar_constant", "value": scalar, "evidence_refs": [evidence_ref]},
        ],
        "evidence_refs": [evidence_ref],
    }


def _maximum(nodes: Iterable[Mapping[str, Any]], evidence_ref: str) -> Dict[str, Any]:
    return {"op": "max", "args": [dict(node) for node in nodes], "evidence_refs": [evidence_ref]}


def _evidence(
    evidence_id: str,
    source_id: str,
    page: int,
    raw_text: str,
    *,
    unit_text: Optional[str] = None,
    transformation: Optional[str] = None,
) -> Dict[str, Any]:
    result: Dict[str, Any] = {
        "evidence_id": evidence_id,
        "source_id": source_id,
        "page": page,
        "raw_text": raw_text,
        "raw_text_sha256": _sha256_text(raw_text),
        "extractor": "pdftotext-layout-plus-visible-row-check",
        "extractor_version": "1.0.0",
        "confidence": "1",
        "status": "verified",
    }
    if unit_text:
        result["unit_text"] = unit_text
    if transformation:
        result["transformation"] = transformation
    return result


def _source(
    source_id: str,
    extract_name: str,
    extract_sha256: str,
    authority: str,
    version: str,
    original_sha256: str,
    page_range: str,
    original_url: Optional[str],
) -> Dict[str, Any]:
    result: Dict[str, Any] = {
        "source_id": source_id,
        "path": f"skill://assets/reference-products/source-extracts/{extract_name}",
        "sha256": extract_sha256,
        "document_type": "verified_extract_from_public_product_pdf",
        "version": version,
        "authority": authority,
        "original_sha256": original_sha256,
        "original_page_range": page_range,
        "extraction": {
            "method": "pdftotext -layout plus visible row/header and clause verification",
            "verified_on": "2026-08-22",
            "original_document_embedded": False,
        },
    }
    if original_url:
        result["original_url"] = original_url
    return result


def _cash_events_per_basic(
    values: List[str], evidence_ref: str, basic_amount: str
) -> List[Dict[str, Any]]:
    return [
        _event(
            year * 12,
            _money(
                value,
                "CNY_per_1000_basic_amount",
                basis_kind="basic_amount",
                basis_value=basic_amount,
                basis_unit="CNY",
                rounding="cent",
            ),
            [evidence_ref],
            order=35,
        )
        for year, value in enumerate(values, start=1)
    ]


def _cash_events_per_annual_premium(
    values: List[str], evidence_ref: str
) -> List[Dict[str, Any]]:
    return [
        _event(
            year * 12,
            _money(
                value,
                "CNY_per_1000_annual_premium",
                basis_kind="annual_premium",
                basis_value=_decimal_text(ANNUAL_PREMIUM),
                basis_unit="CNY",
                rounding="cent",
            ),
            [evidence_ref],
            order=35,
        )
        for year, value in enumerate(values, start=1)
    ]


def _base_product(
    product_id: str,
    name: str,
    insurer: str,
    version: str,
    effective_date: str,
    evidence_refs: List[str],
    sources: List[Dict[str, Any]],
    evidence: List[Dict[str, Any]],
    config: Dict[str, Any],
    survival_ages: List[int],
    death_ages: List[int],
) -> Dict[str, Any]:
    return {
        "schema_version": "1.0.0",
        "product": {
            "product_id": product_id,
            "name": name,
            "insurer": insurer,
            "currency": "CNY",
            "jurisdiction": "CN",
            "document_version": version,
            "effective_date": effective_date,
            "product_type": "annuity",
            "analysis_only": True,
            "evidence_refs": evidence_refs,
        },
        "sources": sources,
        "evidence": evidence,
        "configurations": [config],
        "analysis_assumptions": {
            "target_survival_ages": survival_ages,
            "target_death_ages": death_ages,
            "inflation_rates": ["0", "0.02", "0.03", "0.04"],
            "benchmark_selection": "nearest disclosed tenor without interpolation",
            "analysis_end_age": 105,
        },
    }


def _write_extract(filename: str, payload: Mapping[str, Any]) -> str:
    path = EXTRACT_ROOT / filename
    _write_json(path, payload)
    return _sha256_file(path)


def build_dao() -> Dict[str, Any]:
    basic = _decimal_text(
        (ANNUAL_PREMIUM * Decimal("1000") / Decimal("8352.5")).quantize(
            Decimal("0.01"), rounding=ROUND_HALF_EVEN
        )
    )
    version = "2026-06"
    extract_name = "dao-hsbc-jingcai-fengnian-2026.extract.json"
    documents = {
        "terms": {
            "url": "https://www.hsbcinsurance.com.cn/content/dam/hsbc/insh/docs/about-us/information-disclosure/product/tnc/jing-cai-feng-nian-2026-annuity-insurance-tnc.pdf",
            "sha256": "4c47a5b15f453ca0f5fcd460495068cc625f9db0d876477d7e570be475f3cc51",
            "pages": "1-11",
        },
        "rate": {
            "url": "https://www.hsbcinsurance.com.cn/content/dam/hsbc/insh/docs/about-us/information-disclosure/product/rates/jing-cai-feng-nian-2026-annuity-insurance-rates.pdf",
            "sha256": "e964ee7bfc0e2a5070136d037d736138ec92511d95630125aba1de5511730023",
            "pages": "1-4",
        },
        "cash": {
            "url": "https://www.hsbcinsurance.com.cn/content/dam/hsbc/insh/docs/about-us/information-disclosure/product/cash/jing-cai-feng-nian-2026-annuity-insurance-cash.pdf",
            "sha256": "c531200f0bd352ebc5b00630bf99235d05709ef12bd07613bea3e1c7b5f04432",
            "pages": "1-4; selected row on 2",
        },
    }
    extract = {
        "product_id": "dao-hsbc-jingcai-fengnian-2026",
        "configuration": "female age 40; annual advance premium 200000 for 5 years",
        "premium_rate": {"direction": "premium_per_1000_basic_amount", "value": "8352.5", "page": 1},
        "cash_value_basis": "CNY per 1000 basic amount",
        "cash_values": [{"policy_year": index, "value": value} for index, value in enumerate(DAO_CASH, 1)],
        "contract_facts": {
            "annuity": "basic amount annually from policy year 5 through policy year 64",
            "maturity": "basic amount at policy month 780",
            "death": "max(cumulative premium - cumulative allocated annuity, base cash value)",
            "loan": "80% of cash value net of debt; each loan no longer than 6 months; debt deducted from benefits; lapse at debt equals cash value",
        },
        "original_documents": documents,
    }
    extract_hash = _write_extract(extract_name, extract)
    sources = [
        _source("dao-terms", extract_name, extract_hash, "contract", version, documents["terms"]["sha256"], documents["terms"]["pages"], documents["terms"]["url"]),
        _source("dao-rate", extract_name, extract_hash, "rate_table", version, documents["rate"]["sha256"], documents["rate"]["pages"], documents["rate"]["url"]),
        _source("dao-cash", extract_name, extract_hash, "cash_value_table", version, documents["cash"]["sha256"], documents["cash"]["pages"], documents["cash"]["url"]),
    ]
    cash_row = "female age 40, 5-pay, values by policy year: " + ",".join(DAO_CASH)
    evidence = [
        _evidence("dao-product", "dao-terms", 1, "汇丰精彩丰年2026年金保险（分红型）"),
        _evidence("dao-dimensions", "dao-rate", 1, "female age 40; 5-year annual premium; contract to age 105"),
        _evidence("dao-rate-row", "dao-rate", 1, "female age 40, 5-pay: premium 8352.5 per 1000 basic amount", unit_text="CNY per 1000 basic amount", transformation=f"200000*1000/8352.5={basic}"),
        _evidence("dao-cash-row", "dao-cash", 2, cash_row, unit_text="CNY per 1000 basic amount", transformation=f"factor*{basic}/1000, rounded to cents"),
        _evidence("dao-annuity", "dao-terms", 2, "For lump sum, 3-pay or 5-pay, first annuity allocation date is the fifth policy anniversary; annual annuity equals basic amount until maturity."),
        _evidence("dao-maturity", "dao-terms", 2, "At the maturity date, maturity benefit equals basic amount; contract terminates."),
        _evidence("dao-death", "dao-terms", 2, "Death benefit is the greater of cumulative paid premium less allocated annuity and cash value corresponding to basic amount."),
        _evidence("dao-loan", "dao-terms", 6, "Policy loan principal and interest may not exceed 80% of cash value net of debts; each term at most 6 months; unpaid debt is deducted from benefits and contract lapses when debt reaches cash value."),
    ]
    cash_values = _cash_events_per_basic(DAO_CASH[:-1], "dao-cash-row", basic)
    cash_values.extend(
        [
            _event(780, _money(DAO_CASH[-1], "CNY_per_1000_basic_amount", basis_kind="basic_amount", basis_value=basic, basis_unit="CNY", rounding="cent"), ["dao-cash-row"], order=35, timing="contract_end_before_maturity"),
            _event(780, None, ["dao-maturity"], order=90, status="not_applicable", timing="contract_end_after_maturity"),
        ]
    )
    config = {
        "configuration_id": "dao-f40-5pay-total-premium-1m",
        "dimensions": {
            "published_issue_age": 40,
            "rate_class": "female",
            "premium_term_months": 60,
            "annuity_start_age": 45,
            "annuity_frequency_per_year": 1,
            "guarantee_option": "survival_contingent_no_period_certain",
            "premium_mode": "annual_advance",
            "product_option_code": "DAO",
            "proportionality_verified": True,
        },
        "dimension_evidence_refs": ["dao-dimensions", "dao-rate-row"],
        "basic_amount": _money(basic),
        "premium_events": _premium_events("dao-rate-row"),
        "annuity_rules": [{
            "rule_id": "dao-guaranteed-annuity",
            "first_payment_month": 60,
            "frequency_months": 12,
            "payment_timing": "arrears",
            "amount": _money(basic),
            "annual_growth_rate": "0",
            "growth_interval_months": 12,
            "lifetime": False,
            "last_payment_month": 768,
            "guaranteed_period_months": 0,
            "guarantee_basis": "guaranteed",
            "scenario_id": "guaranteed",
            "rounding": "cent",
            "contingency": "survival",
            "evidence_refs": ["dao-annuity", "dao-rate-row"],
        }],
        "cash_values": cash_values,
        "maturity_events": [_event(780, _money(basic), ["dao-maturity"], order=40, timing="contract_maturity")],
        "death_benefit": {
            "guarantee_basis": "guaranteed",
            "scenario_id": "guaranteed",
            "boundary_order": "after_annuity",
            "lookup": "at_or_before",
            "cash_value_timing": "respect_event_order",
            "rule": _maximum([
                _floor_zero(_subtract(_field("cumulative_premium", "dao-death"), _field("cumulative_annuity", "dao-death"), "dao-death"), "dao-death"),
                _field("cash_value", "dao-death"),
            ], "dao-death"),
            "evidence_refs": ["dao-death", "dao-cash-row"],
        },
        "loan_terms": {
            "available": True,
            "limit_ratio": "0.8",
            "eligible_value": "contract_cash_value_net_of_other_debts",
            "availability_start_month": 0,
            "maximum_term_months": 6,
            "interest_rate_status": "missing",
            "interest_rate_basis": "rate stated in service completion notice; then-current published company loan rate",
            "interest_rate_reset_frequency_months": 6,
            "repayment_terms": "repay principal and interest at any time, or all interest only; overdue balance capitalizes",
            "benefit_deduction": True,
            "lapse_trigger": "loan principal, interest and other debts reach contract cash value",
            "annuity_effect": "loan debt is deducted from insurance benefits; loan proceeds are not income",
            "evidence_refs": ["dao-loan"],
        },
        "notes": "Guaranteed base contract only; non-guaranteed participating additions are excluded. The year-65 table value is retained before maturity and becomes not applicable after maturity.",
    }
    return _base_product("dao-hsbc-jingcai-fengnian-2026", "汇丰精彩丰年2026年金保险（分红型）", "汇丰人寿保险有限公司", version, "2026-06-01", ["dao-product"], sources, evidence, config, [45, 50, 55, 60, 65, 70, 75, 80, 85, 90, 95, 100, 105], [41, 42, 44, 45, 46, 50, 70, 75, 80])


def build_pia() -> Dict[str, Any]:
    basic = _decimal_text(
        (ANNUAL_PREMIUM * Decimal("1000") / Decimal("4229.68")).quantize(
            Decimal("0.01"), rounding=ROUND_HALF_EVEN
        )
    )
    version = "2026-06"
    extract_name = "pia-hsbc-jingcai-yannian-2026.extract.json"
    documents = {
        "terms": {"url": "https://www.hsbcinsurance.com.cn/content/dam/hsbc/insh/docs/about-us/information-disclosure/basic-information/terms/pia-enjoy-golden-life-retirement-annuity-insurance-terms.pdf", "sha256": "3c31b4a4d30d9f85dba31d38b3ebef1e43bf0d94b9c62fe82f4cdcba5ec9d7ed", "pages": "1-12"},
        "rate": {"url": "https://www.hsbcinsurance.com.cn/content/dam/hsbc/insh/docs/about-us/information-disclosure/basic-information/rates/pia-retirement-annuity-insurance-rates.pdf", "sha256": "4d61e93fff22912ffbc860d34f2ccbdb98e22502b837c64a7ae81085b049076c", "pages": "1-5; selected row on 2"},
        "cash": {"url": "https://www.hsbcinsurance.com.cn/content/dam/hsbc/insh/docs/about-us/information-disclosure/basic-information/cashvalue/pia-retirement-annuity-insurance-cashvalue.pdf", "sha256": "c5c5f5b6663505b6cc2c767329075d6e6d7d8a1b417eb072746733d8c619432a", "pages": "1-6; selected row on 3"},
    }
    extract = {
        "product_id": "pia-hsbc-jingcai-yannian-2026",
        "configuration": "female age 40; annual advance premium 200000 for 5 years; income starts age 60",
        "premium_rate": {"direction": "premium_per_1000_basic_amount", "value": "4229.68", "page": 2},
        "cash_value_basis": "CNY per 1000 basic amount; year 20 source value is immediately before first annuity and contract value is zero from first annuity",
        "cash_values": [{"policy_year": index, "value": value} for index, value in enumerate(PIA_CASH, 1)],
        "contract_facts": {
            "annuity": "basic amount annually from age 60 to before maturity; 20-year certain",
            "maturity": "basic amount at age-105 maturity",
            "death": "pre-income max(paid premium, cash value); during guarantee floor(paid premium-20*basic,0) plus remaining guaranteed annuity; later floor(paid premium-cumulative annuity,0)",
            "loan": "80% of cash value net of debt, 6-month maximum; unavailable from first annuity date when cash value becomes zero",
        },
        "original_documents": documents,
    }
    extract_hash = _write_extract(extract_name, extract)
    sources = [
        _source("pia-terms", extract_name, extract_hash, "contract", version, documents["terms"]["sha256"], documents["terms"]["pages"], documents["terms"]["url"]),
        _source("pia-rate", extract_name, extract_hash, "rate_table", version, documents["rate"]["sha256"], documents["rate"]["pages"], documents["rate"]["url"]),
        _source("pia-cash", extract_name, extract_hash, "cash_value_table", version, documents["cash"]["sha256"], documents["cash"]["pages"], documents["cash"]["url"]),
    ]
    cash_row = "female age 40, age-60 start, 5-pay, values by policy year: " + ",".join(PIA_CASH)
    evidence = [
        _evidence("pia-product", "pia-terms", 1, "汇丰精彩延年2026养老年金保险（分红型）"),
        _evidence("pia-dimensions", "pia-rate", 2, "female age 40; age-60 start; 5-year annual premium; contract to age 105"),
        _evidence("pia-rate-row", "pia-rate", 2, "female age 40, age-60 start, 5-pay: premium 4229.68 per 1000 basic amount", unit_text="CNY per 1000 basic amount", transformation=f"200000*1000/4229.68={basic}"),
        _evidence("pia-cash-row", "pia-cash", 3, cash_row, unit_text="CNY per 1000 basic amount", transformation=f"factor*{basic}/1000, rounded to cents"),
        _evidence("pia-annuity", "pia-terms", 2, "Annual retirement annuity equals basic amount from first payment date; guaranteed payment period is 20 years; remaining guaranteed annuity is paid to the guarantee beneficiary after death."),
        _evidence("pia-cash-transition", "pia-terms", 2, "From the first retirement annuity date, contract cash value becomes zero and policy loan service is no longer available."),
        _evidence("pia-maturity", "pia-terms", 3, "At the age-105 maturity date, maturity benefit equals basic amount; contract terminates."),
        _evidence("pia-death", "pia-terms", 3, "Death benefit has separate pre-income, 20-year guarantee-period, and post-guarantee formulas; remaining guaranteed annuity is separately payable during the guarantee period."),
        _evidence("pia-loan", "pia-terms", 7, "Policy loan principal and interest may not exceed 80% of cash value net of debts; each term at most 6 months; debt is deducted from benefits and contract lapses when debt reaches cash value."),
    ]
    cash_values = _cash_events_per_basic(PIA_CASH[:19], "pia-cash-row", basic)
    cash_values.append(_event(240, _money(PIA_CASH[19], "CNY_per_1000_basic_amount", basis_kind="basic_amount", basis_value=basic, basis_unit="CNY", rounding="cent"), ["pia-cash-row"], order=20, timing="immediately_before_first_annuity"))
    cash_values.extend(
        _event(year * 12, _money("0"), ["pia-cash-transition"], order=36, timing="anniversary_end_after_first_annuity")
        for year in range(20, 66)
    )
    twenty_basic = _multiply_money("basic_amount", "20", "pia-death")
    guarantee_period_death = _floor_zero(_subtract(_field("cumulative_premium", "pia-death"), twenty_basic, "pia-death"), "pia-death")
    later_death = _floor_zero(_subtract(_field("cumulative_premium", "pia-death"), _field("cumulative_annuity", "pia-death"), "pia-death"), "pia-death")
    death_rule = {
        "op": "if_period",
        "policy_month_min": 0,
        "policy_month_max": 239,
        "then": _maximum([_field("cumulative_premium", "pia-death"), _field("cash_value", "pia-death")], "pia-death"),
        "else": {
            "op": "if_period",
            "policy_month_min": 240,
            "policy_month_max": 479,
            "then": guarantee_period_death,
            "else": later_death,
            "evidence_refs": ["pia-death"],
        },
        "evidence_refs": ["pia-death"],
    }
    config = {
        "configuration_id": "pia-f40-5pay-start60-total-premium-1m",
        "dimensions": {
            "published_issue_age": 40,
            "rate_class": "female",
            "premium_term_months": 60,
            "annuity_start_age": 60,
            "annuity_frequency_per_year": 1,
            "guarantee_option": "20_year_certain_to_age_105",
            "premium_mode": "annual_advance",
            "product_option_code": "PIA",
            "proportionality_verified": True,
        },
        "dimension_evidence_refs": ["pia-dimensions", "pia-rate-row"],
        "basic_amount": _money(basic),
        "premium_events": _premium_events("pia-rate-row"),
        "annuity_rules": [{
            "rule_id": "pia-guaranteed-retirement-annuity",
            "first_payment_month": 240,
            "frequency_months": 12,
            "payment_timing": "arrears",
            "amount": _money(basic),
            "annual_growth_rate": "0",
            "growth_interval_months": 12,
            "lifetime": False,
            "last_payment_month": 768,
            "guaranteed_period_months": 240,
            "guarantee_basis": "guaranteed",
            "scenario_id": "guaranteed",
            "rounding": "cent",
            "contingency": "survival_or_guarantee_period",
            "evidence_refs": ["pia-annuity", "pia-rate-row"],
        }],
        "cash_values": cash_values,
        "maturity_events": [_event(780, _money(basic), ["pia-maturity"], order=40, timing="contract_maturity")],
        "death_benefit": {
            "guarantee_basis": "guaranteed",
            "scenario_id": "guaranteed",
            "boundary_order": "after_annuity",
            "lookup": "at_or_before",
            "cash_value_timing": "respect_event_order",
            "rule": death_rule,
            "beneficiary_continuation": {"mode": "remaining_guaranteed_annuity", "through_policy_month": 468, "evidence_refs": ["pia-annuity", "pia-death"]},
            "evidence_refs": ["pia-death", "pia-cash-row", "pia-cash-transition"],
        },
        "loan_terms": {
            "available": True,
            "limit_ratio": "0.8",
            "eligible_value": "contract_cash_value_net_of_other_debts",
            "availability_start_month": 0,
            "availability_end_month": 239,
            "maximum_term_months": 6,
            "interest_rate_status": "missing",
            "interest_rate_basis": "rate stated in service completion notice; then-current published company loan rate",
            "interest_rate_reset_frequency_months": 6,
            "repayment_terms": "repay principal and interest at any time, or all interest only; overdue balance capitalizes",
            "benefit_deduction": True,
            "lapse_trigger": "loan principal, interest and other debts reach contract cash value",
            "annuity_effect": "cash value becomes zero and policy loan service ends from first retirement annuity date",
            "evidence_refs": ["pia-loan", "pia-cash-transition"],
        },
        "notes": "Guaranteed base contract only; non-guaranteed participating additions are excluded. The year-20 source value is retained immediately before first annuity and the post-annuity contract state is zero.",
    }
    return _base_product("pia-hsbc-jingcai-yannian-2026", "汇丰精彩延年2026养老年金保险（分红型）", "汇丰人寿保险有限公司", version, "2026-06-01", ["pia-product"], sources, evidence, config, [60, 65, 70, 75, 80, 85, 90, 95, 100, 105], [41, 42, 45, 59, 60, 61, 65, 70, 75, 80])


def build_allianz() -> Dict[str, Any]:
    basic = _decimal_text(ANNUAL_PREMIUM * Decimal("133.04") / Decimal("1000"))
    version = "terms-2026-06-25+tables-2025-08-18"
    extract_name = "allianz-anxiang-fengying-c.extract.json"
    documents = {
        "terms": {"url": "https://www.allianz.com.cn/allianz/001d14c12383421f91106c6ef70ae479.pdf", "sha256": "0b9803793f1d4277448c5576f9b1076e9ad6f19c3ce849e0caa5913faa39ecd6", "pages": "1-10"},
        "rate": {"url": "https://www.allianz.com.cn/allianz/d9455eab50564467a2e4f632a9c93917.pdf", "sha256": "949be054aae2bf10c046ff608fd8f1e54fe6b79864867982b01c7bbb8b74ca66", "pages": "1"},
        "cash": {"url": None, "sha256": "2f4b460bc1b48773f2015f5e4e59eeca2662ceba8890a94e199ecfc335bb754c", "pages": "1-2100; selected row on 514-515"},
    }
    extract = {
        "product_id": "allianz-anxiang-fengying-c",
        "configuration": "female age 40; annual advance premium 200000 for 5 years; income starts age 60",
        "premium_rate": {"direction": "basic_amount_per_1000_annual_premium", "value": "133.04", "page": 1},
        "cash_value_basis": "CNY per 1000 annual premium",
        "cash_values": [{"policy_year": index, "value": value} for index, value in enumerate(ALLIANZ_CASH, 1)],
        "contract_facts": {
            "annuity": "basic amount annually from age 60 while insured survives and contract remains effective",
            "maturity": "none; lifetime contract",
            "death": "max(cumulative scheduled premium, cash value)",
            "loan": "after cooling-off, 80% of cash value net of debt; each loan no longer than 6 months; agreement rate; debt deducted; lapse at debt equals cash value",
        },
        "original_documents": documents,
    }
    extract_hash = _write_extract(extract_name, extract)
    sources = [
        _source("allianz-terms", extract_name, extract_hash, "contract", version, documents["terms"]["sha256"], documents["terms"]["pages"], documents["terms"]["url"]),
        _source("allianz-rate", extract_name, extract_hash, "rate_table", version, documents["rate"]["sha256"], documents["rate"]["pages"], documents["rate"]["url"]),
        _source("allianz-cash", extract_name, extract_hash, "cash_value_table", version, documents["cash"]["sha256"], documents["cash"]["pages"], documents["cash"]["url"]),
    ]
    cash_row = "female age 40, age-60 start, 5-pay, values by policy year: " + ",".join(ALLIANZ_CASH)
    evidence = [
        _evidence("allianz-product", "allianz-terms", 1, "安联安享丰赢C养老年金保险（分红型）"),
        _evidence("allianz-dimensions", "allianz-rate", 1, "female age 40; age-60 start; 5-year annual premium; lifetime contract"),
        _evidence("allianz-rate-row", "allianz-rate", 1, "female age 40, age-60 start, 5-pay: basic amount 133.04 per 1000 annual premium", unit_text="basic amount per CNY 1000 annual premium", transformation=f"200000*133.04/1000={basic}"),
        _evidence("allianz-cash-row", "allianz-cash", 514, cash_row, unit_text="CNY per 1000 annual premium", transformation="factor*200000/1000, rounded to cents; row continues on page 515"),
        _evidence("allianz-annuity", "allianz-terms", 2, "Retirement annuity equals basic amount on each retirement annuity payment date while insured survives and contract remains effective."),
        _evidence("allianz-death", "allianz-terms", 2, "Death benefit is the greater of cumulative scheduled premium and cash value."),
        _evidence("allianz-loan", "allianz-terms", 4, "After cooling-off, policy loan may not exceed 80% of cash value net of debts; each term at most 6 months; rate is agreed in the loan agreement; debt is deducted and contract lapses when debt reaches cash value."),
    ]
    config = {
        "configuration_id": "allianz-f40-5pay-start60-total-premium-1m",
        "dimensions": {
            "published_issue_age": 40,
            "rate_class": "female",
            "premium_term_months": 60,
            "annuity_start_age": 60,
            "annuity_frequency_per_year": 1,
            "guarantee_option": "lifetime_survival_contingent_no_period_certain",
            "premium_mode": "annual_advance",
            "product_option_code": "ALLIANZ-AXFYC",
            "proportionality_verified": True,
        },
        "dimension_evidence_refs": ["allianz-dimensions", "allianz-rate-row"],
        "basic_amount": _money(basic),
        "premium_events": _premium_events("allianz-rate-row"),
        "annuity_rules": [{
            "rule_id": "allianz-guaranteed-lifetime-retirement-annuity",
            "first_payment_month": 240,
            "frequency_months": 12,
            "payment_timing": "arrears",
            "amount": _money(basic),
            "annual_growth_rate": "0",
            "growth_interval_months": 12,
            "lifetime": True,
            "contract_end_age": 106,
            "guaranteed_period_months": 0,
            "guarantee_basis": "guaranteed",
            "scenario_id": "guaranteed",
            "rounding": "cent",
            "contingency": "survival",
            "evidence_refs": ["allianz-annuity", "allianz-rate-row"],
        }],
        "cash_values": _cash_events_per_annual_premium(ALLIANZ_CASH, "allianz-cash-row"),
        "maturity_events": [],
        "death_benefit": {
            "guarantee_basis": "guaranteed",
            "scenario_id": "guaranteed",
            "boundary_order": "after_annuity",
            "lookup": "at_or_before",
            "cash_value_timing": "policy_month_state",
            "rule": _maximum([_field("cumulative_premium", "allianz-death"), _field("cash_value", "allianz-death")], "allianz-death"),
            "evidence_refs": ["allianz-death", "allianz-cash-row"],
        },
        "loan_terms": {
            "available": True,
            "limit_ratio": "0.8",
            "eligible_value": "contract_and_rider_cash_value_net_of_other_debts",
            "availability_start_month": 1,
            "maximum_term_months": 6,
            "interest_rate_status": "missing",
            "interest_rate_basis": "rate agreed in loan agreement based on market rates, funding cost, investment return and liquidity",
            "repayment_terms": "principal and interest due at term; overdue balance capitalizes; partial repayment first pays accrued interest",
            "benefit_deduction": True,
            "lapse_trigger": "loan principal, interest and other debts reach contract and rider cash value",
            "annuity_effect": "no stated cessation at annuity start; debt remains deductible from insurance benefits",
            "evidence_refs": ["allianz-loan"],
        },
        "notes": "Guaranteed base contract only; non-guaranteed participating dividends are excluded. Contract is lifetime; age 106 is only the deterministic expansion boundary supported by the complete published cash-value row.",
    }
    return _base_product("allianz-anxiang-fengying-c", "安联安享丰赢C养老年金保险（分红型）", "安联人寿保险有限公司", version, "2026-06-25", ["allianz-product"], sources, evidence, config, [60, 65, 70, 75, 80, 85, 90, 95, 100, 105], [41, 42, 45, 59, 60, 61, 65, 70, 75, 80])


def main() -> None:
    products = {
        "dao-hsbc-jingcai-fengnian-2026.json": build_dao(),
        "pia-hsbc-jingcai-yannian-2026.json": build_pia(),
        "allianz-anxiang-fengying-c.json": build_allianz(),
    }
    for filename, payload in products.items():
        _write_json(PRODUCT_ROOT / filename, payload)
    print(f"wrote {len(products)} product inputs to {PRODUCT_ROOT}")


if __name__ == "__main__":
    main()
