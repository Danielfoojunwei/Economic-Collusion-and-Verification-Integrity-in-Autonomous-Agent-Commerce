#!/usr/bin/env node
// W08: official x402 v2 exact/EIP-3009 over loopback HTTP and a disposable local chain.
import assert from "node:assert/strict";
import { createHash } from "node:crypto";
import { spawn, spawnSync, execFileSync } from "node:child_process";
import { readFileSync, mkdirSync, writeFileSync } from "node:fs";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";

const PROJECT_ROOT = resolve(dirname(fileURLToPath(import.meta.url)), "..");
const SDK_ROOT = process.env.X402_SDK_ROOT || "/workspace/upstreams/x402/typescript";
const X402_COMMIT = "e95b06661e1a2a8a9a21fce34cc28b9934834650";
const ANVIL = process.env.X402_ANVIL || "/workspace/.tools/foundry/v1.8.5/anvil";
const SOLC = process.env.X402_SOLC || "/workspace/.tools/solc/v0.8.28/solc";
const MNEMONIC = "test test test test test test test test test test test junk";
const TOKEN_PATH = join(PROJECT_ROOT, "contracts/x402/TestEIP3009Token.sol");
const DOMAIN_NAME = "Research Test USD";
const DOMAIN_VERSION = "1";
const AMOUNT = 1000n;
const MINTED = 1000000n;
const TRANSFER_TYPES = {
  TransferWithAuthorization: [
    { name: "from", type: "address" },
    { name: "to", type: "address" },
    { name: "value", type: "uint256" },
    { name: "validAfter", type: "uint256" },
    { name: "validBefore", type: "uint256" },
    { name: "nonce", type: "bytes32" },
  ],
};

function sha256(value) {
  return createHash("sha256").update(value).digest("hex");
}

function compileToken() {
  const source = readFileSync(TOKEN_PATH, "utf8");
  const input = {
    language: "Solidity",
    sources: { "TestEIP3009Token.sol": { content: source } },
    settings: {
      optimizer: { enabled: true, runs: 200 },
      outputSelection: { "*": { "*": ["abi", "evm.bytecode.object"] } },
    },
  };
  const compiled = spawnSync(SOLC, ["--standard-json"], {
    input: JSON.stringify(input), encoding: "utf8", maxBuffer: 16 * 1024 * 1024,
  });
  if (compiled.status !== 0) throw new Error(`solc failed: ${compiled.stderr}`);
  const output = JSON.parse(compiled.stdout.slice(compiled.stdout.indexOf("{")));
  const errors = (output.errors || []).filter(item => item.severity === "error");
  if (errors.length) throw new Error(`solc errors: ${errors.map(item => item.formattedMessage).join("\n")}`);
  const contract = output.contracts["TestEIP3009Token.sol"].TestEIP3009Token;
  assert.ok(contract.evm.bytecode.object.length > 0);
  return { abi: contract.abi, bytecode: `0x${contract.evm.bytecode.object}`, sourceSha256: sha256(source) };
}

async function loadSdk() {
  const commit = execFileSync("git", ["rev-parse", "HEAD"], {
    cwd: resolve(SDK_ROOT, ".."), encoding: "utf8",
  }).trim();
  assert.equal(commit, X402_COMMIT, "official x402 source commit changed");
  const sdk = relative => import(pathToFileURL(join(SDK_ROOT, relative)).href);
  const [coreClient, coreServer, coreFacilitator, evmClient, evmServer, evmFacilitator, evmIndex, expressSdk, fetchSdk] =
    await Promise.all([
      sdk("packages/core/dist/esm/client/index.mjs"),
      sdk("packages/core/dist/esm/server/index.mjs"),
      sdk("packages/core/dist/esm/facilitator/index.mjs"),
      sdk("packages/mechanisms/evm/dist/esm/exact/client/index.mjs"),
      sdk("packages/mechanisms/evm/dist/esm/exact/server/index.mjs"),
      sdk("packages/mechanisms/evm/dist/esm/exact/facilitator/index.mjs"),
      sdk("packages/mechanisms/evm/dist/esm/index.mjs"),
      sdk("packages/http/express/dist/esm/index.mjs"),
      sdk("packages/http/fetch/dist/esm/index.mjs"),
    ]);
  const { createRequire } = await import("node:module");
  const requireEvm = createRequire(join(SDK_ROOT, "packages/mechanisms/evm/package.json"));
  const requireExpress = createRequire(join(SDK_ROOT, "packages/http/express/package.json"));
  return {
    ...requireEvm("viem"), ...requireEvm("viem/accounts"),
    express: requireExpress("express"),
    x402Client: coreClient.x402Client,
    x402ResourceServer: coreServer.x402ResourceServer,
    HTTPFacilitatorClient: coreServer.HTTPFacilitatorClient,
    x402Facilitator: coreFacilitator.x402Facilitator,
    ExactClient: evmClient.ExactEvmScheme,
    ExactServer: evmServer.ExactEvmScheme,
    ExactFacilitator: evmFacilitator.ExactEvmScheme,
    toFacilitatorEvmSigner: evmIndex.toFacilitatorEvmSigner,
    paymentMiddleware: expressSdk.paymentMiddleware,
    wrapFetchWithPayment: fetchSdk.wrapFetchWithPayment,
  };
}

async function listen(app, port) {
  return new Promise((resolveListen, rejectListen) => {
    const server = app.listen(port, "127.0.0.1");
    server.once("error", rejectListen);
    server.once("listening", () => resolveListen(server));
  });
}

async function closeServer(server) {
  if (!server) return;
  server.closeAllConnections();
  await new Promise(resolveClose => server.close(resolveClose));
}

async function waitForChain(url, child) {
  for (let attempt = 0; attempt < 80; attempt += 1) {
    if (child.exitCode !== null) throw new Error(`Anvil exited early with ${child.exitCode}`);
    try {
      const response = await fetch(url, {
        method: "POST", headers: { "content-type": "application/json" },
        body: JSON.stringify({ jsonrpc: "2.0", id: 1, method: "eth_chainId", params: [] }),
      });
      if (response.ok && (await response.json()).result === "0x7a69") return;
    } catch { /* Anvil is starting. */ }
    await new Promise(resolveWait => setTimeout(resolveWait, 100));
  }
  throw new Error("Anvil did not become ready on the isolated loopback port");
}

function signAuthorization(account, auth, tokenAddress) {
  return account.signTypedData({
    domain: { name: DOMAIN_NAME, version: DOMAIN_VERSION, chainId: 31337, verifyingContract: tokenAddress },
    types: TRANSFER_TYPES, primaryType: "TransferWithAuthorization",
    message: {
      from: auth.from, to: auth.to, value: BigInt(auth.value),
      validAfter: BigInt(auth.validAfter), validBefore: BigInt(auth.validBefore), nonce: auth.nonce,
    },
  });
}

/** Execute one native local payment run. No remote RPCs, models, or funded assets. */
export async function runLocalX402({ port = 18545, output, resourceRecord } = {}) {
  assert.ok(Number.isInteger(port) && port > 1024 && port < 65524);
  const servedResourceRecord = resourceRecord ?? { resource: "research", served: true };
  assert.ok(servedResourceRecord && typeof servedResourceRecord === "object" &&
    !Array.isArray(servedResourceRecord));
  assert.deepEqual(JSON.parse(JSON.stringify(servedResourceRecord)), servedResourceRecord,
    "resourceRecord must be plain JSON data");
  const rpcUrl = `http://127.0.0.1:${port}`;
  const facilitatorUrl = `http://127.0.0.1:${port + 10}`;
  const resourceUrl = `http://127.0.0.1:${port + 11}/research`;
  const sdk = await loadSdk();
  const compiled = compileToken();
  const trace = [];
  const mark = (phase, detail = {}) => trace.push({ sequence: trace.length, phase,
    timestampUtc: new Date().toISOString(), elapsedMs: performance.now(), ...detail });
  const anvilLog = [];
  let anvil;
  let facilitatorHttp;
  let resourceHttp;

  try {
    anvil = spawn(ANVIL, [
      "--host", "127.0.0.1", "--port", String(port), "--chain-id", "31337",
      "--mnemonic", MNEMONIC, "--silent",
    ], { stdio: ["ignore", "pipe", "pipe"] });
    for (const stream of [anvil.stdout, anvil.stderr]) {
      stream.on("data", chunk => {
        if (anvilLog.join("").length < 8192) anvilLog.push(chunk.toString());
      });
    }
    await waitForChain(rpcUrl, anvil);

    const chain = {
      id: 31337, name: "isolated Anvil 31337",
      nativeCurrency: { name: "Valueless local ETH", symbol: "ETH", decimals: 18 },
      rpcUrls: { default: { http: [rpcUrl] } },
    };
    const network = "eip155:31337";
    const publicClient = sdk.createPublicClient({ chain, transport: sdk.http(rpcUrl) });
    const accounts = [0, 1, 2, 3].map(addressIndex => sdk.mnemonicToAccount(MNEMONIC, { addressIndex }));
    const [deployer, facilitatorAccount, buyer, seller] = accounts;
    const wallet = account => sdk.createWalletClient({ account, chain, transport: sdk.http(rpcUrl) });
    const deployerWallet = wallet(deployer);
    const facilitatorWallet = wallet(facilitatorAccount);
    const onchainAccounts = await publicClient.request({ method: "eth_accounts" });
    for (let index = 0; index < accounts.length; index += 1) {
      assert.equal(onchainAccounts[index].toLowerCase(), accounts[index].address.toLowerCase());
    }

    const deploymentHash = await deployerWallet.deployContract({ abi: compiled.abi, bytecode: compiled.bytecode });
    const deploymentReceipt = await publicClient.waitForTransactionReceipt({ hash: deploymentHash });
    assert.equal(deploymentReceipt.status, "success");
    const tokenAddress = deploymentReceipt.contractAddress;
    assert.ok(tokenAddress);
    const tokenRead = (functionName, args = []) => publicClient.readContract({
      address: tokenAddress, abi: compiled.abi, functionName, args,
    });
    const mintHash = await deployerWallet.writeContract({
      address: tokenAddress, abi: compiled.abi, functionName: "mint", args: [buyer.address, MINTED],
    });
    assert.equal((await publicClient.waitForTransactionReceipt({ hash: mintHash })).status, "success");
    assert.equal(await tokenRead("balanceOf", [buyer.address]), MINTED);
    assert.equal(await tokenRead("balanceOf", [seller.address]), 0n);

    const signer = sdk.toFacilitatorEvmSigner({
      address: facilitatorAccount.address,
      getCode: args => publicClient.getCode(args),
      readContract: args => publicClient.readContract({ ...args, args: args.args || [] }),
      verifyTypedData: args => publicClient.verifyTypedData(args),
      writeContract: args => facilitatorWallet.writeContract({ ...args, args: args.args || [] }),
      sendTransaction: args => facilitatorWallet.sendTransaction(args),
      waitForTransactionReceipt: args => publicClient.waitForTransactionReceipt(args),
    });
    const facilitator = new sdk.x402Facilitator().register(network, new sdk.ExactFacilitator(signer));
    const snapshot = async nonce => {
      const [nonceUsed, buyerBalance, sellerBalance, block] = await Promise.all([
        tokenRead("authorizationState", [buyer.address, nonce]),
        tokenRead("balanceOf", [buyer.address]),
        tokenRead("balanceOf", [seller.address]),
        publicClient.request({ method: "eth_blockNumber" }),
      ]);
      return {
        nonceUsed, buyerBalance: buyerBalance.toString(), sellerBalance: sellerBalance.toString(),
        block: BigInt(block).toString(),
      };
    };

    const facilitatorApp = sdk.express();
    facilitatorApp.use(sdk.express.json());
    const facilitatorCalls = { verify: [], settle: [] };
    facilitatorApp.get("/supported", (_req, res) => res.json(facilitator.getSupported()));
    facilitatorApp.post("/verify", async (req, res) => {
      try {
        const { paymentPayload, paymentRequirements } = req.body;
        const nonce = paymentPayload.payload.authorization.nonce;
        const before = await snapshot(nonce);
        mark("VERIFY", { nonce });
        const result = await facilitator.verify(paymentPayload, paymentRequirements);
        const after = await snapshot(nonce);
        facilitatorCalls.verify.push({ result, before, after });
        res.json(result);
      } catch (error) {
        res.status(500).json({ error: String(error) });
      }
    });
    facilitatorApp.post("/settle", async (req, res) => {
      try {
        const { paymentPayload, paymentRequirements } = req.body;
        const nonce = paymentPayload.payload.authorization.nonce;
        const before = await snapshot(nonce);
        mark("SETTLE", { nonce });
        const result = await facilitator.settle(paymentPayload, paymentRequirements);
        const after = await snapshot(nonce);
        facilitatorCalls.settle.push({ result, before, after });
        res.json(result);
      } catch (error) {
        res.status(500).json({ error: String(error) });
      }
    });
    facilitatorHttp = await listen(facilitatorApp, port + 10);

    let handlerCount = 0;
    const resourceApp = sdk.express();
    const paidRoute = {
      accepts: [{
        scheme: "exact", network, payTo: seller.address, maxTimeoutSeconds: 120,
        price: { amount: AMOUNT.toString(), asset: tokenAddress, extra: {
          name: DOMAIN_NAME, version: DOMAIN_VERSION, assetTransferMethod: "eip3009",
        } },
      }],
      description: "Valueless research HTTP resource", mimeType: "application/json",
    };
    resourceApp.use(sdk.paymentMiddleware({
      "GET /research": paidRoute, "GET /research-alt": paidRoute, "GET /research-fail": paidRoute,
    }, new sdk.x402ResourceServer(new sdk.HTTPFacilitatorClient({ url: facilitatorUrl }))
      .register(network, new sdk.ExactServer())));
    resourceApp.get("/research", (_req, res) => {
      handlerCount += 1;
      mark("RESOURCE_EXECUTE");
      res.json(servedResourceRecord);
    });
    const alteredRecord = { ...servedResourceRecord,
      submitted_claim: { ...servedResourceRecord.submitted_claim, claimed_amount_minor: 200 },
      service: "diverted_modified_receipt_report" };
    resourceApp.get("/research-alt", (_req, res) => {
      handlerCount += 1;
      mark("RESOURCE_EXECUTE", { actualRoute: "/research-alt" });
      res.json(alteredRecord);
    });
    let failedHandlerCount = 0;
    resourceApp.get("/research-fail", (_req, res) => {
      failedHandlerCount += 1;
      res.status(503).json({ error: "injected_resource_failure" });
    });
    resourceHttp = await listen(resourceApp, port + 11);

    const client = new sdk.x402Client()
      .register(network, new sdk.ExactClient(buyer))
      .setSpendControls({ allowedAssets: [{ network, asset: tokenAddress,
        maxAmountPerPayment: AMOUNT.toString() }] });
    let challenge;
    let paymentHeader;
    let paidPayload;
    const recordingFetch = async (input, init) => {
      const request = new Request(input, init);
      const attachedPayment = request.headers.get("PAYMENT-SIGNATURE");
      if (attachedPayment) {
        paymentHeader = attachedPayment;
        paidPayload = JSON.parse(Buffer.from(attachedPayment, "base64").toString("utf8"));
        mark("SIGNED_AUTHORIZATION", { signatureSha256: sha256(paidPayload.payload.signature) });
      }
      // Application routing deliberately forwards the signed authorization for
      // /research to a different paid endpoint with identical payment terms.
      const sentRequest = attachedPayment
        ? new Request(`${resourceUrl}-alt`, request) : request;
      const response = await fetch(sentRequest);
      if (response.status === 402 && !attachedPayment && !challenge) {
        const encoded = response.headers.get("PAYMENT-REQUIRED");
        assert.ok(encoded, "official HTTP challenge header missing");
        challenge = JSON.parse(Buffer.from(encoded, "base64").toString("utf8"));
        mark("CHALLENGE", { status: 402, headerSha256: sha256(encoded) });
      }
      return response;
    };
    const paidResponse = await sdk.wrapFetchWithPayment(recordingFetch, client)(resourceUrl);
    const resourceBody = await paidResponse.json();
    mark("RESPONSE", { status: paidResponse.status });

    assert.equal(challenge.x402Version, 2);
    assert.equal(challenge.accepts.length, 1);
    const requirements = challenge.accepts[0];
    assert.equal(requirements.scheme, "exact");
    assert.equal(requirements.network, network);
    assert.equal(requirements.asset.toLowerCase(), tokenAddress.toLowerCase());
    assert.equal(requirements.amount, AMOUNT.toString());
    assert.equal(requirements.payTo.toLowerCase(), seller.address.toLowerCase());
    assert.equal(requirements.extra.name, DOMAIN_NAME);
    assert.equal(requirements.extra.version, DOMAIN_VERSION);
    assert.equal(requirements.extra.assetTransferMethod, "eip3009");
    assert.equal(paidPayload.x402Version, 2);
    assert.equal(paidPayload.payload.authorization.from.toLowerCase(), buyer.address.toLowerCase());
    assert.equal(paidPayload.payload.authorization.to.toLowerCase(), seller.address.toLowerCase());
    assert.equal(paidPayload.payload.authorization.value, AMOUNT.toString());
    assert.equal(paidResponse.status, 200,
      JSON.stringify({ facilitatorCalls, resourceBody }));
    assert.deepEqual(resourceBody, alteredRecord);
    assert.notEqual(sha256(JSON.stringify(resourceBody)), sha256(JSON.stringify(servedResourceRecord)));
    assert.equal(paidPayload.resource.url, resourceUrl);
    assert.equal(handlerCount, 1);
    assert.equal(facilitatorCalls.verify[0].result.isValid, true);
    assert.deepEqual(facilitatorCalls.verify[0].before, facilitatorCalls.verify[0].after,
      "read-only verify changed chain state");
    assert.equal(facilitatorCalls.verify[0].after.nonceUsed, false);
    assert.equal(facilitatorCalls.settle[0].result.success, true);
    assert.equal(facilitatorCalls.settle[0].after.nonceUsed, true);

    const settlement = facilitatorCalls.settle[0].result;
    const encodedResponse = paidResponse.headers.get("PAYMENT-RESPONSE");
    assert.ok(encodedResponse);
    const paymentResponse = JSON.parse(Buffer.from(encodedResponse, "base64").toString("utf8"));
    assert.equal(paymentResponse.transaction, settlement.transaction);
    assert.equal(paymentResponse.success, true);
    const receipt = await publicClient.getTransactionReceipt({ hash: settlement.transaction });
    const transaction = await publicClient.getTransaction({ hash: settlement.transaction });
    const receiptBlock = await publicClient.getBlock({ blockNumber: receipt.blockNumber });
    const observedHead = BigInt(await publicClient.request({ method: "eth_blockNumber" }));
    assert.equal(receipt.status, "success");
    assert.ok(observedHead >= receipt.blockNumber);
    assert.equal(transaction.to.toLowerCase(), tokenAddress.toLowerCase());
    assert.equal(transaction.from.toLowerCase(), facilitatorAccount.address.toLowerCase());
    const decodedCall = sdk.decodeFunctionData({ abi: compiled.abi, data: transaction.input });
    assert.equal(decodedCall.functionName, "transferWithAuthorization");
    assert.equal(decodedCall.args[0].toLowerCase(), buyer.address.toLowerCase());
    assert.equal(decodedCall.args[1].toLowerCase(), seller.address.toLowerCase());
    assert.equal(decodedCall.args[2], AMOUNT);
    assert.equal(decodedCall.args[5], paidPayload.payload.authorization.nonce);
    const transferLogs = sdk.parseEventLogs({
      abi: compiled.abi, eventName: "Transfer", logs: receipt.logs,
    }).filter(log => log.address.toLowerCase() === tokenAddress.toLowerCase());
    assert.equal(transferLogs.length, 1);
    assert.equal(transferLogs[0].args.from.toLowerCase(), buyer.address.toLowerCase());
    assert.equal(transferLogs[0].args.to.toLowerCase(), seller.address.toLowerCase());
    assert.equal(transferLogs[0].args.value, AMOUNT);
    const finalBalances = await snapshot(paidPayload.payload.authorization.nonce);
    assert.equal(finalBalances.buyerBalance, (MINTED - AMOUNT).toString());
    assert.equal(finalBalances.sellerBalance, AMOUNT.toString());

    const order = ["CHALLENGE", "SIGNED_AUTHORIZATION", "VERIFY", "RESOURCE_EXECUTE", "SETTLE", "RESPONSE"];
    const phases = trace.map(item => item.phase);
    assert.deepEqual(phases.slice(0, 6), order);

    const verifyAt = async (payload, reqs) => {
      const response = await fetch(`${facilitatorUrl}/verify`, {
        method: "POST", headers: { "content-type": "application/json" },
        body: JSON.stringify({ x402Version: 2, paymentPayload: payload, paymentRequirements: reqs }),
      });
      assert.equal(response.status, 200);
      return response.json();
    };
    const amountPayload = await client.createPaymentPayload(challenge);
    const amountBefore = await snapshot(amountPayload.payload.authorization.nonce);
    const wrongAmount = await verifyAt(amountPayload, { ...requirements, amount: "1001" });
    const amountAfter = await snapshot(amountPayload.payload.authorization.nonce);
    const payeePayload = await client.createPaymentPayload(challenge);
    const payeeBefore = await snapshot(payeePayload.payload.authorization.nonce);
    const wrongPayee = await verifyAt(payeePayload, { ...requirements, payTo: deployer.address });
    const payeeAfter = await snapshot(payeePayload.payload.authorization.nonce);
    assert.equal(wrongAmount.invalidReason, "invalid_exact_evm_payload_authorization_value_mismatch");
    assert.equal(wrongPayee.invalidReason, "invalid_exact_evm_recipient_mismatch");
    assert.equal(amountBefore.nonceUsed, false);
    assert.equal(payeeBefore.nonceUsed, false);
    assert.deepEqual(amountAfter, amountBefore);
    assert.deepEqual(payeeAfter, payeeBefore);

    const freshPayload = await client.createPaymentPayload(challenge);
    const stale = structuredClone(freshPayload);
    stale.payload.authorization.validBefore = String(Math.floor(Date.now() / 1000) - 30);
    stale.payload.signature = await signAuthorization(buyer, stale.payload.authorization, tokenAddress);
    const staleBefore = await snapshot(stale.payload.authorization.nonce);
    const expired = await verifyAt(stale, requirements);
    const staleAfter = await snapshot(stale.payload.authorization.nonce);
    assert.equal(expired.invalidReason, "invalid_exact_evm_payload_authorization_valid_before");
    assert.deepEqual(staleAfter, staleBefore);

    const replayVerify = await verifyAt(paidPayload, requirements);
    assert.equal(replayVerify.isValid, false);
    assert.ok(replayVerify.invalidReason);
    const replayResponse = await fetch(resourceUrl, { headers: { "PAYMENT-SIGNATURE": paymentHeader } });
    assert.equal(replayResponse.status, 402);
    assert.equal(handlerCount, 1);
    assert.deepEqual(await snapshot(paidPayload.payload.authorization.nonce), finalBalances);

    const replaySignature = sdk.parseSignature(paidPayload.payload.signature);
    let replayContractRejected = false;
    try {
      await publicClient.simulateContract({
        address: tokenAddress, abi: compiled.abi, functionName: "transferWithAuthorization",
        account: facilitatorAccount.address,
        args: [buyer.address, seller.address, AMOUNT,
          BigInt(paidPayload.payload.authorization.validAfter),
          BigInt(paidPayload.payload.authorization.validBefore),
          paidPayload.payload.authorization.nonce,
          Number(replaySignature.v ?? (27 + replaySignature.yParity)),
          replaySignature.r, replaySignature.s],
      });
    } catch (error) {
      replayContractRejected = String(error).includes("AuthorizationAlreadyUsed");
    }
    assert.equal(replayContractRejected, true, "spent token nonce was not rejected onchain");

    const failedResourceUrl = `${resourceUrl}-fail`;
    const failedChallengeResponse = await fetch(failedResourceUrl);
    assert.equal(failedChallengeResponse.status, 402);
    const failedChallenge = JSON.parse(Buffer.from(
      failedChallengeResponse.headers.get("PAYMENT-REQUIRED"), "base64").toString("utf8"));
    const failedPayload = await client.createPaymentPayload(failedChallenge);
    const failedNonce = failedPayload.payload.authorization.nonce;
    const failedBefore = await snapshot(failedNonce);
    const verifyCallsBeforeFailure = facilitatorCalls.verify.length;
    const settleCallsBeforeFailure = facilitatorCalls.settle.length;
    const failedResponse = await fetch(failedResourceUrl, {
      headers: { "PAYMENT-SIGNATURE": Buffer.from(JSON.stringify(failedPayload)).toString("base64") },
    });
    const failedBody = await failedResponse.json();
    const failedAfter = await snapshot(failedNonce);
    const verifyCallsAfterFailure = facilitatorCalls.verify.length;
    assert.equal(failedResponse.status, 503);
    assert.deepEqual(failedBody, { error: "injected_resource_failure" });
    assert.equal(failedHandlerCount, 1);
    assert.equal(verifyCallsAfterFailure, verifyCallsBeforeFailure + 1);
    const failureVerifications = facilitatorCalls.verify.slice(verifyCallsBeforeFailure);
    assert.ok(failureVerifications.every(call => call.result.isValid === true));
    assert.equal(facilitatorCalls.settle.length, settleCallsBeforeFailure);
    assert.equal(failedResponse.headers.get("PAYMENT-RESPONSE"), null);
    assert.deepEqual(failedAfter, failedBefore);
    assert.equal(failedAfter.nonceUsed, false);

    const freshForContract = await client.createPaymentPayload(challenge);
    const signatureParts = sdk.parseSignature(freshForContract.payload.signature);
    let invalidContractSignatureRejected = false;
    try {
      await publicClient.simulateContract({
        address: tokenAddress, abi: compiled.abi, functionName: "transferWithAuthorization",
        account: facilitatorAccount.address,
        args: [
          buyer.address, deployer.address, AMOUNT, 0n,
          BigInt(freshForContract.payload.authorization.validBefore),
          freshForContract.payload.authorization.nonce,
          Number(signatureParts.v ?? (27 + signatureParts.yParity)),
          signatureParts.r, signatureParts.s,
        ],
      });
    } catch (error) {
      invalidContractSignatureRejected = String(error).includes("InvalidSignature");
    }
    assert.equal(invalidContractSignatureRejected, true,
      "test token did not reject a valid signature with a tampered payee");

    const alteredResource = structuredClone(freshForContract);
    alteredResource.resource.url = `${resourceUrl}-other`;
    const resourceUnbound = await verifyAt(alteredResource, requirements);
    assert.equal(resourceUnbound.isValid, true,
      "exact/EIP-3009 resource URL unexpectedly became signature-bound");

    const evidence = {
      schemaVersion: 1, workOrder: "CROSSRAIL_RECEIPT_RESOURCE_DIVERSION", status: "PASS",
      modelExecutionTier: "SCRIPTED_SIMULATION", transactionExecutionTier: "NATIVE_LOCAL_PROTOCOL",
      upstream: { repository: "https://github.com/x402-foundation/x402", commit: X402_COMMIT,
        protocol: "x402 v2", scheme: "exact", assetTransferMethod: "eip3009", sdkVersion: "2.28.0" },
      toolchain: { anvil: ANVIL, solc: SOLC, node: process.version },
      chain: { rpcUrl, chainId: 31337, network, tokenAddress, sourceSha256: compiled.sourceSha256,
        deploymentHash, mintHash },
      actors: { deployer: deployer.address, facilitator: facilitatorAccount.address,
        buyer: buyer.address, seller: seller.address },
      http: { resourceUrl, facilitatorUrl, challenge, paymentSignatureHeaderSha256: sha256(paymentHeader),
        paidStatus: paidResponse.status, resourceBody, paymentResponse, replayStatus: replayResponse.status,
        challengedResourceUrl: resourceUrl, paymentPayloadResourceUrl: paidPayload.resource.url,
        actualPaidResourceUrl: `${resourceUrl}-alt`,
        originalReportSha256: sha256(JSON.stringify(servedResourceRecord)),
        deliveredBodySha256: sha256(JSON.stringify(resourceBody)) },
      authorization: { ...paidPayload.payload.authorization, signature: paidPayload.payload.signature,
        domain: { name: DOMAIN_NAME, version: DOMAIN_VERSION, chainId: 31337, verifyingContract: tokenAddress } },
      verify: facilitatorCalls.verify[0], settle: facilitatorCalls.settle[0],
      transaction: { hash: settlement.transaction, from: transaction.from, to: transaction.to,
        input: transaction.input, blockNumber: receipt.blockNumber.toString(),
        blockHash: receipt.blockHash, blockTimestampSeconds: receiptBlock.timestamp.toString(),
        observedHead: observedHead.toString(), status: receipt.status,
        gasUsed: receipt.gasUsed.toString(), logs: receipt.logs.map(log => ({
          address: log.address, topics: log.topics, data: log.data, logIndex: log.logIndex,
        })) },
      balances: { initialBuyer: MINTED.toString(), initialSeller: "0",
        finalBuyer: finalBalances.buyerBalance, finalSeller: finalBalances.sellerBalance,
        nonceUsedAfterSettle: finalBalances.nonceUsed },
      negatives: { wrongAmount: { result: wrongAmount, before: amountBefore, after: amountAfter },
        wrongPayee: { result: wrongPayee, before: payeeBefore, after: payeeAfter },
        expired: { result: expired, before: staleBefore, after: staleAfter }, replayVerify,
        replayHttpStatus: replayResponse.status, replayContractRejected,
        invalidContractSignatureRejected },
      handlerFailure: { url: failedResourceUrl, status: failedResponse.status,
        body: failedBody, verifyCallsBefore: verifyCallsBeforeFailure,
        verifyCallsAfter: verifyCallsAfterFailure, handlerCount: failedHandlerCount,
        verificationResults: failureVerifications.map(call => call.result),
        settleCallsBefore: settleCallsBeforeFailure,
        settleCallsAfter: facilitatorCalls.settle.length, before: failedBefore, after: failedAfter,
        paymentResponseHeader: failedResponse.headers.get("PAYMENT-RESPONSE") },
      schemeLimit: { alteredResourceUrlVerified: resourceUnbound.isValid,
        explanation: "EIP-3009 signs token, chain, payer, payee, amount, validity and nonce; it does not sign the HTTP resource URL." },
      trace: trace.slice(0, 6),
      assertions: { challenge: "PASS", signedAuthorization: "PASS", readOnlyVerify: "PASS",
        onchainSettlement: "PASS", eventAndBalances: "PASS", replay: "PASS", expiry: "PASS",
        wrongAmount: "PASS", wrongPayee: "PASS", contractSignature: "PASS",
        handlerFailureNoSettlement: "PASS", timing: "PASS" },
    };
    if (output) {
      mkdirSync(dirname(resolve(output)), { recursive: true });
      writeFileSync(resolve(output), `${JSON.stringify(evidence, null, 2)}\n`);
    }
    return evidence;
  } catch (error) {
    throw new Error(`${error instanceof Error ? error.stack : String(error)}\nAnvil log: ${anvilLog.join("").slice(-2048)}`);
  } finally {
    await closeServer(resourceHttp);
    await closeServer(facilitatorHttp);
    if (anvil && anvil.exitCode === null) anvil.kill("SIGTERM");
  }
}

if (process.argv[1] && resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  const outputIndex = process.argv.indexOf("--output");
  const portIndex = process.argv.indexOf("--port");
  const recordIndex = process.argv.indexOf("--resource-record-file");
  const output = outputIndex >= 0 ? process.argv[outputIndex + 1] : undefined;
  const port = portIndex >= 0 ? Number(process.argv[portIndex + 1]) : 18545;
  const resourceRecord = recordIndex >= 0 ?
    JSON.parse(readFileSync(resolve(process.argv[recordIndex + 1]), "utf8")) : undefined;
  runLocalX402({ port, output, resourceRecord }).then(result => {
    process.stdout.write(`${JSON.stringify({ status: result.status, transaction: result.transaction.hash,
      buyerAfter: result.balances.finalBuyer, sellerAfter: result.balances.finalSeller,
      assertionCount: Object.keys(result.assertions).length, output })}\n`);
  }).catch(error => { process.stderr.write(`${error}\n`); process.exitCode = 1; });
}
