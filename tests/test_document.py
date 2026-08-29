"""The job document: a spec that builds as it goes.

The interface between phases is a file, not a string on a record that the next
phase hopes was set. That is what makes entry and exit criteria expressible: a
phase requires sections and produces sections, and both are checkable without
running anything.
"""

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "workers" / "ghola-core" / "src"))

import defaults  # noqa: E402
import document as doc  # noqa: E402
import graph as g  # noqa: E402


class Building(unittest.TestCase):
    def test_it_starts_from_the_spec(self):
        d = doc.start("Add a --version flag.", title="Add a version flag")
        self.assertTrue(d.has("spec"))
        self.assertIn("Add a --version flag.", d.get("spec"))
        self.assertIn("# Add a version flag", d.text)

    def test_a_phase_appends_its_own_section(self):
        d = doc.start("spec text").add("plan", "Read the Makefile first.")
        self.assertTrue(d.has("spec"))
        self.assertTrue(d.has("plan"))
        self.assertIn("Read the Makefile first.", d.get("plan"))

    def test_sections_accumulate_in_order(self):
        d = (doc.start("s").add("plan", "p").add("work", "w").add("review", "r"))
        order = list(d.sections())
        self.assertEqual(order, ["spec", "plan", "work", "review"])

    def test_a_rerun_replaces_rather_than_duplicates(self):
        # A revision runs the same phase again. Two `work` sections would leave
        # a reviewer deciding which is current.
        d = doc.start("s").add("work", "first attempt").add("work", "second attempt")
        self.assertEqual(len(doc.MARKER.findall(d.text)), 2)  # spec + work
        self.assertIn("second attempt", d.get("work"))
        self.assertNotIn("first attempt", d.get("work"))

    def test_the_replacement_keeps_the_other_sections(self):
        d = (doc.start("s").add("plan", "the plan").add("work", "v1")
             .add("work", "v2"))
        self.assertIn("the plan", d.get("plan"))
        self.assertTrue(d.has("spec"))

    def test_a_round_trip_through_text_keeps_everything(self):
        d = doc.start("s").add("plan", "p").add("proof", "$ make test")
        again = doc.read(d.text)
        self.assertEqual(again.sections().keys(), d.sections().keys())
        self.assertIn("$ make test", again.get("proof"))


class WhatCountsAsPresent(unittest.TestCase):
    def test_an_empty_section_is_not_a_section(self):
        # A phase that produced a heading and no content has not met its exit
        # criteria, and counting it would make the check worthless.
        d = doc.start("s").add("plan", "   ")
        self.assertFalse(d.has("plan"))

    def test_prose_containing_hashes_does_not_invent_a_section(self):
        d = doc.start("Use `## Heading` in the README.")
        self.assertEqual(list(d.sections()), ["spec"])

    def test_a_missing_section_is_reported_by_name(self):
        d = doc.start("s")
        self.assertEqual(d.missing(("plan", "work")), ["plan", "work"])


class EntryCriteria(unittest.TestCase):
    """A phase that would run on nothing."""

    def test_a_phase_with_what_it_needs_may_start(self):
        self.assertTrue(doc.may_start(doc.start("s"), ("spec",)).ok)

    def test_a_phase_missing_its_input_may_not(self):
        check = doc.may_start(doc.start("s"), ("work",))
        self.assertFalse(check.ok)
        self.assertEqual(check.missing, ("work",))
        self.assertIn("did not run or produced nothing", check.why)

    def test_no_requirements_means_always_ready(self):
        self.assertTrue(doc.may_start(doc.Document(), ()).ok)


class ExitCriteria(unittest.TestCase):
    """A phase that returned something nobody downstream can use."""

    def test_a_phase_that_produced_what_it_promised_is_finished(self):
        d = doc.start("s").add("plan", "a real plan")
        self.assertTrue(doc.is_finished(d, ("plan",)).ok)

    def test_a_phase_that_produced_nothing_is_not(self):
        check = doc.is_finished(doc.start("s"), ("plan",))
        self.assertFalse(check.ok)
        self.assertIn("without doing what the stage is for", check.why)

    def test_an_empty_answer_does_not_satisfy_it(self):
        d = doc.start("s").add("plan", "")
        self.assertFalse(doc.is_finished(d, ("plan",)).ok)


class ThePipelineDeclaresThem(unittest.TestCase):
    def test_the_built_in_stages_name_their_criteria(self):
        graph = g.parse(defaults.pipeline())
        self.assertEqual(graph.get("plan").requires, ("spec",))
        self.assertEqual(graph.get("plan").produces, ("plan",))
        self.assertEqual(graph.get("prove").requires, ("work",))

    def test_run_does_not_require_a_plan(self):
        # Planning is skipped for a revision, and requiring it would make every
        # revision unable to start.
        self.assertNotIn("plan", g.parse(defaults.pipeline()).get("run").requires)

    def test_a_criterion_no_phase_can_satisfy_is_a_reported_typo(self):
        found = g.parse({"stages": {
            "a": {"phase": "plan", "requires": ["speck"], "next": "landed"}}})
        self.assertTrue(any("`speck`" in p for p in found.problems))

    def test_every_built_in_requirement_is_produced_by_an_earlier_stage(self):
        # Otherwise a stage can never start, which is a pipeline that stalls
        # rather than one that fails.
        graph = g.parse(defaults.pipeline())
        produced = {"spec"}
        for name in graph.stages:
            stage = graph.get(name)
            for needed in stage.requires:
                self.assertIn(needed, produced,
                              f"`{name}` requires `{needed}` and nothing before "
                              "it produces one")
            produced.update(stage.produces)




class RefiningAnIdea(unittest.TestCase):
    """A vague idea becomes a spec work can begin from.

    A spec somebody wrote carefully is not rewritten; an idea somebody typed in
    a hurry has to become one before anything is built from it.
    """

    def test_the_idea_is_kept_beside_the_spec(self):
        # A refinement that drifted is only visible if both are there.
        d = doc.start("make the docs better").add("idea", "make the docs better")
        d = d.add("spec", "# Document the ports\n\n## Acceptance criteria\n- ...")
        self.assertIn("make the docs better", d.get("idea"))
        self.assertIn("Document the ports", d.get("spec"))

    def test_refine_requires_and_produces_a_spec(self):
        stage = g.parse(defaults.pipeline()).get("refine")
        self.assertEqual(stage.requires, ("spec",))
        self.assertEqual(stage.produces, ("spec",))

    def test_it_is_opt_in_rather_than_merely_optional(self):
        # Two different things. `optional` is opt-OUT: prove and review run
        # unless a job turns them off, because a factory that quietly stopped
        # checking is worse than one that never checked. `opt_in` is off until
        # asked for. Conflating them made refine run on a job that never asked.
        graph = g.parse(defaults.pipeline())
        self.assertTrue(graph.get("refine").opt_in)
        self.assertTrue(graph.get("prove").optional)
        self.assertFalse(graph.get("prove").opt_in)

    def test_it_is_skipped_for_a_rework(self):
        # A reviewer's comment is already specific. Re-refining would blur it.
        stage = g.parse(defaults.pipeline()).get("refine")
        self.assertIn("rework", stage.skip_when)

    def test_a_job_that_did_not_ask_for_it_goes_straight_to_planning(self):
        graph = g.parse(defaults.pipeline())
        move = g.next_stage({"stage": "prepare", "want_refine": False},
                            graph, {"ok": True})
        self.assertEqual(move.to, "plan")

    def test_a_job_that_asked_for_it_refines_first(self):
        graph = g.parse(defaults.pipeline())
        move = g.next_stage({"stage": "prepare", "want_refine": True},
                            graph, {"ok": True})
        self.assertEqual(move.to, "refine")



class SectionBoundaries(unittest.TestCase):
    """A section ends where the next one's HEADING starts, not at its marker.

    The heading line sits above the marker, so slicing to the marker swallows
    it: the first refined idea came back with `## The plan` appended to it.
    """

    def test_a_section_does_not_swallow_the_next_heading(self):
        d = doc.start("the idea").add("plan", "the plan").add("work", "the work")
        self.assertNotIn("##", d.get("spec"))
        self.assertNotIn("##", d.get("plan"))
        self.assertEqual(d.get("plan"), "the plan")

    def test_the_last_section_still_reads_to_the_end(self):
        d = doc.start("s").add("work", "line one\nline two")
        self.assertEqual(d.get("work"), "line one\nline two")

    def test_a_section_containing_its_own_headings_keeps_them(self):
        # A spec legitimately has `## Acceptance criteria` inside it.
        body = "## What\n\ndo the thing\n\n## Acceptance criteria\n\n- it is done"
        d = doc.start(body)
        self.assertIn("## Acceptance criteria", d.get("spec"))
        self.assertIn("- it is done", d.get("spec"))

if __name__ == "__main__":
    unittest.main()
