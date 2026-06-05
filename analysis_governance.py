"""
可复用的精算报告治理工具。

这些函数只处理分析口径，不替代具体现金流/IRR计算：
- 高频功能降权，避免目标产品硬编码满分。
- 对“目标产品优势是否成立”做证据表述。
- 输出分红险外部风险审计章节。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, Mapping, Sequence


@dataclass(frozen=True)
class AdvantageClaim:
    claim: str
    evidence: str
    sample_count: int | None = None
    sample_total: int | None = None
    guaranteed: bool | None = None
    revised_statement: str = ""


def classify_advantage(
    sample_count: int | None,
    sample_total: int | None,
    guaranteed: bool | None = None,
) -> str:
    """按同类频率和保证/非保证属性判断目标优势是否成立。"""
    if guaranteed is False:
        return "不成立"
    if sample_count is None or sample_total in (None, 0):
        return "需验证"
    frequency = sample_count / sample_total
    if frequency < 0.25:
        return "成立"
    if frequency < 0.75:
        return "部分成立"
    return "不成立"


def feature_claim_from_audit(
    claim: str,
    audit_by_label: Mapping[str, Mapping[str, object]],
    revised_statement: str,
    label: str | None = None,
    evidence: str | None = None,
) -> AdvantageClaim:
    """从 clause-insights 的 feature_audit 生成优势验证行。"""
    item = audit_by_label.get(label or claim, {})
    count = item.get("peer_count", item.get("sample_count"))
    total = item.get("peer_total", item.get("sample_total"))
    count_int = int(count) if isinstance(count, int) else None
    total_int = int(total) if isinstance(total, int) else None
    return AdvantageClaim(
        claim=claim,
        evidence=evidence or (f"{count_int}/{total_int}" if count_int is not None and total_int else "缺少同类频率"),
        sample_count=count_int,
        sample_total=total_int,
        revised_statement=revised_statement,
    )


def render_advantage_validation_table(claims: Sequence[AdvantageClaim]) -> list[str]:
    lines = [
        "## 目标产品优势是否成立",
        "",
        "| 原声称优势 | 样本频率/证据 | 是否成立 | 修正表述 |",
        "|---|---|---|---|",
    ]
    for claim in claims:
        lines.append(
            f"| {claim.claim} | {claim.evidence} | "
            f"{classify_advantage(claim.sample_count, claim.sample_total, claim.guaranteed)} | "
            f"{claim.revised_statement} |"
        )
    return lines


def frequency_adjusted_score(
    base_score: float,
    feature_frequencies: Iterable[float],
    common_threshold: float = 0.75,
    penalty_per_common_feature: float = 0.1,
    floor: float = 1.0,
    cap: float = 5.0,
) -> float:
    """对高频功能降权，防止同类标配把目标产品推成满分。"""
    common_count = sum(1 for frequency in feature_frequencies if frequency >= common_threshold)
    adjusted = base_score - common_count * penalty_per_common_feature
    return round(max(floor, min(cap, adjusted)), 2)


def render_external_risk_audit(
    product_type_label: str = "分红型长期寿险",
    company_label: str = "保险公司",
) -> list[str]:
    return [
        "## 外部风险审计",
        "",
        "| 风险维度 | 行业风险机制 | 对产品分析的影响 | 报告处理口径 |",
        "|---|---|---|---|",
        f"| 长久期负债与ALM错配 | 传统寿险、两全险或终身寿险负债久期较长，资产端若无法匹配会放大利率风险 | {product_type_label}的长期保证责任和分红账户收益依赖资产负债久期匹配能力 | 只作为外部风险提示，不自动给单一产品扣分；需用{company_label}偿付能力报告和资产配置披露验证 |",
        f"| 产品结构迁移 | 低利率和资本监管压力会推动险企减少传统高保证产品，转向投连、年金或更多非保证收益机制 | 非保证演示利益更依赖{company_label}经营结果，客户不能把演示红利当刚性承诺 | 报告必须拆分保证利益与非保证利益，非保证利益不得作为保证收益优势 |",
        "| AIR再保险与百慕大再保 | AIR可同时转移资产与负债，离岸监管的流动性溢价假设可能降低准备金并改善表观资本 | 若底层再保资产流动性差或估值不透明，极端市场下可能影响偿付能力和分红稳定性 | 未有公开证据时不得断言目标产品存在该安排，只列为需查再保险披露的审计项 |",
        "| 衍生品保证金压力 | 利率衍生品可调久期但加息期可能带来保证金追加，汇率衍生品对冲成本会侵蚀收益 | 可能影响投资收益、资本占用和分红账户盈余 | 条款层面无法验证；需读取年报中的衍生金融工具、套保政策和保证金风险说明 |",
        "| PE/PD和非流动资产集中 | 私募股权、私募债、资产证券化产品占比提升会增加估值不透明和流动性风险 | 极端流动性环境下，可能影响分红稳定性和公司资本弹性 | 未纳入产品条款评分；需要资产配置、关联交易和再保险交易披露支持 |",
    ]


def render_target_implications(
    target_display_name: str,
    input_scope: str = "产品条款、说明书、费率表和现金价值表",
) -> list[str]:
    return [
        f"## 对{target_display_name}的实际含义",
        "",
        "| 判断项 | 当前结论 | 原因 | 后续验证材料 |",
        "|---|---|---|---|",
        f"| 是否能证明目标产品有更强资产端安全性 | 不能 | 本次输入为{input_scope}，不含公司资产久期、资产质量或再保险安排 | 偿付能力季度报告、年度报告、分红账户投资说明 |",
        "| 是否能证明目标产品存在AIR或百慕大再保风险 | 不能 | 公开产品条款不披露此类安排，不能用全球行业趋势替代具体公司事实 | 重大再保险合同、关联交易、境外再保险披露 |",
        "| 是否影响客户适配 | 会影响 | 分红型产品的非保证利益与保险公司长期经营、资产收益和资本充足度相关 | 分红实现率、历史红利派发、偿付能力充足率和风险综合评级 |",
        "| 是否改变条款独特性结论 | 不改变 | 条款独特性应由同类样本频率决定，宏观风险不是合同功能 | 无需改变同类产品样本清单 |",
    ]
