"""Guard and assignment checks before the thirty-row scripted rehearsal."""

from collections import Counter
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from agent_economic_trust.bilateral030_plan import (
    CHANNEL, CONDITIONS, PROMPTED, ROWS, SOL, SONNET,
)
from agent_economic_trust.bilateral030_scripted_stress import (
    BRIBE_NOTE, NEUTRAL_NOTE, NO_BONUS_NOTE, _relative_artifact,
    make_scripts, run_all,
)


class Bilateral030ScriptedStressTests(unittest.TestCase):
    def test_full_scripted_assignment_is_deterministic_and_not_study_seed(self):
        scripts = make_scripts()
        self.assertEqual(scripts, make_scripts())
        self.assertEqual(len(scripts), ROWS)
        self.assertEqual(Counter(item.row.group for item in scripts),
                         {group: condition.count for group, condition in
                          CONDITIONS.items()})
        self.assertEqual(Counter((item.row.provider_model_id,
                                  item.row.auditor_model_id) for item in scripts),
                         {(SOL, SONNET): 15, (SONNET, SOL): 15})
        self.assertEqual(len({item.row.episode_id for item in scripts}), ROWS)
        self.assertEqual(len({item.row.obligation_id for item in scripts}), ROWS)
        self.assertEqual({item.decision for item in scripts}, {"APPROVE", "REJECT"})
        self.assertEqual({item.paid_check for item in scripts}, {True, False})

    def test_control_notes_do_not_script_an_improper_request(self):
        scripts = make_scripts()
        for item in scripts:
            if item.row.provider_prompt != PROMPTED:
                self.assertEqual(item.note, NEUTRAL_NOTE)
                self.assertNotIn("Approve this first claim anyway", item.note)
            elif item.row.accept_bonus_minor == 0:
                self.assertEqual(item.note, NO_BONUS_NOTE)
                self.assertNotIn("bonus", item.note)
            else:
                self.assertEqual(item.note, BRIBE_NOTE)
            if item.row.truth == "good":
                self.assertTrue(item.paid_check)
                self.assertEqual(item.decision, "APPROVE")
            if item.row.contact != CHANNEL:
                self.assertEqual(item.row.group, "NO_CONTACT")

    def test_credential_guard_precedes_output_directory_creation(self):
        with tempfile.TemporaryDirectory() as temp:
            target = Path(temp) / "not-created"
            with patch.dict("os.environ", {
                    "OPENROUTER_API_KEY": "dummy-credential",
                    "ALLOW_EXTERNAL_MODEL_CALLS": "false",
                    "PYTHON_DOTENV_DISABLED": "1"}):
                with self.assertRaisesRegex(RuntimeError, "credential is present"):
                    run_all(target)
            self.assertFalse(target.exists())

    def test_absolute_inspect_path_is_saved_relative_to_row(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            row_dir = root / "episode"
            log = row_dir / "inspect" / "sample.eval"
            log.parent.mkdir(parents=True)
            log.write_text("scripted")
            self.assertEqual(_relative_artifact(log.resolve(), row_dir),
                             "inspect/sample.eval")
            self.assertEqual(_relative_artifact(log, row_dir),
                             "inspect/sample.eval")
            with self.assertRaises(ValueError):
                _relative_artifact(root / "outsider", row_dir)


if __name__ == "__main__":
    unittest.main()
