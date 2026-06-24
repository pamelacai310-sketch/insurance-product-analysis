from pathlib import Path

import pandas as pd

from material_irr_analysis import (
    MaterialDocument,
    apply_product_rule,
    build_cashflows,
    extract_scenario_from_text,
    parse_money,
    read_excel_text,
)
from premium_table_reference import (
    build_formal_plan_input,
    detect_version_changes,
    match_premium_table_ref,
)


def test_parse_money_chinese_units():
    assert parse_money("100,000元") == 100000.0
    assert parse_money("100万元") == 1000000.0
    assert parse_money("1.2 万元") == 12000.0


def test_extract_cigna_suiying_example_and_cashflows():
    text = (
        "案例一：35岁的刘女士为自己投保了“招商信诺岁岁盈定期年金保险（分红型）”，"
        "保险期间为15年，交费期间为3年，交费方式为年交，年交保险费100,000元，"
        "基本保险金额256,857元，可获得的保险利益演示如下："
    )
    scenario = extract_scenario_from_text("招商信诺岁岁盈定期年金保险（分红型）", text)
    assert scenario is not None
    scenario = apply_product_rule(scenario, "", text)

    assert scenario.entry_age == 35
    assert scenario.gender == "F"
    assert scenario.payment_period == 3
    assert scenario.annual_benefit == 9000.0

    cashflows = build_cashflows(scenario)
    assert cashflows[1] == -100000.0
    assert cashflows[5] == 9000.0
    assert cashflows[15] == 256857.0


def test_read_excel_text(tmp_path: Path):
    xlsx_path = tmp_path / "rate.xlsx"
    frame = pd.DataFrame([["投保年龄", "男性", "女性"], [40, 123.45, 120.0]])
    frame.to_excel(xlsx_path, index=False, header=False)

    text = read_excel_text(xlsx_path)
    assert "投保年龄 男性 女性" in text
    assert "40 123.45 120" in text


def test_match_premium_table_ref_with_duplicate_hsbc_title():
    docs = [
        MaterialDocument(
            company="HSBC汇丰",
            product_name="汇丰汇赢丰年2026年金保险（分红型）",
            category="费率表",
            url="https://www.hsbcinsurance.com.cn/huiyingfengnian-2026-rates.pdf",
            text="汇丰汇赢丰年2026年金保险（分红型）费率表 汇丰汇赢丰年2026年金保险（分红型）费率表 下载链接",
        )
    ]

    ref = match_premium_table_ref("汇丰汇赢丰年2026年金保险（分红型）", docs)

    assert ref is not None
    assert ref.confidence >= 0.9
    assert ref.url.endswith("huiyingfengnian-2026-rates.pdf")


def test_formal_plan_input_requires_premium_table_ref():
    docs = [
        MaterialDocument(
            company="HSBC汇丰",
            product_name="汇丰汇赢丰年2026年金保险（分红型）",
            category="费率表",
            text="汇丰汇赢丰年2026年金保险（分红型）费率表",
        )
    ]
    ref = match_premium_table_ref("汇丰汇赢丰年2026年金保险（分红型）", docs)

    plan = build_formal_plan_input(
        product_name="汇丰汇赢丰年2026年金保险（分红型）",
        entry_age=35,
        gender="M",
        payment_period=5,
        annual_premium=100000,
        base_amount=50000,
        premium_table_ref=ref,
    )

    assert plan.ready is True
    assert plan.to_dict()["premium_table_ref"]["category"] == "费率表"


def test_detect_version_changes_for_rate_table():
    previous = [{
        "product_name": "测试年金保险",
        "category": "费率表",
        "title": "测试年金保险费率表",
        "url": "https://example.com/rate-v1.pdf",
        "path": "",
        "version_label": "2025",
        "content_hash": "old",
    }]
    current = [{
        "product_name": "测试年金保险",
        "category": "费率表",
        "title": "测试年金保险费率表",
        "url": "https://example.com/rate-v2.pdf",
        "path": "",
        "version_label": "2026",
        "content_hash": "new",
    }]

    changes = detect_version_changes(previous, current)

    assert len(changes) == 1
    assert changes[0]["change_type"] == "changed"
