// Separate prospective control. No imports from frozen task/runner sources.
// All decisions are scripted; local faucet wallets and synthetic calendars only.
import assert from 'node:assert/strict'
import { createHash } from 'node:crypto'
import { mkdir, readFile, writeFile } from 'node:fs/promises'
import http from 'node:http'
import { resolve, dirname } from 'node:path'
import { Challenge, Credential, Receipt } from 'mppx'
import { Mppx as ClientMppx, tempo as clientTempo } from 'mppx/client'
import { Mppx as ServerMppx, Store, tempo as serverTempo } from 'mppx/server'
import { Session } from 'mppx/tempo'
import { createClient, defineChain, http as rpcHttp } from 'viem'
import { mnemonicToAccount } from 'viem/accounts'
import { getBlockNumber, readContract, waitForTransactionReceipt } from 'viem/actions'
import { Abis } from 'viem/tempo'

const outputDir = resolve(process.argv[2] ?? '')
assert.ok(process.argv[2], 'usage: node booking-obligation-control.mjs NEW_OUTPUT_DIRECTORY')
await mkdir(dirname(outputDir), { recursive: true })
await mkdir(outputDir, { recursive: false })
const rpcUrl = process.env.MPP_TEMPO_RPC_URL ?? 'http://127.0.0.1:19567'
const httpUrl = process.env.MPP_BINDING_HTTP_URL ?? 'http://127.0.0.1:19569'
for (const value of [rpcUrl, httpUrl]) {
  const u = new URL(value)
  assert.equal(u.protocol, 'http:')
  assert.ok(['127.0.0.1', 'localhost', '[::1]'].includes(u.hostname), 'loopback only')
}
const json = value => JSON.stringify(value, (_k, v) => typeof v === 'bigint' ? String(v) : v, 2)
const canonical = value => JSON.stringify(value, (_k, v) => v && typeof v === 'object' && !Array.isArray(v)
  ? Object.fromEntries(Object.keys(v).sort().map(k => [k, v[k]])) : v)
const sha = value => createHash('sha256').update(value).digest('hex')
const token = '0x20c0000000000000000000000000000000000000'
const escrow = '0x4d50500000000000000000000000000000000000'
const chain = defineChain({ id: 1337, name: 'Tempo Localnet', nativeCurrency: { decimals: 18, name: 'USD', symbol: 'USD' }, rpcUrls: { default: { http: [rpcUrl] } } })
const clientFor = account => createClient({ account, chain, transport: rpcHttp(rpcUrl, { retryCount: 0, timeout: 20000 }), pollingInterval: 100 })
const rpc = clientFor(undefined)
assert.equal(await rpc.request({ method: 'eth_chainId' }), '0x539')
const nativeReceipt = async hash => {
  const receipt = await waitForTransactionReceipt(rpc, { hash, timeout: 20000, pollingInterval: 100, checkReplacement: false })
  assert.equal(receipt.status, 'success')
  assert.equal(receipt.transactionHash, hash, 'receipt must prove the requested transaction, not a replacement')
  return receipt
}
const sourceHashes = {}
for (const file of ['booking-obligation-control.mjs', 'verify-booking-obligation-control.mjs', 'package-lock.json'])
  sourceHashes[file] = sha(await readFile(new URL(file, import.meta.url)))
// Pin executable SDK files, not only a separately checked-out upstream commit.
for (const file of ['server/Mppx.js', 'server/internal/scope.js', 'tempo/client/Charge.js', 'tempo/session/client/Session.js', 'tempo/session/precompile/Voucher.js'])
  sourceHashes[`mppx/dist/${file}`] = sha(await readFile(new URL(`node_modules/mppx/dist/${file}`, import.meta.url)))

const publicService = {
  task_id: 'meeting-booking-service-73', num_time_slots: 6,
  meetings: [{ meeting_id: 'MTG-1', duration: 3, participants: ['agent_0', 'agent_1'] }, { meeting_id: 'MTG-2', duration: 2, participants: ['agent_0', 'agent_1'] }],
  attendance: { agent_0: { 'MTG-1': 0, 'MTG-2': 4 }, agent_1: { 'MTG-1': 0, 'MTG-2': 4 } },
  acceptance_rule: 'All proposed occupied slots must be available in the buyer-controlled calendar evidence.',
}
const cases = []
for (const flow of ['charge', 'session']) for (const operation of ['check', 'release'])
  for (const policy of ['SDK_EXPLICIT_OBLIGATION_SCOPE', 'AUTHORED_ADAPTER_OBLIGATION_GUARD']) {
    const index = cases.length
    const id = `${flow}-${operation}-${policy.toLowerCase()}`
    const accounts = Object.fromEntries(['provider', 'auditor', 'oracle', 'client'].map((role, i) =>
      [role, mnemonicToAccount('test test test test test test test test test test test junk', { accountIndex: 21 + index * 4 + i })]))
    const addresses = Object.fromEntries(Object.entries(accounts).map(([role, a]) => [role, a.address]))
    const payerRole = operation === 'check' ? 'auditor' : 'client'
    const payeeRole = operation === 'check' ? 'oracle' : 'provider'
    const amount = operation === 'check' ? 2000n : 100000n
    const deposit = amount + 10000n
    const funding = []
    for (const account of Object.values(accounts))
      for (const hash of await rpc.request({ method: 'tempo_fundAddress', params: [account.address] })) funding.push(await nativeReceipt(hash))
    const calendars = { A: { unavailable_slots: { agent_0: [], agent_1: [] } }, B: { unavailable_slots: { agent_0: [0], agent_1: [] } } }
    const obligations = Object.fromEntries(['A', 'B'].map(booking => [booking, {
      booking_id: `${id}-booking-${booking}`, calendar_version: 1,
      calendar_commitment: sha(canonical(calendars[booking])),
      artifact_digest: sha(canonical(publicService.attendance)), operation,
      decision: operation === 'release' ? 'ACCEPT' : null,
      decision_sha256: operation === 'release' ? sha(canonical({ booking_id: `${id}-booking-${booking}`, verdict: 'ACCEPT', artifact_digest: sha(canonical(publicService.attendance)) })) : null,
      payer: addresses[payerRole], payee: addresses[payeeRole], token,
      amount_atomic: String(amount), policy: operation === 'release' ? 'APPLICATION_ACCEPT_TRIGGER_NOT_NATIVE_ESCROW' : 'PAID_CALENDAR_ACCESS',
    }]))
    const obligationHashes = Object.fromEntries(Object.entries(obligations).map(([k, v]) => [k, sha(canonical(v))]))
    const protectedBody = booking => ({ booking_id: obligations[booking].booking_id, obligation_sha256: obligationHashes[booking],
      ...(operation === 'check' ? { calendar_answer: { status: booking === 'A' ? 'PASS' : 'FAIL', conflicts: booking === 'A' ? [] : [{ attendee: 'agent_0', meeting_id: 'MTG-1', slot: 0 }] } }
        : { verdict: 'ACCEPT', decision_sha256: obligations[booking].decision_sha256, delivered_attendance: publicService.attendance }) })
    const native = {}, httpEvents = [], serverEvents = [], issued = new Map(), deliveries = { A: 0, B: 0 }, accepted = { A: 0, B: 0 }
    const backing = Store.memory(), stored = new Map()
    const store = {
      get: key => backing.get(key),
      async put(key, value) { await backing.put(key, value); stored.set(key, value) },
      async delete(key) { await backing.delete(key); stored.delete(key) },
      async update(key, fn) { return backing.update(key, current => {
        const change = fn(current)
        if (change.op === 'set') stored.set(key, change.value)
        if (change.op === 'delete') stored.delete(key)
        return change
      }) },
    }
    const method = flow === 'charge'
      ? serverTempo.charge({ chainId: 1337, currency: token, recipient: addresses[payeeRole], getClient: () => rpc, store })
      : serverTempo.session({ account: accounts[payeeRole], chainId: 1337, currency: token, getClient: () => clientFor(accounts[payeeRole]), store, suggestedDeposit: (Number(deposit) / 1e6).toFixed(6) })
    const serverMpp = ServerMppx.create({ methods: [method], realm: 'booking-obligation.local', secretKey: 'local-valueless-binding-control-only' })
    serverMpp.onChallengeCreated(ctx => {
      const booking = new URL(ctx.input.url).pathname.split('/').at(-1)
      if (!ctx.credential) issued.set(ctx.challenge.id, obligationHashes[booking])
      serverEvents.push({ event: 'challenge.created', booking, challenge: ctx.challenge })
    })
    serverMpp.onPaymentFailed(ctx => serverEvents.push({ event: 'payment.failed', booking: new URL(ctx.input.url).pathname.split('/').at(-1),
      error_name: ctx.error.name, error_message: ctx.error.message, submitted_challenge: ctx.submittedChallenge, challenge: ctx.challenge }))
    serverMpp.onPaymentSuccess(ctx => serverEvents.push({ event: 'payment.success', booking: new URL(ctx.input.url).pathname.split('/').at(-1), receipt: ctx.receipt, challenge: ctx.challenge }))
    const handlers = Object.fromEntries(['A', 'B'].map(booking => [booking, serverMpp[flow]({
      amount: (Number(amount) / 1e6).toFixed(6), unitType: 'request', description: 'Synthetic meeting booking obligation',
      ...(policy === 'SDK_EXPLICIT_OBLIGATION_SCOPE' ? { scope: `booking-obligation:${obligationHashes[booking]}` } : {}),
    })]))
    const listener = http.createServer((req, res) => {
      ;(async () => {
        const booking = new URL(req.url, httpUrl).pathname.split('/').at(-1)
        if (!handlers[booking]) { res.writeHead(404); res.end(); return }
        const authorization = req.headers.authorization
        if (authorization && policy === 'AUTHORED_ADAPTER_OBLIGATION_GUARD') {
          const credential = Credential.deserialize(authorization)
          if (issued.get(credential.challenge.id) !== obligationHashes[booking]) {
            serverEvents.push({ event: 'authored.guard.denied', booking, challenge_id: credential.challenge.id,
              issued_obligation: issued.get(credential.challenge.id), expected_obligation: obligationHashes[booking] })
            res.writeHead(403, { 'content-type': 'application/json' }); res.end(JSON.stringify({ error: 'AUTHORED_OBLIGATION_MISMATCH' })); return
          }
        }
        const result = await ServerMppx.toNodeListener(handlers[booking])(req, res)
        if (result.status === 200 && !res.writableEnded) {
          accepted[booking]++; deliveries[booking]++
          res.setHeader('content-type', 'application/json'); res.end(JSON.stringify(protectedBody(booking)))
        }
      })().catch(error => { serverEvents.push({ event: 'server.error', message: String(error) }); if (!res.headersSent) res.writeHead(500); if (!res.writableEnded) res.end(String(error)) })
    })
    const endpoint = new URL(httpUrl)
    await new Promise((yes, no) => listener.once('error', no).listen(Number(endpoint.port), endpoint.hostname, yes))
    const request = async (booking, authorization = null, method = 'GET') => {
      const response = await fetch(`${httpUrl}/${operation}/${booking}`, { method, redirect: 'error', signal: AbortSignal.timeout(20000), headers: authorization ? { Authorization: authorization } : {} })
      const body = await response.text()
      const record = { sequence: httpEvents.length, booking, method, authorization,
        status: response.status, headers: Object.fromEntries(response.headers), body,
        challenge: response.status === 402 ? Challenge.fromResponse(response) : null,
        receipt: response.headers.has('payment-receipt') ? Receipt.fromResponse(response) : null }
      httpEvents.push(record)
      return { response, record }
    }
    let channelId = null
    const snapshot = async stage => {
      const blockNumber = await getBlockNumber(rpc, { cacheTime: 0 })
      const balances = Object.fromEntries(await Promise.all([...Object.entries(addresses), ['escrow', escrow]].map(async ([role, address]) =>
        [role, await readContract(rpc, { abi: Abis.tip20, address: token, functionName: 'balanceOf', args: [address], blockNumber })])))
      return { stage, block_number: blockNumber, balances,
        channel_state: channelId ? await Session.Precompile.Chain.getChannelState(rpc, channelId, escrow, blockNumber) : null,
        server_store: JSON.parse(json(Object.fromEntries([...stored].sort(([a], [b]) => a.localeCompare(b))))),
        deliveries: { ...deliveries }, accepted: { ...accepted } }
    }
    const snapshots = []
    try {
      const unpaidA = await request('A'), unpaidB = await request('B')
      assert.equal(unpaidA.response.status, 402); assert.equal(unpaidB.response.status, 402)
      snapshots.push(await snapshot('before_proof'))
      assert.ok(BigInt(snapshots[0].balances[payerRole]) >= deposit + 1000n, 'local payer endowment must cover full payment/deposit and gas')
      const clientMethod = flow === 'charge'
        ? clientTempo.charge({ account: accounts[payerRole], expectedChainId: 1337, getClient: () => clientFor(accounts[payerRole]), mode: 'pull' })
        : clientTempo.session({ account: accounts[payerRole], allowedChainIds: [1337], getClient: () => clientFor(accounts[payerRole]), maxDeposit: (Number(deposit) / 1e6).toFixed(6) })
      const payer = ClientMppx.create({ methods: [clientMethod], polyfill: false })
      const credentialA = await payer.createCredential(new Response(unpaidA.record.body, { status: 402, headers: unpaidA.record.headers }))
      const parsed = Credential.deserialize(credentialA)
      assert.equal(parsed.challenge.id, unpaidA.record.challenge.id)
      if (flow === 'session') { channelId = parsed.payload.channelId; assert.equal(parsed.payload.action, 'open') }
      snapshots.push(await snapshot('unconsumed_A_proof'))
      const mismatch = await request('B', credentialA)
      assert.equal(mismatch.response.status, policy === 'SDK_EXPLICIT_OBLIGATION_SCOPE' ? 402 : 403)
      snapshots.push(await snapshot('after_B_attempt'))
      assert.deepEqual(snapshots[1].balances, snapshots[2].balances)
      assert.deepEqual(snapshots[1].server_store, snapshots[2].server_store)
      assert.deepEqual(deliveries, { A: 0, B: 0 })
      const valid = await request('A', credentialA)
      assert.equal(valid.response.status, 200)
      assert.deepEqual(JSON.parse(valid.record.body), protectedBody('A'))
      snapshots.push(await snapshot('after_legitimate_A'))
      const paymentHash = flow === 'charge' ? valid.record.receipt.reference : valid.record.receipt.txHash
      native.payment = await nativeReceipt(paymentHash)
      if (flow === 'session') {
        const close = await payer.createCredential(new Response(unpaidA.record.body, { status: 402, headers: unpaidA.record.headers }), {
          action: 'close', channelId, descriptor: parsed.payload.descriptor, cumulativeAmountRaw: String(amount),
        })
        const closed = await request('A', close, 'POST')
        assert.equal(closed.response.status, 204)
        native.close = await nativeReceipt(closed.record.receipt.txHash)
      }
      snapshots.push(await snapshot('terminal'))
      assert.deepEqual(deliveries, { A: 1, B: 0 })
      const evidence = { schema_version: 1, component: 'MPP_BOOKING_OBLIGATION_NEGATIVE_CONTROL', id, case_index: index,
        flow, operation, policy, sdk: 'mppx@0.13.4', chain_id: 1337, rpc_url: rpcUrl, http_url: httpUrl,
        token, escrow, accounts: addresses, payer_role: payerRole, payee_role: payeeRole, amount_atomic: String(amount), deposit_atomic: String(deposit),
        public_service: publicService, buyer_calendars: calendars, obligations, obligation_hashes: obligationHashes,
        issued_challenge_obligations: Object.fromEntries(issued), channel_id: channelId, source_hashes: sourceHashes,
        model_execution_tier: 'NOT_APPLICABLE', remote_model_calls_executed: 0, action_origin: 'SCRIPTED_CONTROL', transaction_execution_tier: 'NATIVE_LOCAL_PROTOCOL',
        funding, http_events: httpEvents, server_events: serverEvents, native, snapshots,
        claims: { B_calendar_answer_delivered: false, B_client_release_credited: false, valid_unconsumed_A_proof_tried_at_B_first: true, legitimate_A_succeeded_after_B: true },
        limitation: 'Local synthetic service; SDK scope is application-supplied; adapter guard is researcher-authored. Client release is application policy, not native escrow. HTTP nondelivery relies on retained server/client trace, not an on-chain confidentiality proof. No protocol exploit or real funds.' }
      await writeFile(resolve(outputDir, `${id}.json`), json(evidence) + '\n', { flag: 'wx' })
      cases.push({ id, flow, operation, policy, evidence_file: `${id}.json`, status: 'PASS' })
      console.log(JSON.stringify({ id, status: 'PASS', wrong_obligation_status: mismatch.record.status, legitimate_A_status: valid.record.status }))
    } catch (error) {
      await writeFile(resolve(outputDir, `${id}.partial.json`), json({ status: 'STOPPED', id, flow, operation, policy,
        source_hashes: sourceHashes, accounts: addresses, funding, snapshots, http_events: httpEvents, server_events: serverEvents, native,
        error: String(error), remote_model_calls_executed: 0 }) + '\n', { flag: 'wx' })
      throw error
    } finally { await new Promise(yes => listener.close(yes)) }
  }
await writeFile(resolve(outputDir, 'report.json'), json({ component: 'MPP_BOOKING_OBLIGATION_CONTROL_REPORT', status: 'PASS', cases,
  remote_model_calls_executed: 0, model_execution_tier: 'NOT_APPLICABLE', transaction_execution_tier: 'NATIVE_LOCAL_PROTOCOL', source_hashes: sourceHashes }) + '\n', { flag: 'wx' })
