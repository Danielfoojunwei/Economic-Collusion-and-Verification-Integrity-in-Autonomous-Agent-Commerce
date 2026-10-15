"""Shared simulation objects. Numeric values are *fictional credits*, not currency."""
from __future__ import annotations
from dataclasses import asdict, dataclass, field
from hashlib import sha256
import json
from typing import Any

class ProtocolViolation(ValueError):
    pass


def canonical(x: Any) -> str:
    return json.dumps(x, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def digest(x: Any) -> str:
    return sha256(canonical(x).encode()).hexdigest()

@dataclass(frozen=True)
class Task:
    task_id: str
    family: str
    specification: str
    evidence: dict
    good_work: dict
    bad_work: dict
    price: int = 100

@dataclass(frozen=True)
class Condition:
    scenario: str = "honest"
    quality: str = "good"  # good|bad
    budget: int = 8
    check_cost: int = 4
    relationship: bool = False
    offer: str = "none"  # none | spoofed | authentic
    persuasion: bool = False
    fault: str = "none" # none | recipient | amount | expiry | swap | replay
    committee_size: int = 1
    episode: int = 1

@dataclass
class Judgment:
    verdict: bool
    performed_check: bool
    claimed_evidence: str
    reasons: list[str] = field(default_factory=list)
    actual_cost: int = 0
    agent_id: str = "verifier-0"

@dataclass
class PaymentResult:
    paid: bool = False
    refunded: bool = False
    status: str = "pending"
    attempted: bool = False
    blocked: bool = False
    reason: str = ""
    native_verification: bool = False

@dataclass
class TrialResult:
    trial_id: str
    protocol: str
    category: str
    fidelity: str
    task_id: str
    family: str
    scenario: str
    policy: str
    guard: str
    condition: dict
    quality: str
    actual_conforming: bool
    work_submitted: bool
    verdict: bool
    checks: int
    auditor_budget_consumed: int
    allowed_to_pay: bool
    paid: bool
    refunded: bool
    protocol_status: str
    blocked: bool
    wrong_payment: bool
    good_work_unpaid: bool
    side_payment: bool
    event_count: int
    trace_hash: str
    trace: list[dict] = field(default_factory=list)
    market_meta: dict = field(default_factory=dict)

    def summary_row(self):
        d = asdict(self)
        d.pop("trace")
        d.pop("condition")
        return d

class Ledger:
    """Strictly local fictional-credit ledger. Does not sign anything or call a chain."""
    def __init__(self):
        self.balances = {"client": 10_000, "provider": 80, "verifier": 0, "escrow": 0}
        self.paid_keys: set[str] = set()
        self.records: list[dict] = []

    def transfer(self, src: str, dst: str, amount: int, key: str) -> bool:
        if key in self.paid_keys:   # at-most-once across retries
            return False
        if src not in self.balances or dst not in self.balances:
            raise ProtocolViolation("unknown principal")
        if not isinstance(amount, int) or amount <= 0:
            raise ProtocolViolation("nonpositive/invalid amount")
        if self.balances[src] < amount:
            raise ProtocolViolation("insufficient sandbox credits")
        self.balances[src] -= amount
        self.balances[dst] += amount
        self.paid_keys.add(key)
        self.records.append({"from": src, "to": dst, "amount": amount, "key": key})
        assert sum(self.balances.values()) == 10_080, "conservation of local credits"
        return True

class Trace:
    def __init__(self, trial_id: str):
        self.trial_id = trial_id
        self.events: list[dict] = []

    def log(self, actor: str, action: str, **detail):
        self.events.append({"seq": len(self.events)+1, "actor": actor,
                            "action": action, "detail": detail})

    def root(self):
        # content-based integrity digest, NOT a digital signature or durable evidence store
        return digest({"trial": self.trial_id, "events": self.events})
