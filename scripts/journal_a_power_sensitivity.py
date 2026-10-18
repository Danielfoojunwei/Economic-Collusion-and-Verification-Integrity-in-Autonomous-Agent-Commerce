#!/usr/bin/env python3
"""Seeded design sensitivity for Paper A; no behavioral data or model calls."""
from __future__ import annotations

import argparse
from hashlib import sha256
import json
from pathlib import Path
from random import Random
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from journal_A_v1.analysis_frozen import (
    A1_B_WEIGHTS, A1_BC_WEIGHTS, A2_BI_WEIGHTS, assigned_wald, holm_adjust)


def sample_rows(rng: Random, weights: dict, total_per_cell: int,
                rates: dict[str, float], prefix: str) -> list[dict]:
    if total_per_cell % 3 or set(rates) != set(weights):
        raise ValueError("balanced three-stratum cell probabilities required")
    rows = []
    for stratum in range(3):
        for cell, probability in rates.items():
            if not 0 <= probability <= 1:
                raise ValueError("invalid event probability")
            for index in range(total_per_cell // 3):
                rows.append({"episode_id": f"{prefix}-{stratum}-{cell}-{index}",
                             "stratum": str(stratum), "cell": cell,
                             "truth": "BAD", "event": rng.random() < probability})
    return rows


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    plan_path = ROOT / 'journal_A_v1/POWER_SENSITIVITY_PLAN.json'
    plan_bytes = plan_path.read_bytes()
    plan = json.loads(plan_bytes)
    rng = Random(plan['seed'])
    null = plan['null_event_probability']
    effect = plan['effect_event_probability']
    results = []
    for scenario in plan['scenarios']:
        hits = {'H-A1': 0, 'H-A2': 0, 'H-A3': 0, 'ANY': 0}
        inconclusive = 0
        for _ in range(plan['repetitions']):
            a1_rates = {}
            for cell in A1_B_WEIGHTS:
                b, c, _v = map(int, cell)
                a1_rates[cell] = (effect if (
                    (scenario == 'a1_compensation_only' and b == 1) or
                    (scenario == 'a1_contact_interaction' and b == 1 and c == 1))
                    else null)
            a2_rates = {cell: (effect if scenario == 'a2_evidence_interaction'
                              and cell == '10' else null) for cell in A2_BI_WEIGHTS}
            a1 = sample_rows(rng, A1_B_WEIGHTS, plan['a1_bad_per_cell'], a1_rates, 'A1')
            a2 = sample_rows(rng, A2_BI_WEIGHTS, plan['a2_bad_per_cell'], a2_rates, 'A2')
            p = {'H-A1': assigned_wald(a1, A1_B_WEIGHTS)['normal_p_two_sided'],
                 'H-A2': assigned_wald(a1, A1_BC_WEIGHTS)['normal_p_two_sided'],
                 'H-A3': assigned_wald(a2, A2_BI_WEIGHTS)['normal_p_two_sided']}
            if any(value is None for value in p.values()):
                inconclusive += 1
                continue
            adjusted = holm_adjust(p)
            any_hit = False
            for name in ('H-A1', 'H-A2', 'H-A3'):
                if adjusted[name] < .05:
                    hits[name] += 1
                    any_hit = True
            if any_hit:
                hits['ANY'] += 1
        results.append({'scenario': scenario, 'repetitions': plan['repetitions'],
                        'inconclusive': inconclusive,
                        'rejection_fraction': {name: count / plan['repetitions']
                                               for name, count in hits.items()}})
    report = {'schema': 'journal-A-power-sensitivity-report-v1',
              'plan_sha256': sha256(plan_bytes).hexdigest(),
              'source_sha256': sha256(Path(__file__).read_bytes()).hexdigest(),
              'results': results, 'limitation': plan['limitation']}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2) + '\n')
    print(json.dumps({item['scenario']: item['rejection_fraction']
                      for item in results}, sort_keys=True))


if __name__ == '__main__':
    main()
