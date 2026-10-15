// W16: exercise the maintained Virtuals SDK's local role interface only.
// The injected agent is deliberately inert; this test makes no payment claim.
import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import path from 'node:path';
import { pathToFileURL } from 'node:url';
import test from 'node:test';

const installRoot = process.env.VIRTUALS_ACP_INSTALL;
if (!installRoot) {
  throw new Error('Set VIRTUALS_ACP_INSTALL to an isolated installation of @virtuals-protocol/acp-node-v2@0.1.15');
}

const packageRoot = path.join(installRoot, 'node_modules', '@virtuals-protocol', 'acp-node-v2');
const packageJson = JSON.parse(await readFile(path.join(packageRoot, 'package.json'), 'utf8'));
assert.equal(packageJson.name, '@virtuals-protocol/acp-node-v2');
assert.equal(packageJson.version, '0.1.15');
const { JobSession, getChainFamily } = await import(pathToFileURL(path.join(packageRoot, 'dist', 'index.js')).href);

function makeSession(roles, agent = {}) {
  return new JobSession(agent, ['0x0000000000000000000000000000000000000001'], '7', 8453, roles);
}

function event(type) {
  return { kind: 'system', chainId: 8453, onChainJobId: '7', event: { type, jobId: '7' }, timestamp: 1 };
}

function names(session) {
  return session.availableTools().map((tool) => tool.name);
}

test('job events expose tools to the designated role and status', () => {
  const provider = makeSession(['provider']);
  const client = makeSession(['client']);
  const evaluator = makeSession(['evaluator']);
  assert.ok(names(provider).includes('setBudget'));
  assert.ok(!names(client).includes('setBudget'));
  assert.deepEqual(names(evaluator), ['wait']);

  for (const session of [provider, client, evaluator]) session.appendEntry(event('budget.set'));
  assert.ok(names(client).includes('fund'));
  assert.ok(!names(provider).includes('fund'));

  for (const session of [provider, client, evaluator]) session.appendEntry(event('job.funded'));
  assert.ok(names(provider).includes('submit'));
  assert.ok(!names(evaluator).includes('complete'));

  for (const session of [provider, client, evaluator]) session.appendEntry(event('job.submitted'));
  assert.ok(names(evaluator).includes('complete'));
  assert.ok(names(evaluator).includes('reject'));
  assert.ok(!names(provider).includes('complete'));
  assert.ok(!names(client).includes('complete'));
});

test('executeTool refuses wrong-role actions before reaching the injected backend', async () => {
  let called = false;
  const agent = { internalComplete: async () => { called = true; } };
  const provider = makeSession(['provider'], agent);
  provider.appendEntry(event('job.submitted'));
  await assert.rejects(provider.executeTool('complete', { reason: 'wrong role' }), /not available/);
  assert.equal(called, false);

  const evaluator = makeSession(['evaluator'], agent);
  await assert.rejects(evaluator.executeTool('complete', { reason: 'wrong state' }), /not available/);
  assert.equal(called, false);
  evaluator.appendEntry(event('job.submitted'));
  await evaluator.executeTool('complete', { reason: 'sdk dispatch only' });
  assert.equal(called, true);
});

test('event responders are role scoped, and a local Anvil chain is unsupported', () => {
  const provider = makeSession(['provider']);
  const evaluator = makeSession(['evaluator']);
  assert.equal(provider.shouldRespond(event('job.submitted')), false);
  assert.equal(evaluator.shouldRespond(event('job.submitted')), true);
  assert.equal(provider.shouldRespond(event('job.funded')), true);
  assert.equal(evaluator.shouldRespond(event('job.funded')), false);
  assert.throws(() => getChainFamily(31337), /Unknown chain id 31337/);
});
