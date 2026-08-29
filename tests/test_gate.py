"""The pull-request gate, tested without a pull request.

`derive_outcome` is one pure function of the job record and what the forge
returned, which is what lets every branch of the gate be exercised here. wipp
proved this was worth extracting: its whole gate is a decision over two dicts,
and it is the part of a factory most expensive to test any other way.
"""

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "workers" / "ghola-core" / "src"))
sys.path.insert(0, str(ROOT / "workers" / "ghola-factory" / "src"))

import actions  # noqa: E402


def pr(state="open", merged=False, comments=(), created="2026-01-01T00:00:00Z"):
    return {"state": state, "merged": merged, "createdAt": created,
            "comments": list(comments)}


def comment(body, when="2026-01-02T00:00:00Z", ident=None):
    return {"body": body, "createdAt": when, "id": ident or when}


class WhatTheHumanDid(unittest.TestCase):
    def test_a_merge_is_a_merge(self):
        self.assertEqual(actions.derive_outcome({}, pr(merged=True))["outcome"], "merge")

    def test_a_merged_state_counts_too(self):
        self.assertEqual(actions.derive_outcome({}, pr(state="MERGED"))["outcome"],
                         "merge")

    def test_a_close_is_a_close(self):
        self.assertEqual(actions.derive_outcome({}, pr(state="closed"))["outcome"],
                         "close")

    def test_a_comment_is_a_brief(self):
        found = actions.derive_outcome({}, pr(comments=[comment("please rename this")]))
        self.assertEqual(found["outcome"], "comment")
        self.assertEqual(found["brief"], "please rename this")

    def test_nothing_is_a_legitimate_answer(self):
        # The card waits. This is the common case and it must not look like a
        # failure.
        self.assertEqual(actions.derive_outcome({}, pr())["outcome"], "")


class WhoseCommentIsIt(unittest.TestCase):
    """ghola pushes with the operator's credentials and IS the PR's author."""

    def test_gholas_own_comments_are_not_feedback(self):
        # Telling them apart by author would find none of them.
        found = actions.derive_outcome(
            {}, pr(comments=[comment(f"{actions.MARKER}\nopened by ghola")]))
        self.assertEqual(found["outcome"], "")

    def test_a_real_comment_after_gholas_own_is_feedback(self):
        found = actions.derive_outcome({}, pr(comments=[
            comment(f"{actions.MARKER} opened", "2026-01-02T00:00:00Z"),
            comment("this needs a test", "2026-01-03T00:00:00Z"),
        ]))
        self.assertEqual(found["brief"], "this needs a test")

    def test_a_comment_older_than_the_pull_request_is_not_feedback(self):
        found = actions.derive_outcome({}, pr(
            created="2026-01-05T00:00:00Z",
            comments=[comment("from a previous life", "2026-01-01T00:00:00Z")]))
        self.assertEqual(found["outcome"], "")

    def test_a_comment_already_answered_is_not_feedback_again(self):
        # Otherwise the gate reworks the same comment forever.
        found = actions.derive_outcome(
            {"answered_comment": "c1"},
            pr(comments=[comment("please rename", ident="c1")]))
        self.assertEqual(found["outcome"], "")

    def test_the_newest_unanswered_comment_wins(self):
        found = actions.derive_outcome({"answered_comment": "c1"}, pr(comments=[
            comment("old", "2026-01-02T00:00:00Z", ident="c1"),
            comment("new", "2026-01-03T00:00:00Z", ident="c2"),
        ]))
        self.assertEqual(found["brief"], "new")

    def test_the_comment_id_travels_so_it_can_be_marked_answered(self):
        found = actions.derive_outcome({}, pr(comments=[comment("x", ident="c9")]))
        self.assertEqual(found["comment_id"], "c9")


class MergeBeatsEverything(unittest.TestCase):
    def test_a_merged_pull_request_with_comments_still_lands(self):
        # A review arriving after a merge is a note in a closed room.
        found = actions.derive_outcome({}, pr(merged=True, comments=[comment("late")]))
        self.assertEqual(found["outcome"], "merge")


class EveryOutcomeIsAGraphEdge(unittest.TestCase):
    """The gate and the graph have to agree on the vocabulary."""

    def test_the_outcomes_match_what_the_pipeline_declares(self):
        import defaults
        import graph as g
        waiting = g.parse(defaults.pipeline()).get("waiting")
        declared = {name for name, _ in waiting.outcomes}
        for outcome in ("merge", "close", "comment"):
            self.assertIn(outcome, declared,
                          f"the gate can return `{outcome}` and the graph has no "
                          "edge for it, so a job would sit in `waiting` forever")


if __name__ == "__main__":
    unittest.main()
