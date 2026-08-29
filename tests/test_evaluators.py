"""The judgements ghola contributes to the `eval` worker.

These are the SAME checks the pipeline runs — `contracts.read` grades `prove`
and `review` in production — so an eval measures the thing that ships rather
than a second implementation that can drift. That is the property most of this
file is protecting.
"""

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "workers" / "ghola-core" / "src"))

import evaluators  # noqa: E402


def call(name: str, output, **arguments):
    return evaluators.run(name, {"output": output, "arguments": arguments})


class CitingEvidence(unittest.TestCase):
    """The most useful eval on a prove phase: a model that stops running things
    and starts asserting them still produces output that reads like a proof."""

    def test_a_command_under_the_claim_passes(self):
        found = call("cites-evidence",
                     "PROVEN: yes\n- [x] it works\n      $ make test\n      ok")
        self.assertTrue(found["passed"])

    def test_a_bare_assertion_fails(self):
        found = call("cites-evidence", "PROVEN: yes\n- [x] it works, I checked")
        self.assertFalse(found["passed"])
        self.assertIn("claim, not a proof", found["reason"])

    def test_it_can_demand_more_than_one(self):
        text = "PROVEN: yes\n  $ one\n  $ two"
        self.assertTrue(call("cites-evidence", text, at_least=2)["passed"])
        self.assertFalse(call("cites-evidence", text, at_least=3)["passed"])


class ReachingTheExpectedAnswer(unittest.TestCase):
    def test_the_expected_verdict_passes(self):
        found = call("verdict-is", "VERDICT: concerns\n- a.py:1 — x",
                     equals="concerns")
        self.assertTrue(found["passed"])

    def test_it_grades_after_the_downgrade_not_before(self):
        # A `concerns` naming nothing is `unreadable`. Grading the raw claim
        # would reward exactly the behaviour the contract exists to catch.
        found = call("verdict-is", "VERDICT: concerns\n\nbad vibes",
                     equals="concerns")
        self.assertFalse(found["passed"])
        self.assertEqual(found["details"]["value"], "unreadable")

    def test_a_set_of_acceptable_answers(self):
        self.assertTrue(call("verdict-is", "VERDICT: pass",
                             **{"in": ["pass", "concerns"]})["passed"])


class ObeyingTheContract(unittest.TestCase):
    def test_parseable_output_passes(self):
        self.assertTrue(call("contract", "VERDICT: pass")["passed"])

    def test_output_that_does_not_parse_fails(self):
        # A phase whose format drifted reads as unparseable on every later
        # answer, and this catches it before a prompt change ships.
        found = call("contract", "looks fine to me!")
        self.assertFalse(found["passed"])
        self.assertIn("did not parse", found["reason"])


class Mentions(unittest.TestCase):
    def test_any_of_these(self):
        self.assertTrue(call("mentions", "should use Decimal",
                             any=["Decimal", "rounding"])["passed"])

    def test_all_of_these(self):
        self.assertFalse(call("mentions", "should use Decimal",
                              all=["Decimal", "rounding"])["passed"])

    def test_none_of_these(self):
        self.assertFalse(call("mentions", "just use float",
                              none=["float"])["passed"])

    def test_it_is_case_insensitive_by_default(self):
        # A case author writing `Decimal` should not have to think about case.
        self.assertTrue(call("mentions", "use decimal", any=["Decimal"])["passed"])

    def test_a_regex_when_asked_for(self):
        self.assertTrue(call("mentions", "app.py:9 — broken",
                             any=[r"\S+\.py:\d+"], regex=True)["passed"])


class NothingPassesByAccident(unittest.TestCase):
    """An evaluator that cannot run is not evidence, and must not look like it."""

    def test_an_unknown_evaluator_fails(self):
        found = evaluators.run("nosuchthing", {"output": "anything"})
        self.assertFalse(found["passed"])
        self.assertIn("no evaluator called", found["reason"])

    def test_an_unknown_contract_says_so_rather_than_failing_oddly(self):
        # An empty contract has no marker, so every answer "fails to parse" and
        # the case fails for a reason that has nothing to do with the answer.
        found = call("contract", "VERDICT: pass", contract="nope")
        self.assertFalse(found["passed"])
        self.assertIn("no contract called", found["reason"])

    def test_a_raising_evaluator_is_a_failed_case(self):
        # Same reason a predicate that raises is a finding.
        found = call("verdict-is", object())
        self.assertFalse(found["passed"])

    def test_empty_output_never_passes(self):
        for name in ("contract", "cites-evidence"):
            self.assertFalse(call(name, "")["passed"], name)


class WhateverShapeTheRunnerSends(unittest.TestCase):
    """An evaluator that understood one shape would report `passed: false` for a
    turn that answered correctly, which is worse than not running."""

    def test_a_plain_string(self):
        self.assertTrue(call("contract", "VERDICT: pass")["passed"])

    def test_a_dict_with_text(self):
        self.assertTrue(call("contract", {"text": "VERDICT: pass"})["passed"])

    def test_content_blocks(self):
        self.assertTrue(call("contract",
                             {"content": [{"type": "text",
                                           "text": "VERDICT: pass"}]})["passed"])

    def test_a_nested_message(self):
        self.assertTrue(call("contract",
                             {"message": {"text": "VERDICT: pass"}})["passed"])


class DeterministicAndIdempotent(unittest.TestCase):
    """Durable delivery is at-least-once. An evaluator that answered differently
    on a redelivery would make the report a coin toss."""

    def test_the_same_input_gives_the_same_answer(self):
        text = "PROVEN: yes\n  $ make test"
        first = call("cites-evidence", text)
        for _ in range(5):
            self.assertEqual(call("cites-evidence", text), first)


class TheCasesShipped(unittest.TestCase):
    def test_every_case_names_an_evaluator_that_exists(self):
        import json
        for path in sorted((ROOT / "evals").glob("*.json")):
            request = json.loads(path.read_text())
            function_id = (request.get("evaluator") or {}).get("function_id", "")
            name = function_id.replace("ghola::eval::", "")
            self.assertIn(name, evaluators.EVALUATORS,
                          f"{path.name} names `{function_id}`, which nothing registers")

    def test_every_case_changes_exactly_one_dimension(self):
        # The worker's constraint, and the right one: an A/B that changed two
        # things tells you something moved and not which thing moved it.
        import json
        for path in sorted((ROOT / "evals").glob("*.json")):
            request = json.loads(path.read_text())
            self.assertIn(request.get("dimension"), ("prompt", "system_prompt"),
                          path.name)


if __name__ == "__main__":
    unittest.main()
