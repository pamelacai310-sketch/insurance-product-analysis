"""
insurance-clause-insights 与 insurance-product-analysis 的桥接层
从条款比较报告提取精算参数并转换为 ProductSpec

Bridge Layer: Convert clause comparison reports to ProductSpec for actuarial analysis
"""

from pathlib import Path
from typing import Optional
import json
import re
from dataclasses import dataclass

from actuarial_calculator import ProductSpec


@dataclass
class ExtractedProduct:
    """从条款中提取的产品数据

    Extracted product data from clause reports
    """
    company: str
    product_name: str
    category: str
    pdf_path: str

    # 精算参数（可能为空）
    entry_age: Optional[int] = None
    gender: Optional[str] = None
    annual_premium: Optional[float] = None
    sum_assured: Optional[float] = None
    payment_period: Optional[int] = None
    insurance_period: Optional[str] = None
    dividend_type: Optional[str] = None
    guaranteed_rate: Optional[float] = None


def load_clause_report(json_path: Path) -> list[ExtractedProduct]:
    """加载 comparison_report.json 并提取产品

    Load comparison_report.json and extract products

    Args:
        json_path: comparison_report.json 文件路径

    Returns:
        ExtractedProduct 列表
    """
    with open(json_path, 'r', encoding='utf-8') as f:
        data = json.load(f)

    products = []

    for group in data.get("groups", []):
        for product in group.get("products", []):
            params = product.get("actuarial_params", {})

            # 提取并解析参数
            entry_age = params.get("entry_age")
            gender = params.get("gender")
            annual_premium = params.get("annual_premium")
            sum_assured = params.get("sum_assured")

            # 尝试从 key_facts 中提取 sum_assured（如果 actuarial_params 中没有）
            if not sum_assured:
                sum_assured_text = product.get("key_facts", {}).get("保险金额", "")
                if sum_assured_text:
                    sum_assured = extract_premium_from_text(sum_assured_text)

            # 提取缴费期间
            payment_period = params.get("payment_period")
            if not payment_period:
                payment_period_text = product.get("key_facts", {}).get("缴费期间", "")
                if payment_period_text:
                    payment_period = extract_period_from_text(payment_period_text)

            products.append(ExtractedProduct(
                company=product["company"],
                product_name=product["product_name"],
                category=group["category"],
                pdf_path=product["pdf_path"],
                entry_age=entry_age,
                gender=gender,
                annual_premium=annual_premium,
                sum_assured=sum_assured,
                payment_period=payment_period,
                insurance_period=params.get("insurance_period") or product.get("key_facts", {}).get("保险期间"),
                dividend_type=params.get("dividend_type"),
                guaranteed_rate=params.get("guaranteed_rate"),
            ))

    return products


def extract_premium_from_text(text: str) -> Optional[float]:
    """从文本中提取保费金额

    Extract premium amount from text

    Examples:
        >>> extract_premium_from_text("10,000元")
        10000.0
        >>> extract_premium_from_text("1万元")
        10000.0
        >>> extract_premium_from_text("35000元")
        35000.0
    """
    if not text:
        return None

    # 移除逗号和空格
    text = text.replace(",", "").replace(" ", "")

    # 处理 "万" 单位
    match = re.search(r"([\d.]+)\s*万", text)
    if match:
        try:
            return float(match.group(1)) * 10000
        except ValueError:
            pass

    # 直接提取数字
    match = re.search(r"([\d,]+\.?\d*)", text)
    if match:
        try:
            return float(match.group(1).replace(",", ""))
        except ValueError:
            pass

    return None


def extract_period_from_text(text: str) -> Optional[int]:
    """从缴费期间文本提取年数

    Extract payment period in years from text

    Examples:
        >>> extract_period_from_text("5年缴")
        5
        >>> extract_period_from_text("缴费期间10年")
        10
        >>> extract_period_from_text("20年期")
        20
    """
    if not text:
        return None

    match = re.search(r"(\d+)\s*年", text)
    if match:
        try:
            return int(match.group(1))
        except ValueError:
            pass

    return None


def convert_to_product_spec(
    extracted: ExtractedProduct,
    default_age: int = 30,
    default_gender: str = "M"
) -> Optional[ProductSpec]:
    """将提取的产品数据转换为 ProductSpec

    Convert extracted product data to ProductSpec

    Args:
        extracted: 提取的产品数据
        default_age: 缺失年龄时的默认值
        default_gender: 缺失性别时的默认值

    Returns:
        ProductSpec 对象，如果必需参数缺失则返回 None
    """
    # 检查必需参数
    if not extracted.annual_premium or not extracted.sum_assured:
        return None

    # 映射产品类型
    product_type = map_category_to_type(extracted.category)

    # 确定分红类型
    dividend_type = extracted.dividend_type
    if not dividend_type:
        # 根据产品名称推断
        if "分红" in extracted.product_name:
            dividend_type = "accumulate"  # 默认累积生息
        elif "万能" in extracted.product_name:
            dividend_type = "universal"

    # 确定年金开始年龄（如果适用）
    annuity_start_year = None
    if product_type in ["annuity", "annuity_participating"]:
        # 年金险通常在第5或第7年开始领取
        payment_period = extracted.payment_period or 5
        annuity_start_year = payment_period  # 假设交费期满后开始领取

    return ProductSpec(
        product_name=extracted.product_name,
        product_type=product_type,
        entry_age=extracted.entry_age or default_age,
        gender=extracted.gender or default_gender,
        payment_period=extracted.payment_period or 5,
        annual_premium=extracted.annual_premium,
        sum_assured=extracted.sum_assured,
        annuity_start_year=annuity_start_year,
        dividend_type=dividend_type,
        guaranteed_rate=extracted.guaranteed_rate,
    )


def map_category_to_type(category: str) -> str:
    """映射产品类别到精算类型

    Map product category to actuarial type

    Args:
        category: 产品类别名称

    Returns:
        精算产品类型代码
    """
    mapping = {
        "年金保险": "annuity",
        "年金保险（分红型）": "annuity_participating",
        "增额终身寿险": "whole_life",
        "终身寿险": "whole_life",
        "定期寿险": "term",
        "重疾险": "health",
        "万能险": "universal",
        "两全保险": "endowment",
    }
    return mapping.get(category, "endowment")


def calculate_completeness(product: ExtractedProduct) -> float:
    """计算参数完整性

    Calculate parameter completeness score

    Args:
        product: 提取的产品数据

    Returns:
        完整性分数（0-1之间）
    """
    required_fields = [
        product.annual_premium,
        product.sum_assured,
        product.payment_period,
    ]
    optional_fields = [
        product.entry_age,
        product.gender,
    ]

    required_completeness = sum(1 for f in required_fields if f is not None) / len(required_fields)
    optional_completeness = sum(1 for f in optional_fields if f is not None) / len(optional_fields)

    # 必需字段权重80%，可选字段权重20%
    return required_completeness * 0.8 + optional_completeness * 0.2


def batch_analyze_from_clauses(
    clause_report_path: Path,
    default_age: int = 30,
    default_gender: str = "M",
    min_completeness: float = 0.6
) -> dict:
    """
    从条款报告批量分析产品

    Batch analyze products from clause report

    Args:
        clause_report_path: comparison_report.json 路径
        default_age: 缺失年龄时的默认值
        default_gender: 缺失性别时的默认值
        min_completeness: 最小参数完整性阈值

    Returns:
        分析结果字典，包含统计信息和产品分析结果
    """
    from actuarial_calculator import irr_scenario_analysis
    from integrated_calculator import IntegratedAnalyzer

    extracted_products = load_clause_report(clause_report_path)
    results = {
        "total": len(extracted_products),
        "analyzed": 0,
        "skipped": 0,
        "products": []
    }

    for extracted in extracted_products:
        # 检查参数完整性
        completeness = calculate_completeness(extracted)
        if completeness < min_completeness:
            results["skipped"] += 1
            continue

        # 转换为 ProductSpec
        spec = convert_to_product_spec(extracted, default_age, default_gender)
        if not spec:
            results["skipped"] += 1
            continue

        # 执行精算分析
        irr_results = irr_scenario_analysis(spec)
        analyzer = IntegratedAnalyzer(spec)
        report = analyzer.analyze()

        results["products"].append({
            "company": extracted.company,
            "product_name": extracted.product_name,
            "category": extracted.category,
            "completeness": round(completeness, 2),
            "spec": {
                "entry_age": spec.entry_age,
                "gender": spec.gender,
                "payment_period": spec.payment_period,
                "annual_premium": spec.annual_premium,
                "sum_assured": spec.sum_assured,
            },
            "irr_conservative": round(irr_results.get("保守（0分红）", 0), 4),
            "irr_neutral": round(irr_results.get("中性（历史低位分红）", 0), 4),
            "irr_optimistic": round(irr_results.get("乐观（演示分红水平）", 0), 4),
            "rating": report["rating"]["grade"],
            "total_score": round(report["rating"]["total_score"], 2),
        })
        results["analyzed"] += 1

    return results
