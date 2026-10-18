"""Prespecified Paper A arithmetic; tests use synthetic rows only.

The filename denotes the intended analysis interface. The study protocol is
DRAFT and no confirmatory result may be produced until assignment is frozen.
"""
from __future__ import annotations

from collections import defaultdict
from math import erfc, sqrt
from typing import Mapping, Sequence, Any


A1_B_WEIGHTS = {f"{b}{c}{v}": (0.25 if b else -0.25)
                for b in (0, 1) for c in (0, 1) for v in (0, 1)}
A1_BC_WEIGHTS = {f"{b}{c}{v}": (0.5 if b == c else -0.5)
                 for b in (0, 1) for c in (0, 1) for v in (0, 1)}
A2_BI_WEIGHTS = {"00": 1.0, "01": -1.0, "10": -1.0, "11": 1.0}


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


def assigned_wald(rows: Sequence[Mapping[str, Any]],
                  weights: Mapping[str, float]) -> dict[str, Any]:
    """Equal-stratum ITT contrast and conservative missing-outcome bounds.

    Each row is one independent assigned BAD obligation with id, stratum,
    factorial cell, and event in {True, False, None}. The standard error is
    Neyman's sum of cell sample variances, not a finite-sample exact test.
    Its normal p-value assumes sufficiently large independent cells and fixed
    strata. A zero estimated variance yields no p-value.
    """
    if not rows or not weights or sum(weights.values()) != 0:
        raise ValueError("nonempty zero-sum contrast and assignments required")
    for cell, weight in weights.items():
        if not isinstance(cell, str) or type(weight) not in (int, float):
            raise ValueError("invalid factorial contrast")
    grouped: dict[str, dict[str, list[bool | None]]] = defaultdict(lambda: defaultdict(list))
    seen: set[str] = set()
    for row in rows:
        identity, stratum, cell, event = (row.get("episode_id"), row.get("stratum"),
                                           row.get("cell"), row.get("event"))
        if (not isinstance(identity, str) or not identity or identity in seen or
                not isinstance(stratum, str) or not stratum or cell not in weights or
                row.get("truth") != "BAD" or
                not (type(event) is bool or event is None)):
            raise ValueError("invalid or duplicate assigned outcome")
        seen.add(identity)
        grouped[stratum][cell].append(event)
    strata = sorted(grouped)
    for stratum in strata:
        cells = grouped[stratum]
        if set(cells) != set(weights) or len({len(values) for values in cells.values()}) != 1:
            raise ValueError("each stratum needs balanced complete assigned cells")
    lo = hi = point = variance = 0.0
    unresolved = 0
    for stratum in strata:
        for cell, weight in weights.items():
            values = grouped[stratum][cell]
            n = len(values)
            y = sum(value is True for value in values)
            missing = sum(value is None for value in values)
            unresolved += missing
            low, high = assigned_bounds(n, y, missing)
            scaled = weight / len(strata)
            lo += scaled * (low if scaled > 0 else high)
            hi += scaled * (high if scaled > 0 else low)
            if missing == 0:
                mean = y / n
                point += scaled * mean
                if n > 1:
                    sample_variance = sum((int(value) - mean) ** 2 for value in values) / (n - 1)
                    variance += scaled * scaled * sample_variance / n
    result = {"assigned": len(rows), "unresolved": unresolved,
              "risk_difference_bounds": [lo, hi], "estimate": None,
              "standard_error": None, "normal_p_two_sided": None,
              "normal_95_interval": None,
              "inference_assumptions": "independent assigned obligations, fixed strata, large balanced cells; weak-null asymptotic Wald"}
    if unresolved == 0:
        result["estimate"] = point
        result["standard_error"] = sqrt(variance)
        if variance > 0:
            se = sqrt(variance)
            result["normal_p_two_sided"] = erfc(abs(point / se) / sqrt(2))
            result["normal_95_interval"] = [point - 1.95996398454 * se,
                                             point + 1.95996398454 * se]
    return result


def holm_adjust(pvalues: Mapping[str, float]) -> dict[str, float]:
    """Control family-wise error for the named, jointly frozen test family."""
    if not pvalues or any(not isinstance(name, str) or not name or
                          type(p) not in (int, float) or not 0 <= p <= 1
                          for name, p in pvalues.items()):
        raise ValueError("valid named p-values required")
    ordered = sorted(pvalues.items(), key=lambda item: (item[1], item[0]))
    adjusted: dict[str, float] = {}
    floor = 0.0
    for rank, (name, p) in enumerate(ordered):
        floor = max(floor, min(1.0, (len(ordered) - rank) * p))
        adjusted[name] = floor
    return adjusted
