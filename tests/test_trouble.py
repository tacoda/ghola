"""What the improve lane is allowed to call evidence.

The property most of this file protects: a clean record produces no proposals.
A lane that always finds three things is a lane nobody believes by the third
time, and inventing trouble is much easier than finding it.
"""

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "workers" / "ghola-core" / "src"))

import trouble  # noqa: E402


def job(**fields) -> dict:
    return {"id": "a" * 32, "stage": "landed", "revisions": 0, **fields}


def entry(kind: str, actor: str = "", **detail) -> dict:
    return {"kind": kind, "actor": actor, "detail": detail}


class NothingWentWrong(unittest.TestCase):
    def test_a_clean_run_is_quiet(self):
        jobs = [job(), job(id="b" * 32)]
        found = trouble.gather(jobs, [], [])
        self.assertEqual(found, [])
        self.assertTrue(trouble.quiet(jobs, found))

    def test_the_brief_says_so_rather_than_inventing_something(self):
        self.assertIn("Nothing went wrong", trouble.as_brief([], [job()]))

    def test_no_jobs_at_all_is_also_quiet(self):
        self.assertTrue(trouble.quiet([], trouble.gather([], [], [])))


class TroubleIsReadBroadly(unittest.TestCase):
    """A job that reached a pull request still counts if it cost something.

    A lane that only looked at outright failures would miss almost everything
    worth fixing, because most of what goes wrong ends in a merged pull request
    that took two extra turns to get there.
    """

    def test_a_landed_job_that_needed_a_revision_counts(self):
        found = trouble.of_jobs([job(stage="landed", revisions=1)])
        self.assertEqual([s.kind for s in found], ["revision"])

    def test_a_job_that_stopped_to_ask_counts(self):
        found = trouble.of_jobs([job(stage="blocked")])
        self.assertEqual([s.kind for s in found], ["interrupt"])

    def test_a_verdict_of_concerns_counts(self):
        found = trouble.of_jobs([job(verdict="concerns")])
        self.assertEqual([s.kind for s in found], ["verdict-objected"])

    def test_a_downgraded_check_counts(self):
        found = trouble.of_jobs([job(verdict_downgraded=True)])
        self.assertIn("downgrade", [s.kind for s in found])

    def test_a_passing_verdict_does_not(self):
        self.assertEqual(trouble.of_jobs([job(verdict="pass", proven="yes")]), [])


class OnceAndTwice(unittest.TestCase):
    """One failure is enough to raise a proposal, and two is a different claim."""

    def test_a_single_occurrence_is_still_a_signal(self):
        found = trouble.of_jobs([job(stage="blocked")])
        self.assertEqual(len(found), 1)
        self.assertFalse(found[0].recurring)

    def test_a_repeat_is_marked_as_one(self):
        found = trouble.of_jobs([job(stage="blocked"), job(id="b" * 32, stage="blocked")])
        self.assertTrue(found[0].recurring)
        self.assertEqual(found[0].count, 2)


class WhatTheAuditLogKnowsAndTheJobsDoNot(unittest.TestCase):
    def test_a_refusal_names_the_rule_and_the_rung(self):
        found = trouble.of_audit([entry("ladder.refused", "no-secrets", rung=3)])
        self.assertEqual(found[0].kind, "refusal")
        self.assertIn("no-secrets", found[0].what)
        self.assertEqual(found[0].detail["rungs"], ["3"])

    def test_refusals_by_the_same_rule_are_one_signal(self):
        found = trouble.of_audit([entry("ladder.refused", "no-secrets", rung=3),
                                  entry("ladder.refused", "no-secrets", rung=3)])
        refusals = [s for s in found if s.kind == "refusal"]
        self.assertEqual(len(refusals), 1)
        self.assertEqual(refusals[0].count, 2)

    def test_which_rung_is_doing_the_work_is_its_own_finding(self):
        # The one question the job records cannot answer, and the one worth
        # asking: a backstop catching everything says something about how turns
        # write, not that anything wants tightening.
        found = trouble.of_audit([entry("ladder.refused", "a", rung=2),
                                  entry("ladder.refused", "b", rung=4)])
        spread = [s for s in found if s.kind == "rung-distribution"]
        self.assertEqual(len(spread), 1)
        self.assertEqual(spread[0].detail["by_rung"], {"2": 1, "4": 1})

    def test_one_rung_alone_is_not_a_distribution(self):
        found = trouble.of_audit([entry("ladder.refused", "a", rung=3)])
        self.assertNotIn("rung-distribution", [s.kind for s in found])

    def test_a_held_call_is_evidence(self):
        found = trouble.of_audit([entry("approval.held", "shell::exec")])
        self.assertIn("held", [s.kind for s in found])

    def test_an_empty_log_says_nothing(self):
        self.assertEqual(trouble.of_audit([]), [])


def watched(name: str, rung: int = 3) -> dict:
    return {"id": name, "rungs": [{"number": rung}]}


def prose(name: str) -> dict:
    return {"id": name, "rungs": [{"number": 0}]}


class RulesThatNeverFire(unittest.TestCase):
    """Removal is half the work and the one nobody does unprompted."""

    def test_a_rule_that_never_fired_is_reported(self):
        found = trouble.never_fired([watched("no-secrets")], [])
        self.assertEqual(len(found), 1)
        self.assertIn("no-secrets", found[0].what)

    def test_a_rule_that_fired_is_not(self):
        entries = [entry("ladder.refused", "no-secrets", rung=3)]
        self.assertEqual(trouble.never_fired([watched("no-secrets")], entries), [])

    def test_it_names_both_readings_rather_than_choosing(self):
        # Demote or remove is a judgement about whether the reason survives, and
        # the turn makes it. Deciding here would be deciding it without the why.
        found = trouble.never_fired([watched("x")], [])
        self.assertIn("demot", found[0].argues_for)
        self.assertIn("remov", found[0].argues_for)

    def test_no_rules_at_all_is_not_a_finding(self):
        self.assertEqual(trouble.never_fired([], []), [])


class SilenceThatProvesNothing(unittest.TestCase):
    """A rule carried at prose refuses nothing by construction.

    So it appears silent at any volume of jobs and however well it is working,
    and offering that as removal evidence is offering an argument nobody can
    answer. The improve lane's own first live run found this in `never_fired`
    and proposed the split, against three rules it would otherwise have argued
    for deleting.
    """

    def test_a_prose_rule_is_not_reported_as_never_firing(self):
        found = trouble.never_fired([prose("commits")], [])
        self.assertEqual([s.kind for s in found], ["unobservable"])

    def test_its_advice_is_promotion_rather_than_removal(self):
        found = trouble.never_fired([prose("commits")], [])
        self.assertIn("promote it", found[0].argues_for)
        self.assertIn("not the evidence", found[0].argues_for)

    def test_the_two_kinds_are_reported_separately(self):
        found = trouble.never_fired([prose("commits"), watched("no-secrets")], [])
        self.assertEqual({s.kind for s in found}, {"unobservable", "never-fired"})
        by_kind = {s.kind: s for s in found}
        self.assertEqual(by_kind["never-fired"].detail["rules"], ["no-secrets"])
        self.assertEqual(by_kind["unobservable"].detail["rules"], ["commits"])

    def test_a_rule_that_declares_no_rungs_at_all_is_unobservable(self):
        # The `ladder::list` answer for a primitive nobody gave a rung.
        self.assertEqual(trouble.never_fired([{"id": "x"}], [])[0].kind, "unobservable")


class EverySignalArguesForSomething(unittest.TestCase):
    """A count is not an argument. The useful output names a change."""

    def test_nothing_is_a_bare_number(self):
        jobs = [job(stage="failed", revisions=2, verdict="concerns",
                    history=[{"from": "run", "why": "the tests did not pass"}])]
        entries = [entry("ladder.refused", "no-secrets", rung=3),
                   entry("approval.held", "shell::exec"),
                   entry("ladder.warned", "review")]
        for signal in trouble.gather(jobs, entries, [{"id": "unused"}]):
            self.assertTrue(signal.what, signal.kind)
            self.assertGreater(len(signal.argues_for), 30, signal.kind)


class TheBrief(unittest.TestCase):
    def test_it_carries_the_jobs_a_signal_came_from(self):
        text = trouble.as_brief(trouble.of_jobs([job(stage="blocked")]),
                                [job(stage="blocked")])
        self.assertIn("aaaaaaaa", text)

    def test_a_failure_reports_the_stage_it_died_at(self):
        found = trouble.of_jobs([job(stage="failed",
                                     history=[{"from": "commit", "why": "hook refused"}])])
        self.assertEqual(found[0].detail["stage_reached"], "commit")
        self.assertIn("hook refused", found[0].what)


class Pure(unittest.TestCase):
    def test_gathering_does_not_touch_what_it_was_handed(self):
        jobs = [job(stage="blocked")]
        entries = [entry("ladder.refused", "x", rung=3)]
        before = (repr(jobs), repr(entries))
        trouble.gather(jobs, entries, [{"id": "y"}])
        self.assertEqual((repr(jobs), repr(entries)), before)


if __name__ == "__main__":
    unittest.main()
