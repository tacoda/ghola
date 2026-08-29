"""Output contracts: what invalidates a check's own claim about itself.

Most of this file is about downgrades, because a check that grades itself is not
a check. The two that matter are the same rule twice: a proof with no command
under it is a claim, and an objecting review that names nothing is a mood.

The one that matters most is neither: an answer nobody can parse is never read
as a pass. That is the failure where a check's output format drifts and reads as
approval for weeks.
"""

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "workers" / "ghola-core" / "src"))

import contracts  # noqa: E402

PROVEN = contracts.contract("proven")
VERDICT = contracts.contract("verdict")

REAL_PROOF = """PROVEN: yes
- [x] A missing file exits non-zero with a message on stderr, not a traceback.
      $ python3 wordfreq.py /tmp/definitely-not-here.txt; echo "exit=$?"
      wordfreq: /tmp/definitely-not-here.txt: No such file or directory
      exit=1
"""

REAL_REVIEW = """VERDICT: concerns

- app.py:9 — money path uses float + banker's rounding: apply_discount(2.675, 0)
  returns 2.67, not 2.68.
- app.py:12 — self-check is assert-only: `python3 -O app.py` strips every
  assertion and still prints ok.
"""


class Proving(unittest.TestCase):
    def test_a_proof_with_a_command_stands(self):
        answer = contracts.read(REAL_PROOF, PROVEN)
        self.assertEqual(answer.value, "yes")
        self.assertFalse(answer.downgraded)
        self.assertTrue(answer.evidence)

    def test_a_proof_with_no_command_is_downgraded(self):
        # Evidence or it did not happen.
        answer = contracts.read("PROVEN: yes\n- [x] It all works, I checked.", PROVEN)
        self.assertEqual(answer.value, "unproven")
        self.assertEqual(answer.downgraded_from, "yes")
        self.assertIn("claim, not a proof", answer.why)

    def test_a_no_needs_no_evidence(self):
        # Only the claim that something works has to prove itself.
        answer = contracts.read("PROVEN: no\nThe feature is not implemented.", PROVEN)
        self.assertEqual(answer.value, "no")
        self.assertFalse(answer.downgraded)

    def test_a_shell_prompt_counts_as_evidence(self):
        for prompt in ("$ make test", "> make test"):
            answer = contracts.read(f"PROVEN: yes\n  {prompt}\n  ok", PROVEN)
            self.assertEqual(answer.value, "yes", prompt)


class Reviewing(unittest.TestCase):
    def test_a_review_that_names_places_stands(self):
        answer = contracts.read(REAL_REVIEW, VERDICT)
        self.assertEqual(answer.value, "concerns")
        self.assertEqual(len(answer.findings), 2)

    def test_an_objecting_review_with_no_findings_is_downgraded(self):
        answer = contracts.read("VERDICT: concerns\n\nI have a bad feeling.", VERDICT)
        self.assertEqual(answer.value, "unreadable")
        self.assertIn("mood", answer.why)

    def test_a_pass_needs_no_findings(self):
        answer = contracts.read("VERDICT: pass\n\nLooks right.", VERDICT)
        self.assertEqual(answer.value, "pass")
        self.assertFalse(answer.downgraded)

    def test_a_blocker_must_also_name_something(self):
        answer = contracts.read("VERDICT: blocker\n\nDo not merge.", VERDICT)
        self.assertTrue(answer.downgraded)


class NeverAPass(unittest.TestCase):
    """The failure where a check's format drifts and reads as approval."""

    def test_a_missing_marker_is_unreadable_not_a_pass(self):
        answer = contracts.read("Everything looks fine to me!", VERDICT)
        self.assertEqual(answer.value, "unreadable")
        self.assertIn("not a pass", answer.why)

    def test_an_unknown_value_is_unreadable_not_a_pass(self):
        answer = contracts.read("VERDICT: looks-good", VERDICT)
        self.assertEqual(answer.value, "unreadable")
        self.assertEqual(answer.downgraded_from, "looks-good")

    def test_empty_output_is_unreadable(self):
        self.assertEqual(contracts.read("", VERDICT).value, "unreadable")

    def test_an_unparseable_proof_is_unproven_rather_than_no(self):
        # `unproven` and `no` are different answers: one is a failed check, the
        # other is a check that did not report.
        self.assertEqual(contracts.read("no idea", PROVEN).value, "unproven")

    def test_no_downgrade_ever_produces_a_passing_value(self):
        passing = {"pass", "yes"}
        for text in ("VERDICT: concerns\nnothing named",
                     "PROVEN: yes\nno commands here",
                     "VERDICT: nonsense", "nothing at all"):
            for spec in (PROVEN, VERDICT):
                self.assertNotIn(contracts.read(text, spec).value, passing, text)


class ReadingTheMarker(unittest.TestCase):
    def test_the_marker_must_start_a_line(self):
        # A phase explaining itself mid-sentence must not declare a verdict.
        answer = contracts.read(
            "I considered whether to write VERDICT: pass but decided not to.",
            VERDICT)
        self.assertEqual(answer.value, "unreadable")

    def test_punctuation_around_the_value_is_tolerated(self):
        for text in ("VERDICT: pass.", "VERDICT: **pass**", "VERDICT: `pass`"):
            self.assertEqual(contracts.read(text, VERDICT).value, "pass", text)

    def test_case_does_not_matter(self):
        self.assertEqual(contracts.read("VERDICT: PASS", VERDICT).value, "pass")

    def test_the_first_marker_wins(self):
        answer = contracts.read("VERDICT: pass\n\nlater: VERDICT: blocker", VERDICT)
        self.assertEqual(answer.value, "pass")


class ATeamsOwnContract(unittest.TestCase):
    def test_a_file_overrides_the_built_in(self):
        custom = contracts.contract("verdict", {"values": ["ship", "hold"]})
        self.assertEqual(contracts.read("VERDICT: ship", custom).value, "ship")
        self.assertEqual(contracts.read("VERDICT: pass", custom).value, "unreadable")

    def test_a_contract_with_no_requirements_downgrades_nothing(self):
        loose = {"marker": "SAY:", "values": ["ok"], "unparseable": "unreadable"}
        self.assertEqual(contracts.read("SAY: ok", loose).value, "ok")

    def test_an_unknown_contract_is_empty_rather_than_a_crash(self):
        self.assertEqual(contracts.contract("nosuchthing"), {})


class WhatThePipelineDoes(unittest.TestCase):
    def test_a_contract_never_fails_the_job(self):
        # In a dark factory a check reports; only the merge accepts. pass,
        # concerns and blocker all land as a comment and the human decides.
        for text in ("VERDICT: blocker\n- a.py:1 — broken", "VERDICT: pass"):
            self.assertTrue(contracts.as_result(contracts.read(text, VERDICT))["ok"])

    def test_a_downgrade_travels_so_it_can_be_published(self):
        result = contracts.as_result(contracts.read("PROVEN: yes\nno commands", PROVEN))
        self.assertTrue(result["downgraded"])
        self.assertEqual(result["downgraded_from"], "yes")
        self.assertEqual(result["verdict"], "unproven")

    def test_objects_names_every_answer_worth_acting_on(self):
        for text, spec in (("VERDICT: concerns\n- a.py:1 — x", VERDICT),
                           ("VERDICT: nonsense", VERDICT),
                           ("PROVEN: no", PROVEN)):
            self.assertTrue(contracts.read(text, spec).objects, text)
        self.assertFalse(contracts.read("VERDICT: pass", VERDICT).objects)


class Interrupts(unittest.TestCase):
    """The hatch is deliberately narrow."""

    def test_an_opening_line_is_a_question(self):
        self.assertEqual(
            contracts.interrupt("INTERRUPT: which table owns the email?"),
            "which table owns the email?")

    def test_the_word_mid_summary_is_not_a_question(self):
        # Checking anywhere in the text is how a turn that wrote "no INTERRUPT:
        # needed" blocks a job.
        self.assertEqual(contracts.interrupt("Done. No INTERRUPT: was needed."), "")

    def test_a_later_line_does_not_count(self):
        self.assertEqual(contracts.interrupt("I did the work.\nINTERRUPT: really?"), "")

    def test_empty_text_asks_nothing(self):
        self.assertEqual(contracts.interrupt(""), "")




class TheHookPayloadShape(unittest.TestCase):
    """The shape the harness ACTUALLY sends, copied from a logged payload.

    The first version of the verdict guard read `data["text"]`, found nothing,
    and returned quietly — so every downgrade went unrecorded and the guard
    looked like it was working. This test exists so that cannot recur silently.
    """

    def setUp(self):
        sys.path.insert(0, str(ROOT / "workers" / "ghola-policy" / "src"))
        from callbacks import post_generate
        self.extract = post_generate.assistant_text

    def test_content_is_a_list_of_typed_blocks(self):
        payload = {"generated": {"message": {"content": [
            {"type": "text", "text": "PROVEN: yes"}]}}}
        self.assertEqual(self.extract(payload), "PROVEN: yes")

    def test_thinking_is_not_the_answer(self):
        # A model reasoning aloud about what verdict to give must not be read
        # as giving one.
        payload = {"generated": {"message": {"content": [
            {"type": "thinking", "text": "maybe VERDICT: pass"},
            {"type": "text", "text": "VERDICT: concerns\n- a.py:1 — x"}]}}}
        self.assertEqual(contracts.read(self.extract(payload), VERDICT).value,
                         "concerns")

    def test_a_plain_string_still_works(self):
        payload = {"generated": {"message": {"content": "PROVEN: no"}}}
        self.assertEqual(self.extract(payload), "PROVEN: no")

    def test_an_empty_payload_extracts_nothing(self):
        self.assertEqual(self.extract({}), "")
        self.assertEqual(self.extract({"generated": {}}), "")


class EachCheckKeepsItsOwnName(unittest.TestCase):
    """`prove` and `review` both answer with a `verdict` key.

    Stored under one name, the second check overwrites the first and the pull
    request reports only whichever ran last.
    """

    def test_the_two_contracts_do_not_collide(self):
        proven = contracts.as_result(contracts.read("PROVEN: no", PROVEN))
        verdict = contracts.as_result(
            contracts.read("VERDICT: concerns\n- a.py:1 — x", VERDICT))
        job = {}
        job.update({"proven": proven["verdict"]})
        job.update({"verdict": verdict["verdict"]})
        self.assertEqual(job["proven"], "no")
        self.assertEqual(job["verdict"], "concerns")

if __name__ == "__main__":
    unittest.main()
