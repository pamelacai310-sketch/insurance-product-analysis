import unittest

from material_irr_analysis import MaterialDocument
from premium_table_reference import (
    build_formal_plan_input,
    detect_version_changes,
    match_premium_table_ref,
)


class PremiumTableReferenceTests(unittest.TestCase):
    def test_match_premium_table_ref_with_duplicate_hsbc_title(self):
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

        self.assertIsNotNone(ref)
        self.assertGreaterEqual(ref.confidence, 0.9)
        self.assertTrue(ref.url.endswith("huiyingfengnian-2026-rates.pdf"))

    def test_formal_plan_input_ready(self):
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

        self.assertTrue(plan.ready)
        self.assertEqual(plan.to_dict()["premium_table_ref"]["category"], "费率表")

    def test_detect_version_changes_for_rate_table(self):
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

        self.assertEqual(len(changes), 1)
        self.assertEqual(changes[0]["change_type"], "changed")


if __name__ == "__main__":
    unittest.main()
