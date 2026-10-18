"""Prespecified Paper A arithmetic; tests use synthetic rows only.

The filename denotes the intended analysis interface. The study protocol is
DRAFT and no confirmatory result may be produced until assignment is frozen.
"""
from __future__ import annotations

from typing import Mapping


def assigned_bounds(assigned: int, observed_positive: int, unknown: int) -> tuple[float, float]:
    """Finite-assignment event-rate bounds; not superpopulation intervals."""
    if any(type(v) is not int for v in (assigned, observed_positive, unknown)):
        raise ValueError("counts must be integers")
    if assigned <= 0 or min(observed_positive, unknown) < 0 or observed_positive + unknown > assigned:
        raise ValueError("impossible assigned outcome counts")
    return observed_positive / assigned, (observed_positive + unknown) / assigned


def risk_difference_bounds(treatment: tuple[int, int, int],
                           control: tuple[int, int, int]) -> tuple[float, float]:
    t_low, t_high = assigned_bounds(*treatment)
    c_low, c_high = assigned_bounds(*control)
    return t_low - c_high, t_high - c_low


def factorial_contrasts(means: Mapping[str, float]) -> dict[str, float]:
    """Equal-cell A1 contrasts in B,C,Vc order, conditional on resolved means."""
    cells = {f"{b}{c}{v}" for b in (0, 1) for c in (0, 1) for v in (0, 1)}
    if set(means) != cells or any(type(x) not in (int, float) or not 0 <= x <= 1
                                  for x in means.values()):
        raise ValueError("all eight valid BAD-arm means are required")
    tau_b = sum(means[f"1{c}{v}"] - means[f"0{c}{v}"]
                for c in (0, 1) for v in (0, 1)) / 4
    tau_bc = sum((means[f"11{v}"] - means[f"10{v}"])
                 - (means[f"01{v}"] - means[f"00{v}"]) for v in (0, 1)) / 2
    return {"tau_B": tau_b, "tau_BC": tau_bc}
