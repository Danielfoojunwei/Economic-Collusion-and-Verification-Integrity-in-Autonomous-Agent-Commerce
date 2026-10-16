#!/usr/bin/env python3
"""Audit an existing ORBIT log; never call models or sign payment operations."""
import argparse
from hashlib import sha256
import json
from pathlib import Path
import shutil

from inspect_ai.log import read_eval_log
from agent_economic_trust.open_mpp_orbit import inspect_open_mpp_log


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('eval_log', type=Path)
    parser.add_argument('--quality', choices=('GOOD', 'BAD'), required=True)
    parser.add_argument('--condition', choices=('OPEN', 'COERCIVE_STRESS'), default='OPEN')
    parser.add_argument('--expected-model', required=True)
    parser.add_argument('--require-real-model', action='store_true')
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    log = read_eval_log(str(args.eval_log), resolve_attachments=True)
    decision = inspect_open_mpp_log(log, quality=args.quality, condition=args.condition,
        expected_model=args.expected_model, require_real_model=args.require_real_model)
    args.output.mkdir(parents=True, exist_ok=False)
    shutil.copy2(args.eval_log, args.output / 'raw.eval')
    (args.output / 'decision.json').write_text(json.dumps(decision, indent=2) + '\n')
    report = {'status': 'PASS', 'raw_actions_audited': True,
        'raw_eval_sha256': sha256(args.eval_log.read_bytes()).hexdigest(),
        'decision_sha256': decision['decision_sha256'], 'selected_flow': decision['selected_flow'],
        'model_execution_tier': decision['model_execution_tier'],
        'transaction_execution_tier': 'NOT_EXECUTED', 'external_client_payout': 'NOT_EXECUTED'}
    (args.output / 'audit_report.json').write_text(json.dumps(report, indent=2) + '\n')
    print(json.dumps(report))


if __name__ == '__main__':
    main()
