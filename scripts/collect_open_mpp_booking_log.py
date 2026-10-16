#!/usr/bin/env python3
"""Verify a saved private-calendar ORBIT log and live local payment evidence."""
import argparse
import asyncio
from hashlib import sha256
import json
from pathlib import Path
import shutil
from inspect_ai.log import read_eval_log
from agent_economic_trust.open_mpp_native_service import NativeMeetingService, inspect_native_service_log


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('eval_log', type=Path)
    parser.add_argument('--native-dir', type=Path, required=True)
    parser.add_argument('--quality', choices=('GOOD', 'BAD'), required=True)
    parser.add_argument('--condition', choices=('OPEN', 'COERCIVE_STRESS'), default='OPEN')
    parser.add_argument('--expected-model', required=True)
    parser.add_argument('--rpc-url', default='http://127.0.0.1:19567')
    parser.add_argument('--http-url', default='http://127.0.0.1:19559')
    parser.add_argument('--require-real-model', action='store_true')
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    service = NativeMeetingService(args.native_dir.resolve(), args.rpc_url, args.http_url)
    log = read_eval_log(str(args.eval_log), resolve_attachments=True)
    decision = asyncio.run(inspect_native_service_log(log, service=service, quality=args.quality,
        condition=args.condition, expected_model=args.expected_model, require_real_model=args.require_real_model))
    args.output.mkdir(parents=True, exist_ok=False)
    shutil.copy2(args.eval_log, args.output / 'raw.eval')
    (args.output / 'decision.json').write_text(json.dumps(decision, indent=2) + '\n')
    report = {'status': 'PASS', 'raw_eval_sha256': sha256(args.eval_log.read_bytes()).hexdigest(),
              'decision_sha256': decision['decision_sha256'], 'native_evidence_verified': True,
              'model_execution_tier': decision['model_execution_tier'],
              'client_release_policy': decision['client_release_policy']}
    (args.output / 'audit_report.json').write_text(json.dumps(report, indent=2) + '\n')
    print(json.dumps(report))


if __name__ == '__main__':
    main()
