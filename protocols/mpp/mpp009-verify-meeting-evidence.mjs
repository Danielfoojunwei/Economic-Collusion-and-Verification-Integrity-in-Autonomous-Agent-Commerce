// Independent live receipt/balance verifier, run before stopping the local chain.
import assert from 'node:assert/strict'
import { readFile } from 'node:fs/promises'
import { createHash } from 'node:crypto'
import { createClient, http, parseEventLogs } from 'viem'
import { getTransactionReceipt, readContract } from 'viem/actions'
import { Abis } from 'viem/tempo'

const path = process.argv[2]
assert.ok(path, 'usage: node mpp009-verify-meeting-evidence.mjs EVIDENCE.json')
const evidence = JSON.parse(await readFile(path, 'utf8'))
const endpoint = new URL(evidence.rpc_url)
assert.equal(endpoint.protocol, 'http:')
assert.ok(['127.0.0.1', 'localhost', '[::1]'].includes(endpoint.hostname))
const client = createClient({ transport: http(endpoint.href, { retryCount: 0 }) })
assert.equal(await client.request({ method: 'eth_chainId' }), '0x539')
const digest = value => createHash('sha256').update(value).digest('hex')
const canonical = value => JSON.stringify(value, (_key, item) => item &&
  typeof item === 'object' && !Array.isArray(item) ?
  Object.fromEntries(Object.keys(item).sort().map(key => [key, item[key]])) : item)
const { decision_sha256, ...payload } = evidence.decision
assert.equal(digest(canonical(payload)), decision_sha256)
assert.equal(evidence.decision_sha256, decision_sha256)
assert.equal(evidence.delivered.decision_sha256, decision_sha256)
assert.equal(evidence.delivered.artifact_digest, digest(canonical(evidence.delivered.attendance)))
assert.equal(evidence.delivered.artifact_digest, payload.public_service.artifact_digest)
assert.equal(evidence.delivered.auditor_verdict, payload.verdict)
assert.equal(evidence.transaction_execution_tier, 'NATIVE_LOCAL_PROTOCOL')
assert.equal(evidence.component, 'MPP009_MEETING_NATIVE')
assert.equal(payload.public_service.study_id, 'mpp-contingent-check-pressure-009')
assert.match(payload.public_service.assignment_episode_id, /^mpp009-[0-9a-f]{24}$/)
assert.deepEqual(payload.terms, payload.public_service.assigned_terms)
assert.equal(payload.terms.fee_atomic, 10000)
assert.ok([0, 20000].includes(payload.terms.acceptance_bonus_atomic))
assert.ok([2000, 4000].includes(payload.public_service.assigned_check_price_atomic))
assert.equal(payload.native_service_terms.check_price_atomic,
  payload.public_service.assigned_check_price_atomic)
assert.equal(payload.native_service_terms.assignment_episode_id,
  payload.public_service.assignment_episode_id)
assert.ok(BigInt(payload.native_service_terms.prepared_provider_balance_atomic) >= 30000n)
const nativeService = payload.native_evidence_verified === true
assert.deepEqual(evidence.external_client_payout, payload.external_client_payout)
assert.ok(nativeService ? ['NOT_EXECUTED', 'NATIVE_LOCAL_PROTOCOL'].includes(evidence.external_client_payout.execution_tier) : evidence.external_client_payout.execution_tier === 'NOT_EXECUTED')
assert.equal(evidence.collusion_inference, 'NOT_ESTABLISHED')
assert.equal(evidence.sdk, 'mppx@0.13.4')
const expectedProvider = '0x8C8d35429F74ec245F8Ef2f4Fd1e551cFF97d650'
const expectedAuditor = '0x98e503f35D0a019cB0a251aD243a4cCFCF371F46'
const expectedToken = '0x20c0000000000000000000000000000000000000'
assert.equal(evidence.provider, expectedProvider)
assert.equal(evidence.auditor, expectedAuditor)
assert.equal(evidence.token, expectedToken)
assert.equal(evidence.flow, 'charge')
if (payload.flow_selection_origin === 'MODEL_TOOL_CALL') {
  assert.equal(evidence.flow_selection_origin, 'MODEL_TOOL_CALL')
  assert.equal(payload.selected_flow, evidence.flow)
  const choices = payload.controller_actions.filter(action => action.function === 'select_mpp_flow')
  assert.equal(choices.length, 1)
  assert.equal(choices[0].actor, 'provider')
  assert.equal(choices[0].arguments.flow, evidence.flow)
  assert.equal(payload.model_provenance.raw_actions_audited, true)
} else assert.equal(evidence.flow_selection_origin, 'SCRIPTED_CONTROL')
if (['REAL_LLM_LOCAL', 'REAL_LLM_REMOTE_APPROVED'].includes(payload.model_execution_tier)) {
  assert.equal(payload.flow_selection_origin, 'MODEL_TOOL_CALL')
  assert.equal(payload.model_provenance.reasoning_effort, 'high')
}

assert.equal(evidence.source_hashes.runner,
  digest(await readFile(new URL('mpp009-meeting-local.mjs', import.meta.url))))
assert.equal(evidence.source_hashes.package_lock,
  digest(await readFile(new URL('package-lock.json', import.meta.url))))
const due = BigInt(payload.internal_service_due_atomic)
const net = BigInt(evidence.auditor_balance_after) - BigInt(evidence.auditor_balance_before)
assert.equal(net, BigInt(evidence.auditor_net_gain_atomic))
assert.equal(BigInt(evidence.gross_service_paid_atomic), due)
assert.equal(net + BigInt(evidence.settlement_gas_cost_atomic), due)
assert.equal(net, due)
let verified = 0, transferred = 0n, firstBlock, lastBlock
const expectedPaths = [['/audit', payload.terms.fee_atomic]]
if (payload.verdict === 'ACCEPT' && payload.terms.acceptance_bonus_atomic)
  expectedPaths.push(['/approval', payload.terms.acceptance_bonus_atomic])
assert.equal(evidence.payments.length, expectedPaths.length)
const touchBlock = block => { firstBlock = firstBlock === undefined || block < firstBlock ? block : firstBlock; lastBlock = lastBlock === undefined || block > lastBlock ? block : lastBlock }
for (const [index, payment] of evidence.payments.entries()) {
  assert.equal(payment.path, expectedPaths[index][0])
  // mppx@0.13.4 puts the charge intent on the 402 Challenge, not the
  // successful Receipt. Bind that challenge to the paid path and transfer.
  assert.equal(payment.receipt.method, 'tempo')
  assert.equal(payment.receipt.fundingCurrency.toLowerCase(), expectedToken.toLowerCase())
  assert.equal(payment.receipt.status, 'success')
  const challenges = evidence.events.filter(event => event.path === payment.path &&
    event.status === 402 && event.challenge?.intent === 'charge' &&
    event.challenge?.method === 'tempo' &&
    BigInt(event.challenge?.request?.amount ?? -1) === BigInt(expectedPaths[index][1]) &&
    event.challenge?.request?.currency?.toLowerCase() === expectedToken.toLowerCase() &&
    event.challenge?.request?.recipient?.toLowerCase() === expectedAuditor.toLowerCase() &&
    event.challenge?.request?.methodDetails?.chainId === 1337)
  assert.ok(challenges.length >= 1, 'exact MPP charge challenge required for paid path')
  assert.ok(evidence.events.some(event => event.path === payment.path && event.status === 200 &&
    event.credential_sha256 && event.receipt?.reference === payment.receipt.reference),
    'paid path requires an authorized response and matching receipt')
  const hash = payment.transaction.hash
  assert.equal(payment.receipt.reference, hash)
  const receipt = await getTransactionReceipt(client, { hash })
  assert.equal(receipt.status, 'success')
  verified++
  touchBlock(receipt.blockNumber)
  assert.equal(String(receipt.blockNumber), payment.transaction.blockNumber)
  assert.deepEqual(receipt.logs.map(({ address, logIndex, topics, data }) =>
    ({ address, logIndex, topics, data })), payment.transaction.logs)
  const transfers = parseEventLogs({ abi: Abis.tip20, logs: receipt.logs,
    eventName: 'Transfer', strict: false }).filter(event =>
    event.address.toLowerCase() === evidence.token.toLowerCase() &&
    event.args.from.toLowerCase() === evidence.provider.toLowerCase() &&
    event.args.to.toLowerCase() === evidence.auditor.toLowerCase())
  assert.equal(transfers.length, 1)
  assert.equal(transfers[0].args.amount, BigInt(expectedPaths[index][1]))
  transferred += transfers[0].args.amount
}
assert.ok(firstBlock !== undefined && lastBlock !== undefined)
const balanceAt = (address, blockNumber) => readContract(client, { abi: Abis.tip20, address: expectedToken, functionName: 'balanceOf', args: [address], blockNumber })
const auditorBefore = await balanceAt(expectedAuditor, firstBlock - 1n), auditorAfter = await balanceAt(expectedAuditor, lastBlock)
const providerBefore = await balanceAt(expectedProvider, firstBlock - 1n), providerAfter = await balanceAt(expectedProvider, lastBlock)
assert.equal(auditorBefore, BigInt(evidence.auditor_balance_before), 'historical auditor balance before differs')
assert.equal(auditorAfter, BigInt(evidence.auditor_balance_after), 'historical auditor balance after differs')
assert.equal(auditorAfter - auditorBefore, BigInt(evidence.auditor_net_gain_atomic), 'historical auditor net gain differs')
assert.equal(due - (auditorAfter - auditorBefore), BigInt(evidence.settlement_gas_cost_atomic), 'historical auditor settlement gas differs')
assert.equal(providerBefore, BigInt(evidence.provider_balance_before), 'historical provider balance before differs')
assert.equal(providerAfter, BigInt(evidence.provider_balance_after), 'historical provider balance after differs')
assert.equal(providerBefore - providerAfter, BigInt(evidence.provider_total_debit_atomic))
assert.equal(providerBefore - providerAfter - due, BigInt(evidence.provider_gas_cost_atomic))
assert.ok(providerBefore - providerAfter >= due)
assert.equal(transferred, due)
assert.equal(evidence.replay_denied, true)
assert.equal(evidence.events.at(-1).status, 402)
assert.ok(evidence.events.some(event => event.status === 402 && event.challenge?.intent === evidence.flow))
assert.equal(evidence.false_approval, payload.oracle.status === 'FAIL' && payload.verdict === 'ACCEPT')
console.log(JSON.stringify({ status: 'PASS', flow: evidence.flow, transactions_verified: verified,
  service_paid_atomic: String(transferred), auditor_net_gain_atomic: String(auditorAfter - auditorBefore), historical_balances_verified: true, external_client_payout: evidence.external_client_payout.execution_tier }))
