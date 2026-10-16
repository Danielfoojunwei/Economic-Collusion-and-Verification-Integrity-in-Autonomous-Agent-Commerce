# MPP010 local native isolation

MPP010 uses its own bare Tempo localnet container, `mpp010-pressure-localnet`,
with pinned image `ghcr.io/tempoxyz/tempo-localnet@sha256:86f199f161be85d3610d990e5bc2653ece29de3ee9c91e8c8e768cf2b8c05c3b`.
Only `127.0.0.1:19767` is published for RPC. Its transient MPP HTTP listener uses
`127.0.0.1:19759`. MPP009 uses separate ports and retains its own container and
receipts. The local TIP-20 token has no external value.

Both bare localnets report chain ID 1337 and deterministic genesis hash
`0xb54e201b325f207061d3502a1f4022b8a57c57bc86b7851958cc21a922b26a1f`.
The shared genesis therefore does not identify the MPP010 chain. MPP010's first
funder transaction transferred 1010 atomic TIP-20 units to its treasury wallet:

- Transaction: `0xcbfbdd6d88281a0c727e32ab709a2ac188742e188c05db6e514e5c0f0685f977`
- Block: 742, hash `0x2da511a24c05b58a2a22210c4931c92c182b14e7896585243fa908039a3b0e1e`
- Funder: `0xf39Fd6e51aad88F6F4ce6aB8827279cffFb92266` (genesis test wallet)
- Treasury: `0x8e4D1a7b8c4f7F4204EB0643C85AA7656880E18b` (derivation index 15)

Every MPP010 native helper binds the exact RPC port, marker transaction, marker
block hash, historical funder debit and treasury credit, and actor wallet set. The
provider, auditor, oracle, client, and treasury use test mnemonic derivation
indices 11 through 15 respectively, distinct from MPP009's indices 1 through 5.
The MPP010 service and compensation challenges use separate realms and secrets;
their descriptions include the MPP010 episode and request or decision commitment.
The offline report checks observed challenge IDs are unique and disjoint from the
frozen MPP009 control archive. An MPP009 chain RPC and a saved MPP009 check receipt
are both explicit rejection controls.

The container is a live runtime dependency for historical receipt verification.
Restarting a new bare chain at the same port does not restore its marker or saved
transactions; keep this container running through collection and verification.
The scripted controls make no remote model calls, and their local transactions do
not constitute prospective assignments or a freeze.
