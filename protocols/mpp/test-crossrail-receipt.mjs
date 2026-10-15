import assert from 'node:assert/strict'
import { createHash } from 'node:crypto'
import { mkdir, readFile, writeFile } from 'node:fs/promises'
import http from 'node:http'
import { test } from 'node:test'
import { fileURLToPath } from 'node:url'
import { resolve } from 'node:path'

import { Challenge, Credential, Receipt } from 'mppx'
import { Mppx as ClientMppx, tempo as clientTempo } from 'mppx/client'
import { Mppx as ServerMppx, Store, tempo as serverTempo } from 'mppx/server'
import { Session } from 'mppx/tempo'
import { createClient, defineChain, http as rpcHttp, parseEventLogs, parseUnits } from 'viem'
import { mnemonicToAccount } from 'viem/accounts'
import { Abis, Actions } from 'viem/tempo'
import { readContract, waitForTransactionReceipt } from 'viem/actions'

// These wallets and the pathUSD balance exist only on the pinned local Tempo image.
const rpcUrl = process.env.MPP_TEMPO_RPC_URL ?? 'http://127.0.0.1:18547'
const httpUrl = process.env.MPP_HTTP_URL ?? 'http://127.0.0.1:18548'
for (const value of [rpcUrl, httpUrl]) {
  const endpoint = new URL(value)
  assert.equal(endpoint.protocol, 'http:', 'W14 only permits plain HTTP to loopback')
  assert.ok(['127.0.0.1', 'localhost', '[::1]'].includes(endpoint.hostname),
    'W14 only permits loopback endpoints')
}
const pathUsd = '0x20c0000000000000000000000000000000000000'
const mnemonic = 'test test test test test test test test test test test junk'
const payer = mnemonicToAccount(mnemonic, { accountIndex: 1 })
const payee = mnemonicToAccount(mnemonic, { accountIndex: 2 })
const chain = defineChain({
  id: 1337,
  name: 'Tempo Localnet',
  nativeCurrency: { decimals: 18, name: 'USD', symbol: 'USD' },
  rpcUrls: { default: { http: [rpcUrl] } },
})
const transport = rpcHttp(rpcUrl, { retryCount: 0, timeout: 30_000 })
const publicClient = createClient({ chain, transport, pollingInterval: 100 })
const payerClient = createClient({ account: payer, chain, transport, pollingInterval: 100 })
const payeeClient = createClient({ account: payee, chain, transport, pollingInterval: 100 })
const balanceAbi = [{
  type: 'function', name: 'balanceOf', stateMutability: 'view',
  inputs: [{ name: 'account', type: 'address' }], outputs: [{ type: 'uint256' }],
}]
const evidenceDir = resolve(process.env.MPP_CROSSRAIL_EVIDENCE_DIR ??
  fileURLToPath(new URL('../../artifacts/gates/CROSSRAIL_RECEIPT_CONTROL/mpp/', import.meta.url)))
const reportPath = process.env.MPP_CROSSRAIL_REPORT_FILE
assert.ok(reportPath, 'receipt report file is required')
const report = JSON.parse(await readFile(reportPath, 'utf8'))
const digest = (value) => `sha256:${createHash('sha256').update(value).digest('hex')}`
const timestamp = () => new Date().toISOString()
const events = []
const credentialHeaders = new Map()
const results = { schemaVersion: 1, workOrder: 'CROSSRAIL_RECEIPT_CONTROL',
  execution_tier: 'NATIVE_LOCAL_PROTOCOL', model_execution_tier: 'NOT_APPLICABLE',
  report, reportSha256: digest(JSON.stringify(report)), chainId: chain.id,
  rpcUrl, httpUrl, token: pathUsd, payer: payer.address,
  payee: payee.address, imageDigest: 'sha256:86f199f161be85d3610d990e5bc2653ece29de3ee9c91e8c8e768cf2b8c05c3b',
  sdk: 'mppx@0.13.4', upstream: {
    mppx: 'd8d800f101ba1568f0d737e12574c0ae8f6b6e93',
    specs: '50309c8e67e6d64b5547f1cc354fb327bda1301e',
    docs: '39ec9f1b9f6f121d7c0920833476ce66186394c4',
  }, startedAt: timestamp(), events }

function log(type, value) { events.push({ at: timestamp(), type, ...value }) }
function json(value) { return JSON.stringify(value, (_key, item) => typeof item === 'bigint' ? item.toString() : item, 2) }

async function balance(account) {
  return readContract(publicClient, { abi: balanceAbi, address: pathUsd, args: [account], functionName: 'balanceOf' })
}

async function tx(hash) {
  const receipt = await waitForTransactionReceipt(publicClient, { hash, timeout: 30_000, pollingInterval: 100 })
  assert.equal(receipt.status, 'success', `transaction ${hash} failed`)
  return { hash, blockNumber: receipt.blockNumber.toString(), status: receipt.status,
    logs: receipt.logs.map((entry) => ({ address: entry.address, logIndex: entry.logIndex,
      topics: entry.topics, data: entry.data })) }
}

async function fund(account) {
  const hashes = await publicClient.request({ method: 'tempo_fundAddress', params: [account.address] })
  for (const hash of hashes) await tx(hash)
  log('LOCAL_FAUCET', { account: account.address, hashes })
}

async function observedFetch(input, init) {
  const request = new Request(input, init)
  const authorization = request.headers.get('authorization')
  const record = { method: request.method, path: new URL(request.url).pathname,
    credentialHash: authorization ? digest(authorization) : null }
  if (authorization) {
    credentialHeaders.set(record.credentialHash, authorization)
    const credential = Credential.deserialize(authorization)
    record.intent = credential.challenge.intent
    record.challengeId = credential.challenge.id
    record.credentialAction = credential.payload?.action ?? credential.payload?.type ?? null
    record.credentialPayload = credential.payload?.hash ? { hash: credential.payload.hash } : null
    if (credential.payload?.channelId) record.channelId = credential.payload.channelId
    if (credential.payload?.cumulativeAmount) record.cumulativeAmount = credential.payload.cumulativeAmount
  }
  const response = await fetch(request)
  record.status = response.status
  if (response.status === 200) {
    const body = await response.clone().text()
    record.responseBodySha256 = digest(body)
    record.responseBodyBytes = Buffer.byteLength(body)
  }
  const authenticate = response.headers.get('www-authenticate')
  if (authenticate) {
    const challenge = Challenge.fromResponse(response)
    record.challenge = { id: challenge.id, method: challenge.method, intent: challenge.intent,
      request: challenge.request, expires: challenge.expires }
  }
  const paymentReceipt = response.headers.get('payment-receipt')
  if (paymentReceipt) record.receipt = Receipt.fromResponse(response)
  log('HTTP', record)
  return response
}

async function server(handler) {
  const listener = http.createServer((req, res) => {
    (async () => {
      const payment = req.url?.startsWith('/charge') ? handler.charge : handler.session
      const result = await ServerMppx.toNodeListener(payment)(req, res)
      if (result.status === 200 && !res.writableEnded) {
        res.setHeader('content-type', 'application/json')
        res.end(JSON.stringify(report))
      }
    })().catch((error) => {
      log('SERVER_ERROR', { message: String(error) })
      if (!res.headersSent) res.writeHead(500)
      if (!res.writableEnded) res.end(String(error))
    })
  })
  const url = new URL(httpUrl)
  await new Promise((accept, reject) => listener.once('error', reject).listen(Number(url.port), url.hostname, accept))
  return listener
}

async function chargeTest() {
  const store = Store.memory()
  const payment = ServerMppx.create({
    methods: [serverTempo.charge({ chainId: chain.id, currency: pathUsd,
      getClient: () => publicClient, recipient: payee.address, store })],
    realm: 'local.mpp.dev', secretKey: 'research-local-mpp-charge-hmac-32-bytes',
  })
  const listener = await server({ charge: payment.charge({ amount: '0.01', description: 'local audit' }),
    session: payment.charge({ amount: '0.01' }) })
  try {
    const payerBefore = await balance(payer.address)
    const payeeBefore = await balance(payee.address)
    const challengeResponse = await observedFetch(`${httpUrl}/charge`)
    assert.equal(challengeResponse.status, 402)
    const challenge = Challenge.fromResponse(challengeResponse)
    assert.equal(challenge.intent, 'charge')
    assert.ok(Date.parse(challenge.expires) > Date.now())
    assert.equal(challenge.request.amount, parseUnits('0.01', 6).toString())
    assert.equal(challenge.request.currency.toLowerCase(), pathUsd.toLowerCase())
    assert.equal(challenge.request.recipient.toLowerCase(), payee.address.toLowerCase())

    const client = ClientMppx.create({ fetch: observedFetch,
      methods: [clientTempo.charge({ account: payer, expectedChainId: chain.id,
        getClient: () => payerClient, mode: 'push' })], polyfill: false })
    const response = await client.fetch(`${httpUrl}/charge`)
    assert.equal(response.status, 200)
    assert.deepEqual(await response.json(), report)
    const receipt = Receipt.fromResponse(response)
    assert.equal(receipt.method, 'tempo')
    assert.equal(receipt.status, 'success')
    const payerAfter = await balance(payer.address)
    const payeeAfter = await balance(payee.address)
    assert.equal(payeeAfter - payeeBefore, parseUnits('0.01', 6))
    assert.ok(payerBefore - payerAfter >= parseUnits('0.01', 6), 'payer covers transfer and local gas')

    const paymentHttp = events.filter((event) => event.type === 'HTTP' && event.path === '/charge' && event.credentialHash)
    assert.ok(paymentHttp.length >= 1)
    const originalCredential = paymentHttp.at(-1)
    const originalHash = originalCredential.credentialPayload?.hash ?? receipt.reference
    const settlement = await tx(originalHash)
    const transfers = parseEventLogs({ abi: Abis.tip20, logs: settlement.logs,
      eventName: 'Transfer', strict: false }).filter((entry) =>
      entry.address.toLowerCase() === pathUsd.toLowerCase() &&
      entry.args.from.toLowerCase() === payer.address.toLowerCase() &&
      entry.args.to.toLowerCase() === payee.address.toLowerCase())
    assert.equal(transfers.length, 1)
    assert.equal(transfers[0].args.amount, parseUnits('0.01', 6))
    const replayHeader = credentialHeaders.get(originalCredential.credentialHash)
    assert.ok(replayHeader)
    const replay = await observedFetch(`${httpUrl}/charge`, { headers: { Authorization: replayHeader } })
    assert.equal(replay.status, 402)
    const replayBody = await replay.text()
    assert.match(replayBody, /already been used/i)
    results.charge = { challenge, receipt, payerBefore, payerAfter, payeeBefore, payeeAfter,
      execution_tier: 'NATIVE_LOCAL_PROTOCOL',
      transfer: settlement, transferEvent: { name: transfers[0].eventName,
        args: transfers[0].args, logIndex: transfers[0].logIndex,
        transactionHash: transfers[0].transactionHash },
      credentialHash: originalCredential.credentialHash,
      replay: { status: replay.status, message: replayBody } }
  } finally { await new Promise((accept) => listener.close(accept)) }
}

async function sessionTest() {
  const store = Store.memory()
  const payment = ServerMppx.create({
    methods: [serverTempo.session({ account: payee, chainId: chain.id, currency: pathUsd,
      getClient: () => payeeClient, store, suggestedDeposit: '0.05' })],
    realm: 'local.mpp.dev', secretKey: 'research-local-mpp-session-hmac-32-bytes',
  })
  const listener = await server({ charge: payment.session({ amount: '0.01', unitType: 'request' }),
    session: payment.session({ amount: '0.01', unitType: 'request' }) })
  try {
    const payerBefore = await balance(payer.address)
    const payeeBefore = await balance(payee.address)
    const first402 = await observedFetch(`${httpUrl}/session`)
    assert.equal(first402.status, 402)
    const challenge = Challenge.fromResponse(first402)
    assert.equal(challenge.intent, 'session')
    assert.ok(Date.parse(challenge.expires) > Date.now())
    assert.equal(challenge.request.amount, parseUnits('0.01', 6).toString())
    assert.equal(challenge.request.currency.toLowerCase(), pathUsd.toLowerCase())
    assert.equal(challenge.request.recipient.toLowerCase(), payee.address.toLowerCase())

    const manager = clientTempo.session.manager({ client: payerClient, maxDeposit: '0.05',
      fetch: observedFetch, allowedChainIds: [chain.id] })
    const first = await manager.fetch(`${httpUrl}/session?item=1`)
    assert.equal(first.status, 200)
    assert.deepEqual(await first.json(), report)
    assert.ok(manager.channelId)
    assert.equal(manager.cumulative, parseUnits('0.01', 6))
    const channelId = manager.channelId
    const openState = await Session.Precompile.Chain.getChannelState(publicClient, channelId)
    assert.equal(openState.deposit, parseUnits('0.05', 6))
    const escrowAfterOpen = await balance(Session.Precompile.Protocol.tip20ChannelEscrow)
    assert.ok(escrowAfterOpen >= openState.deposit)
    const firstReceipt = first.receipt ?? Receipt.fromResponse(first)
    assert.equal(firstReceipt.status, 'success')
    assert.ok(firstReceipt.txHash)
    const openTx = await tx(firstReceipt.txHash)
    const openEvents = parseEventLogs({ abi: Session.Precompile.escrowAbi,
      logs: openTx.logs, strict: false })
    const openedEvent = openEvents.find((event) => event.eventName === 'ChannelOpened')
    assert.ok(openedEvent)
    assert.equal(openedEvent.args.channelId, channelId)

    const second = await manager.fetch(`${httpUrl}/session?item=2`)
    assert.equal(second.status, 200)
    assert.deepEqual(await second.json(), report)
    assert.equal(manager.channelId, channelId)
    assert.equal(manager.cumulative, parseUnits('0.02', 6))
    const secondReceipt = second.receipt ?? Receipt.fromResponse(second)
    assert.equal(secondReceipt.status, 'success')
    const beforeCloseState = await Session.Precompile.Chain.getChannelState(publicClient, channelId)
    assert.equal(beforeCloseState.deposit, openState.deposit)
    const payeeBeforeClose = await balance(payee.address)
    assert.equal(payeeBeforeClose, payeeBefore, 'vouchers alone have not transferred funds')

    const voucherHttp = events.filter((event) => event.type === 'HTTP' &&
      event.path === '/session' && event.credentialAction === 'voucher')
    assert.ok(voucherHttp.length >= 1, 'second request used native signed voucher')
    const voucherHeader = credentialHeaders.get(voucherHttp.at(-1).credentialHash)
    const voucherCredential = Credential.deserialize(voucherHeader)
    const invalidSignatureHeader = Credential.serialize({ ...voucherCredential,
      payload: { ...voucherCredential.payload, cumulativeAmount: '30000' } })
    const invalidSignature = await observedFetch(`${httpUrl}/session?item=2`,
      { headers: { Authorization: invalidSignatureHeader } })
    assert.equal(invalidSignature.status, 402)
    const invalidSignatureBody = await invalidSignature.text()
    assert.match(invalidSignatureBody, /signature|voucher|invalid/i)
    const replay = await observedFetch(`${httpUrl}/session?item=3`,
      { headers: { Authorization: voucherHeader } })
    assert.equal(replay.status, 402)
    const replayBody = await replay.text()
    assert.match(replayBody, /voucher|cumulative|already|insufficient/i)
    assert.equal(manager.cumulative, parseUnits('0.02', 6))

    const closeReceipt = await manager.close()
    assert.ok(closeReceipt)
    assert.equal(closeReceipt.channelId, channelId)
    assert.equal(BigInt(closeReceipt.acceptedCumulative), parseUnits('0.02', 6))
    assert.ok(closeReceipt.txHash, 'server submitted close to local chain')
    const settlementTx = await tx(closeReceipt.txHash)
    const closeEvents = parseEventLogs({ abi: Session.Precompile.escrowAbi,
      logs: settlementTx.logs, strict: false })
    const closedEvent = closeEvents.find((event) => event.eventName === 'ChannelClosed')
    assert.ok(closedEvent)
    assert.equal(closedEvent.args.channelId, channelId)
    assert.equal(closedEvent.args.settledToPayee, parseUnits('0.02', 6))
    assert.equal(closedEvent.args.refundedToPayer, parseUnits('0.03', 6))
    const finalState = await Session.Precompile.Chain.getChannelState(publicClient, channelId)
    const payerAfter = await balance(payer.address)
    const payeeAfter = await balance(payee.address)
    assert.ok(payeeAfter - payeeBefore > 0n, 'payee received settlement net of local gas')
    assert.ok(payeeAfter - payeeBefore <= parseUnits('0.02', 6))
    assert.ok(payerBefore - payerAfter >= parseUnits('0.02', 6))
    results.session = { challenge, channelId, firstReceipt, secondReceipt, closeReceipt,
      execution_tier: 'NATIVE_LOCAL_PROTOCOL',
      openState, beforeCloseState, finalState, escrowAfterOpen, payerBefore, payerAfter,
      payeeBefore, payeeAfter, payeeBeforeClose, settlementTx,
      openTx, openEvents: openEvents.map((event) => ({ name: event.eventName, args: event.args,
        logIndex: event.logIndex, transactionHash: event.transactionHash })),
      closeEvents: closeEvents.map((event) => ({ name: event.eventName, args: event.args,
        logIndex: event.logIndex, transactionHash: event.transactionHash })),
      replay: { status: replay.status, message: replayBody },
      invalidSignature: { status: invalidSignature.status, message: invalidSignatureBody } }

    const bounded = clientTempo.session.manager({ client: payerClient, maxDeposit: '0.01',
      fetch: observedFetch, allowedChainIds: [chain.id] })
    const boundedFirst = await bounded.fetch(`${httpUrl}/session?item=bounded-1`)
    assert.equal(boundedFirst.status, 200)
    assert.equal(bounded.cumulative, parseUnits('0.01', 6))
    const boundedId = bounded.channelId
    const boundedOpenState = await Session.Precompile.Chain.getChannelState(publicClient, boundedId)
    assert.equal(boundedOpenState.deposit, parseUnits('0.01', 6))
    const boundedOpenTx = await tx(boundedFirst.receipt.txHash)
    let blockedError = null
    let blockedStatus = null
    try {
      const boundedSecond = await bounded.fetch(`${httpUrl}/session?item=bounded-2`)
      blockedStatus = boundedSecond.status
    } catch (error) { blockedError = String(error) }
    assert.notEqual(blockedStatus, 200, 'client did not exceed its maximum deposit')
    assert.match(blockedError ?? '', /exceeds local maxDeposit/)
    assert.equal(bounded.cumulative, parseUnits('0.01', 6))
    const boundedClose = await bounded.close()
    assert.ok(boundedClose?.txHash)
    const boundedCloseTx = await tx(boundedClose.txHash)
    const boundedCloseEvents = parseEventLogs({ abi: Session.Precompile.escrowAbi,
      logs: boundedCloseTx.logs, strict: false })
    const boundedClosed = boundedCloseEvents.find((event) => event.eventName === 'ChannelClosed')
    assert.ok(boundedClosed)
    assert.equal(boundedClosed.args.settledToPayee, parseUnits('0.01', 6))
    assert.equal(boundedClosed.args.refundedToPayer, 0n)
    const boundedFinalState = await Session.Precompile.Chain.getChannelState(publicClient, boundedId)
    assert.equal(boundedFinalState.deposit, 0n)
    results.boundedSession = { channelId: boundedId, openState: boundedOpenState,
      execution_tier: 'NATIVE_LOCAL_PROTOCOL',
      finalState: boundedFinalState, firstReceipt: boundedFirst.receipt, blockedStatus,
      blockedError, closeReceipt: boundedClose, boundedOpenTx, boundedCloseTx,
      boundedClosedEvent: { name: boundedClosed.eventName, args: boundedClosed.args,
        logIndex: boundedClosed.logIndex, transactionHash: boundedClosed.transactionHash } }
  } finally { await new Promise((accept) => listener.close(accept)) }
}

test('MPP native local crossrail receipt charge and session', async (t) => {
  assert.equal(await publicClient.request({ method: 'eth_chainId' }), '0x539')
  await fund(payer)
  await fund(payee)
  await t.test('charge', chargeTest)
  await t.test('session', sessionTest)
  results.finishedAt = timestamp()
  results.sourceHashes = {
    packageLock: digest(await readFile(new URL('./package-lock.json', import.meta.url))),
    runner: digest(await readFile(new URL('./test-crossrail-receipt.mjs', import.meta.url))),
    verifier: digest(await readFile(new URL('./verify-evidence.mjs', import.meta.url))),
  }
  await mkdir(evidenceDir, { recursive: true })
  await writeFile(resolve(evidenceDir, 'evidence.json'), json(results) + '\n')
})
