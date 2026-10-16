// MPP010's bare Tempo genesis is deterministic and shared with MPP009.
// This first, study-only TIP-20 transfer distinguishes the persistent chains.
import assert from 'node:assert/strict'
import { getBlock, getTransactionReceipt, readContract } from 'viem/actions'
import { parseEventLogs } from 'viem'
import { Abis } from 'viem/tempo'

export const RPC_URL = 'http://127.0.0.1:20007'
export const HTTP_URL = 'http://127.0.0.1:19999'
export const TOKEN = '0x20c0000000000000000000000000000000000000'
export const FUNDER = '0xf39Fd6e51aad88F6F4ce6aB8827279cffFb92266'
export const ACCOUNTS = {
  provider: '0x302B6115587a87816DC1539c1ab3a02A4afc3278',
  auditor: '0xb59Bfd2cB139c503c4172e26a6DDfDD1CE6f3795',
  oracle: '0xDA80546764d9D2177Df07c20bE896220D5f98c5a',
  client: '0x59Fc84C01c2317cCDdA6Be40ce1cFf233215c84e',
  treasury: '0x8e4D1a7b8c4f7F4204EB0643C85AA7656880E18b',
}
export const CHAIN_IDENTITY = {
  chain_id: 1337,
  genesis_hash: '0xb54e201b325f207061d3502a1f4022b8a57c57bc86b7851958cc21a922b26a1f',
  marker_transaction_hash: '0x78f4e53e9e25749024901d102c0aacec9c8a82e2dacb2651fa2fb20d992e2e22',
  marker_block_number: '17',
  marker_block_hash: '0x95a218b9c5278ba32bc2f4bd27e45a4e3ce57d93689c6f0fa2d6fde32d278081',
  marker_amount_atomic: '1015',
}

export async function verifyMpp010Chain(client, rpcUrl = RPC_URL) {
  assert.equal(rpcUrl, RPC_URL, 'MPP010 must use its isolated RPC port')
  assert.equal(await client.request({ method: 'eth_chainId' }), '0x539')
  const genesis = await getBlock(client, { blockNumber: 0n })
  assert.equal(genesis.hash, CHAIN_IDENTITY.genesis_hash)
  const blockNumber = BigInt(CHAIN_IDENTITY.marker_block_number)
  const block = await getBlock(client, { blockNumber })
  assert.equal(block.hash, CHAIN_IDENTITY.marker_block_hash)
  assert.deepEqual(block.transactions, [CHAIN_IDENTITY.marker_transaction_hash])
  const receipt = await getTransactionReceipt(client, {
    hash: CHAIN_IDENTITY.marker_transaction_hash })
  assert.equal(receipt.status, 'success')
  assert.equal(receipt.blockNumber, blockNumber)
  assert.equal(receipt.blockHash, block.hash)
  const transfers = parseEventLogs({ abi: Abis.tip20, logs: receipt.logs,
    eventName: 'Transfer', strict: false }).filter(event =>
    event.address.toLowerCase() === TOKEN.toLowerCase() &&
    event.args.from.toLowerCase() === FUNDER.toLowerCase() &&
    event.args.to.toLowerCase() === ACCOUNTS.treasury.toLowerCase())
  assert.equal(transfers.length, 1)
  assert.equal(transfers[0].args.amount, BigInt(CHAIN_IDENTITY.marker_amount_atomic))
  const balanceAt = (address, blockNumber) => readContract(client, { abi: Abis.tip20,
    address: TOKEN, functionName: 'balanceOf', args: [address], blockNumber })
  assert.equal(await balanceAt(ACCOUNTS.treasury, blockNumber - 1n), 0n)
  assert.equal(await balanceAt(ACCOUNTS.treasury, blockNumber),
    BigInt(CHAIN_IDENTITY.marker_amount_atomic))
  assert.ok(await balanceAt(FUNDER, blockNumber - 1n) -
    await balanceAt(FUNDER, blockNumber) >= BigInt(CHAIN_IDENTITY.marker_amount_atomic))
  return CHAIN_IDENTITY
}
