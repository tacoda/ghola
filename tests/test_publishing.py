"""What a job publishes, and what rung 4 gets to see.

A commit message, a pull request body and a reply are not written by any tool
and are not part of any diff, so nothing below the delivery gate has ever seen
them. That is why this is a pure module: the gate is handed exactly the string
that is about to be published.

The first real job opened a pull request with an empty body. Most of this file
exists so that cannot happen again quietly.
"""

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "workers" / "ghola-core" / "src"))
sys.path.insert(0, str(ROOT / "workers" / "ghola-factory" / "src"))

import actions  # noqa: E402
import publishing  # noqa: E402

JOB = {
    "id": "abc123",
    "title": "# Document the make targets",
    "spec": "Add a section to README.md listing the make targets.",
    "plan": "Read the Makefile, then append a section to README.md.",
    "verdict": "concerns",
    "findings": ["README.md:12 — the table drops the db- targets"],
    "proven": "yes",
    "revisions": 1,
}


class ThePullRequestBody(unittest.TestCase):
    def test_it_is_never_empty(self):
        # The failure this module exists to prevent.
        self.assertTrue(publishing.pull_request_body({}).strip())

    def test_it_carries_the_marker(self):
        # ghola pushes with the operator's credentials and IS the author, so
        # telling its own comments apart by author would find none of them.
        self.assertIn(publishing.MARKER, publishing.pull_request_body(JOB))

    def test_it_quotes_the_spec_rather_than_summarising_it(self):
        # A summary of the spec is one more thing that can be wrong.
        self.assertIn("Add a section to README.md", publishing.pull_request_body(JOB))

    def test_without_a_document_it_still_says_what_was_asked(self):
        # The plan no longer comes from the job record: it is a section of the
        # document, which is the interface between phases. A job with no
        # document still gets a body carrying the spec rather than an empty one.
        body = publishing.pull_request_body(JOB)
        self.assertIn("What was asked", body)
        self.assertIn("Add a section to README.md", body)

    def test_the_checks_are_reported(self):
        body = publishing.pull_request_body(JOB)
        self.assertIn("**review**: `concerns`", body)
        self.assertIn("**prove**: `yes`", body)
        self.assertIn("the table drops the db- targets", body)

    def test_revisions_are_reported_with_what_they_mean(self):
        self.assertIn("commit gate refused", publishing.pull_request_body(JOB))

    def test_a_downgrade_is_the_most_visible_thing_on_the_page(self):
        # A check claimed something its own output did not support, and the
        # human reading the pull request is who should know.
        job = {**JOB, "verdict": "unreadable", "verdict_downgraded": True,
               "verdict_downgraded_from": "pass"}
        body = publishing.pull_request_body(job)
        self.assertIn("downgraded from `pass`", body)

    def test_it_says_nothing_merged_itself(self):
        self.assertIn("a human decides", publishing.pull_request_body(JOB))

    def test_a_long_spec_says_it_was_truncated(self):
        # Silently truncating what a reviewer reads is the same failure as
        # silently truncating what a check is given.
        body = publishing.pull_request_body({"spec": "x" * 9000})
        self.assertIn("truncated", body)


class TheTitle(unittest.TestCase):
    def test_a_markdown_heading_does_not_become_a_stray_hash(self):
        self.assertEqual(actions.title_for({"title": "# Do the thing"}),
                         "Do the thing")

    def test_a_job_with_no_title_still_has_one(self):
        self.assertEqual(actions.title_for({}), "ghola")

    def test_it_is_bounded(self):
        self.assertLessEqual(len(actions.title_for({"title": "x" * 300})), 70)


class RepliesUnderComments(unittest.TestCase):
    def test_a_reply_carries_the_marker(self):
        # Or the next poll reads ghola's own acknowledgement as new feedback and
        # reworks forever.
        self.assertIn(publishing.MARKER, publishing.reply_to(JOB, "please rename"))

    def test_it_quotes_what_it_picked_up(self):
        self.assertIn("> please rename", publishing.reply_to(JOB, "please rename"))

    def test_it_says_where_the_answer_will_appear(self):
        self.assertIn("same branch", publishing.reply_to(JOB, "x"))

    def test_the_landed_note_carries_the_marker_too(self):
        self.assertIn(publishing.MARKER, publishing.landed_note(JOB))


class WhatRungFourSees(unittest.TestCase):
    """The gate is handed the published text, which no other rung has seen."""

    def test_the_body_is_a_string_the_gate_can_be_given(self):
        body = publishing.pull_request_body(JOB)
        self.assertIsInstance(body, str)
        self.assertTrue(body.strip())

    def test_no_ai_attribution_reaches_anything_published(self):
        # The operator is the author. Not adding it means rung 4 never has to
        # remove it.
        published = "\n".join([
            publishing.pull_request_body(JOB),
            publishing.reply_to(JOB, "x"),
            publishing.landed_note(JOB),
            actions.commit_message(JOB),
        ])
        for tell in ("Co-Authored-By", "Generated with", "Claude", "claude",
                     "Co-authored-by"):
            self.assertNotIn(tell, published)




class TheBodyIsTheDocument(unittest.TestCase):
    """Each phase appended a section as it went, so the account is already
    written by the time a human reads the pull request."""

    def setUp(self):
        sys.path.insert(0, str(ROOT / "workers" / "ghola-core" / "src"))
        import document
        self.doc = (document.start("Add a --version flag.", "Add a version flag")
                    .add("plan", "Touch cli.py only.")
                    .add("work", "Added the flag and a test.")
                    .add("proof", "$ pytest -q\n2 passed"))

    def test_every_section_reaches_the_reviewer(self):
        body = publishing.pull_request_body({}, self.doc.text)
        for expected in ("Add a --version flag.", "Touch cli.py only.",
                         "Added the flag and a test.", "$ pytest -q"):
            self.assertIn(expected, body)

    def test_it_still_carries_the_marker_and_the_footer(self):
        body = publishing.pull_request_body({}, self.doc.text)
        self.assertIn(publishing.MARKER, body)
        self.assertIn("a human decides", body)

    def test_no_document_falls_back_to_the_spec_rather_than_being_empty(self):
        body = publishing.pull_request_body({"spec": "the ask"}, "")
        self.assertIn("the ask", body)
        self.assertTrue(body.strip())

if __name__ == "__main__":
    unittest.main()
