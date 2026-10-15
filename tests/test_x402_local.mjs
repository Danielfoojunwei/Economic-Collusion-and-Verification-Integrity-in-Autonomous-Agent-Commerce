import assert from "node:assert/strict";
import { createHash } from "node:crypto";
import { createRequire } from "node:module";
import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { test } from "node:test";
import { fileURLToPath } from "node:url";
import { runLocalX402 } from "../scripts/run_x402_local.mjs";

const sdkRoot = process.env.X402_SDK_ROOT || "/workspace/upstreams/x402/typescript";
const requireEvm = createRequire(resolve(sdkRoot, "packages/mechanisms/evm/package.json"));
const { decodeFunctionData, parseAbi, parseEventLogs, recoverTypedDataAddress } = requireEvm("viem");
const tokenAbi = parseAbi([
  "function transferWithAuthorization(address from,address to,uint256 value,uint256 validAfter,uint256 validBefore,bytes32 nonce,uint8 v,bytes32 r,bytes32 s)",
  "event Transfer(address indexed from,address indexed to,uint256 value)",
  "event AuthorizationUsed(address indexed authorizer,bytes32 indexed nonce)",
]);
const types = { TransferWithAuthorization: [
  { name: "from", type: "address" }, { name: "to", type: "address" },
  { name: "value", type: "uint256" }, { name: "validAfter", type: "uint256" },
  { name: "validBefore", type: "uint256" }, { name: "nonce", type: "bytes32" },
] };
const sameAddress = (a, b) => assert.equal(a.toLowerCase(), b.toLowerCase());

test("native x402 v2 exact/EIP-3009 signature, receipt, finality and failure boundary", async () => {
  const run = await runLocalX402({ port: Number(process.env.X402_TEST_PORT || 18565) });
  assert.equal(run.status, "PASS");
  assert.equal(run.upstream.commit, "e95b06661e1a2a8a9a21fce34cc28b9934834650");
  assert.equal(run.http.challenge.x402Version, 2);
  assert.equal(run.http.challenge.accepts[0].scheme, "exact");
  assert.equal(run.http.challenge.accepts[0].network, "eip155:31337");
  assert.equal(run.http.paidStatus, 200);
  assert.deepEqual(run.trace.map(entry => entry.phase), [
    "CHALLENGE", "SIGNED_AUTHORIZATION", "VERIFY", "RESOURCE_EXECUTE", "SETTLE", "RESPONSE",
  ]);

  const source = readFileSync(fileURLToPath(new URL("../contracts/x402/TestEIP3009Token.sol", import.meta.url)));
  assert.equal(createHash("sha256").update(source).digest("hex"), run.chain.sourceSha256);

  const auth = run.authorization;
  const recovered = await recoverTypedDataAddress({
    domain: auth.domain, types, primaryType: "TransferWithAuthorization",
    message: { from: auth.from, to: auth.to, value: BigInt(auth.value),
      validAfter: BigInt(auth.validAfter), validBefore: BigInt(auth.validBefore), nonce: auth.nonce },
    signature: auth.signature,
  });
  sameAddress(recovered, run.actors.buyer);
  sameAddress(auth.to, run.actors.seller);
  sameAddress(auth.domain.verifyingContract, run.chain.tokenAddress);

  assert.equal(run.verify.result.isValid, true);
  assert.deepEqual(run.verify.before, run.verify.after);
  assert.equal(run.verify.after.nonceUsed, false);
  assert.equal(run.settle.result.success, true);
  assert.equal(run.transaction.status, "success");
  assert.equal(run.transaction.hash, run.settle.result.transaction);
  assert.equal(run.http.paymentResponse.transaction, run.transaction.hash);
  sameAddress(run.transaction.from, run.actors.facilitator);
  sameAddress(run.transaction.to, run.chain.tokenAddress);

  const call = decodeFunctionData({ abi: tokenAbi, data: run.transaction.input });
  assert.equal(call.functionName, "transferWithAuthorization");
  sameAddress(call.args[0], run.actors.buyer);
  sameAddress(call.args[1], run.actors.seller);
  assert.equal(call.args[2], 1000n);
  assert.equal(call.args[5], auth.nonce);

  const transfers = parseEventLogs({ abi: tokenAbi, eventName: "Transfer", logs: run.transaction.logs });
  assert.equal(transfers.length, 1);
  sameAddress(transfers[0].args.from, run.actors.buyer);
  sameAddress(transfers[0].args.to, run.actors.seller);
  assert.equal(transfers[0].args.value, 1000n);
  const used = parseEventLogs({ abi: tokenAbi, eventName: "AuthorizationUsed", logs: run.transaction.logs });
  assert.equal(used.length, 1);
  sameAddress(used[0].args.authorizer, run.actors.buyer);
  assert.equal(used[0].args.nonce, auth.nonce);
  assert.equal(run.settle.after.nonceUsed, true);
  assert.equal(BigInt(run.settle.after.block), BigInt(run.settle.before.block) + 1n);
  assert.equal(BigInt(run.balances.initialBuyer) - BigInt(run.balances.finalBuyer), 1000n);
  assert.equal(BigInt(run.balances.finalSeller) - BigInt(run.balances.initialSeller), 1000n);

  for (const key of ["wrongAmount", "wrongPayee", "expired"]) {
    assert.equal(run.negatives[key].result.isValid, false);
    assert.equal(run.negatives[key].before.nonceUsed, false);
    assert.deepEqual(run.negatives[key].before, run.negatives[key].after);
  }
  assert.equal(run.negatives.replayVerify.isValid, false);
  assert.equal(run.negatives.replayHttpStatus, 402);
  assert.equal(run.negatives.replayContractRejected, true);
  assert.equal(run.negatives.invalidContractSignatureRejected, true);
  assert.equal(run.handlerFailure.status, 503);
  assert.equal(run.handlerFailure.settleCallsBefore, run.handlerFailure.settleCallsAfter);
  assert.deepEqual(run.handlerFailure.before, run.handlerFailure.after);
  assert.equal(run.handlerFailure.before.nonceUsed, false);
  assert.equal(run.handlerFailure.paymentResponseHeader, null);
  assert.equal(run.schemeLimit.alteredResourceUrlVerified, true);
});
