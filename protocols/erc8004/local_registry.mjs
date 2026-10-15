/** ERC-8004 local registry evidence; no token, escrow, or public RPC is used. */
import assert from 'node:assert/strict';
import { execFileSync } from 'node:child_process';
import { createHash } from 'node:crypto';
import { readFileSync, writeFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { pathToFileURL } from 'node:url';

const upstream = resolve(process.env.ERC8004_UPSTREAM || '/workspace/upstreams/w17-erc8004');
const upstreamCommit = 'b9e466c250744a7e06b13dff9d3c2844ed64f825';
assert.equal(execFileSync('git', ['-C', upstream, 'rev-parse', 'HEAD'], { encoding: 'utf8' }).trim(), upstreamCommit);
assert.equal(execFileSync('git', ['-C', upstream, 'status', '--porcelain', '--untracked-files=no'], { encoding: 'utf8' }).trim(), '');
const evidencePath = resolve(process.argv[2] || 'artifacts/gates/G6/W17/erc8004-local.json');
const hardhatUrl = pathToFileURL(`${upstream}/node_modules/hardhat/dist/src/index.js`).href;
const { network } = await import(hardhatUrl);
const { viem } = await network.connect();
const publicClient = await viem.getPublicClient();
const [owner, separateClient] = await viem.getWalletClients();
const txs = [];

async function receipt(hash, kind) {
  const result = await publicClient.getTransactionReceipt({ hash });
  assert.equal(result.status, 'success', `${kind} reverted`);
  txs.push({ kind, hash, status: result.status, block: result.blockNumber.toString(), logs: result.logs.map(log => ({
    address: log.address, logIndex: log.logIndex, topic0: log.topics[0],
  })) });
}

async function deployRegistry(name, identityAddress) {
  const minimal = await viem.deployContract('HardhatMinimalUUPS');
  const initAddress = identityAddress ?? '0x0000000000000000000000000000000000000000';
  const init = `0xc4d66de8${initAddress.slice(2).padStart(64, '0')}`;
  const proxy = await viem.deployContract('ERC1967Proxy', [minimal.address, init]);
  const implementation = await viem.deployContract(name);
  const proxyAsMinimal = await viem.getContractAt('HardhatMinimalUUPS', proxy.address);
  const reinit = identityAddress ? `0xc4d66de8${identityAddress.slice(2).padStart(64, '0')}` : '0x8129fc1c';
  await receipt(await proxyAsMinimal.write.upgradeToAndCall([implementation.address, reinit]), `${name}.upgrade`);
  return await viem.getContractAt(name, proxy.address);
}

const identity = await deployRegistry('IdentityRegistryUpgradeable');
const reputation = await deployRegistry('ReputationRegistryUpgradeable', identity.address);
assert.equal((await reputation.read.getIdentityRegistry()).toLowerCase(), identity.address.toLowerCase());
const registerTx = await identity.write.register(['data:application/json,{"name":"local-auditor"}'], { account: owner.account });
await receipt(registerTx, 'identity.register');
const agentId = 0n; // The pinned contract starts _lastId at zero.
assert.equal((await identity.read.ownerOf([agentId])).toLowerCase(), owner.account.address.toLowerCase());

const args = [agentId, 100n, 0, 'quality', 'audit', '', '', `0x${'ab'.repeat(32)}`];
let selfFeedbackRejected = false;
try {
  await reputation.write.giveFeedback(args, { account: owner.account });
} catch (error) {
  selfFeedbackRejected = String(error).includes('Self-feedback not allowed');
}
assert.equal(selfFeedbackRejected, true, 'owner self-feedback should revert');

await receipt(await reputation.write.giveFeedback(args, { account: separateClient.account }), 'reputation.giveFeedback');
const feedback = await reputation.read.readFeedback([agentId, separateClient.account.address, 1n]);
assert.equal(feedback[0], 100n);
assert.equal(feedback[4], false);
const beforeRevoke = await reputation.read.getSummary([agentId, [separateClient.account.address], 'quality', 'audit']);
assert.equal(beforeRevoke[0], 1n);
await receipt(await reputation.write.revokeFeedback([agentId, 1n], { account: separateClient.account }), 'reputation.revokeFeedback');
const afterRevoke = await reputation.read.readFeedback([agentId, separateClient.account.address, 1n]);
assert.equal(afterRevoke[4], true);

const hashFile = path => createHash('sha256').update(readFileSync(path)).digest('hex');
const output = {
  execution_tier: 'NATIVE_LOCAL_PROTOCOL',
  upstream_commit: upstreamCommit,
  upstream_lock_sha256: hashFile(`${upstream}/package-lock.json`),
  compiler_soljson_sha256: hashFile('/workspace/upstreams/w17-solc24/soljson.js'),
  chain_id: await publicClient.getChainId(),
  identity_registry: identity.address,
  reputation_registry: reputation.address,
  deterministic_test_wallets: { agent_owner: owner.account.address, separate_client: separateClient.account.address },
  agent_id: agentId.toString(),
  self_feedback_rejected: selfFeedbackRejected,
  separate_client_feedback: { value: feedback[0].toString(), count_before_revoke: beforeRevoke[0].toString(), revoked: afterRevoke[4] },
  transactions: txs,
  boundary: 'The second wallet is controlled by this test. The registry rejects owner-address feedback, not common-control or sybil feedback. No escrow/payment or work oracle is attached.',
};
writeFileSync(evidencePath, `${JSON.stringify(output, null, 2)}\n`);
console.log(JSON.stringify({ evidencePath, chain_id: output.chain_id, transactions: txs.length, self_feedback_rejected: selfFeedbackRejected }));
