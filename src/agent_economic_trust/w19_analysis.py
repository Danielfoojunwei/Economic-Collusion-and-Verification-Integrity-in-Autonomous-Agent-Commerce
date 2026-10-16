"""Prospective pair-cluster factorial contrasts for W19.

This module contains no experimental observations. The assigned economic pair
is the unit of randomization; multiple tasks from one pair are never treated
as independent replicates. Native evidence must be verified before a caller
constructs PairOutcome rows.
"""

from __future__ import annotations

from dataclasses import dataclass
from math import erfc, sqrt
from random import Random
from typing import Iterable


CELLS = tuple(f"{r}{s}{p}" for r in (0, 1) for s in (0, 1) for p in (0, 1))


@dataclass(frozen=True)
class PairOutcome:
    pair_id: str
    block: str  # frozen model version × task family × oracle truth
    truth: int
    cell: str
    scheduled: int
    wrong_paid: int
    wrong_paid_unknown: int
    checked: int
    checked_unknown: int

    def __post_init__(self) -> None:
        if not self.pair_id or not self.block or self.cell not in CELLS:
            raise ValueError("pair, block and factorial cell are required")
        if type(self.truth) is not int or self.truth not in (0, 1):
            raise ValueError("truth must be a sealed binary oracle label")
        if type(self.scheduled) is not int or self.scheduled < 1:
            raise ValueError("scheduled tasks must be positive")
        for name in ("wrong_paid", "wrong_paid_unknown", "checked", "checked_unknown"):
            value = getattr(self, name)
            if type(value) is not int or value < 0:
                raise ValueError(f"{name} must be a nonnegative integer")
        if self.checked + self.checked_unknown > self.scheduled:
            raise ValueError("check outcomes exceed scheduled tasks")
        if self.truth == 0:
            if self.wrong_paid + self.wrong_paid_unknown > self.scheduled:
                raise ValueError("wrong-payment outcomes exceed scheduled bad tasks")
        elif self.wrong_paid or self.wrong_paid_unknown:
            raise ValueError("wrong payment is only defined for bad tasks")


def _selected(rows: Iterable[PairOutcome], outcome: str) -> list[PairOutcome]:
    if outcome not in ("wrong_paid", "checked"):
        raise ValueError("unknown outcome")
    selected = [row for row in rows if outcome != "wrong_paid" or row.truth == 0]
    if not selected:
        raise ValueError("no assigned rows for outcome")
    pairs: set[str] = set()
    block_truth: dict[str, int] = {}
    counts: dict[str, dict[str, int]] = {}
    sizes: dict[str, set[int]] = {}
    for row in selected:
        if row.pair_id in pairs:
            raise ValueError("pair appears more than once; aggregate its tasks first")
        pairs.add(row.pair_id)
        if row.block in block_truth and block_truth[row.block] != row.truth:
            raise ValueError("block mixes good and bad oracle truth")
        block_truth[row.block] = row.truth
        counts.setdefault(row.block, {}).setdefault(row.cell, 0)
        counts[row.block][row.cell] += 1
        sizes.setdefault(row.block, set()).add(row.scheduled)
    if any(set(cell_counts) != set(CELLS) or len(set(cell_counts.values())) != 1
           for cell_counts in counts.values()):
        raise ValueError("each block requires balanced assignments to all eight cells")
    if any(len(block_sizes) != 1 for block_sizes in sizes.values()):
        raise ValueError("task count per pair must be fixed within each block")
    return selected


def _weights(outcome: str, factor: str) -> dict[str, float]:
    if (outcome, factor) not in (("wrong_paid", "R"), ("checked", "S")):
        raise ValueError("only prespecified R→wrong payment and S→check contrasts")
    index = 0 if factor == "R" else 1
    return {cell: (0.25 if cell[index] == "1" else -0.25) for cell in CELLS}


def _estimate(selected: list[PairOutcome], outcome: str, factor: str,
              *, fill_unknown: int) -> tuple[float, float]:
    weights = _weights(outcome, factor)
    blocks = sorted({row.block for row in selected})
    value = 0.0
    variance = 0.0
    for block in blocks:
        for cell in CELLS:
            pair_values = [
                (getattr(row, outcome) + fill_unknown * getattr(row, outcome + "_unknown"))
                / row.scheduled
                for row in selected if row.block == block and row.cell == cell
            ]
            n = len(pair_values)
            mean = sum(pair_values) / n
            weight = weights[cell] / len(blocks)
            value += weight * mean
            if n > 1:
                sample_variance = sum((v - mean) ** 2 for v in pair_values) / (n - 1)
                variance += weight * weight * sample_variance / n
    return value, variance


def contrast(rows: Iterable[PairOutcome], outcome: str, factor: str) -> dict:
    """Equal-block ITT risk difference and worst-case missingness bounds.

    A point estimate/SE is returned only when every scheduled outcome is
    independently resolved. The SE uses pair-level sample variance, so it
    never counts repeated tasks as independent units.
    """
    selected = _selected(rows, outcome)
    _weights(outcome, factor)
    unknown = sum(getattr(row, outcome + "_unknown") for row in selected)
    # A contrast has positive and negative weights: filling all unknowns the
    # same way does not yield its sharp componentwise lower/upper bounds.
    weights = _weights(outcome, factor)
    blocks = sorted({row.block for row in selected})
    lo = hi = 0.0
    for block in blocks:
        for cell in CELLS:
            cluster = [row for row in selected if row.block == block and row.cell == cell]
            lower = sum(getattr(row, outcome) / row.scheduled for row in cluster) / len(cluster)
            upper = sum((getattr(row, outcome) + getattr(row, outcome + "_unknown"))
                        / row.scheduled for row in cluster) / len(cluster)
            weight = weights[cell] / len(blocks)
            lo += weight * (lower if weight > 0 else upper)
            hi += weight * (upper if weight > 0 else lower)
    result = {
        "outcome": outcome, "factor": factor,
        "assigned_pairs": len(selected),
        "assigned_tasks": sum(row.scheduled for row in selected),
        "unresolved_tasks": unknown,
        "itt_risk_difference_bounds": [round(lo, 12), round(hi, 12)],
        "estimate": None, "cluster_standard_error": None,
    }
    if unknown == 0:
        point, variance = _estimate(selected, outcome, factor, fill_unknown=0)
        result["estimate"] = point
        result["cluster_standard_error"] = sqrt(variance)
    return result


def blocked_randomization_pvalue(
    rows: Iterable[PairOutcome], outcome: str, factor: str,
    *, permutations: int = 9999, seed: int = 1,
) -> float:
    """Two-sided Fisher sharp-null test, reassigning entire pairs within blocks.

    This is for fully resolved confirmatory rows only. Its null is the sharp
    zero-effect null, while the reported estimand is an average risk difference.
    """
    selected = _selected(rows, outcome)
    if any(getattr(row, outcome + "_unknown") for row in selected):
        raise ValueError("unresolved ITT outcomes prohibit a point-null test")
    if permutations < 1:
        raise ValueError("permutations must be positive")
    weights = _weights(outcome, factor)
    rng = Random(seed)
    blocks = sorted({row.block for row in selected})
    data = []
    for block in blocks:
        cluster = sorted((row for row in selected if row.block == block),
                         key=lambda row: row.pair_id)
        labels = [row.cell for row in cluster]
        values = [getattr(row, outcome) / row.scheduled for row in cluster]
        data.append((labels, values))

    def statistic(shuffle: bool) -> float:
        effect = 0.0
        for labels, values in data:
            assigned = labels.copy()
            if shuffle:
                rng.shuffle(assigned)
            count = len(assigned) // len(CELLS)
            effect += sum(weights[cell] * value / count
                          for cell, value in zip(assigned, values)) / len(data)
        return effect

    observed = abs(statistic(False))
    hits = sum(abs(statistic(True)) >= observed - 1e-12
               for _ in range(permutations))
    return (hits + 1) / (permutations + 1)


def pair_bootstrap_interval(
    rows: Iterable[PairOutcome], outcome: str, factor: str,
    *, replicates: int = 9999, seed: int = 2,
) -> tuple[float, float]:
    """Percentile 95% CI, resampling entire pairs within frozen block × arm."""
    selected = _selected(rows, outcome)
    if any(getattr(row, outcome + "_unknown") for row in selected):
        raise ValueError("unresolved ITT outcomes prohibit a point interval")
    if replicates < 1:
        raise ValueError("replicates must be positive")
    weights = _weights(outcome, factor)
    blocks = sorted({row.block for row in selected})
    values = {
        (block, cell): [getattr(row, outcome) / row.scheduled for row in selected
                        if row.block == block and row.cell == cell]
        for block in blocks for cell in CELLS
    }
    rng = Random(seed)
    estimates = []
    for _ in range(replicates):
        estimate = 0.0
        for block in blocks:
            for cell in CELLS:
                cluster = values[(block, cell)]
                mean = sum(rng.choice(cluster) for _ in cluster) / len(cluster)
                estimate += weights[cell] * mean / len(blocks)
        estimates.append(estimate)
    estimates.sort()

    def quantile(probability: float) -> float:
        rank = probability * (len(estimates) - 1)
        lower = int(rank)
        fraction = rank - lower
        return estimates[lower] * (1 - fraction) + estimates[min(lower + 1, len(estimates) - 1)] * fraction

    return quantile(0.025), quantile(0.975)


def holm_two(p_first: float, p_second: float, alpha: float = 0.05) -> dict:
    """Family-wise decisions for the two prespecified confirmatory contrasts."""
    if any(not 0 <= p <= 1 for p in (p_first, p_second)) or not 0 < alpha < 1:
        raise ValueError("p-values and alpha must be probabilities")
    ordered = sorted((("R_wrong_paid", p_first), ("S_check", p_second)),
                     key=lambda item: item[1])
    rejected = {"R_wrong_paid": False, "S_check": False}
    if ordered[0][1] <= alpha / 2:
        rejected[ordered[0][0]] = True
        if ordered[1][1] <= alpha:
            rejected[ordered[1][0]] = True
    return rejected


def cluster_wald_pvalue(estimate: float, standard_error: float) -> float:
    """Approximate only: used in prospective power simulations, not final tests."""
    if standard_error <= 0:
        # A zero estimated variance in a rare binary outcome is not evidence
        # of arbitrarily high precision. The final test uses permutation.
        return 1.0
    return erfc(abs(estimate) / (sqrt(2) * standard_error))
