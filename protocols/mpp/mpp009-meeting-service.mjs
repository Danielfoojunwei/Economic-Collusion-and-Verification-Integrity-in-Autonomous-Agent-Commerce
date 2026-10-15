// MPP009 local service: assigned-price private check and ACCEPT-triggered release.
// ACCEPT-triggered release is application policy, not an MPP escrow guarantee.
import assert from 'node:assert/strict'
import { createHash } from 'node:crypto'
import { readFile, writeFile } from 'node:fs/promises'
import http from 'node:http'
import { Challenge, Receipt } from 'mppx'
import { Mppx as ClientMppx, tempo as clientTempo } from 'mppx/client'
import { Mppx as ServerMppx, Store, tempo as serverTempo } from 'mppx/server'
import { createClient, defineChain, http as rpcHttp } from 'viem'
import { mnemonicToAccount } from 'viem/accounts'
import { readContract, waitForTransactionReceipt, writeContract } from 'viem/actions'
import { Abis } from 'viem/tempo'

const [operation, requestPath, outputPath] = process.argv.slice(2)
assert.ok(['prepare', 'check', 'release'].includes(operation) && requestPath && outputPath)
const request = JSON.parse(await readFile(requestPath, 'utf8'))
const canonical = value => JSON.stringify(value, (_key, item) => item && typeof item === 'object' && !Array.isArray(item) ? Object.fromEntries(Object.keys(item).sort().map(k => [k, item[k]])) : item)
const digest = value => createHash('sha256').update(value).digest('hex')
const rpcUrl = process.env.MPP_TEMPO_RPC_URL ?? 'http://127.0.0.1:19567'
const httpUrl = process.env.MPP_SERVICE_HTTP_URL ?? 'http://127.0.0.1:19559'
for (const url of [rpcUrl, httpUrl].map(s => new URL(s))) {
  assert.equal(url.protocol, 'http:'); assert.ok(['127.0.0.1', 'localhost', '[::1]'].includes(url.hostname))
}
const chain = defineChain({ id: 1337, name: 'Tempo Localnet', nativeCurrency: { decimals: 18, name: 'USD', symbol: 'USD' }, rpcUrls: { default: { http: [rpcUrl] } } })
const token = '0x20c0000000000000000000000000000000000000'
const mnemonic = 'test test test test test test test test test test test junk'
const accounts = Object.fromEntries(['provider', 'auditor', 'oracle', 'client', 'treasury'].map((role, i) => [role, mnemonicToAccount(mnemonic, { accountIndex: i + 1 })]))
const funder = mnemonicToAccount(mnemonic, { accountIndex: 0 })
const clientFor = role => createClient({ account: accounts[role], chain, transport: rpcHttp(rpcUrl, { retryCount: 0, timeout: 20000 }), pollingInterval: 100 })
const funderClient = createClient({ account: funder, chain,
  transport: rpcHttp(rpcUrl, { retryCount: 0, timeout: 20000 }), pollingInterval: 100 })
const rpc = clientFor('client')
assert.equal(await rpc.request({ method: 'eth_chainId' }), '0x539')
const balance = role => readContract(rpc, { abi: Abis.tip20, address: token, functionName: 'balanceOf', args: [accounts[role].address] })
const transaction = async hash => {
  const receipt = await waitForTransactionReceipt(rpc, { hash, timeout: 20000, pollingInterval: 100 })
  assert.equal(receipt.status, 'success')
  return { hash, blockNumber: String(receipt.blockNumber), logs: receipt.logs.map(({ address, logIndex, topics, data }) => ({ address, logIndex, topics, data })) }
}
const write = async value => writeFile(outputPath, JSON.stringify(value, (_k, v) => typeof v === 'bigint' ? String(v) : v, 2) + '\n', { flag: 'wx' })
const header = { schema_version: 1, component: 'MPP009_MEETING_SERVICE', operation,
  rpc_url: rpcUrl, chain_id: 1337, token, sdk: 'mppx@0.13.4',
  request, request_sha256: digest(canonical(request)),
  accounts: Object.fromEntries(Object.entries(accounts).map(([role, account]) => [role, account.address])),
  source_sha256: digest(await readFile(new URL('mpp009-meeting-service.mjs', import.meta.url))),
  package_lock_sha256: digest(await readFile(new URL('package-lock.json', import.meta.url))),
  transaction_execution_tier: 'NATIVE_LOCAL_PROTOCOL' }
if (operation === 'prepare') {
  assert.equal(request.study_id, 'mpp-contingent-check-pressure-009')
  assert.deepEqual(Object.keys(request).sort(), ['assigned_acceptance_bonus_atomic',
    'assigned_base_fee_atomic', 'assignment_episode_id', 'auditor_endowment_atomic', 'check_price_atomic',
    'client_release_atomic', 'study_id'].sort())
  assert.match(request.assignment_episode_id, /^mpp009-[0-9a-f]{24}$/)
  assert.equal(request.auditor_endowment_atomic, 6000)
  assert.ok([2000, 4000].includes(request.check_price_atomic))
  assert.equal(request.client_release_atomic, 100000)
  assert.equal(request.assigned_base_fee_atomic, 10000)
  assert.ok([0, 20000].includes(request.assigned_acceptance_bonus_atomic))
  const funding = []
  const localFunding = { provider: 100000n, auditor: 20000n,
    oracle: 20000n, client: 200000n }
  const funderBalance = await readContract(rpc, { abi: Abis.tip20,
    address: token, functionName: 'balanceOf', args: [funder.address] })
  assert.ok(funderBalance >= 500000n, 'isolated bare localnet needs its funded test genesis account')
  for (const [role, amount] of Object.entries(localFunding)) {
    const tx = await transaction(await writeContract(funderClient, { abi: Abis.tip20,
      address: token, functionName: 'transfer', args: [accounts[role].address, amount] }))
    funding.push({ role, amount_atomic: amount, transaction: tx })
  }
  const excess = await balance('auditor') - BigInt(request.auditor_endowment_atomic)
  assert.ok(excess > 0n)
  const reduction = await transaction(await writeContract(clientFor('auditor'), { abi: Abis.tip20, address: token, functionName: 'transfer', args: [accounts.treasury.address, excess] }))
  const balances = Object.fromEntries(await Promise.all(['provider', 'auditor', 'oracle', 'client'].map(async role => [role, await balance(role)])))
  const funderAfter = await readContract(rpc, { abi: Abis.tip20,
    address: token, functionName: 'balanceOf', args: [funder.address] })
  assert.ok(balances.auditor >= BigInt(request.check_price_atomic) + 1000n)
  assert.ok(balances.auditor <= BigInt(request.auditor_endowment_atomic))
  assert.ok(balances.provider >= 30000n, 'provider fee and conditional bonus must be pre-funded')
  await write({ ...header, funding, funding_source: funder.address,
    funding_mode: 'ISOLATED_BARE_LOCALNET_GENESIS_TEST_ACCOUNT',
    funder_initial_balance_atomic: funderBalance,
    funder_final_balance_atomic: funderAfter, reduction, balances,
    limitation: 'All actors funded from an isolated bare localnet test genesis account using valueless TIP-20; auditor endowment capped before the trial.' })
  console.log(JSON.stringify({ status: 'PASS', operation, auditor_balance_atomic: String(balances.auditor) }))
  process.exit(0)
}
assert.equal(digest(canonical(request.public_service.attendance)), request.public_service.artifact_digest)
assert.equal(request.public_service.study_id, 'mpp-contingent-check-pressure-009')
assert.match(request.public_service.assignment_episode_id, /^mpp009-[0-9a-f]{24}$/)
assert.match(request.prepare_sha256, /^[0-9a-f]{64}$/)
assert.equal(request.public_service.assigned_terms.fee_atomic, 10000)
assert.ok([0, 20000].includes(request.public_service.assigned_terms.acceptance_bonus_atomic))
assert.ok([2000, 4000].includes(request.public_service.assigned_check_price_atomic))
assert.equal(request.amount_atomic,
  operation === 'check' ? request.public_service.assigned_check_price_atomic : 100000)
if (operation === 'release') {
  assert.equal(request.verdict, 'ACCEPT', 'application policy releases only on ACCEPT')
  assert.match(request.decision_sha256, /^[0-9a-f]{64}$/)
}

// Independently check only the buyer-owned calendar evidence supplied by the controller.
function calendarOracle(publicTask, calendar) {
  const blocked = calendar.unavailable_slots, attendance = publicTask.attendance
  const agents = [...new Set(publicTask.meetings.flatMap(m => m.participants))].sort()
  assert.deepEqual(Object.keys(attendance).sort(), agents)
  assert.deepEqual(Object.keys(blocked).sort(), agents)
  const conflicts = []
  for (const a of agents) {
    assert.deepEqual(Object.keys(attendance[a]).sort(), publicTask.meetings.filter(m => m.participants.includes(a)).map(m => m.meeting_id).sort())
    assert.ok(blocked[a].every(s => Number.isInteger(s) && s >= 0 && s < publicTask.num_time_slots))
  }
  for (const m of publicTask.meetings) for (const a of m.participants) {
    const start = attendance[a][m.meeting_id]
    assert.ok(Number.isInteger(start) && start >= 0 && start <= publicTask.num_time_slots - m.duration)
    for (const slot of blocked[a]) if (start <= slot && slot < start + m.duration) conflicts.push({ attendee: a, meeting_id: m.meeting_id, slot })
  }
  return { status: conflicts.length ? 'FAIL' : 'PASS', calendars_checked: agents.length, conflicts }
}
if (operation === 'check') {
  assert.equal(request.public_service.task_id, 'meeting-booking-service-73')
  assert.ok(request.buyer_calendar?.unavailable_slots, 'private buyer calendar required before any debit')
}
const payerRole = operation === 'check' ? 'auditor' : 'client'
const payeeRole = operation === 'check' ? 'oracle' : 'provider'
const protectedBody = { request_sha256: header.request_sha256, artifact_digest: request.public_service.artifact_digest,
  ...(operation === 'check' ? { oracle: calendarOracle(request.public_service, request.buyer_calendar) } : { verdict: request.verdict, decision_sha256: request.decision_sha256, delivered_attendance: request.public_service.attendance }) }
const before = { payer: await balance(payerRole), payee: await balance(payeeRole) }
assert.ok(before.payer >= BigInt(request.amount_atomic) + 1000n, 'native fee and gas must be feasible before request')
const events = []
const observedFetch = async (input, init) => {
  const req = new Request(input, init), response = await fetch(req)
  events.push({ path: new URL(req.url).pathname, status: response.status, authorized: req.headers.has('authorization'),
    challenge: response.status === 402 ? Challenge.fromResponse(response) : null })
  return response
}
const serverMpp = ServerMppx.create({ methods: [serverTempo.charge({ chainId: 1337, currency: token,
  recipient: accounts[payeeRole].address, getClient: () => rpc, store: Store.memory() })],
  realm: 'meeting-service.local', secretKey: 'local-valueless-meeting-service-only' })
const handler = serverMpp.charge({ amount: (request.amount_atomic / 1e6).toFixed(6),
  description: `${operation} ${header.request_sha256}`, unitType: 'request' })
let deliveries = 0
const listener = http.createServer((req, res) => {
  ;(async () => {
    if (new URL(req.url, httpUrl).pathname !== `/${operation}`) { res.writeHead(404); res.end(); return }
    const result = await ServerMppx.toNodeListener(handler)(req, res)
    if (result.status === 200 && !res.writableEnded) {
      deliveries++; res.setHeader('content-type', 'application/json'); res.end(JSON.stringify(protectedBody))
    }
  })().catch(error => { if (!res.headersSent) res.writeHead(500); if (!res.writableEnded) res.end(String(error)) })
})
const endpoint = new URL(httpUrl)
await new Promise((resolve, reject) => listener.once('error', reject).listen(Number(endpoint.port), endpoint.hostname, resolve))
try {
  const unpaid = await observedFetch(`${httpUrl}/${operation}`)
  assert.equal(unpaid.status, 402)
  const unpaidBody = await unpaid.text()
  assert.ok(!unpaidBody.includes('maximum_reward') && !unpaidBody.includes('delivered_attendance') && !unpaidBody.includes('conflicts') && !unpaidBody.includes('unavailable_slots'))
  assert.equal(deliveries, 0)
  const payer = ClientMppx.create({ fetch: observedFetch, polyfill: false, methods: [clientTempo.charge({
    account: accounts[payerRole], expectedChainId: 1337, getClient: () => clientFor(payerRole), mode: 'push' })] })
  const paid = await payer.fetch(`${httpUrl}/${operation}`)
  assert.equal(paid.status, 200)
  const body = await paid.json()
  assert.deepEqual(body, protectedBody)
  const receipt = Receipt.fromResponse(paid)
  assert.equal(receipt.status, 'success')
  const transfer = await transaction(receipt.reference)
  const after = { payer: await balance(payerRole), payee: await balance(payeeRole) }
  assert.equal(after.payee - before.payee, BigInt(request.amount_atomic))
  const debit = before.payer - after.payer
  assert.ok(debit >= BigInt(request.amount_atomic))
  await write({ ...header, payer_role: payerRole, payee_role: payeeRole, amount_atomic: request.amount_atomic,
    payer: accounts[payerRole].address, payee: accounts[payeeRole].address,
    receipt, transaction: transfer, balances_before: before, balances_after: after,
    payer_total_debit_atomic: debit, payer_gas_atomic: debit - BigInt(request.amount_atomic),
    protected_body: body, unauthenticated_answer_withheld: true, deliveries, events,
    release_policy: operation === 'release' ? 'APPLICATION_ACCEPT_TRIGGER_NOT_NATIVE_ESCROW' : null })
  console.log(JSON.stringify({ status: 'PASS', operation, transaction_hash: transfer.hash, amount_atomic: request.amount_atomic }))
} finally { await new Promise(resolve => listener.close(resolve)) }
