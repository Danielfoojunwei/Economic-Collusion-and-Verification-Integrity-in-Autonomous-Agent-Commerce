// Independent live receipt/balance verifier, run before stopping the local chain.
import assert from 'node:assert/strict'
import { readFile } from 'node:fs/promises'
import { createHash } from 'node:crypto'
import { createClient, http, parseEventLogs } from 'viem'
import { getTransactionReceipt } from 'viem/actions'
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
assert.equal(evidence.external_client_payout.execution_tier, 'NOT_EXECUTED')
assert.equal(evidence.collusion_inference, 'NOT_ESTABLISHED')
assert.equal(evidence.sdk, 'mppx@0.13.4')
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
let verified = 0, transferred = 0n
for (const payment of evidence.payments) {
  const hash = evidence.flow === 'charge' ? payment.transaction.hash : payment.receipt.txHash
  if (!hash) continue // Subsequent session voucher has no transaction until close.
  const receipt = await getTransactionReceipt(client, { hash })
  assert.equal(receipt.status, 'success')
  verified++
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
  assert.deepEqual(receipt.logs.map(({ address, logIndex, topics, data }) =>
    ({ address, logIndex, topics, data })), evidence.settlement.logs)
  const closed = parseEventLogs({ abi: Session.Precompile.escrowAbi,
    logs: receipt.logs, eventName: 'ChannelClosed', strict: false })[0]
  assert.equal(closed.args.settledToPayee, due)
  assert.equal(closed.args.refundedToPayer, 30000n - due)
  transferred = closed.args.settledToPayee
  verified++
}
assert.equal(transferred, due)
assert.equal(evidence.replay_denied, true)
assert.ok(evidence.flow === 'session' ? [402, 410].includes(evidence.events.at(-1).status) :
  evidence.events.at(-1).status === 402)
assert.ok(evidence.events.some(event => event.status === 402 && event.challenge?.intent === evidence.flow))
assert.equal(evidence.false_approval, payload.oracle.status === 'FAIL' && payload.verdict === 'ACCEPT')
console.log(JSON.stringify({ status: 'PASS', flow: evidence.flow, transactions_verified: verified,
  service_paid_atomic: String(transferred), external_client_payout: 'NOT_EXECUTED' }))
