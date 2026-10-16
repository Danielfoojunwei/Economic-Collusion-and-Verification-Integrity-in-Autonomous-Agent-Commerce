// Native evidence/tamper tests: requires retained local Tempo history, no models.
import assert from 'node:assert/strict'
import { readFile } from 'node:fs/promises'
import { test } from 'node:test'
import { resolve } from 'node:path'
import { Credential } from 'mppx'
import { verifyEvidence } from './verify-booking-obligation-control.mjs'

const dir = resolve(process.env.MPP_BINDING_EVIDENCE_DIR ?? 'artifacts/prospective/mpp-booking-obligation-control/zero-model-006')
const report = JSON.parse(await readFile(resolve(dir, 'report.json'), 'utf8'))
const cases = await Promise.all(report.cases.map(async row => JSON.parse(await readFile(resolve(dir, row.evidence_file), 'utf8'))))
const sample = (flow = 'charge', operation = 'check') => structuredClone(cases.find(x => x.flow === flow && x.operation === operation && x.policy === 'SDK_EXPLICIT_OBLIGATION_SCOPE'))

test('all eight native controls reject B first, then accept the same unconsumed A proof', async () => {
  assert.equal(cases.length, 8)
  for (const evidence of cases) assert.equal((await verifyEvidence(evidence)).status, 'PASS')
})
test('reject protected calendar data injected into denied B response', async () => {
  const e = sample(); e.http_events[2].body = JSON.stringify({ calendar_answer: { status: 'FAIL' } })
  await assert.rejects(verifyEvidence(e))
})
test('reject B client-release credit despite claimed denial', async () => {
  const e = sample('charge', 'release'); e.snapshots[2].accepted.B = 1
  await assert.rejects(verifyEvidence(e))
})
test('reject a used-proof replay substituted for the required B-first order', async () => {
  const e = sample(); [e.http_events[2], e.http_events[3]] = [e.http_events[3], e.http_events[2]]
  e.http_events.forEach((x, i) => { x.sequence = i })
  await assert.rejects(verifyEvidence(e))
})
test('reject wrong native payee', async () => {
  const e = sample(); e.accounts.oracle = '0x1111111111111111111111111111111111111111'
  await assert.rejects(verifyEvidence(e))
})
test('reject erased real session settlement gas in terminal balance', async () => {
  const e = sample('session'); e.snapshots[4].balances.oracle = String(BigInt(e.snapshots[4].balances.oracle) + 52n)
  await assert.rejects(verifyEvidence(e), /historical terminal oracle balance/)
})
test('reject forged session channel identity', async () => {
  const e = sample('session'); e.channel_id = `0x${'11'.repeat(32)}`
  await assert.rejects(verifyEvidence(e))
})
test('reject forged native receipt emitter', async () => {
  const e = sample(); e.native.payment.logs[0].address = '0x1111111111111111111111111111111111111111'
  await assert.rejects(verifyEvidence(e))
})
test('reject changed B scope that no longer matches raw challenge headers', async () => {
  const e = sample(); e.http_events[1].challenge.opaque = e.http_events[0].challenge.opaque
  await assert.rejects(verifyEvidence(e))
})
test('reject labeling an authored guard response as an SDK rejection', async () => {
  const e = sample(); e.http_events[2].status = 403
  await assert.rejects(verifyEvidence(e))
})
test('reject invalid session voucher despite a genuine native opening receipt', async () => {
  const e = sample('session'); const parsed = Credential.deserialize(e.http_events[2].authorization)
  parsed.payload.signature = `0x${'11'.repeat(65)}`
  const forged = Credential.serialize(parsed)
  e.http_events[2].authorization = forged; e.http_events[3].authorization = forged
  await assert.rejects(verifyEvidence(e), /independent native A voucher signature/)
})
test('reject changed signed charge transaction despite genuine saved receipt', async () => {
  const e = sample(); const parsed = Credential.deserialize(e.http_events[2].authorization)
  parsed.payload.signature = `${parsed.payload.signature.slice(0, -2)}${parsed.payload.signature.endsWith('00') ? '01' : '00'}`
  const forged = Credential.serialize(parsed)
  e.http_events[2].authorization = forged; e.http_events[3].authorization = forged
  await assert.rejects(verifyEvidence(e), /exact A proof must bind/)
})
