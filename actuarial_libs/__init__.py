"""
保险精算库集成系统
Actuarial Libraries Integration System

提供统一的接口访问所有集成的精算开源库
"""

from .core import ActuarialLibraryManager, get_manager
from .adapters import (
    ChainladderAdapter,
    LifelibAdapter,
    CashflowerAdapter,
    AggregateAdapter,
    ModelxAdapter,
    InsuranceratingAdapter,
    JuliaActuaryAdapter
)

__version__ = "1.0.0"
__all__ = [
    'ActuarialLibraryManager',
    'get_manager',
    'ChainladderAdapter',
    'LifelibAdapter',
    'CashflowerAdapter',
    'AggregateAdapter',
    'ModelxAdapter',
    'InsuranceratingAdapter',
    'JuliaActuaryAdapter'
]
