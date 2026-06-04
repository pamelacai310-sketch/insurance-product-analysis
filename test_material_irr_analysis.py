from pathlib import Path

import pandas as pd

from material_irr_analysis import (
    apply_product_rule,
    build_cashflows,
    extract_scenario_from_text,
    parse_money,
    read_excel_text,
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
