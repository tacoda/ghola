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




class TheCommitMessage(unittest.TestCase):
    """No AI attribution, and it is a rule rather than a preference."""

    def test_it_carries_no_tool_attribution(self):
        # The operator is the author. Not adding it here means rung 4 never has
        # to remove it.
        message = actions.commit_message({"title": "add a --version flag"})
        for tell in ("Co-Authored-By", "Generated with", "claude", "Claude", "ghola-bot"):
            self.assertNotIn(tell, message)

    def test_it_is_one_line_and_bounded(self):
        message = actions.commit_message({"title": "x" * 200 + "\nsecond line"})
        self.assertNotIn("\n", message)
        self.assertLessEqual(len(message), 72)

    def test_a_job_with_no_title_still_commits(self):
        self.assertTrue(actions.commit_message({}))



class BranchNaming(unittest.TestCase):
    """The repository's convention, not the worktree worker's default."""

    def test_it_uses_the_repos_prefix(self):
        name = actions.branch_name({"title": "Document the make targets",
                                    "id": "abcdef123456"},
                                   {"branch_prefix": "feature/"})
        self.assertTrue(name.startswith("feature/document-the-make-targets"))

    def test_a_title_becomes_a_readable_slug(self):
        # A person reading a list of branches should be able to tell which is
        # which, which `iii/wt_ab12cd` does not allow.
        name = actions.branch_name({"title": "Add a --version flag!",
                                    "id": "abcdef123456"}, {})
        self.assertEqual(name, "ghola/add-a-version-flag-abcdef12")

    def test_two_jobs_from_one_spec_do_not_collide(self):
        # Without the suffix the second run of any spec fails at
        # worktree::create with `W120: branch already exists`.
        first = actions.branch_name({"title": "same spec", "id": "aaaaaaaa1111"}, {})
        second = actions.branch_name({"title": "same spec", "id": "bbbbbbbb2222"}, {})
        self.assertNotEqual(first, second)

    def test_a_job_with_no_title_falls_back_to_its_id(self):
        name = actions.branch_name({"id": "abcdef123456"}, {})
        self.assertEqual(name, "ghola/abcdef12")

    def test_a_long_title_is_bounded(self):
        name = actions.branch_name({"title": "x " * 200}, {"branch_prefix": "p/"})
        self.assertLessEqual(len(name), 55)

if __name__ == "__main__":
    unittest.main()
