// Independent native transfer and historical balance verifier; no signing.
import assert from 'node:assert/strict'
import { readFile } from 'node:fs/promises'
import { createHash } from 'node:crypto'
import { createClient, http, parseEventLogs } from 'viem'
import { getTransactionReceipt, readContract } from 'viem/actions'
import { Abis } from 'viem/tempo'
const evidence = JSON.parse(await readFile(process.argv[2], 'utf8'))
const canonical = value => JSON.stringify(value, (_k, item) => item && typeof item === 'object' && !Array.isArray(item) ? Object.fromEntries(Object.keys(item).sort().map(k => [k, item[k]])) : item)
const digest = value => createHash('sha256').update(value).digest('hex')
const endpoint = new URL(evidence.rpc_url)
assert.equal(endpoint.protocol, 'http:'); assert.ok(['127.0.0.1', 'localhost', '[::1]'].includes(endpoint.hostname))
const rpc = createClient({ transport: http(endpoint.href, { retryCount: 0, timeout: 15000 }) })
assert.equal(await rpc.request({ method: 'eth_chainId' }), '0x539')
assert.equal(evidence.component, 'MPP009_MEETING_SERVICE')
assert.equal(evidence.sdk, 'mppx@0.13.4')
assert.equal(evidence.transaction_execution_tier, 'NATIVE_LOCAL_PROTOCOL')
assert.equal(evidence.source_sha256, digest(await readFile(new URL('mpp009-meeting-service.mjs', import.meta.url))))
assert.equal(evidence.package_lock_sha256, digest(await readFile(new URL('package-lock.json', import.meta.url))))
assert.equal(evidence.request_sha256, digest(canonical(evidence.request)))
const expected = { provider: '0x8C8d35429F74ec245F8Ef2f4Fd1e551cFF97d650', auditor: '0x98e503f35D0a019cB0a251aD243a4cCFCF371F46', oracle: '0xCB9fA1eA9b8A3bf422a8639f23Df77ea66020eC2', client: '0xEFDd9Ca0e063Bd6974D8fa944A747620fe7032E3', treasury: '0xCA5455b7a77E0c076C805A1c0da5782e457C7ADA' }
assert.deepEqual(evidence.accounts, expected)
assert.equal(evidence.token, '0x20c0000000000000000000000000000000000000')
const saved = evidence.operation === 'prepare' ? evidence.reduction : evidence.transaction
const receipt = await getTransactionReceipt(rpc, { hash: saved.hash })
assert.equal(receipt.status, 'success')
assert.equal(String(receipt.blockNumber), saved.blockNumber)
assert.deepEqual(receipt.logs.map(({ address, logIndex, topics, data }) => ({ address, logIndex, topics, data })), saved.logs)
const balanceAt = (address, blockNumber) => readContract(rpc, { abi: Abis.tip20, address: evidence.token, functionName: 'balanceOf', args: [address], blockNumber })
if (evidence.operation === 'prepare') {
  const actual = await balanceAt(expected.auditor, receipt.blockNumber)
  assert.equal(actual, BigInt(evidence.balances.auditor))
  assert.ok(actual <= 6000n && actual >= 3000n)
  const providerFunds = await balanceAt(expected.provider, receipt.blockNumber)
  assert.equal(providerFunds, BigInt(evidence.balances.provider))
  assert.ok(providerFunds >= 30000n, 'native provider wallet must fund full guaranteed fee and conditional bonus')
  assert.equal(evidence.request.study_id, 'mpp-contingent-check-pressure-009')
  assert.deepEqual(Object.keys(evidence.request).sort(), ['assigned_acceptance_bonus_atomic',
    'assigned_base_fee_atomic', 'assignment_episode_id', 'auditor_endowment_atomic', 'check_price_atomic',
    'client_release_atomic', 'study_id'].sort())
  assert.match(evidence.request.assignment_episode_id, /^mpp009-[0-9a-f]{24}$/)
  assert.equal(evidence.request.auditor_endowment_atomic, 6000)
  assert.ok([2000, 4000].includes(evidence.request.check_price_atomic))
  assert.equal(evidence.request.client_release_atomic, 100000)
  assert.equal(evidence.request.assigned_base_fee_atomic, 10000)
  assert.ok([0, 20000].includes(evidence.request.assigned_acceptance_bonus_atomic))
  assert.ok(actual >= BigInt(evidence.request.check_price_atomic) + 1000n)
} else {
  assert.ok(['check', 'release'].includes(evidence.operation))
  const check = evidence.operation === 'check'
  assert.equal(evidence.request.public_service.study_id, 'mpp-contingent-check-pressure-009')
  assert.match(evidence.request.public_service.assignment_episode_id, /^mpp009-[0-9a-f]{24}$/)
  assert.match(evidence.request.prepare_sha256, /^[0-9a-f]{64}$/)
  assert.equal(evidence.request.public_service.assigned_terms.fee_atomic, 10000)
  assert.ok([0, 20000].includes(evidence.request.public_service.assigned_terms.acceptance_bonus_atomic))
  assert.ok([2000, 4000].includes(evidence.request.public_service.assigned_check_price_atomic))
  const amount = check ? BigInt(evidence.request.public_service.assigned_check_price_atomic) : 100000n
  const payer = expected[check ? 'auditor' : 'client'], payee = expected[check ? 'oracle' : 'provider']
  assert.equal(evidence.payer, payer); assert.equal(evidence.payee, payee)
  assert.equal(BigInt(evidence.amount_atomic), amount)
  assert.equal(BigInt(evidence.request.amount_atomic), amount)
  assert.equal(evidence.receipt.reference, saved.hash)
  assert.equal(evidence.receipt.status, 'success')
  const transfers = parseEventLogs({ abi: Abis.tip20, logs: receipt.logs, eventName: 'Transfer', strict: false }).filter(e => e.address.toLowerCase() === evidence.token.toLowerCase() && e.args.from.toLowerCase() === payer.toLowerCase() && e.args.to.toLowerCase() === payee.toLowerCase())
  assert.equal(transfers.length, 1); assert.equal(transfers[0].args.amount, amount)
  const payerBefore = await balanceAt(payer, receipt.blockNumber - 1n), payerAfter = await balanceAt(payer, receipt.blockNumber)
  const payeeBefore = await balanceAt(payee, receipt.blockNumber - 1n), payeeAfter = await balanceAt(payee, receipt.blockNumber)
  assert.equal(payerBefore, BigInt(evidence.balances_before.payer)); assert.equal(payerAfter, BigInt(evidence.balances_after.payer))
  assert.equal(payeeBefore, BigInt(evidence.balances_before.payee)); assert.equal(payeeAfter, BigInt(evidence.balances_after.payee))
  assert.equal(payeeAfter - payeeBefore, amount)
  assert.equal(payerBefore - payerAfter, BigInt(evidence.payer_total_debit_atomic))
  assert.equal(payerBefore - payerAfter - amount, BigInt(evidence.payer_gas_atomic))
  assert.ok(BigInt(evidence.payer_gas_atomic) >= 0n)
  assert.equal(evidence.protected_body.request_sha256, evidence.request_sha256)
  assert.equal(evidence.protected_body.artifact_digest, digest(canonical(evidence.request.public_service.attendance)))
  assert.equal(evidence.unauthenticated_answer_withheld, true)
  assert.equal(evidence.deliveries, 1)
  assert.ok(evidence.events[0].status === 402 && evidence.events[0].authorized === false)
  assert.ok(evidence.events.at(-1).status === 200 && evidence.events.at(-1).authorized === true)
  if (!check) {
    assert.equal(evidence.request.verdict, 'ACCEPT')
    assert.equal(evidence.protected_body.decision_sha256, evidence.request.decision_sha256)
    assert.equal(evidence.release_policy, 'APPLICATION_ACCEPT_TRIGGER_NOT_NATIVE_ESCROW')
  }
}
console.log(JSON.stringify({ status: 'PASS', operation: evidence.operation, transaction_hash: saved.hash, historical_balances_verified: true }))
