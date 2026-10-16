"""Auditor-facing contact mask on the pinned MPP011 calendar/native bridge.

Only provider-authored proposal text is masked. The exact text remains in the
controller action log for independent attribution. Terms, offer ownership,
oracle truth, buyer calendar and native payment obligations stay identical.
"""
from __future__ import annotations

from dataclasses import dataclass
from functools import partial

from .mpp011_market import PressureBookingMarket
from .mpp011_native_service import NativeMeetingService
from .mpp012_plan import CHANNEL, NO_CONTACT


class ContactBookingMarket(PressureBookingMarket):
    def __init__(self, quality: str, *, condition: str = "OPEN",
                 base_fee_atomic: int, acceptance_bonus_atomic: int,
                 check_price_atomic: int, episode_id: str, contact: str):
        if contact not in {CHANNEL, NO_CONTACT}:
            raise ValueError("MPP012 contact arm differs")
        self.contact = contact
        super().__init__(quality, condition=condition,
                         base_fee_atomic=base_fee_atomic,
                         acceptance_bonus_atomic=acceptance_bonus_atomic,
                         check_price_atomic=check_price_atomic,
                         episode_id=episode_id)

    def public_view(self):
        view = super().public_view()
        if self.contact == NO_CONTACT:
            for event in view["negotiation_messages_untrusted"]:
                if event.get("action") == "propose" and event.get("actor") == "provider":
                    event["message_untrusted"] = ""
        return view


@dataclass(frozen=True)
class ContactNativeMeetingService(NativeMeetingService):
    contact: str = CHANNEL

    def __post_init__(self):
        super().__post_init__()
        if self.contact not in {CHANNEL, NO_CONTACT}:
            raise ValueError("MPP012 contact arm differs")

    def market_factory(self):
        return partial(ContactBookingMarket,
            base_fee_atomic=self.row.base_fee_atomic,
            acceptance_bonus_atomic=self.row.acceptance_bonus_atomic,
            check_price_atomic=self.row.check_price_atomic,
            episode_id=self.row.episode_id, contact=self.contact)
