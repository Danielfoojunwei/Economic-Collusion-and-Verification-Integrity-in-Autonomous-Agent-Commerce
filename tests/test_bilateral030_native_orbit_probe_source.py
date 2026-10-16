"""Fail-closed source controls for a local-only scripted mechanism probe."""

from __future__ import annotations

import os
import unittest
from unittest.mock import patch

from agent_economic_trust.bilateral030_native_orbit_probe import (
    _environment_guard, representative_rows,
)
from agent_economic_trust.bilateral030_plan import (
    CHANNEL, FUNDED, NO_CONTACT, SOL, SONNET,
)


class Bilateral030NativeOrbitProbeSourceTests(unittest.TestCase):
    def test_representative_controls_are_bad_funded_and_reverse_role_directions(self):
        (channel, approve), (no_contact, reject) = representative_rows()
        self.assertEqual((channel.truth, channel.accept_bonus, channel.contact,
                          channel.provider_model_id, channel.auditor_model_id, approve),
                         ("bad", FUNDED, CHANNEL, SOL, SONNET, "APPROVE"))
        self.assertEqual((no_contact.truth, no_contact.accept_bonus,
                          no_contact.contact, no_contact.provider_model_id,
                          no_contact.auditor_model_id, reject),
                         ("bad", FUNDED, NO_CONTACT, SONNET, SOL, "REJECT"))
        self.assertNotEqual(channel.episode_id, no_contact.episode_id)

    def test_environment_guard_refuses_credential_or_external_opt_in(self):
        env = {"ALLOW_EXTERNAL_MODEL_CALLS": "false",
               "PYTHON_DOTENV_DISABLED": "1"}
        with patch.dict(os.environ, env, clear=True):
            _environment_guard()
            for addition in ({"OPENROUTER_API_KEY": "secret"},
                             {"OPENROUTER_API_KEY": ""},
                             {"ALLOW_EXTERNAL_MODEL_CALLS": "true"},
                             {"PYTHON_DOTENV_DISABLED": "0"}):
                with self.subTest(addition=addition):
                    with patch.dict(os.environ, addition):
                        with self.assertRaises(RuntimeError):
                            _environment_guard()


if __name__ == "__main__":
    unittest.main()
