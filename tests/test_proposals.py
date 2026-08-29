"""What the improve lane is allowed to produce, and what accepting one does.

Two properties matter more than the parsing. A proposal that cannot be traced
back to evidence is dropped, because this lane turns evidence into suggestions
and not the other way around. And accepting one **applies nothing**: it writes
a spec that goes through the same pipeline and the same pull request as any
other work.
"""

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "workers" / "ghola-core" / "src"))

import proposals  # noqa: E402

WHOLE = """
## Say the money rule out loud

- lane: charter
- kind: rule
- action: add
- target: CLAUDE.md
- evidence: job a48bf8ec, refusal
- why: two jobs used floats for money and the reviewer caught both

Money is `Decimal`, everywhere. The rule exists in the reviewer's head and
nowhere a turn can read it.
"""


def one(text: str = WHOLE) -> proposals.Proposal:
    found, problems = proposals.parse(text)
    assert not problems, problems
    return found[0]


class Reading(unittest.TestCase):
    def test_it_reads_the_three_things_a_proposal_names(self):
        p = one()
        self.assertEqual((p.lane, p.kind, p.action), ("charter", "rule", "add"))
        self.assertEqual(p.target, "CLAUDE.md")

    def test_it_keeps_the_prose_under_the_fields(self):
        self.assertIn("Money is `Decimal`", one().body)

    def test_the_heading_is_the_title(self):
        self.assertEqual(one().title, "Say the money rule out loud")

    def test_several_in_one_answer(self):
        found, _ = proposals.parse(WHOLE + WHOLE.replace("money rule", "port"))
        self.assertEqual(len(found), 2)

    def test_bold_fields_and_backticked_values_still_read(self):
        text = WHOLE.replace("- lane: charter", "- **lane**: `charter`")
        self.assertEqual(one(text).lane, "charter")

    def test_a_proposal_prefix_on_the_heading_is_not_part_of_the_title(self):
        self.assertEqual(one(WHOLE.replace("## Say", "## PROPOSAL: Say")).title,
                         "Say the money rule out loud")

    def test_an_empty_answer_is_no_proposals_and_no_problems(self):
        # Propose nothing if nothing went wrong. This is a correct answer.
        self.assertEqual(proposals.parse(""), ([], []))

    def test_prose_with_no_proposals_in_it_raises_no_proposals(self):
        found, _ = proposals.parse("I read the evidence and found nothing.")
        self.assertEqual(found, [])


class EvidenceOrItIsDropped(unittest.TestCase):
    """The rule keeping this lane honest."""

    def test_a_proposal_with_no_evidence_is_dropped(self):
        found, problems = proposals.parse(WHOLE.replace(
            "- evidence: job a48bf8ec, refusal", ""))
        self.assertEqual(found, [])
        self.assertIn("no evidence", problems[0])

    def test_the_dropped_one_is_named_rather_than_vanishing(self):
        _, problems = proposals.parse(WHOLE.replace("- why:", "- unwhy:"))
        self.assertIn("Say the money rule out loud", problems[0])

    def test_several_jobs_read_as_several_pieces_of_evidence(self):
        self.assertEqual(one().evidence, ("job a48bf8ec", "refusal"))


class Vocabulary(unittest.TestCase):
    def test_a_lane_nothing_defines_is_refused(self):
        _, problems = proposals.parse(WHOLE.replace("lane: charter", "lane: vibes"))
        self.assertIn("lane must be one of", problems[0])

    def test_a_kind_that_is_not_a_primitive_of_its_lane_is_refused(self):
        # `stage` is a factory primitive. A charter does not have stages, and a
        # proposal naming one has picked the wrong lane.
        _, problems = proposals.parse(WHOLE.replace("kind: rule", "kind: stage"))
        self.assertIn("not a charter primitive", problems[0])

    def test_the_refusal_says_what_would_have_worked(self):
        _, problems = proposals.parse(WHOLE.replace("kind: rule", "kind: stage"))
        self.assertIn("hook", problems[0])

    def test_an_eval_belongs_in_any_lane(self):
        for lane in proposals.LANES:
            text = WHOLE.replace("lane: charter", f"lane: {lane}").replace(
                "kind: rule", "kind: eval")
            self.assertTrue(one(text).usable, lane)

    def test_removal_is_a_first_class_action(self):
        # Improvement is not only addition, and this is the one nobody does
        # unprompted.
        self.assertIn("remove", proposals.ACTIONS)
        self.assertTrue(one(WHOLE.replace("action: add", "action: remove")).usable)

    def test_a_proposal_that_names_nothing_to_change_is_refused(self):
        _, problems = proposals.parse(WHOLE.replace("- target: CLAUDE.md", ""))
        self.assertIn("cannot be acted on", problems[0])


class Moves(unittest.TestCase):
    """Promotion and demotion are the only two ghola applies, and only because
    each is one number in a file that still becomes a pull request."""

    def test_a_promotion_is_a_move(self):
        text = WHOLE.replace("action: add", "action: promote") + "\n- rung: 3\n"
        self.assertTrue(one(text).is_move)

    def test_a_move_without_a_rung_is_refused(self):
        _, problems = proposals.parse(WHOLE.replace("action: add", "action: demote"))
        self.assertIn("needs a rung", problems[0])

    def test_an_ordinary_proposal_is_not_a_move(self):
        self.assertFalse(one().is_move)

    def test_only_two_actions_are_applied_directly(self):
        self.assertEqual(set(proposals.MOVES), {"promote", "demote"})


class TheSpecItBecomes(unittest.TestCase):
    def test_accepting_produces_a_spec_and_says_nothing_was_applied(self):
        spec = proposals.as_spec(one())
        self.assertIn("Nothing was applied", spec)
        self.assertIn("same pipeline", spec)

    def test_the_spec_does_not_repeat_the_fields_as_prose(self):
        spec = proposals.as_spec(one())
        self.assertNotIn("- lane:", spec)
        self.assertIn("Money is `Decimal`", spec)

    def test_the_spec_carries_the_evidence_forward(self):
        self.assertIn("job a48bf8ec", proposals.as_spec(one()))

    def test_it_has_the_sections_a_spec_has(self):
        spec = proposals.as_spec(one())
        for heading in ("## What", "## Why", "## Acceptance criteria"):
            self.assertIn(heading, spec)

    def test_the_filename_is_readable(self):
        self.assertEqual(proposals.slug(one()), "say-the-money-rule-out-loud")

    def test_a_title_of_punctuation_still_produces_a_filename(self):
        self.assertEqual(proposals.slug(proposals.Proposal(title="!!!")), "proposal")


class LaneDistribution(unittest.TestCase):
    """Proposals should thin out with distance from the project's own code."""

    def test_it_counts_every_lane_including_the_empty_ones(self):
        self.assertEqual(proposals.lane_distribution([one()]),
                         {"charter": 1, "harness": 0, "factory": 0})

    def test_more_factory_than_charter_is_flagged(self):
        note = proposals.distribution_note({"charter": 0, "harness": 0, "factory": 2})
        self.assertIn("lane was picked", note)

    def test_a_normal_distribution_is_not(self):
        self.assertEqual(
            proposals.distribution_note({"charter": 3, "harness": 1, "factory": 1}), "")

    def test_one_factory_proposal_is_not_a_pattern(self):
        self.assertEqual(
            proposals.distribution_note({"charter": 0, "harness": 0, "factory": 1}), "")


class ThePromptTeachesTheSameVocabulary(unittest.TestCase):
    """A prompt naming a lane the parser rejects would produce proposals that
    are dropped for obeying their own instructions."""

    def setUp(self):
        self.prompt = (ROOT / "prompts" / "improve.md").read_text()

    def test_every_lane_is_described(self):
        for lane in proposals.LANES:
            self.assertIn(f"**{lane}**", self.prompt)

    def test_every_action_is_offered(self):
        for action in proposals.ACTIONS:
            self.assertIn(f"**{action}**", self.prompt)

    def test_the_example_it_gives_actually_parses(self):
        body = self.prompt.split("```")[1]
        found, problems = proposals.parse(
            body.replace("<a title naming the change>", "An example")
                .replace("<what happened, and what this would have changed about it>",
                         "it happened"))
        self.assertEqual(problems, [])
        self.assertEqual(len(found), 1)

    def test_it_says_an_empty_answer_is_allowed(self):
        self.assertIn("Propose nothing if nothing went wrong", self.prompt)


if __name__ == "__main__":
    unittest.main()
