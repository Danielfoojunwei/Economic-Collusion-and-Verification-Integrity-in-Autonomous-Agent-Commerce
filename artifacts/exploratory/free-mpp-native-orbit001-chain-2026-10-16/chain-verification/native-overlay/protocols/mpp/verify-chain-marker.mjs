import { createClient, http } from 'viem'
import { RPC_URL, verifyMpp010Chain } from './mpp010-chain-identity.mjs'
const result = await verifyMpp010Chain(createClient({ transport: http(RPC_URL, { retryCount: 0 }) }), RPC_URL)
console.log(JSON.stringify({status: 'PASS', chain_identity: result}))
