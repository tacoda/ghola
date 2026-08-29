"""The stage graph, and every branch of the state machine.

`next_stage` is a pure function of two dicts, so all of this runs without an
engine, a worktree, or a pull request. That is the whole reason the factory is
written this way: wipp's equivalent decision was spread across a 3,000-line
worker and could only be exercised by sending a real spec and paying for it.
"""

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "workers" / "ghola-core" / "src"))

import defaults  # noqa: E402
import graph as g  # noqa: E402


def built_in():
    return g.parse(defaults.pipeline())


def job(stage, **fields):
    return {"stage": stage, **fields}


class TheBuiltInPipeline(unittest.TestCase):
    """It has to be valid, because most adopters will never change it."""

    def test_it_has_no_problems(self):
        self.assertEqual(built_in().problems, [])

    def test_states_are_derived_from_the_stages(self):
        # A team that adds a `threat-model` stage gets a `threat-model` state for
        # free, and one that deletes `prove` leaves no dead state behind.
        states = built_in().states
        for expected in ("prepare", "plan", "run", "waiting", "landed", "blocked"):
            self.assertIn(expected, states)

    def test_the_phases_it_names_all_exist(self):
        # A stage naming a phase nothing defines runs on the bare defaults, which
        # is a turn with the wrong model and no explanation.
        known = set(defaults.config()["phases"])
        for phase in built_in().phases():
            self.assertIn(phase, known, f"stage runs phase `{phase}` which is not defined")

    def test_nothing_merges_itself(self):
        # The one invariant of this whole repository.
        self.assertNotIn("merge", [s.action for s in built_in().stages.values()])


class Validation(unittest.TestCase):
    """The checks that catch a job stuck in a state nobody is watching."""

    def test_a_stage_pointing_nowhere_is_reported(self):
        found = g.parse({"stages": {"a": {"phase": "plan", "next": "nowhere"}}})
        self.assertTrue(any("nowhere" in p for p in found.problems))

    def test_a_stage_doing_nothing_is_reported(self):
        found = g.parse({"stages": {"a": {"next": "failed"}}})
        self.assertTrue(any("neither a phase nor an action" in p for p in found.problems))

    def test_a_stage_doing_two_things_is_reported(self):
        found = g.parse({"stages": {"a": {"phase": "plan", "action": "teardown",
                                          "next": "failed"}}})
        self.assertTrue(any("One stage does one thing" in p for p in found.problems))

    def test_a_stage_with_no_next_is_reported(self):
        # A job reaching it stops without ending: it does not crash, it just
        # stops, and nothing says so.
        found = g.parse({"stages": {"a": {"phase": "plan"}}})
        self.assertTrue(any("stops without ending" in p for p in found.problems))

    def test_an_unreachable_stage_is_reported(self):
        # A stage nobody arrives at was renamed somewhere else and not here.
        found = g.parse({"stages": {
            "a": {"phase": "plan", "next": "landed"},
            "orphan": {"phase": "run", "next": "landed"}}})
        self.assertTrue(any("cannot be reached" in p for p in found.problems))

    def test_an_empty_pipeline_says_it_does_nothing(self):
        self.assertTrue(any("does nothing" in p for p in g.parse({}).problems))

    def test_a_watched_stage_needs_no_next(self):
        found = g.parse({"stages": {"w": {"action": "watch_pull_request",
                                          "on_merge": "landed"}}})
        self.assertEqual(found.problems, [])


class MovingForward(unittest.TestCase):
    def test_a_finished_stage_goes_to_its_next(self):
        move = g.next_stage(job("plan"), built_in(), {"ok": True})
        self.assertEqual(move.to, "run")

    def test_an_unknown_stage_fails_rather_than_guessing(self):
        move = g.next_stage(job("nonsense"), built_in(), {"ok": True})
        self.assertEqual(move.to, "failed")

    def test_a_failed_stage_fails_the_job(self):
        move = g.next_stage(job("run"), built_in(), {"ok": False, "error": "boom"})
        self.assertEqual(move.to, "failed")
        self.assertIn("boom", move.why)

    def test_a_stage_allowed_to_fail_carries_on(self):
        # A plan turn that fails does not fail the job; it hands over an empty
        # plan.
        move = g.next_stage(job("plan"), built_in(), {"ok": False, "error": "x"})
        self.assertEqual(move.to, "run")


class Skipping(unittest.TestCase):
    def test_planning_is_skipped_for_a_revision(self):
        # A gate's complaint is already a brief; re-planning would blur it.
        move = g.next_stage(job("prepare", reason="revision"), built_in(), {"ok": True})
        self.assertEqual(move.to, "run")

    def test_planning_happens_for_a_fresh_job(self):
        move = g.next_stage(job("prepare"), built_in(), {"ok": True})
        self.assertEqual(move.to, "plan")

    def test_an_optional_stage_can_be_turned_off(self):
        move = g.next_stage(job("run", want_prove=False), built_in(), {"ok": True})
        self.assertEqual(move.to, "review")

    def test_turning_off_two_in_a_row_reaches_the_next_real_stage(self):
        # Chained, or turning off both checks lands on a stage that is also
        # skipped. `commit` is next because the checks are optional and the
        # delivery gate is not.
        move = g.next_stage(job("run", want_prove=False, want_review=False),
                            built_in(), {"ok": True})
        self.assertEqual(move.to, "commit")


class Refusals(unittest.TestCase):
    """The revision loop, bounded twice."""

    def test_a_refusal_sends_it_back_with_the_refusal_as_the_brief(self):
        move = g.next_stage(job("run", revisions=0), built_in(),
                            {"refused": True, "refusal": "tests fail"})
        self.assertEqual(move.to, "run")
        self.assertTrue(move.revision)

    def test_the_revision_budget_is_enforced(self):
        # An agent that cannot satisfy a gate twice will not satisfy it on the
        # ninth try, and finding out costs a turn each time.
        move = g.next_stage(job("run", revisions=2), built_in(),
                            {"refused": True, "refusal": "tests fail"})
        self.assertEqual(move.to, "failed")
        self.assertIn("max", move.why)

    def test_an_identical_refusal_stops_early(self):
        # A gate repeating itself word for word has already proved its complaint
        # is not a function of the diff.
        move = g.next_stage(job("run", revisions=0, last_refusal="tests fail"),
                            built_in(), {"refused": True, "refusal": "tests fail"})
        self.assertEqual(move.to, "failed")
        self.assertIn("word for word", move.why)

    def test_a_different_refusal_still_gets_another_turn(self):
        move = g.next_stage(job("run", revisions=0, last_refusal="tests fail"),
                            built_in(), {"refused": True, "refusal": "lint fails"})
        self.assertEqual(move.to, "run")

    def test_a_stage_with_nowhere_to_go_on_refusal_fails_loudly(self):
        move = g.next_stage(job("review"), built_in(), {"refused": True})
        self.assertEqual(move.to, "failed")
        self.assertIn("on_refusal", move.why)


class TheGate(unittest.TestCase):
    """What the human did is the edge out of `waiting`."""

    def test_a_merge_lands_it(self):
        self.assertEqual(
            g.next_stage(job("waiting"), built_in(), {"outcome": "merge"}).to, "landed")

    def test_a_close_closes_it(self):
        self.assertEqual(
            g.next_stage(job("waiting"), built_in(), {"outcome": "close"}).to, "closed")

    def test_a_comment_reworks_it(self):
        self.assertEqual(
            g.next_stage(job("waiting"), built_in(), {"outcome": "comment"}).to, "rework")

    def test_nothing_means_the_card_waits(self):
        move = g.next_stage(job("waiting"), built_in(), {})
        self.assertEqual(move.to, "waiting")
        self.assertIn("waits", move.why)


class Blocking(unittest.TestCase):
    def test_a_turn_that_asked_a_question_waits(self):
        # Nothing is retried: asking the same thing twice is not asking.
        move = g.next_stage(job("run"), built_in(), {"blocked": True})
        self.assertEqual(move.to, "blocked")

    def test_blocking_beats_a_refusal(self):
        move = g.next_stage(job("run"), built_in(),
                            {"blocked": True, "refused": True})
        self.assertEqual(move.to, "blocked")


class ATeamsOwnPipeline(unittest.TestCase):
    """The customization claim, made checkable."""

    def test_a_stage_can_be_added_without_touching_python(self):
        custom = g.parse({
            "first": "threat-model",
            "stages": {
                "threat-model": {"phase": "threat-model", "next": "run"},
                "run": {"phase": "run", "next": "landed"},
            }})
        self.assertEqual(custom.problems, [])
        self.assertEqual(g.next_stage(job("threat-model"), custom, {"ok": True}).to,
                         "run")
        self.assertIn("threat-model", custom.states)

    def test_a_minimal_pipeline_is_valid(self):
        minimal = g.parse({"stages": {"run": {"phase": "run", "next": "landed"}}})
        self.assertEqual(minimal.problems, [])

    def test_terminal_states_can_be_declared(self):
        custom = g.parse({"terminal": ["shipped"],
                          "stages": {"run": {"phase": "run", "next": "shipped"}}})
        self.assertEqual(custom.problems, [])
        self.assertIn("shipped", custom.states)


if __name__ == "__main__":
    unittest.main()
