#!/usr/bin/env python3
"""Build auditable WWA/WWB/Allianz reference cases from official PDFs.

The generated canonical files contain normalized annual values only. Source PDFs
remain outside the repository; their SHA-256 hashes and official URLs are kept in
every generated artifact.
"""

from __future__ import annotations

import argparse
from decimal import Decimal, ROUND_HALF_EVEN
import hashlib
import json
from pathlib import Path
import re
import subprocess
import xml.etree.ElementTree as ET


ISSUE_YEAR = 2026
ANNUAL_PREMIUM = Decimal("100000.00")
ENTRY_AGE = 30
HSBC_DISCLOSED_YEARS = 75
ALLIANZ_DISCLOSED_YEARS = 76
MONEY_QUANTUM = Decimal("0.01")
BENCHMARK_ID = "LLPI-STD-10PAY-100K-v1"
BENCHMARK_TEXT = (
    "LLPI standard product experiment: ten annual CNY 100,000 payments at "
    "times 0 through 9; benefits observed at each policy-year end; 2% base "
    "inflation assumption; no customer suitability inference."
)

SOURCE_FILES = {
    "wwa_terms": "wwa-terms.pdf",
    "wwa_rates": "wwa-rates.pdf",
    "wwa_cash": "wwa-cashvalue.pdf",
    "wwb_terms": "wwb-terms.pdf",
    "wwb_rates": "wwb-rates.pdf",
    "wwb_cash": "wwb-cashvalue.pdf",
    "wwb_illustration": "wwb-description.pdf",
    "allianz_terms": "allianz-terms.pdf",
    "allianz_rates": "allianz-rates.pdf",
    "allianz_cash": "allianz-cashvalue.pdf",
}

SOURCE_META = {
    "wwa_terms": (
        "汇丰福佑逸生2025终身寿险条款",
        "contract",
        "2025-07 WWA",
        "https://www.hsbcinsurance.com.cn/content/dam/hsbc/insh/docs/about-us/"
        "information-disclosure/basic-information/terms/"
        "wwa-fortune-life-2025-whole-life-insurance-terms.pdf",
    ),
    "wwa_rates": (
        "汇丰福佑逸生2025终身寿险费率表",
        "rate_table",
        "2025",
        "https://www.hsbcinsurance.com.cn/content/dam/hsbc/insh/docs/about-us/"
        "information-disclosure/basic-information/rates/"
        "wwa-fortune-life-2025-whole-life-insurance-rates.pdf",
    ),
    "wwa_cash": (
        "汇丰福佑逸生2025终身寿险现金价值表",
        "cash_value_table",
        "2025",
        "https://www.hsbcinsurance.com.cn/content/dam/hsbc/insh/docs/about-us/"
        "information-disclosure/basic-information/cashvalue/"
        "wwa-fortune-life-2025-whole-life-insurance-cashvalue.pdf",
    ),
    "wwb_terms": (
        "汇丰汇传卓悦2025终身寿险（分红型）条款",
        "contract",
        "2026-07 WWB",
        "https://www.hsbcinsurance.com.cn/content/dam/hsbc/insh/docs/about-us/"
        "information-disclosure/basic-information/terms/"
        "wwb-huichuan-bonjour-2025-whole-life-insurance-terms.pdf",
    ),
    "wwb_rates": (
        "汇丰汇传卓悦2025终身寿险（分红型）费率表",
        "rate_table",
        "2025",
        "https://www.hsbcinsurance.com.cn/content/dam/hsbc/insh/docs/about-us/"
        "information-disclosure/basic-information/rates/"
        "wwb-huichuan-bonjour-2025-whole-life-insurance-rates.pdf",
    ),
    "wwb_cash": (
        "汇丰汇传卓悦2025终身寿险（分红型）现金价值表",
        "cash_value_table",
        "2025",
        "https://www.hsbcinsurance.com.cn/content/dam/hsbc/insh/docs/about-us/"
        "information-disclosure/basic-information/cashvalue/"
        "wwb-huichuan-bonjour-2025-whole-life-insurance-cashvalue.pdf",
    ),
    "wwb_illustration": (
        "汇丰汇传卓悦2025终身寿险（分红型）产品说明书及利益测算书",
        "illustration",
        "2026",
        "https://www.hsbcinsurance.com.cn/content/dam/hsbc/insh/docs/about-us/"
        "information-disclosure/basic-information/description/"
        "wwb-huichuan-bonjour-2025-whole-life-insurance-description.pdf",
    ),
    "allianz_terms": (
        "安联盛世臻传C（5.0）终身寿险（分红型）条款",
        "contract",
        "5.0",
        "https://www.allianz.com.cn/allianz/"
        "安联盛世臻传C（5.0）终身寿险（分红型）条款.pdf",
    ),
    "allianz_rates": (
        "安联盛世臻传C（5.0）终身寿险（分红型）费率表",
        "rate_table",
        "5.0",
        "https://www.allianz.com.cn/allianz/"
        "安联盛世臻传C（5.0）终身寿险（分红型）费率表.pdf",
    ),
    "allianz_cash": (
        "安联盛世臻传C（5.0）终身寿险（分红型）现金价值表",
        "cash_value_table",
        "5.0",
        "https://www.allianz.com.cn/allianz/"
        "安联盛世臻传C（5.0）终身寿险（分红型）现金价值表.pdf",
    ),
}

WWA_RATE = Decimal("51.99")
WWB_RATES = {1: Decimal("525.44"), 2: Decimal("381.61")}
ALLIANZ_RATES = {
    "A": Decimal("50.47"),
    "B": Decimal("50.17"),
    "C": Decimal("48.53"),
    "D": Decimal("47.60"),
    "E": Decimal("47.00"),
}
ALLIANZ_START_PAGES = {"A": 215, "B": 1089, "C": 1963, "D": 2836, "E": 3710}


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def sha256_file(path: Path) -> str:
    return sha256_bytes(path.read_bytes())


def number(value: str) -> Decimal:
    return Decimal(value.replace(",", "").strip())


def money(value: Decimal) -> str:
    return format(value.quantize(MONEY_QUANTUM, rounding=ROUND_HALF_EVEN), "f")


def run_text(args: list[str]) -> str:
    completed = subprocess.run(args, check=True, capture_output=True, text=True)
    return completed.stdout


def pdf_text(path: Path, first_page: int | None = None, last_page: int | None = None) -> str:
    args = ["pdftotext"]
    if first_page is not None:
        args.extend(["-f", str(first_page)])
    if last_page is not None:
        args.extend(["-l", str(last_page)])
    args.extend(["-layout", str(path), "-"])
    return run_text(args)


def xml_row(
    path: Path,
    page: int,
    required_tokens: tuple[str, ...],
    expected_values: int = HSBC_DISCLOSED_YEARS,
) -> list[Decimal]:
    xml = run_text(
        [
            "pdftohtml",
            "-xml",
            "-hidden",
            "-f",
            str(page),
            "-l",
            str(page),
            "-stdout",
            str(path),
        ]
    )
    root = ET.fromstring(xml)
    page_node = root.find("page")
    if page_node is None:
        raise ValueError(f"No XML page extracted from {path.name} page {page}")
    cells = [
        (
            int(item.attrib["top"]),
            int(item.attrib["left"]),
            "".join(item.itertext()).strip(),
        )
        for item in page_node.findall("text")
    ]
    for top, left, text in cells:
        if text != str(ENTRY_AGE) or left >= 200:
            continue
        row = sorted(
            (cell_left, cell_text)
            for cell_top, cell_left, cell_text in cells
            if abs(cell_top - top) <= 2 and cell_text
        )
        prefix = " ".join(value for cell_left, value in row if cell_left <= left)
        if not all(token in prefix for token in required_tokens):
            continue
        values = []
        for cell_left, value in row:
            if cell_left <= left or not re.fullmatch(r"[0-9][0-9,.]*", value):
                continue
            values.append(number(value))
        if len(values) == expected_values:
            return values
    raise ValueError(
        f"Could not locate {required_tokens!r} with {expected_values} values "
        f"in {path.name} page {page}"
    )


def allianz_row(path: Path, grade: str) -> list[Decimal]:
    start = ALLIANZ_START_PAGES[grade]
    # Rows may straddle either two or three physical PDF pages.
    text = pdf_text(path, start, start + 2)
    pattern = re.compile(
        rf"^\s*{ENTRY_AGE}\s+男\s+{grade}\s+10\s+(\d+)\s+([0-9,.]+)\s*$"
    )
    values: dict[int, Decimal] = {}
    for line in text.splitlines():
        match = pattern.match(line)
        if match:
            values[int(match.group(1))] = number(match.group(2))
    if sorted(values) != list(range(1, ALLIANZ_DISCLOSED_YEARS + 1)):
        raise ValueError(f"Incomplete Allianz grade {grade} cash-value row")
    return [values[year] for year in range(1, ALLIANZ_DISCLOSED_YEARS + 1)]


def verify_rates(paths: dict[str, Path]) -> None:
    checks = {
        "wwa_rates": [WWA_RATE],
        "wwb_rates": list(WWB_RATES.values()),
        "allianz_rates": list(ALLIANZ_RATES.values()),
    }
    for source_key, expected in checks.items():
        text = pdf_text(paths[source_key])
        missing = [value for value in expected if format(value, "f") not in text]
        if missing:
            raise ValueError(f"Rate row verification failed for {source_key}: {missing}")


def parse_illustration_rows(section: str, layout: str) -> list[dict[str, Decimal | int]]:
    lines = section.splitlines()
    rows: list[dict[str, Decimal | int]] = []
    expected_year = 1
    index = 0
    while index < len(lines) and expected_year <= 65:
        tokens = re.findall(r"(?<!\d)[0-9][0-9,]*(?!\d)", lines[index])
        parsed = [number(token) for token in tokens]
        if not parsed or parsed[0] != expected_year:
            index += 1
            continue
        if layout == "wrapped" and len(parsed) >= 6:
            base = parsed[:6]
            continuation: list[Decimal] = []
            lookahead = index + 1
            while lookahead < min(index + 5, len(lines)):
                candidate = [
                    number(token)
                    for token in re.findall(
                        r"(?<!\d)[0-9][0-9,]*(?!\d)", lines[lookahead]
                    )
                ]
                if len(candidate) == 2:
                    continuation = candidate
                    break
                lookahead += 1
            if len(continuation) != 2:
                raise ValueError(f"Missing wrapped scenario row for year {expected_year}")
            values = [*base, *continuation]
            index = lookahead + 1
        elif layout == "inline" and len(parsed) >= 8:
            values = parsed[:8]
            index += 1
        else:
            index += 1
            continue
        rows.append(
            {
                "policy_year": int(values[0]),
                "annual_premium": values[2],
                "cumulative_premium": values[3],
                "guaranteed_death": values[4],
                "illustrated_death": values[6] if layout == "wrapped" else values[5],
                "guaranteed_cash": values[5] if layout == "wrapped" else values[6],
                "illustrated_cash": values[7],
            }
        )
        expected_year += 1
    if len(rows) != 65:
        raise ValueError(f"Expected 65 illustration rows, found {len(rows)}")
    return rows


def wwb_illustrations(path: Path) -> dict[int, list[dict[str, Decimal | int]]]:
    text = pdf_text(path)
    sections = text.split("综合利益演示表")
    if len(sections) < 3:
        raise ValueError("WWB illustration does not contain both benefit tables")
    parsed: dict[int, list[dict[str, Decimal | int]]] = {}
    expected_premium = {1: Decimal("900360"), 2: Decimal("611920")}
    for plan, layout in ((1, "wrapped"), (2, "inline")):
        for section in sections[1:]:
            try:
                candidate = parse_illustration_rows(section, layout)
            except ValueError:
                continue
            if Decimal(str(candidate[0]["annual_premium"])) != expected_premium[plan]:
                continue
            parsed[plan] = candidate
            break
        if plan not in parsed:
            raise ValueError(f"Could not locate WWB plan {plan} illustration table")
    return parsed


def source(paths: dict[str, Path], key: str) -> dict:
    title, kind, version, uri = SOURCE_META[key]
    return {
        "source_id": f"src-{key.replace('_', '-')}",
        "title": title,
        "kind": kind,
        "version": version,
        "uri": uri,
        "document_sha256": sha256_file(paths[key]),
    }


def evidence(source_item: dict, evidence_id: str, page: int, raw_text: str, **locator: object) -> dict:
    return {
        "evidence_id": evidence_id,
        "source_id": source_item["source_id"],
        "document_sha256": source_item["document_sha256"],
        "page": page,
        "locator": locator,
        "raw_text": raw_text,
        "content_sha256": sha256_bytes(raw_text.encode("utf-8")),
        "extractor": "official_pdf_reference_importer",
        "extractor_version": "1.0.0",
        "confidence": 0.99,
        "reason_codes": ["official_table", "deterministic_row_match"],
    }


def provenance(evidence_ids: list[str]) -> dict:
    return {
        "evidence_ids": evidence_ids,
        "extractor": "official_pdf_reference_importer",
        "extractor_version": "1.0.0",
        "confidence": 0.99,
        "status": "accepted",
        "reason_codes": ["official_source", "deterministic_normalization"],
    }


def benchmark_source() -> dict:
    digest = sha256_bytes(BENCHMARK_TEXT.encode("utf-8"))
    return {
        "source_id": "src-standard-benchmark",
        "title": "LLPI ten-pay standard product experiment",
        "kind": "synthetic_benchmark",
        "version": "1.0.0",
        "document_sha256": digest,
    }


def benchmark_evidence() -> dict:
    digest = sha256_bytes(BENCHMARK_TEXT.encode("utf-8"))
    return {
        "evidence_id": "ev-standard-benchmark",
        "source_id": "src-standard-benchmark",
        "document_sha256": digest,
        "page": 1,
        "raw_text": BENCHMARK_TEXT,
        "content_sha256": digest,
        "extractor": "registered_standard_benchmark",
        "extractor_version": "1.0.0",
        "confidence": 1.0,
        "reason_codes": ["registered_benchmark"],
    }


def premium_cashflows(amount: Decimal = ANNUAL_PREMIUM, count: int = 10) -> list[dict]:
    return [
        {
            "date": f"{ISSUE_YEAR + index}-01-01",
            "time_years": str(index),
            "amount": money(amount),
        }
        for index in range(count)
    ]


def age_factor(attained_age: int) -> Decimal:
    if attained_age <= 40:
        return Decimal("1.6")
    if attained_age <= 60:
        return Decimal("1.4")
    return Decimal("1.2")


def standard_death(
    family: str,
    plan: int | None,
    base_amount: Decimal,
    policy_year: int,
) -> Decimal:
    attained_age = ENTRY_AGE + policy_year - 1
    paid = ANNUAL_PREMIUM * min(policy_year, 10)
    premium_floor = paid * age_factor(attained_age)
    if family == "wwa":
        base_term = base_amount * (
            Decimal("1.5") if attained_age <= 65 else Decimal("1")
        )
    elif family == "wwb" and plan == 2:
        if attained_age <= 66:
            effective_ratio = Decimal("1")
        else:
            effective_ratio = max(
                Decimal("0.62"),
                Decimal("1") - Decimal("0.03") * Decimal(attained_age - 65),
            )
        base_term = base_amount * effective_ratio
    else:
        base_term = base_amount
    return max(base_term, premium_floor)


def standard_case(
    family: str,
    plan: int | None,
    factors: list[Decimal],
    rate: Decimal,
    factor_unit: Decimal,
) -> dict:
    base_amount = ANNUAL_PREMIUM / rate * factor_unit
    projection = []
    for policy_year, factor in enumerate(factors, start=1):
        projection.append(
            {
                "policy_year": policy_year,
                "date": f"{ISSUE_YEAR + policy_year - 1}-12-31",
                "time_years": str(policy_year),
                "death_benefit": {
                    "guaranteed": money(
                        standard_death(family, plan, base_amount, policy_year)
                    ),
                    "scenarios": {},
                },
                "cash_surrender_value": {
                    "guaranteed": money(base_amount * factor / factor_unit),
                    "scenarios": {},
                },
            }
        )
    return {
        "case_id": BENCHMARK_ID,
        "label": "Ten-pay standard product experiment; official disclosed pricing row",
        "basis": {"kind": "standard_benchmark", "benchmark_version": "1.0.0"},
        "timing": {
            "issue_date": f"{ISSUE_YEAR}-01-01",
            "premium_timing": "explicit_dates",
            "benefit_timing": "projection_date",
        },
        "amount_scale": "currency_unit",
        "inflation_rate": "0.02",
        "premium_cashflows": premium_cashflows(),
        "scenario_definitions": {},
        "projection": projection,
    }


def document_case(plan: int, rows: list[dict[str, Decimal | int]]) -> dict:
    premiums = [row["annual_premium"] for row in rows if row["annual_premium"]]
    annual_amount = Decimal(str(premiums[0]))
    payment_count = len(premiums)
    projection = []
    for row in rows:
        policy_year = int(row["policy_year"])
        projection.append(
            {
                "policy_year": policy_year,
                "date": f"{ISSUE_YEAR + policy_year - 1}-12-31",
                "time_years": str(policy_year),
                "death_benefit": {
                    "guaranteed": money(Decimal(str(row["guaranteed_death"]))),
                    "scenarios": {
                        "illustrated": money(Decimal(str(row["illustrated_death"])))
                    },
                },
                "cash_surrender_value": {
                    "guaranteed": money(Decimal(str(row["guaranteed_cash"]))),
                    "scenarios": {
                        "illustrated": money(Decimal(str(row["illustrated_cash"])))
                    },
                },
            }
        )
    return {
        "case_id": f"WWB-DOC-P{plan}-2026-v1",
        "label": f"Official WWB plan {plan} benefit illustration; non-guaranteed scenario separated",
        "basis": {
            "kind": "document_illustration",
            "benchmark_version": "WWB-description-2026-v1",
        },
        "timing": {
            "issue_date": f"{ISSUE_YEAR}-01-01",
            "premium_timing": "explicit_dates",
            "benefit_timing": "projection_date",
        },
        "amount_scale": "currency_unit",
        "inflation_rate": "0.02",
        "premium_cashflows": premium_cashflows(annual_amount, payment_count),
        "scenario_definitions": {
            "illustrated": {
                "label": "情景2非保证红利利益演示",
                "guaranteed": False,
            }
        },
        "projection": projection,
    }


def build_product(
    paths: dict[str, Path],
    family: str,
    factors: list[Decimal],
    rate: Decimal,
    factor_unit: Decimal,
    plan: int | None = None,
    grade: str | None = None,
    illustration_rows: list[dict[str, Decimal | int]] | None = None,
) -> dict:
    if family == "wwa":
        product_id = "wwa-fortune-life-2025"
        name = "WWA 汇丰福佑逸生2025终身寿险"
        insurer = "汇丰人寿保险有限公司"
        participating = False
        source_keys = ["wwa_terms", "wwa_rates", "wwa_cash"]
        cash_page = 1
        rate_page = 1
        death_page = 2
    elif family == "wwb":
        product_id = f"wwb-bonjour-2025-plan-{plan}"
        name = f"WWB 汇丰汇传卓悦2025终身寿险（分红型）计划{plan}"
        insurer = "汇丰人寿保险有限公司"
        participating = True
        source_keys = ["wwb_terms", "wwb_rates", "wwb_cash", "wwb_illustration"]
        cash_page = 2 if plan == 1 else 12
        rate_page = 1
        death_page = 2
    else:
        product_id = f"allianz-prosperous-legacy-c-5-grade-{grade.lower()}"
        name = f"安联盛世臻传C（5.0）终身寿险（分红型）费率等级{grade}"
        insurer = "安联人寿保险有限公司"
        participating = True
        source_keys = ["allianz_terms", "allianz_rates", "allianz_cash"]
        cash_page = ALLIANZ_START_PAGES[str(grade)]
        rate_page = list(ALLIANZ_RATES).index(str(grade)) + 1
        death_page = 2

    sources = [source(paths, key) for key in source_keys]
    source_by_key = dict(zip(source_keys, sources))
    sources.append(benchmark_source())
    rate_key = f"{family}_rates" if family != "allianz" else "allianz_rates"
    cash_key = f"{family}_cash" if family != "allianz" else "allianz_cash"
    terms_key = f"{family}_terms" if family != "allianz" else "allianz_terms"
    rate_evidence = evidence(
        source_by_key[rate_key],
        "ev-rate-row",
        rate_page,
        f"官网费率行，十年交公开定价坐标；费率 {rate}，单位口径 {factor_unit} 元基本保险金额。",
        row="official pricing coordinate",
        rate=str(rate),
    )
    cash_evidence = evidence(
        source_by_key[cash_key],
        "ev-cash-row",
        cash_page,
        f"官网现金价值完整行，第1至第{len(factors)}保单年度；共{len(factors)}个连续数值。",
        row="official annual cash-value coordinate",
        value_count=len(factors),
    )
    death_evidence = evidence(
        source_by_key[terms_key],
        "ev-death-rule",
        death_page,
        "合同普通身故责任按基本保险金额或累计应交保险费年龄比例取大；阶段变化依条款逐年展开。",
        clause="ordinary death benefit",
    )
    evidence_items = [
        rate_evidence,
        cash_evidence,
        death_evidence,
        benchmark_evidence(),
    ]
    cases = [standard_case(family, plan, factors, rate, factor_unit)]
    provenance_map = {
        "/product": provenance(["ev-death-rule"]),
        "/cases/0/basis": provenance(["ev-standard-benchmark"]),
        "/cases/0/timing": provenance(["ev-standard-benchmark"]),
        "/cases/0/amount_scale": provenance(["ev-standard-benchmark"]),
        "/cases/0/inflation_rate": provenance(["ev-standard-benchmark"]),
        "/cases/0/premium_cashflows": provenance(["ev-standard-benchmark"]),
        "/cases/0/scenario_definitions": provenance(["ev-standard-benchmark"]),
        "/cases/0/projection": provenance(
            ["ev-rate-row", "ev-cash-row", "ev-death-rule"]
        ),
    }
    if illustration_rows is not None:
        illustration_source = source_by_key["wwb_illustration"]
        illustration_evidence = evidence(
            illustration_source,
            "ev-formal-illustration",
            8 if plan == 1 else 15,
            f"正式综合利益演示表计划{plan}，第1至65保单年度；保证值与情景2非保证演示值分列。",
            table="comprehensive benefit illustration",
            plan=plan,
            value_count=65,
        )
        evidence_items.append(illustration_evidence)
        cases.append(document_case(int(plan), illustration_rows))
        provenance_map.update(
            {
                "/cases/1/basis": provenance(
                    ["ev-formal-illustration", "ev-standard-benchmark"]
                ),
                "/cases/1/timing": provenance(["ev-standard-benchmark"]),
                "/cases/1/amount_scale": provenance(["ev-formal-illustration"]),
                "/cases/1/inflation_rate": provenance(["ev-standard-benchmark"]),
                "/cases/1/premium_cashflows": provenance(
                    ["ev-formal-illustration"]
                ),
                "/cases/1/scenario_definitions": provenance(
                    ["ev-formal-illustration"]
                ),
                "/cases/1/projection": provenance(["ev-formal-illustration"]),
            }
        )
    return {
        "schema_version": "1.0.0",
        "analysis_scope": "product_only",
        "product": {
            "product_id": product_id,
            "name": name,
            "insurer": insurer,
            "currency": "CNY",
            "product_type": (
                "participating_whole_life" if participating else "whole_life"
            ),
            "jurisdiction": "CN",
            "participating": participating,
        },
        "sources": sources,
        "evidence": evidence_items,
        "cases": cases,
        "provenance": provenance_map,
    }


def write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def build(source_dir: Path, output_dir: Path) -> list[Path]:
    paths = {key: source_dir / filename for key, filename in SOURCE_FILES.items()}
    missing = [str(path) for path in paths.values() if not path.is_file()]
    if missing:
        raise FileNotFoundError("Missing official source PDFs: " + ", ".join(missing))
    verify_rates(paths)

    wwa_factors = xml_row(
        paths["wwa_cash"], 1, ("混合标准体", "10", "年交", "男性")
    )
    wwb_factors = {
        1: xml_row(
            paths["wwb_cash"],
            2,
            ("混合标准体", "计划一", "10", "年交", "男性"),
        ),
        2: xml_row(
            paths["wwb_cash"],
            12,
            ("混合标准体", "计划二", "10", "年交", "男性"),
        ),
    }
    allianz_factors = {
        grade: allianz_row(paths["allianz_cash"], grade)
        for grade in ALLIANZ_RATES
    }
    illustrations = wwb_illustrations(paths["wwb_illustration"])

    outputs: list[tuple[str, dict]] = [
        (
            "wwa-fortune-life-2025.json",
            build_product(
                paths,
                "wwa",
                wwa_factors,
                WWA_RATE,
                Decimal("1000"),
            ),
        ),
        *[
            (
                f"wwb-bonjour-2025-plan-{plan}.json",
                build_product(
                    paths,
                    "wwb",
                    wwb_factors[plan],
                    WWB_RATES[plan],
                    Decimal("10000"),
                    plan=plan,
                    illustration_rows=illustrations[plan],
                ),
            )
            for plan in (1, 2)
        ],
        *[
            (
                f"allianz-prosperous-legacy-c-5-grade-{grade.lower()}.json",
                build_product(
                    paths,
                    "allianz",
                    allianz_factors[grade],
                    ALLIANZ_RATES[grade],
                    Decimal("1000"),
                    grade=grade,
                ),
            )
            for grade in ALLIANZ_RATES
        ],
    ]
    written = []
    for filename, value in outputs:
        target = output_dir / filename
        write_json(target, value)
        written.append(target)

    manifest = {
        "schema_version": "1.0.0",
        "generated_by": "build_reference_products.py",
        "benchmark_case_id": BENCHMARK_ID,
        "source_sha256": {
            key: sha256_file(path) for key, path in sorted(paths.items())
        },
        "annual_value_counts": {
            "wwa": len(wwa_factors),
            "wwb_plan_1": len(wwb_factors[1]),
            "wwb_plan_2": len(wwb_factors[2]),
            **{
                f"allianz_grade_{grade.lower()}": len(values)
                for grade, values in allianz_factors.items()
            },
        },
        "formal_illustration_counts": {
            f"wwb_plan_{plan}": len(rows) for plan, rows in illustrations.items()
        },
        "canonical_files": [path.name for path in written],
    }
    manifest_path = output_dir / "manifest.json"
    write_json(manifest_path, manifest)
    written.append(manifest_path)
    return written


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Import official WWA/WWB/Allianz annual reference data."
    )
    parser.add_argument("--source-dir", type=Path, required=True)
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=(
            Path(__file__).resolve().parents[1]
            / "assets"
            / "reference-products"
        ),
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    written = build(args.source_dir.resolve(), args.output_dir.resolve())
    print(
        json.dumps(
            {"status": "ok", "files": [str(path) for path in written]},
            ensure_ascii=False,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
