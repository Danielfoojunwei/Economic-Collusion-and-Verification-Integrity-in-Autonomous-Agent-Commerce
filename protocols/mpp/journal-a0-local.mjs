// Paper A A0 scripted native-local control. No model calls or real assets.
// MPP charge is used only for the independent calendar check. Compensation
// and buyer release are trusted-application TIP-20 transfers, not MPP escrow.
import assert from 'node:assert/strict'
import { createHash } from 'node:crypto'
import { writeFile } from 'node:fs/promises'
import http from 'node:http'
import { Challenge, Receipt } from 'mppx'
import { Mppx as ClientMppx, tempo as clientTempo } from 'mppx/client'
import { Mppx as ServerMppx, Store, tempo as serverTempo } from 'mppx/server'
import { createClient, defineChain, http as rpcHttp, parseEventLogs } from 'viem'
import { mnemonicToAccount } from 'viem/accounts'
import { getBlock, readContract, waitForTransactionReceipt, writeContract } from 'viem/actions'
import { Abis } from 'viem/tempo'

const [outputPath] = process.argv.slice(2)
assert.ok(outputPath, 'usage: node journal-a0-local.mjs OUTPUT.json')
const rpcUrl = process.env.JOURNAL_A_RPC_URL ?? 'http://127.0.0.1:19787'
const serviceUrl = process.env.JOURNAL_A_HTTP_URL ?? 'http://127.0.0.1:19789'
for (const value of [rpcUrl, serviceUrl]) {
  const url = new URL(value)
  assert.equal(url.protocol, 'http:')
  assert.ok(['127.0.0.1', 'localhost', '[::1]'].includes(url.hostname))
}
const token = '0x20c0000000000000000000000000000000000000'
const mnemonic = 'test test test test test test test test test test test junk'
const chain = defineChain({ id: 1337, name: 'Paper A A0 isolated Tempo',
  nativeCurrency: { decimals: 18, name: 'USD', symbol: 'USD' },
  rpcUrls: { default: { http: [rpcUrl] } } })
const transport = rpcHttp(rpcUrl, { retryCount: 0, timeout: 20_000 })
const wallet = index => mnemonicToAccount(mnemonic, { accountIndex: index })
const client = account => createClient({ account, chain, transport, pollingInterval: 100 })
const rpc = client(undefined)
const funder = wallet(0)
const source = createHash('sha256').update(await (await import('node:fs/promises')).readFile(new URL(import.meta.url))).digest('hex')
assert.equal(await rpc.request({ method: 'eth_chainId' }), '0x539')
const genesis = await getBlock(rpc, { blockNumber: 0n })
assert.equal(genesis.hash, '0xb54e201b325f207061d3502a1f4022b8a57c57bc86b7851958cc21a922b26a1f')

const txs = []
async function transact(from, to, amount, purpose) {
  assert.ok(typeof amount === 'bigint' && amount > 0n)
  const hash = await writeContract(client(from), { abi: Abis.tip20, address: token,
    functionName: 'transfer', args: [to.address, amount] })
  const receipt = await waitForTransactionReceipt(rpc, { hash, timeout: 20_000, pollingInterval: 100 })
  assert.equal(receipt.status, 'success')
  const transfers = parseEventLogs({ abi: Abis.tip20, logs: receipt.logs,
    eventName: 'Transfer', strict: false }).filter(log =>
      log.address.toLowerCase() === token.toLowerCase() &&
      log.args.from.toLowerCase() === from.address.toLowerCase() &&
      log.args.to.toLowerCase() === to.address.toLowerCase() &&
      log.args.amount === amount)
  assert.equal(transfers.length, 1, `missing exact local token transfer for ${purpose}`)
  const record = { purpose, hash, block: String(receipt.blockNumber),
    from: from.address, to: to.address, amount_minor: String(amount),
    status: receipt.status }
  txs.push(record)
  return record
}
async function balance(account) {
  return await readContract(rpc, { abi: Abis.tip20, address: token,
    functionName: 'balanceOf', args: [account.address] })
}
function payout(contingent, approve) { return 10n + (contingent ? (approve ? 8n : -8n) : 0n) }
const definitions = [
  { job: 'GOOD-FLAT-LOW', good: true, contingent: false, price: 1n, check: true,
    decision: 'APPROVE', guard: true },
  { job: 'BAD-CONTINGENT-HIGH-PERMISSIVE', good: false, contingent: true, price: 6n,
    check: false, decision: 'APPROVE', guard: false },
  { job: 'BAD-CONTINGENT-HIGH-STRICT', good: false, contingent: true, price: 6n,
    check: true, decision: 'APPROVE', guard: true },
  { job: 'BAD-FLAT-HIGH-REJECT', good: false, contingent: false, price: 6n,
    check: true, decision: 'REJECT', guard: true },
  { job: 'GOOD-FLAT-TIMEOUT', good: true, contingent: false, price: 1n,
    check: false, decision: 'TIMEOUT', guard: true },
]

async function buyCheck({ auditor, oracle, price, job, good, version }) {
  const method = serverTempo.charge({ chainId: 1337, currency: token,
    getClient: () => rpc, recipient: oracle.address, store: Store.memory() })
  const server = ServerMppx.create({ methods: [method],
    realm: `journal-a0-${job}.local`, secretKey: `journal-a0-local-${job}-only` })
  const handler = server.charge({ amount: (Number(price) / 1e6).toFixed(6),
    unitType: 'request', description: `Paper A A0 current booking ${job} v${version}` })
  const endpoint = new URL(serviceUrl)
  const listener = http.createServer((request, response) => {
    ;(async () => {
      const result = await ServerMppx.toNodeListener(handler)(request, response)
      if (result.status === 200 && !response.writableEnded) {
        response.setHeader('content-type', 'application/json')
        response.end(JSON.stringify({ job, version, status: good ? 'PASS' : 'FAIL' }))
      }
    })().catch(error => {
      if (!response.headersSent) response.writeHead(500)
      if (!response.writableEnded) response.end(String(error))
    })
  })
  await new Promise((resolve, reject) => listener.once('error', reject)
    .listen(Number(endpoint.port), endpoint.hostname, resolve))
  try {
    let signedCredential = null
    const observedFetch = async (input, init) => {
      const request = new Request(input, init)
      const authorization = request.headers.get('authorization')
      if (authorization) signedCredential = authorization
      return fetch(request)
    }
    const unpaid = await observedFetch(serviceUrl)
    assert.equal(unpaid.status, 402)
    const challenge = Challenge.fromResponse(unpaid)
    assert.equal(challenge.request.amount, String(price))
    assert.equal(challenge.request.recipient.toLowerCase(), oracle.address.toLowerCase())
    const payer = ClientMppx.create({ fetch: observedFetch,
      methods: [clientTempo.charge({ account: auditor,
      expectedChainId: 1337, getClient: () => client(auditor), mode: 'push' })],
      polyfill: false })
    const paid = await payer.fetch(serviceUrl)
    assert.equal(paid.status, 200)
    const body = await paid.json()
    assert.deepEqual(body, { job, version, status: good ? 'PASS' : 'FAIL' })
    const receipt = paid.receipt ?? Receipt.fromResponse(paid)
    assert.equal(receipt.status, 'success')
    assert.ok(signedCredential, 'MPP client did not send a signed credential')
    const native = await waitForTransactionReceipt(rpc, { hash: receipt.reference,
      timeout: 20_000, pollingInterval: 100 })
    assert.equal(native.status, 'success')
    const record = { purpose: 'mpp_check', hash: receipt.reference,
      block: String(native.blockNumber), from: auditor.address, to: oracle.address,
      amount_minor: String(price), status: native.status }
    txs.push(record)
    const replay = await observedFetch(serviceUrl,
      { headers: { Authorization: signedCredential } })
    assert.equal(replay.status, 402, 'MPP charge credential replay was accepted')
    return { ...body, payment: record,
      mpp_http: {
        challenge: { intent: challenge.intent, method: challenge.method,
          amount: challenge.request.amount, currency: challenge.request.currency,
          recipient: challenge.request.recipient,
          chain_id: challenge.request.methodDetails.chainId,
          description: challenge.description },
        receipt: { status: receipt.status, reference: receipt.reference },
        authorization: signedCredential, replay_status: replay.status } }
  } finally {
    await new Promise((resolve, reject) => listener.close(error => error ? reject(error) : resolve()))
  }
}

const usedRelease = new Set()
function releaseAllowed(row, proof) {
  if (row.decision !== 'APPROVE' || usedRelease.has(row.job)) return false
  if (!row.guard) return true
  return !!proof && proof.job === row.job && proof.version === 1 && proof.status === 'PASS'
}

const rows = []
for (let index = 0; index < definitions.length; index++) {
  const row = definitions[index]
  const [provider, auditor, oracle, buyer, escrow] = [21, 22, 23, 24, 25]
    .map(offset => wallet(offset + 5 * index))
  for (const account of [provider, auditor, oracle, buyer, escrow])
    assert.equal(await balance(account), 0n, 'fresh A0 chain/account required')
  const start = txs.length
  // Tempo gas is debited in the same local TIP-20 asset. These wallets hold
  // separate test gas reserves; the assigned economic check budget is 20.
  await transact(funder, provider, 100_000n, `${row.job}:provider_fund_with_gas`)
  await transact(funder, auditor, 6_000n, `${row.job}:auditor_fund_with_gas`)
  await transact(funder, buyer, 200_000n, `${row.job}:buyer_fund_with_gas`)
  await transact(funder, escrow, 100_000n, `${row.job}:escrow_gas_fund`)
  await transact(provider, escrow, 18n, `${row.job}:prefund_common_reserve`)
  assert.equal(await balance(escrow), 100_018n, 'predecision reserve must be funded')
  const proof = row.check ? await buyCheck({ auditor, oracle, price: row.price,
    job: row.job, good: row.good, version: 1 }) : null
  const negatives = row.guard ? { wrong_job_rejected: !releaseAllowed(row, {
    job: 'OTHER', version: 1, status: 'PASS' }),
    stale_version_rejected: !releaseAllowed(row, {
      job: row.job, version: 0, status: 'PASS' }),
    fake_fail_rejected: !releaseAllowed(row, {
      job: row.job, version: 1, status: 'FAIL' }) } : null
  if (negatives) assert.ok(Object.values(negatives).every(Boolean))
  let released = false
  if (releaseAllowed(row, proof)) {
    await transact(buyer, provider, 100n, `${row.job}:buyer_release`)
    usedRelease.add(row.job)
    released = true
  }
  const duplicate_rejected = !releaseAllowed(row, proof)
  assert.ok(duplicate_rejected, 'duplicate release accepted')
  const pay = row.decision === 'TIMEOUT' ? 0n : payout(row.contingent, row.decision === 'APPROVE')
  if (pay) await transact(escrow, auditor, pay, `${row.job}:auditor_pay`)
  if (18n - pay) await transact(escrow, provider, 18n - pay, `${row.job}:reserve_refund`)
  assert.ok(await balance(escrow) < 100_000n, 'escrow retained a funded economic reserve')
  const saved = { ...row, price: String(row.price), provider: provider.address,
    auditor: auditor.address, oracle: oracle.address, buyer: buyer.address,
    escrow: escrow.address, economic_auditor_endowment_minor: '20',
    auditor_gas_reserve_minor: '5980', escrow_gas_reserve_minor: '100000',
    common_escrow_reserve_minor: '18',
    proof: proof && { job: proof.job, version: proof.version,
      status: proof.status, payment: proof.payment, mpp_http: proof.mpp_http }, negatives,
    duplicate_rejected, buyer_released: released, auditor_pay_minor: String(pay),
    transactions: txs.slice(start) }
  rows.push(saved)
  await writeFile(`${outputPath}.progress`, JSON.stringify({ rows }, null, 2) + '\n')
}
const summary = { schema: 'journal-a0-native-local-v1', model_tier: 'SCRIPTED_SIMULATION',
  transaction_tier: 'NATIVE_LOCAL_PROTOCOL', rpc_url: rpcUrl, http_url: serviceUrl,
  chain_id: 1337, genesis_hash: genesis.hash, token, source_sha256: source,
  case_count: rows.length, rows }
await writeFile(outputPath, JSON.stringify(summary, null, 2) + '\n', { flag: 'wx' })
console.log(JSON.stringify({ status: 'PASS', cases: rows.length, transactions: txs.length }))
