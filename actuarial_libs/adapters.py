"""Library availability adapters with formal product analysis disabled."""

from __future__ import annotations

import importlib
from typing import Any, Dict, Optional


DEMO_ONLY_ERROR = (
    "适配器没有接入保险公司真实资产、负债、准备金或经验数据，"
    "不能据此评价单一保险产品。请改用严格comparison-case。"
)


def _demo_only_result(adapter: str) -> Dict[str, Any]:
    return {
        "status": "disabled",
        "error": DEMO_ONLY_ERROR,
        "adapter": adapter,
        "formal_analysis_supported": False,
        "evidence_quality": "synthetic_demo",
    }


class BaseAdapter:
    """Report installation status but never manufacture product metrics."""

    module_name = ""

    def __init__(self):
        self.library = None
        self.available = False
        self._check_availability()

    def _check_availability(self) -> None:
        if not self.module_name:
            return
        try:
            self.library = importlib.import_module(self.module_name)
            self.available = True
        except (ImportError, OSError):
            self.library = None
            self.available = False

    def analyze(self, product_spec) -> Dict[str, Any]:
        del product_spec
        return _demo_only_result(self.__class__.__name__)

    def is_available(self) -> bool:
        return self.available

    def get_version(self) -> Optional[str]:
        if self.library is None:
            return None
        return str(getattr(self.library, "__version__", "unknown"))

    def initialize(self) -> None:
        self._check_availability()


class ChainladderAdapter(BaseAdapter):
    module_name = "chainladder"

    def analyze_reserve_adequacy(self, triangles_data) -> Dict[str, Any]:
        del triangles_data
        return _demo_only_result(self.__class__.__name__)


class LifelibAdapter(BaseAdapter):
    module_name = "lifelib"

    def get_mortality_table(self, table_name: str = "CL2020_Male"):
        del table_name
        return None


class CashflowerAdapter(BaseAdapter):
    module_name = "cashflower"


class AggregateAdapter(BaseAdapter):
    module_name = "aggregate"


class ModelxAdapter(BaseAdapter):
    module_name = "modelx"


class InsuranceratingAdapter(BaseAdapter):
    module_name = "insurancerating"


class JuliaActuaryAdapter(BaseAdapter):
    module_name = "julia"


def get_adapter(name: str) -> Optional[BaseAdapter]:
    adapters = {
        "chainladder": ChainladderAdapter,
        "lifelib": LifelibAdapter,
        "cashflower": CashflowerAdapter,
        "aggregate": AggregateAdapter,
        "modelx": ModelxAdapter,
        "insurancerating": InsuranceratingAdapter,
        "julia_actuary": JuliaActuaryAdapter,
    }
    adapter_class = adapters.get(name)
    return adapter_class() if adapter_class else None
