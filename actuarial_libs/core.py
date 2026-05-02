"""
精算库集成核心引擎
Core Integration Engine for Actuarial Libraries
"""

import importlib
import warnings
from typing import Dict, List, Optional, Any
from dataclasses import dataclass


@dataclass
class LibraryStatus:
    """库状态信息"""
    name: str
    installed: bool
    version: Optional[str] = None
    error: Optional[str] = None

    def __str__(self):
        status = "✅" if self.installed else "❌"
        version = f" v{self.version}" if self.version else ""
        error = f" ({self.error})" if self.error else ""
        return f"{status} {self.name}{version}{error}"


class ActuarialLibraryManager:
    """精算库管理器 - 统一管理所有集成的库"""

    def __init__(self):
        self.libraries: Dict[str, Any] = {}
        self.adapters: Dict[str, Any] = {}
        self.status: Dict[str, LibraryStatus] = {}

        # 自动发现和初始化适配器
        self._initialize_adapters()

    def _initialize_adapters(self):
        """初始化所有适配器"""
        from .adapters import (
            ChainladderAdapter,
            LifelibAdapter,
            CashflowerAdapter,
            AggregateAdapter,
            ModelxAdapter,
            InsuranceratingAdapter,
            JuliaActuaryAdapter
        )

        adapters = [
            ('chainladder', ChainladderAdapter),
            ('lifelib', LifelibAdapter),
            ('cashflower', CashflowerAdapter),
            ('aggregate', AggregateAdapter),
            ('modelx', ModelxAdapter),
            ('insurancerating', InsuranceratingAdapter),
            ('julia_actuary', JuliaActuaryAdapter)
        ]

        for name, adapter_class in adapters:
            try:
                adapter = adapter_class()
                self.adapters[name] = adapter
                self.status[name] = LibraryStatus(
                    name=name,
                    installed=adapter.is_available(),
                    version=adapter.get_version() if adapter.is_available() else None
                )
            except Exception as e:
                self.status[name] = LibraryStatus(
                    name=name,
                    installed=False,
                    error=str(e)
                )

    def check_all(self) -> Dict[str, LibraryStatus]:
        """检查所有库的安装状态"""
        return self.status

    def get_adapter(self, name: str):
        """获取指定适配器"""
        return self.adapters.get(name)

    def is_available(self, name: str) -> bool:
        """检查指定库是否可用"""
        return self.status.get(name, LibraryStatus(name=name, installed=False)).installed

    def get_available_libraries(self) -> List[str]:
        """获取所有可用的库名称"""
        return [name for name, status in self.status.items() if status.installed]

    def get_missing_libraries(self) -> List[str]:
        """获取所有缺失的库名称"""
        return [name for name, status in self.status.items() if not status.installed]

    def print_status(self):
        """打印所有库的状态"""
        print("="*60)
        print("精算库集成状态")
        print("Actuarial Libraries Integration Status")
        print("="*60)
        print()

        for name, status in self.status.items():
            print(status)

        print()
        installed_count = len(self.get_available_libraries())
        total_count = len(self.status)
        print(f"已安装: {installed_count}/{total_count}")

        if installed_count < total_count:
            missing = self.get_missing_libraries()
            print(f"未安装: {', '.join(missing)}")
            print()
            print("提示：运行 ./install_dependencies.sh 安装缺失的库")

    def enable_library(self, name: str) -> bool:
        """动态启用库"""
        adapter = self.adapters.get(name)
        if adapter and not adapter.is_available():
            try:
                adapter.initialize()
                self.status[name].installed = adapter.is_available()
                self.status[name].version = adapter.get_version()
                return True
            except Exception as e:
                self.status[name].error = str(e)
                return False
        return False

    def analyze_with_available_libs(self, product_spec):
        """使用所有可用库进行分析"""
        results = {
            'basic': {},
            'enhanced': {},
            'available_libs': self.get_available_libraries()
        }

        # 基础分析（使用你现有的代码）
        from actuarial_calculator import irr_scenario_analysis

        try:
            basic_irr = irr_scenario_analysis(product_spec)
            results['basic']['irr_scenarios'] = basic_irr
        except Exception as e:
            results['basic']['error'] = str(e)

        # 增强分析（使用各个库）
        for name in self.get_available_libraries():
            adapter = self.adapters.get(name)
            if adapter:
                try:
                    lib_results = adapter.analyze(product_spec)
                    if lib_results:
                        results['enhanced'][name] = lib_results
                except Exception as e:
                    results['enhanced'][name] = {'error': str(e)}

        return results

    def get_integration_report(self) -> Dict[str, Any]:
        """生成集成报告"""
        available = self.get_available_libraries()
        missing = self.get_missing_libraries()

        # 功能覆盖分析
        capabilities = {
            'chainladder': '准备金分析、偿付能力评估',
            'lifelib': '完整生命表、精确定价',
            'cashflower': '现金流建模、ALM分析',
            'aggregate': '极端风险、聚合损失',
            'modelx': '复杂产品建模',
            'insurancerating': '费率厘定、公平性分析',
            'julia_actuary': '高精度精算计算'
        }

        available_capabilities = {k: capabilities[k] for k in available}
        missing_capabilities = {k: capabilities[k] for k in missing}

        return {
            'total_libraries': len(self.status),
            'available_count': len(available),
            'missing_count': len(missing),
            'available_libraries': available,
            'missing_libraries': missing,
            'available_capabilities': available_capabilities,
            'missing_capabilities': missing_capabilities,
            'integration_rate': len(available) / len(self.status) * 100
        }


# 单例模式
_manager_instance = None

def get_manager():
    """获取管理器单例"""
    global _manager_instance
    if _manager_instance is None:
        _manager_instance = ActuarialLibraryManager()
    return _manager_instance
