// Independent live receipt/balance verifier, run before stopping the local chain.
import assert from 'node:assert/strict'
import { readFile } from 'node:fs/promises'
import { createHash } from 'node:crypto'
import { createClient, http, parseEventLogs } from 'viem'
import { getTransactionReceipt, readContract } from 'viem/actions'
import { Abis } from 'viem/tempo'
import { Session } from 'mppx/tempo'

const path = process.argv[2]
assert.ok(path, 'usage: node verify-meeting-evidence.mjs EVIDENCE.json')
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
const nativeService = payload.native_evidence_verified === true
assert.deepEqual(evidence.external_client_payout, payload.external_client_payout)
assert.ok(nativeService ? ['NOT_EXECUTED', 'NATIVE_LOCAL_PROTOCOL'].includes(evidence.external_client_payout.execution_tier) : evidence.external_client_payout.execution_tier === 'NOT_EXECUTED')
assert.equal(evidence.collusion_inference, 'NOT_ESTABLISHED')
assert.equal(evidence.sdk, 'mppx@0.13.4')
const expectedProvider = '0x8C8d35429F74ec245F8Ef2f4Fd1e551cFF97d650'
const expectedAuditor = '0x98e503f35D0a019cB0a251aD243a4cCFCF371F46'
const expectedToken = '0x20c0000000000000000000000000000000000000'
const escrow = '0x4d50500000000000000000000000000000000000'
assert.equal(evidence.provider, expectedProvider)
assert.equal(evidence.auditor, expectedAuditor)
assert.equal(evidence.token, expectedToken)
assert.ok(['charge', 'session'].includes(evidence.flow))
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
  digest(await readFile(new URL('meeting-local.mjs', import.meta.url))))
assert.equal(evidence.source_hashes.package_lock,
  digest(await readFile(new URL('package-lock.json', import.meta.url))))
const due = BigInt(payload.internal_service_due_atomic)
const net = BigInt(evidence.auditor_balance_after) - BigInt(evidence.auditor_balance_before)
assert.equal(net, BigInt(evidence.auditor_net_gain_atomic))
assert.equal(BigInt(evidence.gross_service_paid_atomic), due)
assert.equal(net + BigInt(evidence.settlement_gas_cost_atomic), due)
assert.ok(evidence.flow === 'charge' ? net === due : net <= due)
let verified = 0, transferred = 0n, firstBlock, lastBlock, opening
const touchBlock = block => { firstBlock = firstBlock === undefined || block < firstBlock ? block : firstBlock; lastBlock = lastBlock === undefined || block > lastBlock ? block : lastBlock }
const same = (a, b) => a.toLowerCase() === b.toLowerCase()
for (const payment of evidence.payments) {
  const hash = evidence.flow === 'charge' ? payment.transaction.hash : payment.receipt.txHash
  if (!hash) continue // Subsequent session voucher has no transaction until close.
  const receipt = await getTransactionReceipt(client, { hash })
  assert.equal(receipt.status, 'success')
  verified++
  touchBlock(receipt.blockNumber)
  if (evidence.flow === 'session') {
    const opened = parseEventLogs({ abi: Session.Precompile.escrowAbi, logs: receipt.logs, eventName: 'ChannelOpened', strict: false }).filter(e => same(e.address, escrow))
    assert.equal(opened.length, 1)
    opening = opened[0].args
    assert.ok(same(opening.payer, expectedProvider) && same(opening.payee, expectedAuditor) && same(opening.token, expectedToken))
    assert.equal(opening.deposit, 30000n)
    assert.equal(opening.channelId, evidence.session_channel_id)
    const deposits = parseEventLogs({ abi: Abis.tip20, logs: receipt.logs, eventName: 'Transfer', strict: false }).filter(e => same(e.address, expectedToken) && same(e.args.from, expectedProvider) && same(e.args.to, escrow))
    assert.equal(deposits.length, 1); assert.equal(deposits[0].args.amount, 30000n)
  }
  if (evidence.flow === 'charge') {
    assert.equal(String(receipt.blockNumber), payment.transaction.blockNumber)
    assert.deepEqual(receipt.logs.map(({ address, logIndex, topics, data }) =>
      ({ address, logIndex, topics, data })), payment.transaction.logs)
    const transfers = parseEventLogs({ abi: Abis.tip20, logs: receipt.logs,
      eventName: 'Transfer', strict: false }).filter(event =>
      event.address.toLowerCase() === evidence.token.toLowerCase() &&
      event.args.from.toLowerCase() === evidence.provider.toLowerCase() &&
      event.args.to.toLowerCase() === evidence.auditor.toLowerCase())
    assert.equal(transfers.length, 1)
    transferred += transfers[0].args.amount
  }
}
if (evidence.flow === 'session') {
  const receipt = await getTransactionReceipt(client, { hash: evidence.settlement.hash })
  assert.equal(receipt.status, 'success')
  touchBlock(receipt.blockNumber)
  assert.equal(String(receipt.blockNumber), evidence.settlement.blockNumber)
  assert.ok(opening, 'native channel opening is required')
  assert.ok(receipt.blockNumber >= firstBlock, 'close precedes channel opening')
  const actualState = await Session.Precompile.Chain.getChannelState(client, opening.channelId)
  assert.equal(actualState.deposit, 0n, 'native channel is not closed')
  assert.equal(actualState.settled, 0n)
  assert.equal(String(actualState.deposit), evidence.session_state.deposit)
  assert.equal(String(actualState.settled), evidence.session_state.settled)
  const expectedPaths = [['/audit', payload.terms.fee_atomic]]
  if (payload.verdict === 'ACCEPT' && payload.terms.acceptance_bonus_atomic) expectedPaths.push(['/approval', payload.terms.acceptance_bonus_atomic])
  assert.equal(evidence.payments.length, expectedPaths.length)
  let cumulative = 0n
  for (const [index, payment] of evidence.payments.entries()) {
    assert.equal(payment.path, expectedPaths[index][0])
    cumulative += BigInt(expectedPaths[index][1])
    assert.equal(payment.receipt.method, 'tempo'); assert.equal(payment.receipt.intent, 'session'); assert.equal(payment.receipt.status, 'success')
    assert.equal(payment.receipt.channelId, opening.channelId)
    assert.equal(payment.receipt.reference, opening.channelId)
    assert.equal(BigInt(payment.receipt.acceptedCumulative), cumulative)
    assert.equal(BigInt(payment.receipt.spent), cumulative)
    assert.equal(payment.receipt.units, index + 1)
  }
  assert.equal(cumulative, due)
  assert.deepEqual(receipt.logs.map(({ address, logIndex, topics, data }) =>
    ({ address, logIndex, topics, data })), evidence.settlement.logs)
  const closes = parseEventLogs({ abi: Session.Precompile.escrowAbi,
    logs: receipt.logs, eventName: 'ChannelClosed', strict: false }).filter(e => same(e.address, escrow))
  assert.equal(closes.length, 1)
  const closed = closes[0]
  assert.equal(closed.args.channelId, opening.channelId)
  assert.ok(same(closed.args.payer, expectedProvider) && same(closed.args.payee, expectedAuditor))
  const transfers = parseEventLogs({ abi: Abis.tip20, logs: receipt.logs, eventName: 'Transfer', strict: false }).filter(e => same(e.address, expectedToken) && same(e.args.from, escrow))
  const toAuditor = transfers.filter(e => same(e.args.to, expectedAuditor))
  assert.equal(toAuditor.length, 1); assert.equal(toAuditor[0].args.amount, due)
  const toProvider = transfers.filter(e => same(e.args.to, expectedProvider))
  const refund = 30000n - due
  assert.equal(toProvider.reduce((n, e) => n + e.args.amount, 0n), refund)
  assert.equal(transfers.length, refund ? 2 : 1)
  assert.equal(closed.args.settledToPayee, due)
  assert.equal(closed.args.refundedToPayer, 30000n - due)
  transferred = closed.args.settledToPayee
  verified++
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
assert.ok(evidence.flow === 'session' ? [402, 410].includes(evidence.events.at(-1).status) :
  evidence.events.at(-1).status === 402)
assert.ok(evidence.events.some(event => event.status === 402 && event.challenge?.intent === evidence.flow))
assert.equal(evidence.false_approval, payload.oracle.status === 'FAIL' && payload.verdict === 'ACCEPT')
console.log(JSON.stringify({ status: 'PASS', flow: evidence.flow, transactions_verified: verified,
  service_paid_atomic: String(transferred), auditor_net_gain_atomic: String(auditorAfter - auditorBefore), historical_balances_verified: true, external_client_payout: evidence.external_client_payout.execution_tier }))
