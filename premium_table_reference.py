"""
费率表引用与版本审计工具。

目标：
- 为正式投保计划生成保留可核验的 premium_table_ref。
- 用模糊匹配提升“产品名 -> 费率表”命中率。
- 对条款/费率表材料生成稳定版本签名，便于识别版本变更。
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import asdict, dataclass, field
from difflib import SequenceMatcher
from pathlib import Path
from typing import Iterable, Mapping, Optional
from urllib.parse import urlparse


@dataclass
class PremiumTableRef:
    product_name: str
    matched_title: str
    category: str
    url: str = ""
    path: str = ""
    version_label: str = ""
    content_hash: str = ""
    confidence: float = 0.0
    match_reason: str = ""

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class MaterialVersionRef:
    product_name: str
    category: str
    title: str
    url: str = ""
    path: str = ""
    version_label: str = ""
    content_hash: str = ""

    def key(self) -> tuple[str, str]:
        return (normalize_product_name(self.product_name), self.category)

    def signature(self) -> tuple[str, str, str]:
        return (self.version_label, self.content_hash, self.url or self.path)

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class FormalPlanInput:
    product_name: str
    entry_age: Optional[int] = None
    gender: str = ""
    payment_period: Optional[int] = None
    annual_premium: Optional[float] = None
    base_amount: Optional[float] = None
    premium_table_ref: Optional[PremiumTableRef] = None
    missing_fields: list[str] = field(default_factory=list)

    @property
    def ready(self) -> bool:
        return not self.missing_fields and self.premium_table_ref is not None

    def to_dict(self) -> dict:
        payload = asdict(self)
        payload["premium_table_ref"] = (
            self.premium_table_ref.to_dict() if self.premium_table_ref else None
        )
        payload["ready"] = self.ready
        return payload


def normalize_text(text: str) -> str:
    return re.sub(r"\s+", " ", str(text or "").replace("\u3000", " ")).strip()


def normalize_product_name(text: str) -> str:
    name = normalize_text(text)
    name = re.sub(r"(下载链接|点击下载|download)", "", name, flags=re.I)
    name = re.sub(
        r"(?:产品)?(?:条款|合同文本|合同条款|产品说明书|说明书|保险费率表|费率表|现金价值全表|现金价值表|现金价值).*$",
        "",
        name,
        flags=re.I,
    )
    return name.strip(" ：:-_.。")


def normalized_match_key(text: str) -> str:
    key = normalize_product_name(text)
    key = re.sub(r"[（）()【】\[\]·\s_\-—.。]", "", key)
    key = key.replace("保险", "").replace("产品", "")
    return key.lower()


def content_hash_for_path(path: str) -> str:
    if not path or not Path(path).exists():
        return ""
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()[:16]


def infer_version_label(title: str = "", url: str = "", path: str = "") -> str:
    bag = " ".join([title or "", url or "", path or ""])
    tokens = []
    tokens.extend(re.findall(r"20\d{2}(?:[-_/年]\d{1,2})?(?:[-_/月]\d{1,2})?", bag))
    tokens.extend(re.findall(r"(?:v|version|版|款|b款|c款|d款|e款|f款)[-_ ]?\d*\.?\d*", bag, flags=re.I))
    normalized = []
    for token in tokens:
        token = normalize_text(token)
        if token and token not in normalized:
            normalized.append(token)
    if normalized:
        return "|".join(normalized[:4])
    parsed_name = Path(urlparse(url).path).stem if url else Path(path).stem
    return parsed_name[:80]


def document_title(doc) -> str:
    text = getattr(doc, "text", "") or ""
    if text:
        return normalize_text(text)
    if getattr(doc, "url", ""):
        return Path(urlparse(doc.url).path).stem
    if getattr(doc, "path", ""):
        return Path(doc.path).stem
    return ""


def document_ref(doc) -> MaterialVersionRef:
    title = document_title(doc)
    product_name = getattr(doc, "product_name", "") or normalize_product_name(title)
    return MaterialVersionRef(
        product_name=product_name,
        category=getattr(doc, "category", ""),
        title=title,
        url=getattr(doc, "url", ""),
        path=getattr(doc, "path", ""),
        version_label=infer_version_label(title, getattr(doc, "url", ""), getattr(doc, "path", "")),
        content_hash=content_hash_for_path(getattr(doc, "path", "")),
    )


def score_product_match(product_name: str, candidate_title: str) -> tuple[float, str]:
    target_key = normalized_match_key(product_name)
    candidate_key = normalized_match_key(candidate_title)
    if not target_key or not candidate_key:
        return 0.0, "empty"
    if target_key == candidate_key:
        return 1.0, "normalized-exact"
    if target_key in candidate_key or candidate_key in target_key:
        shorter = min(len(target_key), len(candidate_key))
        longer = max(len(target_key), len(candidate_key))
        return round(0.9 + 0.09 * shorter / longer, 4), "substring"
    ratio = SequenceMatcher(None, target_key, candidate_key).ratio()
    return round(ratio, 4), "fuzzy"


def match_premium_table_ref(product_name: str, docs: Iterable, threshold: float = 0.72) -> Optional[PremiumTableRef]:
    best: Optional[PremiumTableRef] = None
    for doc in docs:
        if getattr(doc, "category", "") != "费率表":
            continue
        title = document_title(doc)
        score, reason = score_product_match(product_name, title or getattr(doc, "product_name", ""))
        if score < threshold:
            continue
        ref = PremiumTableRef(
            product_name=product_name,
            matched_title=title,
            category="费率表",
            url=getattr(doc, "url", ""),
            path=getattr(doc, "path", ""),
            version_label=infer_version_label(title, getattr(doc, "url", ""), getattr(doc, "path", "")),
            content_hash=content_hash_for_path(getattr(doc, "path", "")),
            confidence=score,
            match_reason=reason,
        )
        if best is None or ref.confidence > best.confidence:
            best = ref
    return best


def build_material_version_refs(docs: Iterable) -> list[MaterialVersionRef]:
    return [
        document_ref(doc)
        for doc in docs
        if getattr(doc, "category", "") in {"条款", "费率表"}
    ]


def detect_version_changes(
    previous_refs: Iterable[MaterialVersionRef | Mapping],
    current_refs: Iterable[MaterialVersionRef | Mapping],
) -> list[dict]:
    def coerce(ref) -> MaterialVersionRef:
        if isinstance(ref, MaterialVersionRef):
            return ref
        return MaterialVersionRef(**dict(ref))

    previous = {coerce(ref).key(): coerce(ref) for ref in previous_refs}
    current = {coerce(ref).key(): coerce(ref) for ref in current_refs}
    changes = []
    for key, current_ref in current.items():
        previous_ref = previous.get(key)
        if previous_ref is None:
            changes.append({"change_type": "added", "current": current_ref.to_dict(), "previous": None})
        elif previous_ref.signature() != current_ref.signature():
            changes.append({
                "change_type": "changed",
                "current": current_ref.to_dict(),
                "previous": previous_ref.to_dict(),
            })
    for key, previous_ref in previous.items():
        if key not in current:
            changes.append({"change_type": "removed", "current": None, "previous": previous_ref.to_dict()})
    return changes


def build_formal_plan_input(
    product_name: str,
    entry_age: Optional[int],
    gender: str,
    payment_period: Optional[int],
    annual_premium: Optional[float],
    base_amount: Optional[float],
    premium_table_ref: Optional[PremiumTableRef],
) -> FormalPlanInput:
    missing = []
    for field_name, value in [
        ("entry_age", entry_age),
        ("gender", gender),
        ("payment_period", payment_period),
        ("annual_premium", annual_premium),
        ("base_amount", base_amount),
        ("premium_table_ref", premium_table_ref),
    ]:
        if value in (None, ""):
            missing.append(field_name)
    return FormalPlanInput(
        product_name=product_name,
        entry_age=entry_age,
        gender=gender,
        payment_period=payment_period,
        annual_premium=annual_premium,
        base_amount=base_amount,
        premium_table_ref=premium_table_ref,
        missing_fields=missing,
    )
