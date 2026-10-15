"""Independent native controls and saved-evidence tampering, without model calls."""
from copy import deepcopy
from hashlib import sha256
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from agent_economic_trust.open004_native_verifier import (
    CUSTODY_LABEL, verify_funded_evidence, verify_native_evidence,
)


class NativeEvidenceVerifierTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from agent_economic_trust import open004_native as native
        from agent_economic_trust.open004_task import Arm, SCHEDULE, invoice_case
        import scripts.run_erc8183_local as helper

        source_candidates = [helper.UPSTREAM, Path('/workspace/upstreams/erc8183')]
        cls.source = next((p for p in source_candidates if (p / 'out/ERC8183.sol/ERC8183.json').is_file()), None)
        if cls.source is None:
            raise unittest.SkipTest('pinned official ERC8183 checkout and built artifacts unavailable')
        tools = cls.source.parent.parent / '.tools'
        cls.temp = tempfile.TemporaryDirectory(prefix='open004-independent-verifier-', dir='/tmp')
        cls.addClassCleanup(cls.temp.cleanup)
        cls.root = Path(cls.temp.name)
        overrides = {'UPSTREAM': cls.source, 'CAST': tools / 'foundry/v1.8.5/cast',
                     'FORGE': tools / 'foundry/v1.8.5/forge',
                     'ANVIL': tools / 'foundry/v1.8.5/anvil', 'SOLC': tools / 'solc/v0.8.28/solc'}
        cls.controls = {}
        cls.funded_controls = {}
        with patch.multiple(helper, **overrides), patch.multiple(native, **{k: v for k, v in overrides.items() if k != 'CAST'}):
            for name, truth, arm, verdict, condition, response, checked, fund in (
                ('bad_accept_bonus', 'bad', Arm.OPEN, 'ACCEPT', 'ACCEPT_WITHOUT_CHECK', 'ACCEPT', False, True),
                ('bad_reject_refund', 'bad', Arm.OPEN, 'REJECT', 'ACCEPT', 'ACCEPT', True, True),
                ('good_accept_no_side', 'good', Arm.INDEPENDENT, 'ACCEPT', 'UNCONDITIONAL', 'REFUSE', True, False),
                ('good_accept_refused_side', 'good', Arm.OPEN, 'ACCEPT', 'UNCONDITIONAL', 'REFUSE', True, True),
            ):
                row = next(r for r in SCHEDULE if r.truth == truth and r.arm is arm)
                fixture, artifact = invoice_case(truth)
                path = cls.root / name
                proposal = {'proposal_id': 'verifier-control', 'side_amount_minor': 1_000_000,
                            'side_condition': condition, 'auditor_response': response}
                with native.Open004NativeController(row, fixture, artifact, path) as controller:
                    if fund:
                        controller.fund_side_term(row, fixture, artifact, proposal)
                    controller.settle_downstream(row, fixture, artifact, verdict, checked, proposal)
                cls.controls[name] = json.loads((path / 'native-evidence.json').read_text())

            for fund in (False, True):
                name = 'incomplete_with_side' if fund else 'incomplete_no_side'
                row = next(r for r in SCHEDULE if r.truth == 'bad' and r.arm is Arm.OPEN)
                fixture, artifact = invoice_case('bad')
                path = cls.root / name
                proposal = {'proposal_id': 'incomplete-control', 'side_amount_minor': 1_000_000,
                            'side_condition': 'ACCEPT_WITHOUT_CHECK', 'auditor_response': None}
                with native.Open004NativeController(row, fixture, artifact, path) as controller:
                    if fund:
                        controller.fund_side_term(row, fixture, artifact, proposal)
                    # Deliberately end without any verdict or settlement action.
                cls.funded_controls[name] = json.loads((path / 'native-evidence.json').read_text())

    def verify(self, evidence):
        return verify_native_evidence(evidence, source_root=self.source)

    def test_positive_native_payout_refund_and_false_accept_consequence(self):
        for name, evidence in self.controls.items():
            with self.subTest(control=name):
                report = self.verify(evidence)
                self.assertTrue(report['ok'], report)
                self.assertEqual(report['custody_label'], CUSTODY_LABEL)
        report = self.verify(self.controls['bad_accept_bonus'])
        self.assertEqual(report['bad_accept_consequence'], {
            'false_accept': True, 'wrongful_provider_payout_minor': 20_000_000,
            'auditor_side_payment_minor': 1_000_000})
        rejected = self.verify(self.controls['bad_reject_refund'])
        self.assertTrue(rejected['client_refunded'])
        self.assertEqual(rejected['side_recipient'], 'provider')
        self.assertEqual(rejected['bad_accept_consequence']['wrongful_provider_payout_minor'], 0)

    def test_incomplete_native_prefix_preserves_outstanding_funds_without_settlement(self):
        for name, evidence in self.funded_controls.items():
            with self.subTest(control=name):
                report = verify_funded_evidence(evidence, self.source)
                self.assertTrue(report['ok'], report)
                self.assertEqual(report['status'], 'FUNDED_SUBMITTED_VERIFIED')
                self.assertIs(report['terminal_settlement'], False)
                self.assertEqual(report['episode_outcome'], 'INCOMPLETE_NO_VERDICT')
                self.assertEqual(report['job_status'], 'Submitted')
                self.assertEqual(report['outstanding_job_escrow_minor'], 20_000_000)
                self.assertEqual(report['outstanding_application_custody_minor'],
                                 1_000_000 if name.endswith('with_side') else 0)
                self.assertIsNone(report['verdict'])
                self.assertIsNone(report['bad_accept_consequence'])
                self.assertFalse(report['provider_paid'])
                self.assertFalse(report['client_refunded'])
                self.assertFalse(self.verify(evidence)['ok'])
                self.assertTrue(verify_funded_evidence(self.root / name, self.source)['ok'])
        for evidence in self.controls.values():
            self.assertFalse(verify_funded_evidence(evidence, self.source)['ok'])

    def test_incomplete_prefix_tampering_and_hidden_terminal_transactions_fail(self):
        mutations = {
            'raw_sender': lambda e: e['transactions'][-1]['raw_transaction'].__setitem__('from', e['roles']['evaluator']),
            'raw_status': lambda e: e['transactions'][-1]['raw_receipt'].__setitem__('status', '0x0'),
            'raw_input': lambda e: e['transactions'][-1]['raw_transaction'].__setitem__('input', '0x'),
            'receipt_hash': lambda e: e['side_funding'].__setitem__('raw_receipt_sha256', '0' * 64),
            'side_amount': lambda e: e['side_funding'].__setitem__('amount_minor', 1),
            'side_condition': lambda e: e['side_funding'].__setitem__('condition', 'UNKNOWN'),
            'side_proposal': lambda e: e['side_funding'].__setitem__('proposal_id', ''),
            'side_snapshot': lambda e: e['side_funding']['after']['balances_minor_units'].__setitem__('escrow', 0),
            'side_log': lambda e: e['transactions'][-1]['raw_receipt']['logs'][0].__setitem__('data', '0x0'),
            'funded_state': lambda e: e['funded_job']['job'].__setitem__('status', 'Completed'),
            'submitted_state': lambda e: e['submitted_job']['job'].__setitem__('status', 'Completed'),
            'submitted_raw': lambda e: e['submitted_job'].__setitem__('raw_jobs_call', '0x'),
            'artifact': lambda e: e['episode'].__setitem__('artifact_digest', '0' * 64),
            'obligation': lambda e: e['episode'].__setitem__('obligation_id', 'different-obligation'),
            'source': lambda e: e['source'].__setitem__('erc8183_commit', '0' * 40),
            'fee': lambda e: e['audit_fee'].__setitem__('payer_role', 'client'),
            'order': lambda e: e['transactions'].reverse(),
            'missing_submit': lambda e: e['transactions'].pop(-2),
        }
        for name, mutate in mutations.items():
            evidence = deepcopy(self.funded_controls['incomplete_with_side'])
            mutate(evidence)
            with self.subTest(tamper=name):
                report = verify_funded_evidence(evidence, self.source)
                self.assertFalse(report['ok'], report)
                self.assertNotEqual(report['status'], 'FUNDED_SUBMITTED_VERIFIED')
        evidence = deepcopy(self.controls['bad_accept_bonus'])
        evidence['settlement'] = None  # Retain terminal txs: must never truncate or relabel.
        self.assertFalse(verify_funded_evidence(evidence, self.source)['ok'])

    def test_saved_file_checksum_is_required_for_directory_input(self):
        path = self.root / 'bad_accept_bonus'
        self.assertTrue(self.verify(path)['ok'])
        forged = self.root / 'forged'
        forged.mkdir()
        evidence = self.controls['bad_accept_bonus']
        (forged / 'native-evidence.json').write_text(json.dumps(evidence))
        self.assertFalse(self.verify(forged)['ok'])
        raw = (forged / 'native-evidence.json').read_bytes()
        (forged / 'native-evidence.sha256').write_text(sha256(raw).hexdigest() + '  native-evidence.json\n')
        self.assertTrue(self.verify(forged)['ok'])
        changed = deepcopy(evidence)
        changed['settlement']['provider_paid'] = False
        raw = json.dumps(changed).encode()
        (forged / 'native-evidence.json').write_bytes(raw)
        (forged / 'native-evidence.sha256').write_text(sha256(raw).hexdigest() + '  native-evidence.json\n')
        self.assertFalse(self.verify(forged)['ok'])

    def test_raw_receipt_transaction_log_and_binding_tampering_fails(self):
        def row(e, step):
            return next(r for r in e['transactions'] if r['step'] == step)

        def assign(path, value):
            def mutate(e):
                current = e
                for key in path[:-1]:
                    current = current[key]
                current[path[-1]] = value
            return mutate

        cases = {
            'genesis': assign(['chain', 'genesis_timestamp'], 0),
            'source_commit': assign(['source', 'erc8183_commit'], '0' * 40),
            'artifact_hash': assign(['source', 'erc8183_artifact_sha256'], '0' * 64),
            'truth': assign(['episode', 'truth'], 'good'),
            'artifact_binding': assign(['episode', 'artifact_digest'], '0' * 64),
            'job_id': assign(['job_id'], 2),
            'terminal_state': assign(['settlement', 'job', 'status'], 'Submitted'),
            'raw_job_state': assign(['settlement', 'raw_jobs_call'], '0x' + '00' * 416),
            'provider_paid_summary': assign(['settlement', 'provider_paid'], False),
            'side_amount': assign(['side_funding', 'amount_minor'], 5_000_001),
            'side_condition': assign(['side_funding', 'condition'], 'UNCONDITIONAL'),
            'side_recipient': assign(['settlement', 'side_term', 'recipient_role'], 'provider'),
            'side_conservation': assign(['side_funding', 'after', 'balances_minor_units', 'outsider'], 0),
            'job_conservation': assign(['settlement', 'after', 'total_supply_minor_units'], 0),
            'audit_payer': assign(['audit_fee', 'payer_role'], 'client'),
            'receipt_status': lambda e: row(e, 'open004.invoice.complete')['raw_receipt'].__setitem__('status', '0x0'),
            'raw_sender': lambda e: row(e, 'open004.invoice.complete')['raw_transaction'].__setitem__('from', e['roles']['provider']),
            'raw_destination': lambda e: row(e, 'open004.invoice.complete')['raw_transaction'].__setitem__('to', e['token_address']),
            'raw_chain': lambda e: row(e, 'open004.side_fund')['raw_transaction'].__setitem__('chainId', '0x1'),
            'fund_input': lambda e: row(e, 'open004.invoice.fund')['raw_transaction'].__setitem__('input', '0x'),
            'submit_input': lambda e: row(e, 'open004.invoice.submit')['raw_transaction'].__setitem__('input', '0x'),
            'side_fund_input': lambda e: row(e, 'open004.side_fund')['raw_transaction'].__setitem__('input', '0x'),
            'side_release_input': lambda e: row(e, 'open004.side_settle')['raw_transaction'].__setitem__('input', '0x'),
            'fund_log': lambda e: row(e, 'open004.invoice.fund')['raw_receipt']['logs'][0].__setitem__('data', '0x01'),
            'submit_log': lambda e: row(e, 'open004.invoice.submit')['raw_receipt']['logs'][0].__setitem__('data', '0x' + '00' * 32),
            'terminal_log_core': lambda e: row(e, 'open004.invoice.complete')['raw_receipt']['logs'][-1].__setitem__('address', e['token_address']),
            'terminal_log_job': lambda e: row(e, 'open004.invoice.complete')['raw_receipt']['logs'][-1]['topics'].__setitem__(1, '0x' + f'{2:064x}'),
            'side_transfer_amount': lambda e: row(e, 'open004.side_settle')['raw_receipt']['logs'][0].__setitem__('data', '0x' + f'{1:064x}'),
            'extra_log': lambda e: row(e, 'open004.invoice.submit')['raw_receipt']['logs'].append(deepcopy(row(e, 'open004.invoice.submit')['raw_receipt']['logs'][0])),
            'log_removed': lambda e: row(e, 'open004.side_fund')['raw_receipt']['logs'][0].__setitem__('removed', True),
            'log_hash': lambda e: row(e, 'open004.side_fund')['raw_receipt']['logs'][0].__setitem__('transactionHash', '0x' + '00' * 32),
            'nonce': lambda e: row(e, 'open004.side_fund')['raw_transaction'].__setitem__('nonce', '0x99'),
            'chronology': lambda e: e['transactions'].reverse(),
            'duplicate': lambda e: e['transactions'].append(deepcopy(e['transactions'][-1])),
        }
        for name, mutate in cases.items():
            evidence = deepcopy(self.controls['bad_accept_bonus'])
            mutate(evidence)
            with self.subTest(tamper=name):
                report = self.verify(evidence)
                self.assertFalse(report['ok'], report)
                self.assertTrue(report['errors'])

    def test_side_refund_transfer_tampering_fails(self):
        evidence = deepcopy(self.controls['bad_reject_refund'])
        row = next(r for r in evidence['transactions'] if r['step'] == 'open004.side_refund')
        row['raw_receipt']['logs'][0]['topics'][2] = '0x' + evidence['roles']['evaluator'][2:].zfill(64)
        self.assertFalse(self.verify(evidence)['ok'])

    def test_malformed_evidence_fails_closed(self):
        for evidence in ({}, {'schema': 'other'}, {'schema': 'open004-native-erc8183-v1', 'chain': None}):
            with self.subTest(evidence=evidence):
                self.assertFalse(self.verify(evidence)['ok'])


if __name__ == '__main__':
    unittest.main()
