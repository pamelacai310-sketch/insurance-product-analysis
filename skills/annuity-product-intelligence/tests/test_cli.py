from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path


SCRIPTS_DIR = Path(__file__).resolve().parents[1] / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

from annuity_intelligence.cli import _validate_benchmark, run_pipeline  # noqa: E402
from annuity_intelligence.common import (  # noqa: E402
    ProhibitedCustomerDataError,
    ReviewRequiredError,
    ValidationError,
)
from test_core import make_product  # noqa: E402


def benchmark() -> dict:
    return {
        "schema_version": "1.0.0",
        "benchmark_id": "synthetic-curve",
        "currency": "CNY",
        "as_of_date": "2026-08-22",
        "compounding": "annual_effective",
        "day_count": "ACT/365",
        "source_sha256": "1" * 64,
        "points": [{"term_years": "10", "annual_effective_rate": "0.02"}],
    }


class PipelineGateTests(unittest.TestCase):
    def test_report_without_benchmark_renders_missing_relative_value(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            input_path = root / "product.json"
            output = root / "result"
            input_path.write_text(json.dumps(make_product()), encoding="utf-8")

            result = run_pipeline(
                input_path,
                output,
                allow_embedded_fixtures=True,
            )

            self.assertIn("未提供版本化基准", result["report"])

    def test_unresolved_input_writes_typed_block_queue_and_no_metrics(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            input_path = root / "product.json"
            output = root / "result"
            data = make_product()
            data["evidence"][0]["status"] = "unresolved"
            input_path.write_text(json.dumps(data), encoding="utf-8")

            with self.assertRaises(ReviewRequiredError):
                run_pipeline(input_path, output, allow_embedded_fixtures=True)

            queue = json.loads(
                (output / "review_queue.json").read_text(encoding="utf-8")
            )
            self.assertEqual(
                {item["route"] for item in queue["items"]}, {"unresolved_input_block"}
            )
            self.assertFalse(queue["llm_called"])
            self.assertFalse((output / "metrics.json").exists())

    def test_report_is_standalone_and_artifact_chain_is_hashed(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            input_path = root / "product.json"
            benchmark_path = root / "benchmark.json"
            output = root / "result"
            input_path.write_text(json.dumps(make_product()), encoding="utf-8")
            benchmark_path.write_text(json.dumps(benchmark()), encoding="utf-8")

            result = run_pipeline(
                input_path,
                output,
                benchmark_path,
                allow_embedded_fixtures=True,
            )

            report = result["report"]
            self.assertIn("合同现金流结构", report)
            self.assertIn("通胀压力情景", report)
            self.assertIn("无风险基准相对价值", report)
            self.assertIn("`ev1`（第 1 页", report)
            self.assertNotIn("Decimal(", report)
            chain = result["provenance"]["artifact_chain"]
            self.assertTrue(
                all(len(value) == 64 for value in chain.values() if value is not None)
            )


class BenchmarkGateTests(unittest.TestCase):
    def test_benchmark_schema_is_closed_and_customer_data_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            path = Path(temporary_directory) / "benchmark.json"
            path.write_text("{}", encoding="utf-8")
            extra = {**benchmark(), "extra": True}
            with self.assertRaises(ValidationError):
                _validate_benchmark(extra, path)
            nonfinite = benchmark()
            nonfinite["points"][0]["annual_effective_rate"] = "Infinity"
            with self.assertRaises(ValidationError):
                _validate_benchmark(nonfinite, path)
            private = {**benchmark(), "customer_name": "张三"}
            with self.assertRaises(ProhibitedCustomerDataError):
                _validate_benchmark(private, path)


if __name__ == "__main__":
    unittest.main()
