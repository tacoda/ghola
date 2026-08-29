"""The oversight dial: from a person answering every call to a person answering
none.

The property that matters most is the one asserted first: `ask` never becomes
`allow`. An unattended factory reading "ask" as "yes" has answered a question
nobody put, and that is a silent failure rather than a loud one.
"""

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "workers" / "ghola-core" / "src"))

import oversight  # noqa: E402


class AskNeverBecomesAllow(unittest.TestCase):
    """The invariant. If this breaks, the dial is dangerous rather than useful."""

    def test_no_level_turns_ask_into_allow(self):
        for level in oversight.LEVELS:
            setting = oversight.resolve(level)
            self.assertIn(setting.ask_becomes, ("ask", "refuse"),
                          f"{level} turns `ask` into {setting.ask_becomes}")

    def test_dark_refuses_rather_than_allowing(self):
        # Nothing waits for a person, so a rule that wanted one refuses.
        self.assertEqual(oversight.resolve("dark").ask_becomes, "refuse")

    def test_every_attended_level_still_asks(self):
        for level in (oversight.MANUAL, oversight.ATTENDED, oversight.SUPERVISED):
            self.assertEqual(oversight.resolve(level).ask_becomes, "ask")


class TheDial(unittest.TestCase):
    def test_it_runs_from_manual_to_dark(self):
        self.assertEqual(oversight.LEVELS,
                         ("manual", "attended", "supervised", "dark"))

    def test_manual_holds_everything(self):
        self.assertEqual(oversight.resolve("manual").approval_mode, "manual")

    def test_attended_holds_writes_and_lets_reads_run(self):
        self.assertEqual(oversight.resolve("attended").approval_mode, "auto")

    def test_supervised_is_the_default(self):
        self.assertEqual(oversight.DEFAULT, "supervised")
        self.assertEqual(oversight.resolve(None).level, "supervised")
        self.assertEqual(oversight.resolve("").level, "supervised")

    def test_an_unknown_level_falls_back_rather_than_failing(self):
        # Failing a job because somebody wrote `oversight: paranoid` is worse
        # than running it supervised and saying so.
        self.assertEqual(oversight.resolve("paranoid").level, "supervised")

    def test_a_level_is_case_insensitive(self):
        self.assertEqual(oversight.resolve("DARK").level, "dark")

    def test_every_level_explains_itself(self):
        for level in oversight.LEVELS:
            self.assertTrue(oversight.resolve(level).why,
                            f"{level} has no explanation an operator can read")


class PerStage(unittest.TestCase):
    """`run` and `review` genuinely want different answers."""

    CONFIG = {"default": "supervised", "stages": {"run": "attended", "review": "dark"}}

    def test_a_stage_may_name_its_own(self):
        self.assertEqual(oversight.for_stage(self.CONFIG, "run").level, "attended")
        self.assertEqual(oversight.for_stage(self.CONFIG, "review").level, "dark")

    def test_an_unnamed_stage_falls_to_the_default(self):
        self.assertEqual(oversight.for_stage(self.CONFIG, "prove").level, "supervised")

    def test_no_config_at_all_is_the_default(self):
        self.assertEqual(oversight.for_stage(None, "run").level, "supervised")
        self.assertEqual(oversight.for_stage({}, "run").level, "supervised")

    def test_the_top_level_default_is_honoured(self):
        self.assertEqual(oversight.for_stage({"default": "manual"}, "run").level,
                         "manual")


class WhatAnOperatorReads(unittest.TestCase):
    def test_the_description_names_both_mechanisms(self):
        # Without one name for the pair, an operator has to know that setting a
        # mode to `full` silently changes what every `ask` rule does.
        line = oversight.describe(oversight.resolve("dark"))
        self.assertIn("approvals full", line)
        self.assertIn("refuse", line)


if __name__ == "__main__":
    unittest.main()
