// Independent read-only receipt, historical balance, scope and HTTP-trace verifier.
// No import of the runner, no signing, faucet, model client or mutation calls.
import assert from 'node:assert/strict'
import { createHash } from 'node:crypto'
import { readFile, writeFile } from 'node:fs/promises'
import { resolve, dirname } from 'node:path'
import { fileURLToPath } from 'node:url'
import { Challenge, Credential, Receipt } from 'mppx'
import { Session } from 'mppx/tempo'
import { createClient, http, parseEventLogs, keccak256, stringToHex } from 'viem'
import { mnemonicToAccount } from 'viem/accounts'
import { getTransactionReceipt, readContract } from 'viem/actions'
import { Abis } from 'viem/tempo'

const sha = value => createHash('sha256').update(value).digest('hex')
const canonical = value => JSON.stringify(value, (_k, v) => v && typeof v === 'object' && !Array.isArray(v)
  ? Object.fromEntries(Object.keys(v).sort().map(k => [k, v[k]])) : v)
const normalized = value => JSON.parse(JSON.stringify(value, (_k, v) => typeof v === 'bigint' ? String(v) : v))
const same = (a, b) => a.toLowerCase() === b.toLowerCase()
const token = '0x20c0000000000000000000000000000000000000'
const escrow = '0x4d50500000000000000000000000000000000000'

export async function verifyEvidence(e) {
  assert.equal(e.component, 'MPP_BOOKING_OBLIGATION_NEGATIVE_CONTROL')
  assert.equal(e.schema_version, 1)
  assert.equal(e.sdk, 'mppx@0.13.4')
  assert.equal(e.chain_id, 1337)
  assert.equal(e.model_execution_tier, 'NOT_APPLICABLE')
  assert.equal(e.remote_model_calls_executed, 0)
  assert.equal(e.action_origin, 'SCRIPTED_CONTROL')
  assert.equal(e.transaction_execution_tier, 'NATIVE_LOCAL_PROTOCOL')
  assert.ok(['charge', 'session'].includes(e.flow))
  assert.ok(['check', 'release'].includes(e.operation))
  assert.ok(['SDK_EXPLICIT_OBLIGATION_SCOPE', 'AUTHORED_ADAPTER_OBLIGATION_GUARD'].includes(e.policy))
  const expectedIndex = (e.flow === 'session' ? 4 : 0) + (e.operation === 'release' ? 2 : 0) + (e.policy === 'AUTHORED_ADAPTER_OBLIGATION_GUARD' ? 1 : 0)
  assert.equal(e.case_index, expectedIndex)
  assert.equal(e.id, `${e.flow}-${e.operation}-${e.policy.toLowerCase()}`)
  assert.equal(e.token, token); assert.equal(e.escrow, escrow)
  const actors = Object.fromEntries(['provider', 'auditor', 'oracle', 'client'].map((role, i) => [role,
    mnemonicToAccount('test test test test test test test test test test test junk', { accountIndex: 21 + expectedIndex * 4 + i }).address]))
  assert.deepEqual(e.accounts, actors)
  const amount = e.operation === 'check' ? 2000n : 100000n
  const payerRole = e.operation === 'check' ? 'auditor' : 'client'
  const payeeRole = e.operation === 'check' ? 'oracle' : 'provider'
  assert.equal(e.payer_role, payerRole); assert.equal(e.payee_role, payeeRole)
  assert.equal(e.amount_atomic, String(amount)); assert.equal(e.deposit_atomic, String(amount + 10000n))
  const payer = actors[payerRole], payee = actors[payeeRole]
  const attendance = { agent_0: { 'MTG-1': 0, 'MTG-2': 4 }, agent_1: { 'MTG-1': 0, 'MTG-2': 4 } }
  assert.deepEqual(e.public_service.attendance, attendance)
  assert.deepEqual(e.public_service.meetings, [{ meeting_id: 'MTG-1', duration: 3, participants: ['agent_0', 'agent_1'] }, { meeting_id: 'MTG-2', duration: 2, participants: ['agent_0', 'agent_1'] }])
  assert.equal(e.public_service.num_time_slots, 6)
  assert.deepEqual(e.buyer_calendars, { A: { unavailable_slots: { agent_0: [], agent_1: [] } }, B: { unavailable_slots: { agent_0: [0], agent_1: [] } } })
  for (const booking of ['A', 'B']) {
    const bookingId = `${e.id}-booking-${booking}`
    const obligation = { booking_id: bookingId, calendar_version: 1,
      calendar_commitment: sha(canonical(e.buyer_calendars[booking])), artifact_digest: sha(canonical(attendance)), operation: e.operation,
      decision: e.operation === 'release' ? 'ACCEPT' : null,
      decision_sha256: e.operation === 'release' ? sha(canonical({ booking_id: bookingId, verdict: 'ACCEPT', artifact_digest: sha(canonical(attendance)) })) : null,
      payer, payee, token, amount_atomic: String(amount), policy: e.operation === 'release' ? 'APPLICATION_ACCEPT_TRIGGER_NOT_NATIVE_ESCROW' : 'PAID_CALENDAR_ACCESS' }
    assert.deepEqual(e.obligations[booking], obligation)
    assert.equal(e.obligation_hashes[booking], sha(canonical(obligation)))
  }
  for (const file of ['booking-obligation-control.mjs', 'verify-booking-obligation-control.mjs', 'package-lock.json'])
    assert.equal(e.source_hashes[file], sha(await readFile(new URL(file, import.meta.url))))
  for (const file of ['server/Mppx.js', 'server/internal/scope.js', 'tempo/client/Charge.js', 'tempo/session/client/Session.js', 'tempo/session/precompile/Voucher.js'])
    assert.equal(e.source_hashes[`mppx/dist/${file}`], sha(await readFile(new URL(`node_modules/mppx/dist/${file}`, import.meta.url))))

  const events = e.http_events
  assert.equal(events.length, e.flow === 'session' ? 5 : 4)
  assert.deepEqual(events.map(x => [x.sequence, x.booking, x.method]), [[0, 'A', 'GET'], [1, 'B', 'GET'], [2, 'B', 'GET'], [3, 'A', 'GET'], ...(e.flow === 'session' ? [[4, 'A', 'POST']] : [])])
  assert.deepEqual(events.slice(0, 2).map(x => [x.status, x.authorization]), [[402, null], [402, null]])
  assert.ok(events[2].authorization)
  assert.equal(events[2].authorization, events[3].authorization, 'same still-unconsumed proof must succeed at A after B')
  const credential = Credential.deserialize(events[2].authorization)
  const metadata = challenge => JSON.parse(Buffer.from(challenge.opaque, 'base64url').toString('utf8'))
  for (const event of events.filter(x => x.status === 402)) {
    const parsed = Challenge.fromResponse(new Response(event.body, { status: 402, headers: event.headers }))
    assert.deepEqual(event.challenge, parsed)
    assert.ok(Challenge.verify(parsed, { secretKey: 'local-valueless-binding-control-only' }))
    assert.equal(parsed.request.amount, String(amount))
    assert.ok(same(parsed.request.currency, token) && same(parsed.request.recipient, payee))
  }
  const challengeA = Challenge.fromResponse(new Response(events[0].body, { status: 402, headers: events[0].headers }))
  assert.deepEqual(events[0].challenge, challengeA)
  assert.deepEqual(credential.challenge, challengeA)
  assert.ok(Challenge.verify(challengeA, { secretKey: 'local-valueless-binding-control-only' }), 'native SDK challenge provenance')
  assert.equal(credential.challenge.method, 'tempo'); assert.equal(credential.challenge.intent, e.flow)
  assert.equal(credential.challenge.request.amount, String(amount))
  assert.ok(same(credential.challenge.request.currency, token))
  assert.ok(same(credential.challenge.request.recipient, payee))
  assert.equal(credential.source, `did:pkh:eip155:1337:${payer}`)
  assert.equal(e.issued_challenge_obligations[challengeA.id], e.obligation_hashes.A)
  const failures = e.server_events.filter(x => x.event === 'payment.failed')
  const guards = e.server_events.filter(x => x.event === 'authored.guard.denied')
  if (e.policy === 'SDK_EXPLICIT_OBLIGATION_SCOPE') {
    assert.equal(events[2].status, 402)
    assert.equal(guards.length, 0)
    assert.equal(failures.length, 1)
    assert.equal(failures[0].booking, 'B')
    assert.equal(failures[0].submitted_challenge.id, challengeA.id)
    assert.match(failures[0].error_message, /opaque does not match this route/)
    assert.equal(metadata(credential.challenge)._mppx_scope, `booking-obligation:${e.obligation_hashes.A}`)
    assert.equal(metadata(events[1].challenge)._mppx_scope, `booking-obligation:${e.obligation_hashes.B}`)
  } else {
    assert.equal(events[2].status, 403)
    assert.equal(failures.length, 0)
    assert.equal(guards.length, 1)
    assert.equal(guards[0].booking, 'B')
    assert.equal(guards[0].challenge_id, challengeA.id)
    assert.equal(guards[0].issued_obligation, e.obligation_hashes.A)
    assert.equal(guards[0].expected_obligation, e.obligation_hashes.B)
    assert.equal(metadata(credential.challenge)._mppx_scope, undefined)
  }
  assert.equal(events[3].status, 200)
  const expectedBody = { booking_id: e.obligations.A.booking_id, obligation_sha256: e.obligation_hashes.A,
    ...(e.operation === 'check' ? { calendar_answer: { status: 'PASS', conflicts: [] } }
      : { verdict: 'ACCEPT', decision_sha256: e.obligations.A.decision_sha256, delivered_attendance: attendance }) }
  assert.deepEqual(JSON.parse(events[3].body), expectedBody)
  for (const event of events.filter(x => x !== events[3])) {
    assert.doesNotMatch(event.body, /calendar_answer|delivered_attendance|unavailable_slots|"conflicts"/)
  }
  const successes = e.server_events.filter(x => x.event === 'payment.success')
  assert.ok(successes.length >= 1 && successes.every(x => x.booking === 'A'))
  assert.ok(!e.server_events.some(x => x.event === 'server.error'))
  const stages = ['before_proof', 'unconsumed_A_proof', 'after_B_attempt', 'after_legitimate_A', 'terminal']
  assert.deepEqual(e.snapshots.map(x => x.stage), stages)
  const [before, proof, afterB, afterA, terminal] = e.snapshots
  for (const snapshot of [before, proof, afterB]) {
    assert.deepEqual(snapshot.deliveries, { A: 0, B: 0 }); assert.deepEqual(snapshot.accepted, { A: 0, B: 0 })
  }
  for (const snapshot of [afterA, terminal]) {
    assert.deepEqual(snapshot.deliveries, { A: 1, B: 0 }); assert.deepEqual(snapshot.accepted, { A: 1, B: 0 })
  }
  assert.deepEqual(before.balances, proof.balances, 'proof construction must only sign, not prepay')
  assert.deepEqual(proof.balances, afterB.balances, 'B must not debit or release native value')
  assert.deepEqual(proof.server_store, afterB.server_store, 'B must not advance accepted credit/replay state')
  assert.deepEqual(e.claims, { B_calendar_answer_delivered: false, B_client_release_credited: false, valid_unconsumed_A_proof_tried_at_B_first: true, legitimate_A_succeeded_after_B: true })

  for (const url of [e.rpc_url, e.http_url]) {
    const endpoint = new URL(url)
    assert.equal(endpoint.protocol, 'http:'); assert.ok(['127.0.0.1', 'localhost', '[::1]'].includes(endpoint.hostname))
  }
  const rpc = createClient({ transport: http(e.rpc_url, { retryCount: 0, timeout: 15000 }) })
  assert.equal(await rpc.request({ method: 'eth_chainId' }), '0x539')
  for (const [i, snapshot] of e.snapshots.entries()) {
    if (i) assert.ok(BigInt(snapshot.block_number) >= BigInt(e.snapshots[i - 1].block_number))
    for (const [role, address] of [...Object.entries(actors), ['escrow', escrow]]) {
      const actual = await readContract(rpc, { abi: Abis.tip20, address: token, functionName: 'balanceOf', args: [address], blockNumber: BigInt(snapshot.block_number) })
      assert.equal(String(actual), snapshot.balances[role], `historical ${snapshot.stage} ${role} balance`)
    }
    if (snapshot.channel_state) {
      const state = await Session.Precompile.Chain.getChannelState(rpc, e.channel_id, escrow, BigInt(snapshot.block_number))
      assert.deepEqual(normalized(state), snapshot.channel_state)
    }
  }
  const actualPayment = await getTransactionReceipt(rpc, { hash: e.native.payment.transactionHash })
  assert.equal(actualPayment.status, 'success')
  assert.deepEqual(normalized(actualPayment), e.native.payment)
  const signedTransaction = e.flow === 'charge' ? credential.payload.signature : credential.payload.transaction
  assert.equal(keccak256(signedTransaction), actualPayment.transactionHash, 'the exact A proof must bind to the executed native transaction')
  assert.ok(actualPayment.blockNumber > BigInt(afterB.block_number), 'native A operation must follow rejected B')
  assert.ok(actualPayment.blockNumber <= BigInt(afterA.block_number))
  for (const saved of e.funding) {
    const actual = await getTransactionReceipt(rpc, { hash: saved.transactionHash })
    assert.equal(actual.status, 'success')
    assert.deepEqual(normalized(actual), saved)
    assert.ok(actual.blockNumber <= BigInt(before.block_number), 'all endowment funding must precede the control')
  }
  const receipt = Receipt.fromResponse(new Response(events[3].body, { status: 200, headers: events[3].headers }))
  assert.deepEqual(receipt, events[3].receipt)
  assert.equal(receipt.status, 'success')
  const transfers = native => parseEventLogs({ abi: Abis.tip20, logs: native.logs, eventName: 'Transfer', strict: false }).filter(x => same(x.address, token))
  let payout, closingGas = 0n
  if (e.flow === 'charge') {
    assert.equal(receipt.reference, actualPayment.transactionHash)
    assert.equal(e.channel_id, null); assert.equal(e.native.close, undefined)
    const paid = transfers(actualPayment).filter(x => same(x.args.from, payer) && same(x.args.to, payee))
    assert.equal(paid.length, 1); assert.equal(paid[0].args.amount, amount)
    const memos = parseEventLogs({ abi: Abis.tip20, logs: actualPayment.logs, eventName: 'TransferWithMemo', strict: false }).filter(x => same(x.address, token) && same(x.args.from, payer) && same(x.args.to, payee))
    assert.equal(memos.length, 1)
    assert.equal(memos[0].args.memo.slice(-14).toLowerCase(), keccak256(stringToHex(challengeA.id)).slice(2, 16).toLowerCase(), 'native memo binds payment to A challenge')
    payout = BigInt(terminal.balances[payeeRole]) - BigInt(before.balances[payeeRole])
    assert.equal(payout, amount)
  } else {
    assert.equal(credential.payload.action, 'open')
    assert.equal(credential.payload.channelId, e.channel_id)
    assert.equal(credential.payload.cumulativeAmount, String(amount))
    assert.ok(Session.Precompile.Voucher.verifyVoucher(escrow, 1337, {
      channelId: e.channel_id, cumulativeAmount: amount, signature: credential.payload.signature,
    }, payer), 'independent native A voucher signature')
    const descriptor = credential.payload.descriptor
    assert.ok(same(descriptor.payer, payer) && same(descriptor.payee, payee) && same(descriptor.token, token))
    assert.equal(Session.Precompile.Channel.computeId({ ...descriptor, chainId: 1337, escrow }), e.channel_id)
    assert.equal(receipt.channelId, e.channel_id)
    assert.equal(String(receipt.acceptedCumulative), String(amount))
    assert.equal(receipt.txHash, actualPayment.transactionHash)
    for (const snapshot of [proof, afterB]) { assert.equal(snapshot.channel_state.deposit, '0'); assert.equal(snapshot.channel_state.settled, '0') }
    assert.equal(afterA.channel_state.deposit, e.deposit_atomic)
    assert.equal(terminal.channel_state.deposit, '0')
    assert.equal(events[4].status, 204)
    const open = parseEventLogs({ abi: Session.Precompile.escrowAbi, logs: actualPayment.logs, eventName: 'ChannelOpened', strict: false }).filter(x => same(x.address, escrow))
    assert.equal(open.length, 1)
    assert.equal(open[0].args.channelId, e.channel_id)
    assert.ok(same(open[0].args.payer, payer) && same(open[0].args.payee, payee) && same(open[0].args.token, token))
    assert.equal(open[0].args.deposit, BigInt(e.deposit_atomic))
    const deposits = transfers(actualPayment).filter(x => same(x.args.from, payer) && same(x.args.to, escrow))
    assert.equal(deposits.length, 1); assert.equal(deposits[0].args.amount, BigInt(e.deposit_atomic))
    const close = await getTransactionReceipt(rpc, { hash: e.native.close.transactionHash })
    assert.equal(close.status, 'success'); assert.deepEqual(normalized(close), e.native.close)
    assert.ok(close.blockNumber >= actualPayment.blockNumber && close.blockNumber <= BigInt(terminal.block_number))
    assert.equal(events[4].receipt.txHash, close.transactionHash)
    assert.equal(events[4].receipt.channelId, e.channel_id)
    const closed = parseEventLogs({ abi: Session.Precompile.escrowAbi, logs: close.logs, eventName: 'ChannelClosed', strict: false }).filter(x => same(x.address, escrow))
    assert.equal(closed.length, 1); assert.equal(closed[0].args.channelId, e.channel_id)
    assert.equal(closed[0].args.settledToPayee, amount)
    assert.equal(closed[0].args.refundedToPayer, BigInt(e.deposit_atomic) - amount)
    const paid = transfers(close).filter(x => same(x.args.from, escrow) && same(x.args.to, payee))
    const refund = transfers(close).filter(x => same(x.args.from, escrow) && same(x.args.to, payer))
    assert.equal(paid.length, 1); assert.equal(paid[0].args.amount, amount)
    assert.equal(refund.length, 1); assert.equal(refund[0].args.amount, BigInt(e.deposit_atomic) - amount)
    const acceptedState = Object.values(afterA.server_store).find(value => value?.channelId === e.channel_id && value?.spent !== undefined)
    assert.ok(acceptedState); assert.equal(String(acceptedState.spent), String(amount))
    payout = BigInt(terminal.balances[payeeRole]) - BigInt(before.balances[payeeRole])
    closingGas = amount - payout
    assert.ok(closingGas >= 0n)
  }
  const payerDebit = BigInt(before.balances[payerRole]) - BigInt(terminal.balances[payerRole])
  const payerGas = payerDebit - amount
  assert.ok(payerGas > 0n)
  for (const role of Object.keys(actors).filter(role => ![payerRole, payeeRole].includes(role)))
    assert.equal(terminal.balances[role], before.balances[role], 'uninvolved actor must remain unchanged')
  return { id: e.id, status: 'PASS', rejection_layer: e.policy, B_answer_or_release: false,
    gross_A_payment_atomic: String(amount), payer_total_debit_atomic: String(payerDebit), payer_gas_atomic: String(payerGas),
    payee_net_gain_atomic: String(payout), payee_settlement_gas_atomic: String(closingGas) }
}

if (process.argv[1] && resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  const path = resolve(process.argv[2] ?? '')
  assert.ok(process.argv[2], 'usage: node verify-booking-obligation-control.mjs REPORT_OR_EVIDENCE.json [NEW_VERIFIED_REPORT.json]')
  const evidence = JSON.parse(await readFile(path, 'utf8'))
  const cases = evidence.component === 'MPP_BOOKING_OBLIGATION_CONTROL_REPORT'
    ? await Promise.all(evidence.cases.map(async row => {
      assert.equal(row.evidence_file, `${row.id}.json`)
      return JSON.parse(await readFile(resolve(dirname(path), row.evidence_file), 'utf8'))
    })) : [evidence]
  if (evidence.component === 'MPP_BOOKING_OBLIGATION_CONTROL_REPORT') {
    assert.equal(cases.length, 8); assert.equal(new Set(cases.map(x => x.case_index)).size, 8)
    assert.equal(evidence.remote_model_calls_executed, 0)
  }
  const verified = []
  for (const item of cases) verified.push(await verifyEvidence(item))
  const report = { status: 'PASS', verifier: 'INDEPENDENT_READ_ONLY_NATIVE_AND_HTTP_TRACE', cases: verified, remote_model_calls_executed: 0,
    limitation: 'Native receipts and historical balances are independently fetched from retained localhost RPC. HTTP nondelivery and application credit attribution rely on authenticated trace/source provenance, not an on-chain confidentiality proof.' }
  if (process.argv[3]) await writeFile(resolve(process.argv[3]), JSON.stringify(report, null, 2) + '\n', { flag: 'wx' })
  console.log(JSON.stringify(report))
}
