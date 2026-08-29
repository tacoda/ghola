"""Rung 1: the grant, and what a constraint takes out of it.

This is the seam a previous design got wrong in the most instructive way. The
rule said it withheld the editors from `review`; `phases.yaml` also omitted them
by hand; and the two agreed only because somebody kept them agreeing. The rule
had no caller outside its own test. These tests exist so that cannot recur
silently: they assert the subtraction happens in the payload, which is the only
place it is real.
"""

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "workers" / "ghola-core" / "src"))

import defaults  # noqa: E402
import turn  # noqa: E402


class Subtracting(unittest.TestCase):
    def test_an_exactly_granted_function_is_removed(self):
        kept, taken = turn.granted(
            ["coder::read-file", "coder::create-file"], ["coder::create-file"])
        self.assertEqual(kept, ["coder::read-file"])
        self.assertEqual(taken, ["coder::create-file"])

    def test_nothing_withheld_changes_nothing(self):
        allowed = ["coder::read-file", "shell::exec"]
        kept, taken = turn.granted(allowed, [])
        self.assertEqual(kept, allowed)
        self.assertEqual(taken, [])

    def test_a_glob_that_reaches_a_withheld_function_reports_it(self):
        # The glob is kept, because narrowing it here would silently rewrite what
        # the phase asked for. What stops the call is the deny list.
        kept, taken = turn.granted(["coder::*"], ["coder::create-file"])
        self.assertEqual(kept, ["coder::*"])
        self.assertEqual(taken, ["coder::create-file"])

    def test_a_withheld_function_nobody_granted_is_not_reported(self):
        _kept, taken = turn.granted(["coder::read-file"], ["worktree::land"])
        self.assertEqual(taken, [])


class InThePayload(unittest.TestCase):
    """The subtraction has to reach `harness::send` or it is not rung 1."""

    def test_a_withheld_function_lands_in_the_deny_list(self):
        # The harness refuses a call on "no allow-glob match OR a deny-glob
        # match", so a deny beats an allow whatever the glob said. Without this
        # the grant would still reach `coder::*` and the rule would enforce
        # nothing.
        payload = turn.payload_for("run", "go", config=defaults.config(),
                                   withheld=["coder::create-file"])
        functions = payload["options"]["functions"]
        self.assertIn("coder::create-file", functions["deny"])

    def test_nothing_withheld_leaves_the_grant_untouched(self):
        plain = turn.payload_for("run", "go", config=defaults.config())
        withheld_none = turn.payload_for("run", "go", config=defaults.config(),
                                         withheld=[])
        self.assertEqual(plain["options"]["functions"],
                         withheld_none["options"]["functions"])

    def test_a_withheld_function_the_phase_never_had_adds_no_deny(self):
        # `review` is not granted the editors, so withholding one takes nothing
        # away and should not invent a deny list to say so.
        payload = turn.payload_for("review", "go", config=defaults.config(),
                                   withheld=["coder::create-file"])
        self.assertNotIn("deny", payload["options"]["functions"])

    def test_the_exact_grant_is_dropped_from_allow(self):
        config = defaults.config()
        config["phases"]["run"]["functions"] = {
            "allow": ["coder::read-file", "coder::create-file"]}
        payload = turn.payload_for("run", "go", config=config,
                                   withheld=["coder::create-file"])
        self.assertNotIn("coder::create-file", payload["options"]["functions"]["allow"])


class WhenTheLadderIsUnreachable(unittest.TestCase):
    """A missing ladder must not fail the turn, and must not lie about it."""

    def test_no_worker_withholds_nothing(self):
        self.assertEqual(turn.withheld_by_ladder(None, "/repo"), [])

    def test_a_raising_worker_withholds_nothing(self):
        class Broken:
            def trigger(self, _payload):
                raise ConnectionError("ladder is down")
        self.assertEqual(turn.withheld_by_ladder(Broken(), "/repo"), [])

    def test_a_working_ladder_is_read(self):
        class Ladder:
            def trigger(self, payload):
                assert payload["function_id"] == "ladder::list"
                return {"withheld": ["coder::create-file"]}
        self.assertEqual(turn.withheld_by_ladder(Ladder(), "/repo"),
                         ["coder::create-file"])

    def test_a_payload_wrapped_answer_is_unwrapped(self):
        class Ladder:
            def trigger(self, _payload):
                return {"payload": {"withheld": ["shell::exec"]}}
        self.assertEqual(turn.withheld_by_ladder(Ladder(), "/repo"), ["shell::exec"])


if __name__ == "__main__":
    unittest.main()
