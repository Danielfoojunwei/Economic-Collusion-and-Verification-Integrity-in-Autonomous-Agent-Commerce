# Project-wide OpenRouter budget authorization — 2026-10-15

The owner authorized: “we should spend the entire $50 to test different scenarios for different A2A payment protocols” and “ensure they use more thinking” (owner message in the 2026-10-15 Codex conversation). This raises the **total lifetime project cap** from USD 20 to USD 50. It is not an additional USD 50 allowance. Paid requests remain subject to the existing reservation, reconciliation, and stop rules.

The canonical `artifacts/budget/openrouter-ledger.jsonl` retains its original USD 20 genesis, all earlier reservations and settlements, and their hashes. A single prospective `cap_raise` event at sequence 116 (hash `82d65cf27265d9f2e79471ab6a99e67b85144f1eb50bb9b3e67692a8cfa69d21`) records the prior cap, new cap, and this authorization reference. Earlier runs and evidence freezes remain historical records under the original cap.

At the authorization boundary, the verified ledger was at sequence 115 with USD 3.796522 settled, no reservations or unknown charges, and USD 16.203478 available under the original USD 20 cap. After the cap raise alone, USD 46.203478 is available under the total USD 50 cap. These are conservative ledger charges; only separately reconciled provider billing is an invoice-level amount.
