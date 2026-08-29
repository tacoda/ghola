"""Governance gates: what a machine can prove before something ships.

The invariant under all of it: a promote-class call with no verdict is refused,
at every oversight level. A person watching is not the same as a machine having
proved something, and those two are routinely confused.
"""

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "workers" / "ghola-core" / "src"))

import governance  # noqa: E402
import oversight  # noqa: E402


class WhatCountsAsShipping(unittest.TestCase):
    def test_the_suffixes_are_promote_class(self):
        for name in ("myapp::deploy", "x::merge", "y::publish", "z::push",
                     "a::apply", "b::promote"):
            promote, why = governance.is_promote(name)
            self.assertTrue(promote, name)
            self.assertTrue(why)

    def test_a_function_that_ships_without_saying_so_is_still_caught(self):
        # A gate that only catches calls polite enough to be called `::deploy`
        # is theatre. `worktree::land` is a merge whatever it is called.
        promote, why = governance.is_promote("worktree::land")
        self.assertTrue(promote)
        self.assertIn("fast-forwards", why)

    def test_merging_counts(self):
        self.assertTrue(governance.is_promote("github::pr::merge")[0])
        self.assertTrue(governance.is_promote("worktree::land")[0])

    def test_opening_a_pull_request_does_not_count(self):
        # The first real job through this pipeline failed here, and it was right
        # to fail and wrong to be asked. A pull request is a PROPOSAL a human
        # decides on: it is the one thing ghola exists to do, and gating it
        # behind a machine proof means a factory whose entire output requires a
        # verdict it cannot yet mint. What changes the world is the merge.
        for name in ("github::pr::create", "github::pr::comment",
                     "github::issue::create"):
            self.assertFalse(governance.is_promote(name)[0], name)

    def test_a_proposal_needs_no_verdict(self):
        self.assertTrue(governance.decide("github::pr::create", has_verdict=False).allowed)

    def test_an_ordinary_call_is_not_promote_class(self):
        for name in ("coder::read-file", "shell::exec", "ladder::list"):
            self.assertFalse(governance.is_promote(name)[0], name)


class FailingClosed(unittest.TestCase):
    """The invariant. If this breaks, the gate is decoration."""

    def test_a_promote_with_no_verdict_is_refused(self):
        gate = governance.decide("worktree::land", has_verdict=False)
        self.assertEqual(gate.decision, governance.REQUIRE_VERDICT)
        self.assertFalse(gate.allowed)

    def test_no_oversight_level_lets_an_unproven_promote_through(self):
        # Including `manual`. A person watching is not proof, and this is the
        # confusion the gate exists to prevent.
        for level in oversight.LEVELS:
            gate = governance.decide("myapp::deploy", has_verdict=False,
                                     oversight_level=level)
            self.assertFalse(gate.allowed, f"{level} allowed an unproven promote")

    def test_a_verdict_lets_it_through(self):
        self.assertTrue(governance.decide("myapp::deploy", has_verdict=True).allowed)

    def test_an_ordinary_call_needs_no_verdict(self):
        self.assertTrue(governance.decide("coder::read-file", has_verdict=False).allowed)

    def test_the_refusal_explains_what_would_satisfy_it(self):
        gate = governance.decide("worktree::land", has_verdict=False)
        self.assertIn("repository's own gates", gate.reason)
        self.assertIn("exact revision", gate.reason)
        self.assertIn("not a substitute", gate.reason)


class RungOneAgrees(unittest.TestCase):
    def test_a_promote_the_stage_was_never_granted_is_denied_outright(self):
        gate = governance.decide("worktree::land", has_verdict=True,
                                 allowed_functions=("coder::read-file",))
        self.assertEqual(gate.decision, governance.DENY)
        self.assertIn("Rung 1 already stopped this", gate.reason)


class ThePolicy(unittest.TestCase):
    def test_require_verdict_defaults_to_on(self):
        # A governance gate that ships off is a governance gate nobody turns on.
        self.assertTrue(governance.Policy.of(None).require_verdict)
        self.assertTrue(governance.Policy.of({}).require_verdict)

    def test_a_deployment_may_declare_its_own_promote_class_functions(self):
        policy = governance.Policy.of(
            {"also_promote": {"myapp::ship-it": "pushes to production"}})
        gate = policy.gate("myapp::ship-it", has_verdict=False)
        self.assertEqual(gate.decision, governance.REQUIRE_VERDICT)
        self.assertIn("pushes to production", gate.reason)

    def test_an_exemption_is_allowed_and_named_as_a_hole(self):
        # A deliberate hole recorded as one. "Why did that ship unproven" needs
        # an answer that is not a shrug.
        policy = governance.Policy.of({"exempt": ["github::pr::comment"]})
        gate = policy.gate("github::pr::comment", has_verdict=False)
        self.assertTrue(gate.allowed)
        self.assertIn("deliberate hole", gate.reason)

    def test_turning_it_off_says_so_in_the_reason(self):
        policy = governance.Policy.of({"require_verdict": False})
        gate = policy.gate("worktree::land", has_verdict=False)
        self.assertTrue(gate.allowed)
        self.assertIn("settings/governance.yaml", gate.reason)

    def test_turning_it_off_leaves_ordinary_calls_silent(self):
        policy = governance.Policy.of({"require_verdict": False})
        self.assertEqual(policy.gate("coder::read-file", has_verdict=False).reason, "")


class TheThreeMechanismsAreDistinct(unittest.TestCase):
    """Confusing them is how a system ends up with two of them and a gap."""

    def test_governance_does_not_ask_a_person(self):
        # That is approval-gate's job. This gate refuses and says what would
        # satisfy it, which is a different answer from "wait".
        gate = governance.decide("worktree::land", has_verdict=False)
        self.assertNotEqual(gate.decision, "hold")

    def test_governance_does_not_judge_the_code(self):
        # That is the ladder's job. Governance asks whether this change PROVED
        # itself, not whether it is well written.
        self.assertTrue(governance.decide("coder::create-file", has_verdict=False).allowed)


if __name__ == "__main__":
    unittest.main()
