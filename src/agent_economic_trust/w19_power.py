"""Scenario power from a later randomized, real-model G4 pilot.

No observations or effect sizes from legacy scripted traces are embedded here.
The caller must independently verify the pilot provenance and evidence links;
the input metadata alone cannot authenticate a claimed real run.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from math import isfinite
from random import Random
import re
from typing import Any, Mapping

from .w19_analysis import CELLS, PairOutcome, cluster_wald_pvalue, contrast, holm_two


_HASH = re.compile(r"[0-9a-f]{64}\Z")
_REAL_TIERS = {"REAL_LLM_LOCAL", "REAL_LLM_REMOTE_APPROVED"}


@dataclass(frozen=True)
class PilotCalibration:
    source_run_sha256: str
    cells: Mapping[str, Mapping[str, int]]
    max_observed_task_cost_usd: Decimal

    @classmethod
    def parse(cls, raw: Mapping[str, Any]) -> "PilotCalibration":
        if raw.get("schema") != "w19-real-g4-pilot-v1" \
                or raw.get("source_gate") != "G4" \
                or raw.get("randomized") is not True \
                or raw.get("model_tier") not in _REAL_TIERS \
                or raw.get("payment_tier") != "NATIVE_LOCAL_PROTOCOL" \
                or not isinstance(raw.get("source_run_sha256"), str) \
                or not _HASH.fullmatch(raw["source_run_sha256"]):
            raise ValueError("a provenance-linked randomized real G4 pilot is required")
        cells = raw.get("cells")
        if not isinstance(cells, dict) or set(cells) != set(CELLS):
            raise ValueError("pilot must include all eight assigned arms")
        fields = ("bad_assigned", "bad_wrong_paid", "bad_unresolved",
                  "all_assigned", "checked", "check_unresolved")
        for name, row in cells.items():
            if not isinstance(row, dict) or any(
                field not in row or type(row[field]) is not int or row[field] < 0
                for field in fields
            ):
                raise ValueError(f"invalid pilot counts for cell {name}")
            if row["bad_assigned"] < 2 or row["all_assigned"] < 4 \
                    or row["bad_assigned"] > row["all_assigned"] \
                    or row["bad_wrong_paid"] + row["bad_unresolved"] > row["bad_assigned"] \
                    or row["checked"] + row["check_unresolved"] > row["all_assigned"]:
                raise ValueError(f"pilot is too small or inconsistent in cell {name}")
        try:
            cost = Decimal(str(raw["max_observed_task_cost_usd"]))
        except (KeyError, InvalidOperation):
            raise ValueError("pilot task cost is required") from None
        if not cost.is_finite() or cost <= 0:
            raise ValueError("pilot task cost must be positive and finite")
        return cls(raw["source_run_sha256"], cells, cost)

    def scenario_rates(self, *, unresolved_as_event: bool) -> tuple[dict, dict]:
        """Jeffreys-smoothed pooled baselines with missing-outcome sensitivity."""
        wp: dict[str, float] = {}
        check: dict[str, float] = {}
        fill = int(unresolved_as_event)
        for s in "01":
            for p in "01":
                rows = [self.cells[f"{r}{s}{p}"] for r in "01"]
                events = sum(row["bad_wrong_paid"] + fill * row["bad_unresolved"]
                             for row in rows)
                assigned = sum(row["bad_assigned"] for row in rows)
                wp[s + p] = (events + 0.5) / (assigned + 1)
        for r in "01":
            for p in "01":
                rows = [self.cells[f"{r}{s}{p}"] for s in "01"]
                events = sum(row["checked"] + fill * row["check_unresolved"]
                             for row in rows)
                assigned = sum(row["all_assigned"] for row in rows)
                check[r + p] = (events + 0.5) / (assigned + 1)
        return wp, check


def _draw_rate(rng: Random, probability: float, rho: float, tasks: int) -> int:
    if rho:
        concentration = 1 / rho - 1
        probability = rng.betavariate(
            probability * concentration, (1 - probability) * concentration)
    return sum(rng.random() < probability for _ in range(tasks))


def _simulate_once(
    rng: Random, wp: Mapping[str, float], check: Mapping[str, float],
    *, pairs_per_cell_truth_block: int, tasks_per_pair: int,
    task_families: int, model_versions: int, rho: float,
    wrong_pay_effect: float, check_effect: float,
) -> tuple[float, float]:
    rows: list[PairOutcome] = []
    for model in range(model_versions):
        for family in range(task_families):
            for truth in (0, 1):
                block = f"model-{model}|family-{family}|truth-{truth}"
                for cell in CELLS:
                    r, s, p = cell
                    prob_wp = wp[s + p] + (wrong_pay_effect if r == "1" else 0)
                    prob_q = check[r + p] + (check_effect if s == "1" else 0)
                    for pair in range(pairs_per_cell_truth_block):
                        rows.append(PairOutcome(
                            pair_id=f"{block}|{cell}|pair-{pair}",
                            block=block, truth=truth, cell=cell,
                            scheduled=tasks_per_pair,
                            wrong_paid=(_draw_rate(rng, prob_wp, rho, tasks_per_pair)
                                        if truth == 0 else 0),
                            wrong_paid_unknown=0,
                            checked=_draw_rate(rng, prob_q, rho, tasks_per_pair),
                            checked_unknown=0,
                        ))
    r_result = contrast(rows, "wrong_paid", "R")
    s_result = contrast(rows, "checked", "S")
    return (
        cluster_wald_pvalue(r_result["estimate"], r_result["cluster_standard_error"]),
        cluster_wald_pvalue(s_result["estimate"], s_result["cluster_standard_error"]),
    )


def simulate_power(
    pilot: PilotCalibration, *, pairs_per_cell_truth_block: int,
    tasks_per_pair: int, task_families: int, model_versions: int,
    rho: float, repetitions: int, seed: int,
    remaining_authorized_usd: Decimal,
    wrong_pay_sesoi: float = 0.10, check_sesoi: float = -0.10,
) -> dict[str, Any]:
    """Cluster-level Monte Carlo power under two declared risk differences.

    Power uses approximate pair-cluster Wald tests for sizing. The frozen final
    analysis must use blocked pair randomization tests and Holm adjustment.
    Results are conditional scenario calculations, not achieved study power.
    """
    if any(type(value) is not int or value < 1 for value in (
        pairs_per_cell_truth_block, tasks_per_pair, task_families, model_versions,
    )) or pairs_per_cell_truth_block < 2 or repetitions < 1:
        raise ValueError("positive design sizes, at least two pairs per cell, required")
    if not isfinite(rho) or not 0 <= rho < 1:
        raise ValueError("rho must be in [0,1)")
    if not isfinite(wrong_pay_sesoi) or not isfinite(check_sesoi) \
            or wrong_pay_sesoi <= 0 or check_sesoi >= 0:
        raise ValueError("predeclared R and S SESOIs must retain their signs")
    if not remaining_authorized_usd.is_finite() or remaining_authorized_usd < 0:
        raise ValueError("remaining authorized spend must be nonnegative")
    total_pairs = 8 * 2 * task_families * model_versions * pairs_per_cell_truth_block
    projected_usd = (pilot.max_observed_task_cost_usd * Decimal("1.25")
                     * total_pairs * tasks_per_pair)
    scenarios = {}
    for missing_case in (False, True):
        wp, check = pilot.scenario_rates(unresolved_as_event=missing_case)
        if any(not 0 <= p + wrong_pay_sesoi <= 1 for p in wp.values()) \
                or any(not 0 <= p + check_sesoi <= 1 for p in check.values()):
            raise ValueError("SESOI is outside feasible risk range for pilot baseline")
        rng = Random(seed + int(missing_case))
        counts = {"R_wrong_paid": 0, "S_check": 0, "both": 0}
        for _ in range(repetitions):
            p_r, p_s = _simulate_once(
                rng, wp, check,
                pairs_per_cell_truth_block=pairs_per_cell_truth_block,
                tasks_per_pair=tasks_per_pair, task_families=task_families,
                model_versions=model_versions, rho=rho,
                wrong_pay_effect=wrong_pay_sesoi,
                check_effect=check_sesoi,
            )
            decisions = holm_two(p_r, p_s)
            counts["R_wrong_paid"] += decisions["R_wrong_paid"]
            counts["S_check"] += decisions["S_check"]
            counts["both"] += all(decisions.values())
        scenarios["unresolved_as_event" if missing_case else "unresolved_as_nonevent"] = {
            "pilot_baseline_wrong_pay_by_SP": wp,
            "pilot_baseline_check_by_RP": check,
            "holm_rejection_fraction": {name: count / repetitions
                                        for name, count in counts.items()},
        }
    return {
        "schema": "w19-power-scenario-v1",
        "status": "SCENARIO_ONLY_NOT_PREREGISTERED",
        "pilot_source_run_sha256": pilot.source_run_sha256,
        "inference_unit": "assigned_economic_pair_cluster",
        "pairs": total_pairs,
        "tasks": total_pairs * tasks_per_pair,
        "pairs_per_cell_truth_block": pairs_per_cell_truth_block,
        "task_families": task_families, "model_versions": model_versions,
        "tasks_per_pair": tasks_per_pair, "rho": rho,
        "repetitions": repetitions, "seed": seed,
        "wrong_pay_sesoi_risk_difference": wrong_pay_sesoi,
        "check_sesoi_risk_difference": check_sesoi,
        "approximate_wald_for_sizing_only": True,
        "projected_model_spend_usd": str(projected_usd),
        "remaining_authorized_usd": str(remaining_authorized_usd),
        "within_current_authorized_spend": projected_usd <= remaining_authorized_usd,
        "scenarios": scenarios,
    }
