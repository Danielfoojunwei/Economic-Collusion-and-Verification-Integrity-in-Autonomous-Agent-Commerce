// One-time marker for a fresh, valueless exploratory live-ORBIT Tempo chain.
import assert from 'node:assert/strict'
import { createHash } from 'node:crypto'
import { readFile, writeFile } from 'node:fs/promises'
import { createClient, defineChain, http } from 'viem'
import { mnemonicToAccount } from 'viem/accounts'
import { getBlock, getTransactionReceipt, readContract, waitForTransactionReceipt, writeContract } from 'viem/actions'
import { Abis } from 'viem/tempo'

const [outputPath] = process.argv.slice(2)
assert.ok(outputPath, 'usage: node free-orbit005-chain-marker.mjs OUTPUT.json')
const rpc = 'http://127.0.0.1:20007'
const token = '0x20c0000000000000000000000000000000000000'
const chain = defineChain({ id: 1337, name: 'Disposable Free MPP ORBIT005 Tempo',
  nativeCurrency: { decimals: 18, name: 'USD', symbol: 'USD' },
  rpcUrls: { default: { http: [rpc] } } })
const mnemonic = 'test test test test test test test test test test test junk'
const funder = mnemonicToAccount(mnemonic, { accountIndex: 0 })
const treasury = mnemonicToAccount(mnemonic, { accountIndex: 15 })
assert.equal(funder.address, '0xf39Fd6e51aad88F6F4ce6aB8827279cffFb92266')
assert.equal(treasury.address, '0x8e4D1a7b8c4f7F4204EB0643C85AA7656880E18b')
const transport = http(rpc, { retryCount: 0, timeout: 20000 })
const client = createClient({ chain, transport, pollingInterval: 500 })
const signer = createClient({ account: funder, chain, transport, pollingInterval: 500 })
assert.equal(await client.request({ method: 'eth_chainId' }), '0x539')
const genesis = await getBlock(client, { blockNumber: 0n })
assert.equal(genesis.hash, '0xb54e201b325f207061d3502a1f4022b8a57c57bc86b7851958cc21a922b26a1f')
const before = await readContract(client, { abi: Abis.tip20, address: token,
  functionName: 'balanceOf', args: [treasury.address] })
assert.equal(before, 0n, 'exploratory marker treasury is not fresh')
const txHash = await writeContract(signer, { abi: Abis.tip20, address: token,
  functionName: 'transfer', args: [treasury.address, 1015n] })
const receipt = await waitForTransactionReceipt(client, { hash: txHash,
  timeout: 30000, pollingInterval: 500 })
assert.equal(receipt.status, 'success')
const block = await getBlock(client, { blockNumber: receipt.blockNumber })
assert.deepEqual(block.transactions, [txHash])
const after = await readContract(client, { abi: Abis.tip20, address: token,
  functionName: 'balanceOf', args: [treasury.address] })
assert.equal(after - before, 1015n)
const result = { chain_id: 1337, genesis_hash: genesis.hash,
  marker_transaction_hash: txHash, marker_block_number: String(receipt.blockNumber),
  marker_block_hash: block.hash, marker_amount_atomic: '1015',
  rpc_url: rpc, token, funder: funder.address, treasury: treasury.address,
  source_sha256: createHash('sha256').update(await readFile(new URL('free-orbit005-chain-marker.mjs', import.meta.url))).digest('hex'),
  image: 'ghcr.io/tempoxyz/tempo-localnet@sha256:86f199f161be85d3610d990e5bc2653ece29de3ee9c91e8c8e768cf2b8c05c3b',
  container: 'free-mpp-live-orbit005-localnet', block_time: '500ms',
  test_only: true, asset: 'valueless local TIP-20' }
await writeFile(outputPath, JSON.stringify(result, null, 2) + '\n', { flag: 'wx' })
console.log(JSON.stringify(result))
