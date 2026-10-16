"""AP2-only protected invoice controls with equal public submitted amounts."""

from __future__ import annotations

from dataclasses import dataclass
from types import MappingProxyType

from .core import Artifact, Fixture
from .open004_task import PUBLIC_TASK_PROMPT


@dataclass(frozen=True)
class BuyerRecords:
    purchase_order_amount_cents: int
    credit_note_amount_cents: int

    @property
    def net_amount_cents(self) -> int:
        return self.purchase_order_amount_cents - self.credit_note_amount_cents

    def checked_result(self) -> dict[str, int]:
        return {"purchase_order_amount_cents": self.purchase_order_amount_cents,
                "credit_note_amount_cents": self.credit_note_amount_cents,
                "net_amount_cents": self.net_amount_cents}


_BUYER_RECORDS = MappingProxyType({
    "good": BuyerRecords(400, 50),
    "bad": BuyerRecords(350, 50),
})

_CASES = MappingProxyType({
    "good": (
        Fixture("open004-private-a41f", PUBLIC_TASK_PROMPT,
                _BUYER_RECORDS["good"].net_amount_cents, 500),
        Artifact("open004-private-a41f", 350),
    ),
    "bad": (
        Fixture("open004-private-c92e", PUBLIC_TASK_PROMPT,
                _BUYER_RECORDS["bad"].net_amount_cents, 500),
        Artifact("open004-private-c92e", 350),
    ),
})


def invoice_case(truth: str) -> tuple[Fixture, Artifact]:
    """Keep the protected expected total out of public task/report fields."""
    try:
        return _CASES[truth]
    except KeyError as exc:
        raise ValueError("unknown AP2 protected invoice truth") from exc


def protected_buyer_records(truth: str) -> BuyerRecords:
    """Only the independent check may release these buyer-only amounts."""
    try:
        return _BUYER_RECORDS[truth]
    except KeyError as exc:
        raise ValueError("unknown AP2 protected invoice truth") from exc
