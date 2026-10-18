"""Integer-only proposed Paper A compensation schedule and funding preflight.

This is a design calculation, not a native payment adapter or a completed
funding attestation. Local native funding must be independently verified.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Schedule:
    base: int = 10
    amplitude: int = 8
    reserve: int = 18

    def __post_init__(self) -> None:
        for name in ("base", "amplitude", "reserve"):
            value = getattr(self, name)
            if type(value) is not int or value < 0:
                raise ValueError(f"{name} must be a nonnegative integer")
        if self.amplitude > self.base or self.reserve < self.base + self.amplitude:
            raise ValueError("reserve must cover the maximum payout; rejection pay cannot be negative")

    def payout(self, *, contingent: bool, approve: bool) -> int:
        if type(contingent) is not bool or type(approve) is not bool:
            raise ValueError("contingent and approve must be booleans")
        return self.base + (self.amplitude * (2 * int(approve) - 1) if contingent else 0)

    def refund(self, *, contingent: bool, approve: bool) -> int:
        """Return unused common reserve for a finalized decision."""
        return self.reserve - self.payout(contingent=contingent, approve=approve)


def check_affordable(endowment: int, price: int, gas_reserve: int = 0) -> bool:
    """Check price feasibility before assignment; no actual debit occurs."""
    for name, value in (("endowment", endowment), ("price", price),
                        ("gas_reserve", gas_reserve)):
        if type(value) is not int or value < 0:
            raise ValueError(f"{name} must be a nonnegative integer")
    return price + gas_reserve <= endowment
