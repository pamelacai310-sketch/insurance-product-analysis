from __future__ import annotations

import hashlib
import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path


SCRIPTS_DIR = Path(__file__).resolve().parents[1] / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

from annuity_intelligence.extraction import (  # noqa: E402
    detect_prohibited_customer_data,
    fingerprint_file,
    inspect_inputs,
    route_confidence,
)


OPENPYXL_AVAILABLE = importlib.util.find_spec("openpyxl") is not None
PDF_TEST_DEPS_AVAILABLE = importlib.util.find_spec("pdfplumber") is not None


def _write_minimal_pdf(path: Path, text: str = "") -> None:
    escaped = text.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")
    content = (
        f"BT /F1 12 Tf 72 720 Td ({escaped}) Tj ET" if text else "0 0 m 100 100 l S"
    )
    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Resources << /Font << /F1 4 0 R >> >> /Contents 5 0 R >>",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
        f"<< /Length {len(content.encode('ascii'))} >>\nstream\n{content}\nendstream".encode(
            "ascii"
        ),
    ]
    payload = bytearray(b"%PDF-1.4\n")
    offsets = [0]
    for index, obj in enumerate(objects, start=1):
        offsets.append(len(payload))
        payload.extend(f"{index} 0 obj\n".encode("ascii"))
        payload.extend(obj)
        payload.extend(b"\nendobj\n")
    xref_offset = len(payload)
    payload.extend(f"xref\n0 {len(objects) + 1}\n".encode("ascii"))
    payload.extend(b"0000000000 65535 f \n")
    for offset in offsets[1:]:
        payload.extend(f"{offset:010d} 00000 n \n".encode("ascii"))
    payload.extend(
        f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\nstartxref\n{xref_offset}\n%%EOF\n".encode(
            "ascii"
        )
    )
    path.write_bytes(bytes(payload))


class FingerprintTests(unittest.TestCase):
    def test_fingerprint_is_content_based_and_stable(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            path = Path(temporary_directory) / "product.txt"
            payload = "养老年金产品\n".encode("utf-8")
            path.write_bytes(payload)

            first = fingerprint_file(path)
            second = fingerprint_file(path)

            self.assertEqual(first, second)
            self.assertEqual(first["sha256"], hashlib.sha256(payload).hexdigest())
            self.assertEqual(first["size_bytes"], len(payload))
            self.assertEqual(first["extension"], ".txt")
            self.assertEqual(first["path"], str(path.resolve()))

    def test_fingerprint_rejects_directories(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            with self.assertRaises(ValueError):
                fingerprint_file(temporary_directory)


class PrivacyAndRoutingTests(unittest.TestCase):
    def test_detects_customer_data_without_returning_values(self) -> None:
        text = (
            "投保年龄范围：0-75周岁。"
            "客户姓名：张三；身份证号：11010519491231002X；"
            "联系电话：13800138000；邮箱：zhangsan@example.com"
        )
        findings = detect_prohibited_customer_data(text)
        finding_types = {finding["type"] for finding in findings}

        self.assertIn("customer_field", finding_types)
        self.assertIn("mainland_china_id", finding_types)
        self.assertIn("mainland_china_phone", finding_types)
        self.assertIn("email_address", finding_types)
        serialized = json.dumps(findings, ensure_ascii=False)
        self.assertNotIn("张三", serialized)
        self.assertNotIn("11010519491231002X", serialized)
        self.assertNotIn("zhangsan@example.com", serialized)

    def test_product_issue_age_is_not_customer_data(self) -> None:
        self.assertEqual(detect_prohibited_customer_data("投保年龄范围：0-75周岁"), [])
        self.assertEqual(detect_prohibited_customer_data("Issue age: 0 to 75"), [])
        self.assertEqual(
            detect_prohibited_customer_data("被保险人年龄范围为 0-75 周岁"), []
        )
        self.assertEqual(
            detect_prohibited_customer_data("Insured age range is 0 to 75"), []
        )
        self.assertEqual(
            detect_prohibited_customer_data("被保险人年龄应为18至70周岁"), []
        )
        self.assertEqual(
            detect_prohibited_customer_data("若被保险人健康状况发生变化，应及时通知"),
            [],
        )
        self.assertEqual(
            detect_prohibited_customer_data("被保险人职业类别以投保时为准"), []
        )
        self.assertEqual(
            detect_prohibited_customer_data("受益人姓名和受益顺序由投保人指定"), []
        )
        self.assertTrue(detect_prohibited_customer_data("客户姓名"))

    def test_confidence_router_has_safe_precedence(self) -> None:
        self.assertEqual(
            route_confidence(0.99, True, True, True),
            "deterministic_manual_verification",
        )
        self.assertEqual(route_confidence(0.99, False, True, True), "targeted_ocr")
        self.assertEqual(
            route_confidence(0.99, False, True, False),
            "llm_semantic_resolution",
        )
        self.assertEqual(
            route_confidence(0.89, False, True, False),
            "deterministic_second_pass",
        )
        self.assertEqual(
            route_confidence(0.20, False, True, False), "manual_verification"
        )
        self.assertEqual(route_confidence(0.95, False, False, False), "direct_accept")
        self.assertEqual(
            route_confidence(0.75, False, False, False),
            "deterministic_second_pass",
        )
        self.assertEqual(
            route_confidence(0.20, False, False, False), "manual_verification"
        )

    def test_confidence_router_rejects_invalid_scores(self) -> None:
        for score in (-0.01, 1.01, float("nan"), float("inf"), "unknown"):
            with self.subTest(score=score):
                with self.assertRaises(ValueError):
                    route_confidence(score, False, False, False)  # type: ignore[arg-type]


class InspectionTests(unittest.TestCase):
    def test_csv_and_text_outputs_are_sorted_auditable_and_stable(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            csv_path = root / "b-product.csv"
            text_path = root / "a-product.txt"
            csv_path.write_text(
                "项目,第1年\n年金领取,10000\n现金价值,85000\n",
                encoding="utf-8",
            )
            text_path.write_text(
                "Guaranteed lifetime annuity\n年度保费：100000\n",
                encoding="utf-8",
            )

            first_output = root / "first-output"
            second_output = root / "second-output"
            first = inspect_inputs([csv_path, text_path], first_output)
            second = inspect_inputs([text_path, csv_path], second_output)

            expected_names = ["a-product.txt", "b-product.csv"]
            self.assertEqual(
                [entry["name"] for entry in first["manifest"]["files"]],
                expected_names,
            )
            self.assertEqual(first["manifest"], second["manifest"])
            self.assertEqual(first["extraction"], second["extraction"])
            self.assertEqual(first["review_queue"], second["review_queue"])
            self.assertFalse(first["review_queue"]["llm_called"])

            for output_name in (
                "manifest.json",
                "extraction.json",
                "review_queue.json",
            ):
                first_bytes = (first_output / output_name).read_bytes()
                second_bytes = (second_output / output_name).read_bytes()
                self.assertEqual(first_bytes, second_bytes)
                self.assertTrue(first_bytes.endswith(b"\n"))

            records = first["extraction"]["records"]
            self.assertTrue(records)
            csv_records = [
                record for record in records if record["source_name"] == csv_path.name
            ]
            self.assertTrue(
                any(record["location"].get("cell") == "A2" for record in csv_records)
            )
            self.assertTrue(
                all(len(record["raw_text_sha256"]) == 64 for record in records)
            )
            self.assertTrue(all("name" in record["extractor"] for record in records))
            self.assertTrue(all("version" in record["extractor"] for record in records))
            categories = {
                classification["category"]
                for record in records
                for classification in record["section_classifications"]
            }
            self.assertIn("annuity_cash_flow", categories)
            self.assertIn("cash_value_liquidity", categories)
            self.assertIn("premium_structure", categories)

    def test_review_queue_never_contains_probable_pii_values(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            source = root / "input.txt"
            source.write_text(
                "客户姓名：张三；身份证号：11010519491231002X；邮箱：private@example.com\n"
                "身故保险金为已交保费与现金价值取较大者。\n",
                encoding="utf-8",
            )

            result = inspect_inputs(source, root / "output")
            queue_text = (root / "output" / "review_queue.json").read_text(
                encoding="utf-8"
            )
            extraction_text = (root / "output" / "extraction.json").read_text(
                encoding="utf-8"
            )

            for prohibited_value in (
                "张三",
                "11010519491231002X",
                "private@example.com",
            ):
                self.assertNotIn(prohibited_value, queue_text)
                self.assertNotIn(prohibited_value, extraction_text)
            self.assertEqual(result["extraction"]["records"], [])
            self.assertIn(
                "[REDACTED:REJECTED_SOURCE]",
                (root / "output" / "manifest.json").read_text(),
            )

            routes = {item["route"] for item in result["review_queue"]["items"]}
            self.assertEqual(routes, {"reject_prohibited_customer_data"})
            for item in result["review_queue"]["items"]:
                if "snippet" in item:
                    self.assertEqual(item["route"], "llm_semantic_resolution")

    def test_custom_keywords_are_merged_with_annuity_defaults(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            source = root / "terms.md"
            source.write_text(
                "领取递增率 3%\nSpecial Vesting Value\n", encoding="utf-8"
            )

            result = inspect_inputs(
                source,
                root / "output",
                keywords={"custom_value": ["vesting value"]},
            )
            categories = {
                classification["category"]
                for record in result["extraction"]["records"]
                for classification in record["section_classifications"]
            }
            self.assertIn("inflation_escalation", categories)
            self.assertIn("custom_value", categories)

    def test_json_preserves_pointer_and_rejects_customer_field(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            source = root / "product.json"
            source.write_text(
                json.dumps(
                    {
                        "product": {"annuity": 12000, "customer age": 52},
                        "cash value": [80000, 90000],
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )

            result = inspect_inputs(source, root / "output")
            records = result["extraction"]["records"]
            self.assertEqual(records, [])
            self.assertEqual(
                {item["route"] for item in result["review_queue"]["items"]},
                {"reject_prohibited_customer_data"},
            )

    def test_adjacent_customer_values_are_quarantined_with_entire_source(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            source = root / "input.csv"
            source.write_text(
                "客户姓名,张三\n身份证号,11010519491231002X\n年金,10000\n",
                encoding="utf-8",
            )

            result = inspect_inputs(source, root / "output")
            artifacts = "".join(
                (root / "output" / name).read_text(encoding="utf-8")
                for name in ("manifest.json", "extraction.json", "review_queue.json")
            )

            self.assertEqual(result["extraction"]["records"], [])
            self.assertNotIn("张三", artifacts)
            self.assertNotIn("11010519491231002X", artifacts)
            self.assertEqual(
                {item["route"] for item in result["review_queue"]["items"]},
                {"reject_prohibited_customer_data"},
            )

    def test_adjacent_selected_age_and_occupation_are_quarantined(self) -> None:
        samples = (
            "客户年龄,61\n",
            "投保人职业,医生\n",
            "被保险人年龄,45\n",
        )
        for index, content in enumerate(samples):
            with self.subTest(content=content):
                with tempfile.TemporaryDirectory() as temporary_directory:
                    root = Path(temporary_directory)
                    source = root / f"input-{index}.csv"
                    source.write_text(content, encoding="utf-8")

                    result = inspect_inputs(source, root / "output")

            self.assertEqual(result["extraction"]["records"], [])
            self.assertEqual(
                {item["route"] for item in result["review_queue"]["items"]},
                {"reject_prohibited_customer_data"},
            )

    def test_json_semantic_review_retains_safe_pointer(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            source = root / "terms.json"
            source.write_text(
                json.dumps(
                    {"death_benefit": "whichever is greater: premium or cash value"}
                ),
                encoding="utf-8",
            )

            result = inspect_inputs(source, root / "output")
            item = result["review_queue"]["items"][0]

            self.assertEqual(item["route"], "llm_semantic_resolution")
            self.assertEqual(item["location"]["json_pointer"], "/death_benefit")

    @unittest.skipUnless(OPENPYXL_AVAILABLE, "openpyxl is optional")
    def test_xlsx_cells_include_sheet_and_coordinates_when_available(self) -> None:
        import openpyxl

        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            source = root / "product.xlsx"
            workbook = openpyxl.Workbook()
            sheet = workbook.active
            sheet.title = "Benefits"
            sheet["A1"] = "Guaranteed annuity"
            sheet["B2"] = 12000
            workbook.save(source)

            result = inspect_inputs(source, root / "output")
            records = result["extraction"]["records"]
            locations = [record["location"] for record in records]
            self.assertIn(
                {"cell": "A1", "column": 1, "row": 1, "sheet": "Benefits"},
                locations,
            )
            self.assertTrue(
                any(record["extractor"]["name"] == "openpyxl" for record in records)
            )

    @unittest.skipUnless(PDF_TEST_DEPS_AVAILABLE, "pdfplumber is optional")
    def test_pdf_native_words_keep_page_and_bbox_when_available(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            source = root / "product.pdf"
            _write_minimal_pdf(source, "Guaranteed annuity premium and cash value")

            result = inspect_inputs(source, root / "output")
            records = result["extraction"]["records"]
            native = [
                record for record in records if record["record_type"] == "pdf_text_line"
            ]
            self.assertTrue(native)
            self.assertEqual(native[0]["location"]["page"], 1)
            self.assertEqual(len(native[0]["location"]["bbox"]), 4)

    @unittest.skipUnless(PDF_TEST_DEPS_AVAILABLE, "pdfplumber is optional")
    def test_image_only_pdf_routes_page_targeted_ocr_when_available(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            source = root / "image-only.pdf"
            _write_minimal_pdf(source)

            result = inspect_inputs(source, root / "output")
            targeted = [
                item
                for item in result["review_queue"]["items"]
                if item["route"] == "targeted_ocr"
            ]
            self.assertTrue(targeted)
            self.assertEqual(targeted[0]["location"]["page"], 1)
            self.assertNotIn("snippet", targeted[0])


if __name__ == "__main__":
    unittest.main()
