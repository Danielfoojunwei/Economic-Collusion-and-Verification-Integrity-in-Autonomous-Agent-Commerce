#!/usr/bin/env python3
"""Negative native verifier checks against genuine saved compensation evidence."""
import argparse
from copy import deepcopy
import json
import os
from pathlib import Path
import subprocess

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('evidence', type=Path)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    original = json.loads(args.evidence.read_text())
    if original['flow'] != 'session':
        raise ValueError('a genuine session control is required')
    args.output.mkdir(parents=True, exist_ok=False)
    env = {'PATH': os.environ.get('PATH', '/usr/bin:/bin')}
    def verify(path):
        return subprocess.run(['node', str(ROOT / 'protocols/mpp/verify-meeting-evidence.mjs'), str(path)],
                              cwd=ROOT, env=env, text=True, capture_output=True, timeout=30)
    positive = verify(args.evidence.resolve())
    if positive.returncode:
        raise RuntimeError('positive evidence failed the current independent verifier')
    assert 'historical_balances_verified' in positive.stdout
    due = int(original['gross_service_paid_atomic'])
    variants = []
    forged = deepcopy(original)
    forged['auditor_net_gain_atomic'] = str(due)
    forged['settlement_gas_cost_atomic'] = '0'
    forged['auditor_balance_after'] = str(int(forged['auditor_balance_before']) + due)
    variants.append(('erased-auditor-gas', forged, 'historical auditor balance after differs'))
    forged = deepcopy(original)
    forged.update(provider='0x'+'11'*20, auditor='0x'+'22'*20, token='0x'+'33'*20)
    variants.append(('forged-parties-token', forged, 'AssertionError'))
    forged = deepcopy(original)
    forged['session_channel_id'] = '0x'+'44'*32
    for p in forged['payments']:
        p['receipt'].update(channelId=forged['session_channel_id'], reference=forged['session_channel_id'])
    variants.append(('forged-channel-identity', forged, 'AssertionError'))
    forged = deepcopy(original)
    for event in forged['settlement']['logs']:
        if event['address'].lower() == '0x4d50500000000000000000000000000000000000':
            event['address'] = '0x'+'55'*20
    variants.append(('forged-close-emitter', forged, 'AssertionError'))
    forged = deepcopy(original)
    forged['provider_balance_after'] = str(int(forged['provider_balance_before']) - due)
    forged['provider_total_debit_atomic'] = str(due)
    forged['provider_gas_cost_atomic'] = '0'
    variants.append(('erased-provider-gas', forged, 'historical provider balance after differs'))
    rows = []
    for label, payload, needle in variants:
        path = args.output / f'{label}.json'
        path.write_text(json.dumps(payload, indent=2) + '\n')
        result = verify(path)
        if result.returncode == 0 or needle not in result.stderr:
            raise RuntimeError(f'independent verifier failed to reject {label}')
        rows.append({'case': label, 'status': 'PASS', 'verifier_exit_code': result.returncode,
                     'expected_rejection': needle})
    report = {'status': 'PASS', 'positive_verifier': json.loads(positive.stdout), 'negative_cases': rows,
        'remote_model_calls': 0, 'no_mutating_native_operation': True}
    (args.output / 'report.json').write_text(json.dumps(report, indent=2) + '\n')
    print(json.dumps(report))


if __name__ == '__main__':
    main()
