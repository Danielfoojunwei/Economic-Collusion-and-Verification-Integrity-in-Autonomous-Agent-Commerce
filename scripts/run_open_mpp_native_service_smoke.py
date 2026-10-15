#!/usr/bin/env python3
"""Zero-model native check purchase/client release controls; loopback only."""
import argparse
import asyncio
import json
from pathlib import Path
from inspect_ai import eval as inspect_eval
from inspect_ai.log import read_eval_log
from agent_economic_trust.open_mpp_native_service import (
    NativeMeetingService, inspect_native_service_log, native_service_orbit,
)
from agent_economic_trust.open_mpp_smoke import MODEL, scripted_model


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--rpc-url', default='http://127.0.0.1:19567')
    parser.add_argument('--http-url', default='http://127.0.0.1:19559')
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=False)
    rows = []
    for index, (quality, checked, flow, repeat_check) in enumerate([
            ('GOOD', True, 'charge', False), ('BAD', True, 'session', False),
            ('BAD', False, 'charge', False), ('GOOD', False, 'session', False),
            ('BAD', True, 'charge', True)]):
        path = args.output / f'trial-{index:02}'
        service = NativeMeetingService(path.resolve(), args.rpc_url, args.http_url)
        asyncio.run(service.prepare())
        [log] = inspect_eval(native_service_orbit(quality, service=service,
                trial_id=f'service-trial-{index:02}', scheduler_seconds=120, task_token_limit=20000),
            model=scripted_model(checked=checked, flow=flow, repeat_check=repeat_check), log_dir=str(path / 'logs'),
            display='none', log_realtime=False, max_retries=0, retry_on_error=0)
        if log.status != 'success':
            raise RuntimeError(f'native ORBIT control failed: {log.error}')
        saved = read_eval_log(log.location, resolve_attachments=True)
        decision = asyncio.run(inspect_native_service_log(saved, service=service, quality=quality,
            expected_model=MODEL))
        (path / 'decision.json').write_text(json.dumps(decision, indent=2) + '\n')
        awaitable = service._command(Path('protocols/mpp/meeting-local.mjs'), path / 'decision.json',
                                     flow, path / 'compensation-evidence.json')
        asyncio.run(awaitable)
        asyncio.run(service._command(Path('protocols/mpp/verify-meeting-evidence.mjs'),
                                     path / 'compensation-evidence.json'))
        rows.append({'trial_id': f'trial-{index:02}', 'quality': quality, 'checked': checked,
            'selected_flow': flow, 'repeat_check': repeat_check, 'verdict': decision['verdict'], 'false_approval': decision['false_approval'],
            'check_debit_executed': any(r['operation'] == 'check' for r in decision['native_operations']),
            'client_release': decision['external_client_payout'], 'decision_sha256': decision['decision_sha256']})
    result = {'status': 'PASS', 'remote_model_calls': 0, 'model_execution_tier': 'SCRIPTED_SIMULATION',
        'transaction_execution_tier': 'NATIVE_LOCAL_PROTOCOL', 'release_policy': 'APPLICATION_ACCEPT_TRIGGER_NOT_NATIVE_ESCROW',
        'rows': rows, 'collusion_inference': 'NOT_ESTABLISHED'}
    (args.output / 'summary.json').write_text(json.dumps(result, indent=2) + '\n')
    print(json.dumps(result))


if __name__ == '__main__':
    main()
