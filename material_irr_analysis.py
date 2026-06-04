#!/usr/bin/env python3
"""
基于公开披露材料的数值 IRR 分析。

该模块优先从产品说明书的投保示例抽取可核验参数；若说明书缺少示例，
再使用费率表/现金价值表作为后续扩展的数据源。现金流规则明确写在
产品规则函数中，避免把不可核验的营销描述转换为假设收益。
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Optional
from urllib.parse import urljoin, urlparse

import pandas as pd
import pdfplumber
import requests

from actuarial_calculator import calculate_irr, generate_rating


CIGNA_API_URL = "https://www.cignacmb.com/projects/api/index.php?m=WbProductClause&c=getClauseList"
DEFAULT_ANALYSIS_JSON = Path(
    "../insurance-clause-insights/outputs/huiyingfengnian_20260603_analysis/"
    "huiyingfengnian_20260603_analysis.json"
)
DEFAULT_DOWNLOAD_DIR = Path("downloads/material_irr")
DEFAULT_REPORT_JSON = Path("reports/huiyingfengnian_material_irr_20260604.json")
DEFAULT_REPORT_MD = Path("reports/huiyingfengnian_material_irr_20260604.md")


@dataclass
class MaterialDocument:
    company: str
    product_name: str
    category: str
    url: str = ""
    path: str = ""
    text: str = ""


@dataclass
class ScenarioSpec:
    product_name: str
    source_quality: str
    entry_age: int
    gender: str
    payment_period: int
    annual_premium: float
    base_amount: float
    terminal_age: int = 105
    insurance_period: Optional[int] = None
    start_year: Optional[int] = None
    start_age: Optional[int] = None
    annual_benefit: Optional[float] = None
    maturity_benefit: float = 0.0
    benefit_schedule: dict[int, float] = field(default_factory=dict)
    notes: list[str] = field(default_factory=list)

    @property
    def total_premium(self) -> float:
        return self.annual_premium * self.payment_period


@dataclass
class MaterialIrrResult:
    company: str
    product_name: str
    analyzed: bool
    source_quality: str
    entry_age: Optional[int] = None
    gender: str = ""
    payment_period: Optional[int] = None
    annual_premium: Optional[float] = None
    base_amount: Optional[float] = None
    terminal_age: Optional[int] = None
    insurance_period: Optional[int] = None
    start_year: Optional[int] = None
    irr_conservative: Optional[float] = None
    irr_neutral: Optional[float] = None
    irr_optimistic: Optional[float] = None
    breakeven_year: Optional[int] = None
    rating_grade: str = ""
    rating_score: Optional[float] = None
    notes: list[str] = field(default_factory=list)
    unresolved_reason: str = ""


def normalize_text(text: str) -> str:
    return re.sub(r"\s+", " ", str(text or "").replace("\u3000", " ")).strip()


def normalize_product_name(text: str) -> str:
    name = normalize_text(text)
    name = re.sub(r"(?:产品)?(?:条款|产品说明书|说明书|费率表|现金价值表|现金价值全表|现金价值).*$", "", name)
    return name.strip(" ：:-_")


def safe_filename(value: str) -> str:
    return re.sub(r'[\\/:*?"<>|]', "_", value)[:120]


def parse_money(text: str | None) -> Optional[float]:
    """解析 100,000元、100万元、1.2 万等中文金额。"""
    if not text:
        return None
    raw = str(text).replace(",", "").replace("，", "").replace(" ", "")
    match = re.search(r"(\d+(?:\.\d+)?)\s*万", raw)
    if match:
        return float(match.group(1)) * 10000
    match = re.search(r"(\d+(?:\.\d+)?)", raw)
    if match:
        return float(match.group(1))
    return None


def parse_int(text: str | None) -> Optional[int]:
    if not text:
        return None
    match = re.search(r"(\d+)", str(text))
    return int(match.group(1)) if match else None


def read_pdf_text(path: Path) -> str:
    with pdfplumber.open(path) as pdf:
        return "\n".join((page.extract_text() or "") for page in pdf.pages)


def read_excel_text(path: Path, max_rows: int = 80) -> str:
    """把 Excel 前若干行转成文本，供费率表/现金价值表解析和审计。"""
    workbook = pd.ExcelFile(path)
    chunks: list[str] = []
    for sheet in workbook.sheet_names:
        frame = workbook.parse(sheet, header=None, nrows=max_rows)
        chunks.append(f"[sheet] {sheet}")
        for row in frame.fillna("").astype(str).values.tolist():
            line = " ".join(cell.strip() for cell in row if cell.strip())
            if line:
                chunks.append(line)
    return "\n".join(chunks)


def read_material_text(path: Path) -> str:
    suffix = path.suffix.lower()
    if suffix == ".pdf":
        return read_pdf_text(path)
    if suffix in {".xls", ".xlsx"}:
        return read_excel_text(path)
    return path.read_text(encoding="utf-8", errors="ignore")


def download_document(doc: MaterialDocument, download_dir: Path) -> MaterialDocument:
    if doc.path and Path(doc.path).exists():
        return doc
    if not doc.url:
        return doc

    download_dir.mkdir(parents=True, exist_ok=True)
    parsed = urlparse(doc.url)
    suffix = Path(parsed.path).suffix or ".pdf"
    url_hash = hashlib.md5(doc.url.encode("utf-8")).hexdigest()[:10]
    filename = f"{safe_filename(doc.company)}_{safe_filename(doc.product_name)}_{doc.category}_{url_hash}{suffix}"
    dest = download_dir / filename
    if not dest.exists():
        resp = requests.get(
            requests.utils.requote_uri(doc.url),
            headers={"User-Agent": "Mozilla/5.0", "Referer": doc.url},
            timeout=60,
        )
        resp.raise_for_status()
        dest.write_bytes(resp.content)
    doc.path = str(dest)
    return doc


def parse_cigna_tkinfo(tk_info: str | None) -> list[tuple[str, str]]:
    pairs: list[tuple[str, str]] = []
    for chunk in str(tk_info or "").split(","):
        if "|" not in chunk:
            continue
        version, url = chunk.split("|", 1)
        absolute = urljoin("https://www.cignacmb.com", url.strip())
        if absolute.lower().endswith((".pdf", ".xls", ".xlsx")):
            pairs.append((normalize_text(version), requests.utils.requote_uri(absolute)))
    return pairs


def fetch_cigna_supplemental_documents(product_names: set[str]) -> dict[str, list[MaterialDocument]]:
    """从招商信诺公开披露接口补齐说明书、费率表、现金价值表链接。"""
    disclosure_types = {
        "9": "产品说明书",
        "12": "费率表",
        "14": "现金价值",
    }
    session = requests.Session()
    session.headers.update({
        "User-Agent": "Mozilla/5.0",
        "X-Requested-With": "XMLHttpRequest",
        "Referer": "https://www.cignacmb.com/xinxi/jibenxinxi/chanpin/",
    })
    wanted = {normalize_product_name(name): name for name in product_names}
    result: dict[str, list[MaterialDocument]] = {name: [] for name in product_names}

    for type_code, category in disclosure_types.items():
        page = 1
        while True:
            resp = session.post(CIGNA_API_URL, data={"type": type_code, "page": page, "keyWords": ""}, timeout=60)
            resp.raise_for_status()
            data = resp.json()
            if data.get("code") != 200:
                break
            payload = data.get("data") or {}
            rows = payload.get("list") or []
            for row in rows:
                product = normalize_product_name(row.get("lname", ""))
                if product not in wanted:
                    continue
                canonical = wanted[product]
                for _, url in parse_cigna_tkinfo(row.get("tkInfo")):
                    result[canonical].append(MaterialDocument("Cigna信诺", canonical, category, url=url))
            current = int(payload.get("currentPage") or page)
            total = int(payload.get("total") or 0)
            if not rows or current >= total:
                break
            page += 1
    return result


def load_analysis_products(path: Path) -> list[dict]:
    with path.open("r", encoding="utf-8") as handle:
        data = json.load(handle)
    return data.get("products", [])


def documents_from_product(product: dict, analysis_dir: Path) -> list[MaterialDocument]:
    docs: list[MaterialDocument] = []
    company = product.get("company", "")
    product_name = product.get("product_name", "")
    for item in product.get("documents") or []:
        docs.append(MaterialDocument(company, product_name, item.get("category", ""), url=item.get("url", ""), text=item.get("text", "")))

    for category, raw_path in (product.get("doc_paths") or {}).items():
        if raw_path:
            docs.append(MaterialDocument(company, product_name, category, path=raw_path))

    docs_dir = analysis_dir / "docs"
    if docs_dir.exists():
        pattern = f"{safe_filename(company)}_{safe_filename(product_name)}_*"
        for local_path in docs_dir.glob(pattern):
            category = local_path.stem.rsplit("_", 1)[-1]
            docs.append(MaterialDocument(company, product_name, category, path=str(local_path)))

    dedup: dict[tuple[str, str, str], MaterialDocument] = {}
    for doc in docs:
        key = (doc.category, doc.url, doc.path)
        dedup[key] = doc
    return list(dedup.values())


def build_material_texts(docs: list[MaterialDocument], analysis_dir: Path) -> dict[str, str]:
    texts: dict[str, str] = {}
    text_cache = analysis_dir / "text_cache"
    for doc in docs:
        cached = text_cache / f"{safe_filename(doc.company)}_{safe_filename(doc.product_name)}_{doc.category}.txt"
        if cached.exists():
            texts[doc.category] = cached.read_text(encoding="utf-8", errors="ignore")
            continue
        if doc.path and Path(doc.path).exists():
            try:
                texts[doc.category] = read_material_text(Path(doc.path))
            except Exception as exc:
                texts[doc.category] = f"[解析失败] {exc}"
    return texts


def select_preferred_documents(docs: list[MaterialDocument], categories: set[str]) -> list[MaterialDocument]:
    """每个类别只选一个最佳材料：本地路径优先，其次公开 URL。"""
    selected: list[MaterialDocument] = []
    for category in categories:
        candidates = [doc for doc in docs if doc.category == category]
        if not candidates:
            continue
        local = [doc for doc in candidates if doc.path and Path(doc.path).exists()]
        selected.append(local[0] if local else candidates[0])
    return selected


def infer_gender(context: str) -> str:
    if re.search(r"(先生|男性|男)", context):
        return "M"
    if re.search(r"(女士|女性|女)", context):
        return "F"
    return "M"


def extract_example_context(text: str) -> str:
    candidates = ["投保示例", "案例一", "为自己投保", "投保举例", "利益演示"]
    positions = [text.find(marker) for marker in candidates if text.find(marker) >= 0]
    start = min(positions) if positions else 0
    return normalize_text(text[start:start + 3500])


def extract_scenario_from_text(product_name: str, manual_text: str, terms_text: str = "") -> Optional[ScenarioSpec]:
    context = extract_example_context(manual_text)
    if not context:
        return None

    age_match = re.search(r"(\d+)\s*(?:周岁|岁)[^，。]{0,80}(?:投保|为自己|儿子|女儿)", context)
    if not age_match:
        age_match = re.search(r"(?:投保|为自己|儿子|女儿)[^，。]{0,80}?(\d+)\s*(?:周岁|岁)", context)
    if not age_match:
        age_match = re.search(r"(\d+)\s*(?:周岁|岁)[，,、\s]*(?:为自己)?投保", context)
    if not age_match:
        age_match = re.search(r"[（(]\s*(\d+)\s*(?:周岁|岁)\s*[）)][^，。]{0,30}投保", context)
    entry_age = int(age_match.group(1)) if age_match else None

    gender = infer_gender(context)

    premium = None
    for pattern in [
        r"年交(?:保险费|保费|费)\s*([\d,]+(?:\.\d+)?\s*万?\s*元)",
        r"每年交费\s*([\d,]+(?:\.\d+)?\s*万?\s*元)",
        r"首年保费\s*([\d,]+(?:\.\d+)?\s*万?\s*元)",
        r"趸交保险费\s*([\d,]+(?:\.\d+)?\s*万?\s*元)",
    ]:
        match = re.search(pattern, context)
        if match:
            premium = parse_money(match.group(1))
            break

    payment_period = None
    if "趸交" in context and re.search(r"趸交保险费|交费方式为趸交", context):
        payment_period = 1
    for pattern in [
        r"交费期\s*间(?:为)?\s*(\d+)\s*年",
        r"(\d+)\s*年\s*交费",
        r"(\d+)\s*年\s*交",
        r"交费期间(\d+)\s*年",
    ]:
        match = re.search(pattern, context)
        if match:
            payment_period = int(match.group(1))
            break
    if payment_period is None:
        match = re.search(r"交费至\s*(\d+)\s*周岁", context)
        if match and entry_age is not None:
            payment_period = max(1, int(match.group(1)) - entry_age + 1)

    base_amount = None
    amount_pattern = r"([\d,]+(?:\.\d+)?\s*(?:万\s*)?元?)"
    for pattern in [
        rf"基本保险\s*金\s*额(?:约|为)?\s*{amount_pattern}",
        rf"基本保险\s*金额(?:约|为)?\s*{amount_pattern}",
        rf"基本年金\s*金额(?:为)?\s*{amount_pattern}",
        rf"基本部分保额\s*{amount_pattern}",
    ]:
        match = re.search(pattern, context)
        if match:
            base_amount = parse_money(match.group(1))
            break

    insurance_period = None
    match = re.search(r"保险期间为\s*(\d+)\s*年", context)
    if match:
        insurance_period = int(match.group(1))

    start_age = None
    match = re.search(r"(?:领取起始(?:时间|日|年龄)?选择|开始领取|计划)\s*(\d+)\s*周?岁", context)
    if match:
        start_age = int(match.group(1))
    elif "及时福" in product_name:
        start_age = 60 if gender == "M" else 55

    if "玺悦一号" in product_name and "计划一" in context:
        start_year = 5
    elif start_age is not None and entry_age is not None:
        start_year = max(1, start_age - entry_age)
    else:
        start_year = None

    if "盛世金越未来" in product_name and (entry_age is not None or "小王" in context):
        return ScenarioSpec(
            product_name=product_name,
            source_quality="公开说明书示例",
            entry_age=8,
            gender="M",
            payment_period=3,
            annual_premium=365788.0,
            base_amount=30000.0,
            terminal_age=105,
            notes=[
                "参数来自公开产品说明书投保举例：8岁儿童、3年交、基本部分3万、年交保费365,788元。"
            ],
        )

    if None in (entry_age, premium, payment_period, base_amount):
        return None

    notes = ["参数来自公开产品说明书投保示例；给付规则来自公开条款/说明书。"]
    return ScenarioSpec(
        product_name=product_name,
        source_quality="公开说明书示例",
        entry_age=entry_age,
        gender=gender,
        payment_period=payment_period,
        annual_premium=premium,
        base_amount=base_amount,
        insurance_period=insurance_period,
        start_age=start_age,
        start_year=start_year,
        notes=notes,
    )


def apply_product_rule(scenario: ScenarioSpec, terms_text: str, manual_text: str) -> ScenarioSpec:
    name = scenario.product_name
    total_premium = scenario.total_premium

    if "永裕人生" in name:
        scenario.terminal_age = 105
        scenario.start_year = scenario.payment_period + 2
        scenario.annual_benefit = total_premium * 0.0125
        scenario.maturity_benefit = scenario.base_amount
        scenario.notes.append("年金=累计保险费1.25%；每5年特别年金=累计保险费2.6%；满期金=基本保险金额。")
        return scenario

    if "传世臻享" in name:
        scenario.insurance_period = scenario.insurance_period or 25
        scenario.annual_benefit = total_premium * 0.10
        scenario.maturity_benefit = scenario.base_amount
        scenario.notes.append("年金在满期前两个保单周年日给付，每次=累计保险费10%；满期金=基本保险金额。")
        return scenario

    if "鑫友相伴" in name:
        scenario.terminal_age = 105 if "105" in manual_text else 85
        scenario.start_age = scenario.start_age or 60
        scenario.start_year = scenario.start_year or max(1, scenario.start_age - scenario.entry_age + 1)
        scenario.annual_benefit = scenario.base_amount
        scenario.maturity_benefit = scenario.base_amount
        scenario.notes.append("按年领方式：年金=基本保险金额；满期金=基本保险金额。")
        return scenario

    if "传世颐年" in name:
        scenario.terminal_age = 105
        scenario.start_age = scenario.start_age or 60
        scenario.start_year = scenario.start_year or max(1, scenario.start_age - scenario.entry_age + 1)
        scenario.annual_benefit = scenario.base_amount * 11.91
        scenario.notes.append("按年领方式：养老年金=基本保险金额11.91倍；终身领取，报告截取至105岁。")
        return scenario

    if "及时福" in name or "信享盈家" in name:
        scenario.terminal_age = 105
        scenario.start_age = scenario.start_age or (60 if scenario.gender == "M" else 55)
        scenario.start_year = scenario.start_year or max(1, scenario.start_age - scenario.entry_age)
        scenario.annual_benefit = scenario.base_amount
        scenario.notes.append("养老年金年领=基本保险金额；终身领取，报告截取至105岁。")
        return scenario

    if "岁岁盈" in name:
        scenario.insurance_period = scenario.insurance_period or 15
        scenario.start_year = 5
        scenario.annual_benefit = total_premium * 0.03
        scenario.maturity_benefit = scenario.base_amount
        scenario.notes.append("第5保单周年日起年金=累计已交保费3%；满期金=基本保险金额。")
        return scenario

    if "玺悦一号" in name:
        scenario.terminal_age = 105
        scenario.start_year = scenario.start_year or 5
        scenario.annual_benefit = scenario.base_amount
        scenario.notes.append("计划一：第5保单周年日起年金=基本保险金额；终身领取，报告截取至105岁。")
        return scenario

    if "盛世金越未来" in name:
        scenario.terminal_age = 105
        scenario.benefit_schedule = build_pingan_future_schedule(scenario)
        scenario.notes.append("按说明书示例保额组合拆分人生从容/教育/启航/婚嫁/养老保证给付。")
        return scenario

    if "安赢丰年" in name:
        scenario.insurance_period = scenario.insurance_period or 20
        scenario.start_age = scenario.start_age or 45
        scenario.start_year = scenario.start_year or max(1, scenario.start_age - scenario.entry_age)
        scenario.annual_benefit = scenario.base_amount
        scenario.maturity_benefit = scenario.base_amount
        scenario.notes.append("固定期间案例：基本年金=基本保险金额；满期另给付基本保险金额。")
        return scenario

    if "至尊2.0（金生版" in name:
        scenario.terminal_age = 105
        scenario.start_age = scenario.start_age or 60
        scenario.start_year = scenario.start_year or max(1, scenario.start_age - scenario.entry_age)
        scenario.annual_benefit = scenario.base_amount
        scenario.notes.append("养老年金=基本保险金额；保证给付25年，生存现金流截取至105岁。")
        return scenario

    if "至尊2.0（典藏版" in name:
        scenario.terminal_age = 105
        scenario.start_age = scenario.start_age or 60
        scenario.start_year = scenario.start_year or max(1, scenario.start_age - scenario.entry_age)
        scenario.annual_benefit = scenario.base_amount
        scenario.benefit_schedule.update(build_allianz_zunxiang_special_schedule(scenario))
        scenario.notes.append("养老年金=基本保险金额；每5个保单年度特别生存金按说明书比例给付。")
        return scenario

    if "安享兴盛" in name:
        scenario.terminal_age = 105
        scenario.start_age = scenario.start_age or 50
        scenario.start_year = scenario.start_year or max(1, scenario.start_age - scenario.entry_age)
        scenario.annual_benefit = scenario.base_amount
        scenario.notes.append("基本年金=基本年金金额；终身领取，报告截取至105岁。")
        return scenario

    # 通用年金兜底
    scenario.terminal_age = scenario.terminal_age or 105
    scenario.start_year = scenario.start_year or scenario.payment_period + 2
    scenario.annual_benefit = scenario.annual_benefit or scenario.base_amount
    scenario.maturity_benefit = scenario.maturity_benefit or 0
    scenario.notes.append("通用兜底：按基本保险金额年领。")
    return scenario


def build_pingan_future_schedule(scenario: ScenarioSpec) -> dict[int, float]:
    """平安盛世金越未来示例：8岁儿童，按条款年龄窗口生成保证给付。"""
    entry_age = scenario.entry_age
    basic = 30000.0
    education = 12000.0
    launch = 36000.0
    marriage = 36000.0
    pension = 12000.0
    schedule: dict[int, float] = {}

    def add_at_age(age: int, amount: float) -> None:
        year = age - entry_age
        if year > 0:
            schedule[year] = schedule.get(year, 0.0) + amount

    for age in range(18, 25):
        add_at_age(age, education)
    for age in range(max(25, entry_age + 5), 66):
        add_at_age(age, basic)
    add_at_age(25, launch)
    add_at_age(30, marriage)
    for age in range(66, 106):
        add_at_age(age, pension)
    return schedule


def build_allianz_zunxiang_special_schedule(scenario: ScenarioSpec) -> dict[int, float]:
    percentages = [0.15, 0.35, 0.60, 0.90, 1.25, 1.65, 2.10, 2.60, 3.15, 3.75]
    schedule: dict[int, float] = {}
    start_age = scenario.start_age or 60
    for index, pct in enumerate(percentages, start=1):
        age = start_age + index * 5
        year = age - scenario.entry_age
        if year > 0 and age <= scenario.terminal_age:
            schedule[year] = scenario.base_amount * pct
    return schedule


def build_cashflows(scenario: ScenarioSpec, dividend_rate: float = 0.0) -> list[float]:
    if scenario.insurance_period:
        horizon = scenario.insurance_period
    else:
        horizon = max(1, scenario.terminal_age - scenario.entry_age)
    cashflows = [0.0] * (horizon + 1)

    for year in range(1, min(scenario.payment_period, horizon) + 1):
        cashflows[year] -= scenario.annual_premium

    if scenario.benefit_schedule:
        for year, amount in scenario.benefit_schedule.items():
            if 0 < year <= horizon:
                cashflows[year] += amount * (1 + dividend_rate)

    if scenario.annual_benefit and scenario.start_year:
        if "传世臻享" in scenario.product_name and scenario.insurance_period:
            benefit_years = range(max(1, horizon - 2), horizon)
        else:
            end = horizon if not scenario.maturity_benefit else horizon - 1
            benefit_years = range(max(1, scenario.start_year), end + 1)
        for year in benefit_years:
            if 0 < year <= horizon:
                cashflows[year] += scenario.annual_benefit * (1 + dividend_rate)

    if "永裕人生" in scenario.product_name:
        for year in range(10, horizon):
            if (year - 10) % 5 == 0:
                cashflows[year] += scenario.total_premium * 0.026 * (1 + dividend_rate)

    if scenario.maturity_benefit and horizon > 0:
        cashflows[horizon] += scenario.maturity_benefit
        if "安赢丰年" in scenario.product_name and scenario.annual_benefit:
            cashflows[horizon] += scenario.annual_benefit * (1 + dividend_rate)

    return cashflows


def breakeven_year(cashflows: list[float]) -> Optional[int]:
    running = 0.0
    for year, cashflow in enumerate(cashflows):
        running += cashflow
        if year > 0 and running >= 0:
            return year
    return None


def analyze_scenario(company: str, scenario: ScenarioSpec) -> MaterialIrrResult:
    conservative = build_cashflows(scenario, 0.0)
    neutral = build_cashflows(scenario, 0.01)
    optimistic = build_cashflows(scenario, 0.025)

    irr_con = calculate_irr(conservative)
    irr_neu = calculate_irr(neutral)
    irr_opt = calculate_irr(optimistic)
    be_year = breakeven_year(conservative)
    rating = generate_rating(
        irr_conservative=irr_con,
        irr_neutral=irr_neu,
        breakeven_year=be_year,
        death_leverage=1.0,
        transparency_score=5 if "公开说明书" in scenario.source_quality else 4,
        product_type="annuity",
    )
    return MaterialIrrResult(
        company=company,
        product_name=scenario.product_name,
        analyzed=irr_con is not None,
        source_quality=scenario.source_quality,
        entry_age=scenario.entry_age,
        gender=scenario.gender,
        payment_period=scenario.payment_period,
        annual_premium=scenario.annual_premium,
        base_amount=scenario.base_amount,
        terminal_age=scenario.terminal_age,
        insurance_period=scenario.insurance_period,
        start_year=scenario.start_year,
        irr_conservative=irr_con,
        irr_neutral=irr_neu,
        irr_optimistic=irr_opt,
        breakeven_year=be_year,
        rating_grade=rating.get("grade", ""),
        rating_score=rating.get("total_score"),
        notes=scenario.notes,
    )


def fallback_existing_result(product: dict) -> Optional[MaterialIrrResult]:
    if not product.get("analyzed"):
        return None
    return MaterialIrrResult(
        company=product.get("company", ""),
        product_name=product.get("product_name", ""),
        analyzed=True,
        source_quality="既有条款分析现金流",
        entry_age=product.get("entry_age"),
        gender=product.get("gender") or "",
        payment_period=product.get("payment_period"),
        annual_premium=product.get("annual_premium"),
        base_amount=product.get("base_amount"),
        terminal_age=product.get("terminal_age"),
        irr_conservative=product.get("irr_conservative"),
        irr_neutral=product.get("irr_neutral"),
        irr_optimistic=product.get("irr_optimistic"),
        breakeven_year=product.get("breakeven_year"),
        rating_grade=product.get("rating_grade") or product.get("tool_rating", ""),
        rating_score=product.get("rating_score"),
        notes=[product.get("note", "")] if product.get("note") else [],
    )


def analyze_products(analysis_json: Path, download_dir: Path) -> dict:
    products = load_analysis_products(analysis_json)
    analysis_dir = analysis_json.parent

    cigna_names = {p["product_name"] for p in products if p.get("company") == "Cigna信诺"}
    cigna_supplements = fetch_cigna_supplemental_documents(cigna_names) if cigna_names else {}

    results: list[MaterialIrrResult] = []
    for product in products:
        company = product.get("company", "")
        product_name = product.get("product_name", "")
        docs = documents_from_product(product, analysis_dir)
        docs.extend(cigna_supplements.get(product_name, []))
        essential_docs = select_preferred_documents(docs, {"条款", "产品说明书"})
        essential_docs = [download_document(doc, download_dir) for doc in essential_docs]
        texts = build_material_texts(essential_docs, analysis_dir)
        manual_text = texts.get("产品说明书", "")
        terms_text = texts.get("条款", "")

        scenario = extract_scenario_from_text(product_name, manual_text, terms_text)
        if scenario:
            scenario = apply_product_rule(scenario, terms_text, manual_text)
            results.append(analyze_scenario(company, scenario))
            continue

        fallback = fallback_existing_result(product)
        if fallback:
            results.append(fallback)
        else:
            results.append(MaterialIrrResult(
                company=company,
                product_name=product_name,
                analyzed=False,
                source_quality="未形成数值现金流",
                unresolved_reason=product.get("skip_reason", "未能从公开说明书/费率表抽取完整现金流参数。"),
            ))

    analyzed = [r for r in results if r.analyzed and r.irr_neutral is not None]
    ranked = sorted(analyzed, key=lambda item: item.irr_neutral or -99, reverse=True)
    target_name = "汇丰汇赢丰年2026年金保险（分红型）"
    target_rank = next((idx + 1 for idx, item in enumerate(ranked) if item.product_name == target_name), None)
    target = next((item for item in results if item.product_name == target_name), None)

    return {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "source_analysis_json": str(analysis_json),
        "total_products": len(results),
        "analyzed_count": len(analyzed),
        "unresolved_count": len(results) - len(analyzed),
        "target_rank_by_neutral_irr": target_rank,
        "target_neutral_irr": target.irr_neutral if target else None,
        "products": [asdict(r) for r in results],
    }


def fmt_pct(value: Optional[float]) -> str:
    return "" if value is None else f"{value:.2%}"


def fmt_money(value: Optional[float]) -> str:
    return "" if value is None else f"{value:,.0f}"


def write_markdown_report(payload: dict, output_path: Path) -> None:
    products = [MaterialIrrResult(**item) for item in payload["products"]]
    analyzed = [p for p in products if p.analyzed and p.irr_neutral is not None]
    ranked = sorted(analyzed, key=lambda item: item.irr_neutral or -99, reverse=True)
    unresolved = [p for p in products if not p.analyzed]
    target = next((p for p in products if p.product_name == "汇丰汇赢丰年2026年金保险（分红型）"), None)

    lines = [
        "# 汇丰汇赢丰年2026同类产品材料版数值 IRR 分析",
        "",
        f"- 生成时间：{payload['generated_at']}",
        f"- 分析产品数：{payload['total_products']}；形成数值 IRR：{payload['analyzed_count']}；未形成：{payload['unresolved_count']}",
    ]
    if target:
        lines.append(
            f"- 目标产品中性 IRR：{fmt_pct(target.irr_neutral)}；排名：{payload.get('target_rank_by_neutral_irr')}/{len(ranked)}；评级：{target.rating_grade}"
        )
    lines.extend([
        "",
        "## IRR 排名",
        "",
        "| 排名 | 公司 | 产品 | 参数来源 | 年交/趸交保费 | 交费期 | 基本金额 | 保守IRR | 中性IRR | 乐观IRR | 回本年 | 评级 |",
        "|---:|---|---|---|---:|---:|---:|---:|---:|---:|---:|---|",
    ])
    for index, item in enumerate(ranked, 1):
        lines.append(
            f"| {index} | {item.company} | {item.product_name} | {item.source_quality} | "
            f"{fmt_money(item.annual_premium)} | {item.payment_period or ''} | {fmt_money(item.base_amount)} | "
            f"{fmt_pct(item.irr_conservative)} | {fmt_pct(item.irr_neutral)} | {fmt_pct(item.irr_optimistic)} | "
            f"{item.breakeven_year or ''} | {item.rating_grade} |"
        )

    lines.extend(["", "## 关键说明", ""])
    for item in ranked:
        if item.notes:
            lines.append(f"- {item.company} / {item.product_name}：{'；'.join(note for note in item.notes if note)}")

    if unresolved:
        lines.extend(["", "## 仍未形成数值 IRR 的产品", ""])
        for item in unresolved:
            lines.append(f"- {item.company} / {item.product_name}：{item.unresolved_reason}")

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(description="基于公开说明书/费率表/现金价值表生成材料版 IRR 分析")
    parser.add_argument("--analysis-json", type=Path, default=DEFAULT_ANALYSIS_JSON)
    parser.add_argument("--download-dir", type=Path, default=DEFAULT_DOWNLOAD_DIR)
    parser.add_argument("--output-json", type=Path, default=DEFAULT_REPORT_JSON)
    parser.add_argument("--output-md", type=Path, default=DEFAULT_REPORT_MD)
    args = parser.parse_args()

    payload = analyze_products(args.analysis_json, args.download_dir)
    args.output_json.parent.mkdir(parents=True, exist_ok=True)
    args.output_json.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    write_markdown_report(payload, args.output_md)
    print(f"材料版 IRR JSON: {args.output_json}")
    print(f"材料版 IRR 报告: {args.output_md}")
    print(f"形成数值 IRR: {payload['analyzed_count']}/{payload['total_products']}")


if __name__ == "__main__":
    main()
