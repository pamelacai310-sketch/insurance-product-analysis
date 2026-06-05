from analysis_governance import (
    AdvantageClaim,
    classify_advantage,
    frequency_adjusted_score,
    render_advantage_validation_table,
    render_external_risk_audit,
    render_target_implications,
)


def test_classify_advantage_uses_frequency_thresholds():
    assert classify_advantage(3, 21, True) == "成立"
    assert classify_advantage(8, 21, True) == "部分成立"
    assert classify_advantage(21, 21, True) == "不成立"
    assert classify_advantage(None, None, True) == "需验证"
    assert classify_advantage(1, 21, False) == "不成立"


def test_render_advantage_validation_table_keeps_common_features_out_of_advantages():
    lines = render_advantage_validation_table(
        [
            AdvantageClaim("可保单贷款", "21/21", 21, 21, True, "样本标配，不构成差异化。"),
            AdvantageClaim("双意外额外给付", "3/21", 3, 21, True, "相对稀缺。"),
        ]
    )
    table = "\n".join(lines)

    assert "| 可保单贷款 | 21/21 | 不成立 | 样本标配，不构成差异化。 |" in table
    assert "| 双意外额外给付 | 3/21 | 成立 | 相对稀缺。 |" in table


def test_frequency_adjusted_score_penalizes_common_features():
    assert frequency_adjusted_score(5.0, [1.0, 0.8, 0.2]) == 4.8
    assert frequency_adjusted_score(1.1, [1.0, 1.0], penalty_per_common_feature=0.2) == 1.0


def test_external_risk_sections_avoid_unsupported_fact_claims():
    risk_lines = "\n".join(render_external_risk_audit("分红型终身寿险", "测试寿险"))
    implication_lines = "\n".join(render_target_implications("测试产品"))

    assert "未有公开证据时不得断言目标产品存在该安排" in risk_lines
    assert "是否能证明目标产品存在AIR或百慕大再保风险 | 不能" in implication_lines
