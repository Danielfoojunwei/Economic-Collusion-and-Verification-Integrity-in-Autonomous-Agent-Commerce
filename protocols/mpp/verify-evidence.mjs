import assert from 'node:assert/strict'
import { createHash } from 'node:crypto'
import { readFile } from 'node:fs/promises'
import { fileURLToPath } from 'node:url'
import { resolve } from 'node:path'

import { createClient, defineChain, http, parseEventLogs } from 'viem'
import { getTransactionReceipt } from 'viem/actions'
import { Abis } from 'viem/tempo'
import { Session } from 'mppx/tempo'

const path = resolve(process.env.MPP_EVIDENCE_DIR ??
  fileURLToPath(new URL('../../artifacts/gates/G6/W14/', import.meta.url)), 'evidence.json')
const evidence = JSON.parse(await readFile(path, 'utf8'))
const rpcUrl = process.env.MPP_TEMPO_RPC_URL ?? 'http://127.0.0.1:18547'
const rpcEndpoint = new URL(rpcUrl)
assert.equal(rpcEndpoint.protocol, 'http:')
assert.ok(['127.0.0.1', 'localhost', '[::1]'].includes(rpcEndpoint.hostname))
const chain = defineChain({ id: 1337, name: 'Tempo Localnet',
  nativeCurrency: { decimals: 18, name: 'USD', symbol: 'USD' },
  rpcUrls: { default: { http: [rpcUrl] } } })
const client = createClient({ chain, transport: http(rpcUrl, { retryCount: 0 }) })

assert.equal(await client.request({ method: 'eth_chainId' }), '0x539')
assert.equal(evidence.chainId, 1337)
assert.equal(evidence.execution_tier, 'NATIVE_LOCAL_PROTOCOL')
assert.equal(evidence.model_execution_tier, 'NOT_APPLICABLE')
for (const outcome of [evidence.charge, evidence.session, evidence.boundedSession])
  assert.equal(outcome.execution_tier, 'NATIVE_LOCAL_PROTOCOL')
for (const [name, file] of Object.entries({ packageLock: 'package-lock.json',
  runner: 'test-local.mjs', verifier: 'verify-evidence.mjs' })) {
  const actual = `sha256:${createHash('sha256').update(
    await readFile(new URL(file, import.meta.url))).digest('hex')}`
  assert.equal(evidence.sourceHashes[name], actual)
}
assert.equal(evidence.sdk, 'mppx@0.13.4')
assert.equal(evidence.imageDigest,
  'sha256:86f199f161be85d3610d990e5bc2653ece29de3ee9c91e8c8e768cf2b8c05c3b')

const transactions = [evidence.charge.transfer, evidence.session.openTx,
  evidence.session.settlementTx, evidence.boundedSession.boundedOpenTx,
  evidence.boundedSession.boundedCloseTx]
for (const recorded of transactions) {
  const live = await getTransactionReceipt(client, { hash: recorded.hash })
  assert.equal(live.status, 'success')
  assert.equal(live.blockNumber.toString(), recorded.blockNumber)
  assert.deepEqual(live.logs.map((entry) => ({ address: entry.address,
    logIndex: entry.logIndex, topics: entry.topics, data: entry.data })), recorded.logs)
}

const transfer = parseEventLogs({ abi: Abis.tip20, logs: evidence.charge.transfer.logs,
  eventName: 'Transfer', strict: false }).find((entry) =>
    entry.address.toLowerCase() === evidence.token.toLowerCase() &&
    entry.args.from.toLowerCase() === evidence.payer.toLowerCase() &&
    entry.args.to.toLowerCase() === evidence.payee.toLowerCase())
assert.ok(transfer)
assert.equal(transfer.args.amount, 10_000n)
assert.equal(evidence.charge.receipt.reference, evidence.charge.transfer.hash)
assert.equal(BigInt(evidence.charge.payeeAfter) - BigInt(evidence.charge.payeeBefore), 10_000n)
assert.equal(evidence.charge.replay.status, 402)

const escrow = Session.Precompile.escrowAbi
const opened = parseEventLogs({ abi: escrow, logs: evidence.session.openTx.logs,
  eventName: 'ChannelOpened', strict: false })[0]
const closed = parseEventLogs({ abi: escrow, logs: evidence.session.settlementTx.logs,
  eventName: 'ChannelClosed', strict: false })[0]
assert.equal(opened.args.channelId, evidence.session.channelId)
assert.equal(opened.args.deposit, 50_000n)
assert.equal(closed.args.channelId, evidence.session.channelId)
assert.equal(closed.args.settledToPayee, 20_000n)
assert.equal(closed.args.refundedToPayer, 30_000n)
assert.equal(evidence.session.firstReceipt.txHash, evidence.session.openTx.hash)
assert.equal(evidence.session.closeReceipt.txHash, evidence.session.settlementTx.hash)
assert.equal(evidence.session.invalidSignature.status, 402)
assert.equal(evidence.session.replay.status, 402)
assert.equal(BigInt(evidence.session.finalState.deposit), 0n)

const boundedClosed = parseEventLogs({ abi: escrow,
  logs: evidence.boundedSession.boundedCloseTx.logs,
  eventName: 'ChannelClosed', strict: false })[0]
assert.equal(boundedClosed.args.channelId, evidence.boundedSession.channelId)
assert.equal(boundedClosed.args.settledToPayee, 10_000n)
assert.equal(boundedClosed.args.refundedToPayer, 0n)
assert.match(evidence.boundedSession.blockedError, /exceeds local maxDeposit/)

const httpEvents = evidence.events.filter((event) => event.type === 'HTTP')
assert.ok(httpEvents.some((event) => event.path === '/charge' && event.status === 402))
assert.ok(httpEvents.some((event) => event.path === '/charge' && event.status === 200 &&
  event.credentialAction === 'hash'))
assert.ok(httpEvents.some((event) => event.path === '/session' && event.status === 200 &&
  event.credentialAction === 'open'))
assert.ok(httpEvents.some((event) => event.path === '/session' && event.status === 200 &&
  event.credentialAction === 'voucher'))
assert.ok(httpEvents.some((event) => event.path === '/session' && event.status === 204 &&
  event.credentialAction === 'close'))

console.log(JSON.stringify({ status: 'PASS', chainId: 1337,
  transactionsVerified: transactions.length, httpEvents: httpEvents.length,
  chargeReplayDenied: true, voucherReplayDenied: true,
  invalidVoucherDenied: true, boundedSpendDenied: true }))
