"""Dependency-free IRR and XIRR solvers with explicit ambiguity handling."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal
import math
from typing import Callable, Iterable, List, Optional, Sequence, Tuple


@dataclass(frozen=True)
class RootResult:
    """A serializable root-solver outcome."""

    rate: Optional[float]
    status: str
    reason: Optional[str]
    method: str
    root_count: int = 0

    def to_dict(self) -> dict:
        value = None
        if self.rate is not None:
            value = round(self.rate, 12)
            nearest_integer = round(value)
            if abs(value - nearest_integer) <= 1e-10:
                value = float(nearest_integer)
        return {
            "value": value,
            "status": self.status,
            "reason": self.reason,
            "method": self.method,
            "root_count": self.root_count,
        }


def _aggregate(
    cashflows: Iterable[Tuple[float, Decimal]],
) -> List[Tuple[float, Decimal]]:
    totals = {}
    for timing, amount in cashflows:
        key = round(float(timing), 12)
        totals[key] = totals.get(key, Decimal("0")) + Decimal(amount)
    return sorted((timing, amount) for timing, amount in totals.items() if amount != 0)


def _sign_changes(amounts: Sequence[Decimal]) -> int:
    signs = [1 if value > 0 else -1 for value in amounts if value != 0]
    return sum(left != right for left, right in zip(signs, signs[1:]))


def _safe_npv(function: Callable[[float], float], x_value: float) -> float:
    try:
        value = function(x_value)
    except (OverflowError, ZeroDivisionError, ValueError):
        return math.nan
    return value if math.isfinite(value) else math.nan


def _bisect(function: Callable[[float], float], left: float, right: float) -> float:
    f_left = _safe_npv(function, left)
    for _ in range(240):
        middle = (left + right) / 2.0
        f_middle = _safe_npv(function, middle)
        if math.isnan(f_middle):
            left = middle
            continue
        if abs(f_middle) <= 1e-12 or abs(right - left) <= 1e-12:
            return middle
        if (f_left < 0) == (f_middle < 0):
            left, f_left = middle, f_middle
        else:
            right = middle
    return (left + right) / 2.0


def _solve(cashflows: Sequence[Tuple[float, Decimal]], method: str) -> RootResult:
    ordered = _aggregate(cashflows)
    if len(ordered) < 2:
        return RootResult(None, "not_computable", "insufficient_cashflows", method)
    amounts = [amount for _, amount in ordered]
    if not any(value < 0 for value in amounts) or not any(
        value > 0 for value in amounts
    ):
        return RootResult(None, "not_computable", "cashflows_need_both_signs", method)

    # Solve in x = log(1 + r). This covers rates close to -100% and very
    # large positive rates without an unstable hand-picked linear grid.
    def npv_x(x_value: float) -> float:
        total = 0.0
        for timing, amount in ordered:
            total += float(amount) * math.exp(-x_value * timing)
        return total

    x_min = math.log(1e-6)
    x_max = math.log(1_000_001.0)
    samples = 1600
    roots: List[float] = []
    previous_x = x_min
    previous_y = _safe_npv(npv_x, previous_x)
    for index in range(1, samples + 1):
        current_x = x_min + (x_max - x_min) * index / samples
        current_y = _safe_npv(npv_x, current_x)
        if not math.isnan(previous_y) and not math.isnan(current_y):
            if current_y == 0.0:
                roots.append(current_x)
            elif previous_y == 0.0:
                roots.append(previous_x)
            elif (previous_y < 0) != (current_y < 0):
                roots.append(_bisect(npv_x, previous_x, current_x))
        previous_x, previous_y = current_x, current_y

    deduplicated: List[float] = []
    for root in roots:
        rate = math.exp(root) - 1.0
        if not any(
            abs(rate - existing) <= 1e-8 * max(1.0, abs(existing))
            for existing in deduplicated
        ):
            deduplicated.append(rate)

    if not deduplicated:
        return RootResult(None, "not_computable", "no_root_in_supported_range", method)
    if len(deduplicated) > 1 or _sign_changes(amounts) > 1:
        # Multiple sign changes do not prove multiple roots, but they do make
        # an automatically selected economic return unsafe to report.
        return RootResult(
            None, "ambiguous", "multiple_irr_possible", method, len(deduplicated)
        )
    return RootResult(deduplicated[0], "ok", None, method, 1)


def irr(cashflows: Sequence[Tuple[float, Decimal]]) -> RootResult:
    """Return annual effective IRR using explicit year offsets."""

    if not cashflows:
        return RootResult(
            None, "not_computable", "insufficient_cashflows", "periodic_irr"
        )
    first_time = min(timing for timing, _ in cashflows)
    shifted = [(timing - first_time, amount) for timing, amount in cashflows]
    return _solve(shifted, "periodic_irr")


def xirr(cashflows: Sequence[Tuple[date, Decimal]]) -> RootResult:
    """Return ACT/365F annual effective XIRR from explicit calendar dates."""

    if not cashflows:
        return RootResult(
            None, "not_computable", "insufficient_cashflows", "xirr_act_365f"
        )
    first_date = min(flow_date for flow_date, _ in cashflows)
    timed = [
        ((flow_date - first_date).days / 365.0, amount)
        for flow_date, amount in cashflows
    ]
    return _solve(timed, "xirr_act_365f")
