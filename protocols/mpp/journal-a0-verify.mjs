// Independent read-only Paper A A0 receipt reconstruction. Does not import
// the signer, runner policy, or its outcome functions. It verifies native
// TIP-20 transfers, accounting, and fixed-case consequences on a live chain.
import assert from 'node:assert/strict'
import { createHash } from 'node:crypto'
import { readFile, writeFile } from 'node:fs/promises'
import { Credential } from 'mppx'
import { createClient, defineChain, http, parseEventLogs } from 'viem'
import { mnemonicToAccount } from 'viem/accounts'
import { getBlock, getTransactionReceipt, readContract } from 'viem/actions'
import { Abis } from 'viem/tempo'

const [evidencePath, outputPath] = process.argv.slice(2)
assert.ok(evidencePath && outputPath, 'usage: node journal-a0-verify.mjs EVIDENCE.json REPORT.json')
const raw = await readFile(evidencePath)
const evidence = JSON.parse(raw)
assert.equal(evidence.schema, 'journal-a0-native-local-v1')
assert.equal(evidence.model_tier, 'SCRIPTED_SIMULATION')
assert.equal(evidence.transaction_tier, 'NATIVE_LOCAL_PROTOCOL')
const hash = bytes => createHash('sha256').update(bytes).digest('hex')
const signerSource = await readFile(new URL('journal-a0-local.mjs', import.meta.url))
assert.equal(evidence.source_sha256, hash(signerSource), 'runner source drift')
const url = new URL(evidence.rpc_url)
assert.equal(url.protocol, 'http:')
assert.ok(['127.0.0.1', 'localhost', '[::1]'].includes(url.hostname))
const chain = defineChain({ id: 1337, name: 'Paper A A0 receipt verifier',
  nativeCurrency: { decimals: 18, name: 'USD', symbol: 'USD' },
  rpcUrls: { default: { http: [evidence.rpc_url] } } })
const rpc = createClient({ chain, transport: http(evidence.rpc_url, { retryCount: 0, timeout: 20_000 }) })
assert.equal(await rpc.request({ method: 'eth_chainId' }), '0x539')
const genesis = await getBlock(rpc, { blockNumber: 0n })
assert.equal(genesis.hash, evidence.genesis_hash)
assert.equal(genesis.hash, '0xb54e201b325f207061d3502a1f4022b8a57c57bc86b7851958cc21a922b26a1f')
const token = '0x20c0000000000000000000000000000000000000'
assert.equal(evidence.token.toLowerCase(), token.toLowerCase())
const mnemonic = 'test test test test test test test test test test test junk'
const address = index => mnemonicToAccount(mnemonic, { accountIndex: index }).address
const lower = value => value.toLowerCase()
const balanceAt = (owner, block) => readContract(rpc, { abi: Abis.tip20,
  address: token, functionName: 'balanceOf', args: [owner], blockNumber: block })
const expected = [
  ['GOOD-FLAT-LOW', true, false, 1n, true, 'APPROVE', true],
  ['BAD-CONTINGENT-HIGH-PERMISSIVE', false, true, 6n, false, 'APPROVE', false],
  ['BAD-CONTINGENT-HIGH-STRICT', false, true, 6n, true, 'APPROVE', true],
  ['BAD-FLAT-HIGH-REJECT', false, false, 6n, true, 'REJECT', true],
  ['GOOD-FLAT-TIMEOUT', true, false, 1n, false, 'TIMEOUT', true],
]
assert.equal(evidence.case_count, expected.length)
assert.equal(evidence.rows.length, expected.length)
const seenHashes = new Set()
const reports = []
let lastBlock = -1n
for (let index = 0; index < expected.length; index++) {
  const [job, good, contingent, price, check, decision, guard] = expected[index]
  const row = evidence.rows[index]
  assert.deepEqual([row.job, row.good, row.contingent, BigInt(row.price), row.check,
    row.decision, row.guard], [job, good, contingent, price, check, decision, guard])
  const [provider, auditor, oracle, buyer, escrow] = [21, 22, 23, 24, 25]
    .map(offset => address(offset + 5 * index))
  for (const [role, expectedAddress] of Object.entries({ provider, auditor, oracle, buyer, escrow }))
    assert.equal(lower(row[role]), lower(expectedAddress))
  const expectedPay = decision === 'TIMEOUT' ? 0n :
    10n + (contingent ? (decision === 'APPROVE' ? 8n : -8n) : 0n)
  const expectedRelease = decision === 'APPROVE' && (!guard || good)
  assert.equal(row.buyer_released, expectedRelease)
  assert.equal(BigInt(row.auditor_pay_minor), expectedPay)
  assert.equal(row.common_escrow_reserve_minor, '18')
  assert.equal(row.economic_auditor_endowment_minor, '20')
  if (guard) assert.deepEqual(row.negatives,
    { wrong_job_rejected: true, stale_version_rejected: true, fake_fail_rejected: true })
  else assert.equal(row.negatives, null)
  assert.equal(row.duplicate_rejected, true)
  const purposes = new Map()
  for (const record of row.transactions) {
    assert.ok(!seenHashes.has(record.hash), 'duplicate native transaction hash')
    seenHashes.add(record.hash)
    assert.ok(!purposes.has(record.purpose), 'duplicate purpose')
    purposes.set(record.purpose, record)
    const receipt = await getTransactionReceipt(rpc, { hash: record.hash })
    assert.equal(receipt.status, 'success')
    assert.equal(receipt.blockNumber, BigInt(record.block))
    assert.ok(receipt.blockNumber > lastBlock, 'A0 transactions reordered or share a block')
    lastBlock = receipt.blockNumber
    const logs = parseEventLogs({ abi: Abis.tip20, logs: receipt.logs,
      eventName: 'Transfer', strict: false }).filter(log =>
        lower(log.address) === lower(token) &&
        lower(log.args.from) === lower(record.from) &&
        lower(log.args.to) === lower(record.to) &&
        log.args.amount === BigInt(record.amount_minor))
    assert.equal(logs.length, 1, `receipt lacks exact Transfer: ${record.purpose}`)
    const before = await balanceAt(record.to, receipt.blockNumber - 1n)
    const after = await balanceAt(record.to, receipt.blockNumber)
    assert.equal(after - before, BigInt(record.amount_minor),
      `payee balance did not gain exact amount: ${record.purpose}`)
  }
  const required = [
    [`${job}:provider_fund_with_gas`, address(0), provider, 100_000n],
    [`${job}:auditor_fund_with_gas`, address(0), auditor, 6_000n],
    [`${job}:buyer_fund_with_gas`, address(0), buyer, 200_000n],
    [`${job}:escrow_gas_fund`, address(0), escrow, 100_000n],
    [`${job}:prefund_common_reserve`, provider, escrow, 18n],
  ]
  if (check) required.push(['mpp_check', auditor, oracle, price])
  if (expectedRelease) required.push([`${job}:buyer_release`, buyer, provider, 100n])
  if (expectedPay) required.push([`${job}:auditor_pay`, escrow, auditor, expectedPay])
  if (18n - expectedPay) required.push([`${job}:reserve_refund`, escrow, provider, 18n - expectedPay])
  assert.equal(purposes.size, required.length, 'unrecognized additional transaction')
  for (const [purpose, from, to, amount] of required) {
    const record = purposes.get(purpose)
    assert.ok(record, `missing ${purpose}`)
    assert.equal(lower(record.from), lower(from))
    assert.equal(lower(record.to), lower(to))
    assert.equal(BigInt(record.amount_minor), amount)
  }
  if (check) {
    assert.deepEqual([row.proof?.job, row.proof?.version, row.proof?.status],
      [job, 1, good ? 'PASS' : 'FAIL'])
    assert.equal(row.proof.payment.hash, purposes.get('mpp_check').hash)
    const mpp = row.proof.mpp_http
    assert.deepEqual([mpp.challenge.intent, mpp.challenge.method,
      mpp.challenge.amount, lower(mpp.challenge.currency),
      lower(mpp.challenge.recipient), mpp.challenge.chain_id],
      ['charge', 'tempo', String(price), lower(token), lower(oracle), 1337])
    assert.equal(mpp.challenge.description, `Paper A A0 current booking ${job} v1`)
    assert.deepEqual([mpp.receipt.status, mpp.receipt.reference, mpp.replay_status],
      ['success', purposes.get('mpp_check').hash, 402])
    const credential = Credential.deserialize(mpp.authorization)
    assert.equal(credential.challenge.request.amount, String(price))
    assert.equal(lower(credential.challenge.request.recipient), lower(oracle))
    assert.equal(credential.challenge.request.methodDetails.chainId, 1337)
    assert.equal(credential.payload.hash, purposes.get('mpp_check').hash)
  } else assert.equal(row.proof, null)
  reports.push({ job, checked: check, independent_status: check ? (good ? 'PASS' : 'FAIL') : null,
    buyer_release_minor: expectedRelease ? '100' : '0',
    provider_to_auditor_minor: String(expectedPay),
    provider_reserve_refund_minor: String(18n - expectedPay),
    native_transactions: purposes.size })
}
const result = { status: 'INDEPENDENT_NATIVE_TRANSFER_AND_BALANCE_PASS',
  model_tier: 'SCRIPTED_SIMULATION', transaction_tier: 'NATIVE_LOCAL_PROTOCOL',
  evidence_sha256: hash(raw), signer_source_sha256: hash(signerSource),
  chain_id: 1337, genesis_hash: genesis.hash,
  cases: reports, native_transactions: seenHashes.size,
  limitation: 'Receipt, historical balance, and saved MPP challenge/credential binding are independently checked. The live HTTP replay rejection and in-run policy-negative booleans were asserted by the runner, not repeated by this read-only verifier.' }
await writeFile(outputPath, JSON.stringify(result, null, 2) + '\n', { flag: 'wx' })
console.log(JSON.stringify({ status: result.status, cases: reports.length,
  transactions: seenHashes.size }))
