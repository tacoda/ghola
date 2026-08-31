"""The ladder, tested without an engine.

Every decision here is a pure function of primitives and a proposed write, which
is why `gate.decide` takes its predicate runner as an argument. If these tests
ever need a running engine, something has been wired the wrong way round.
"""

import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "workers" / "ghola-ladder" / "src"))

import gate  # noqa: E402
import lifecycle  # noqa: E402
import load as loader  # noqa: E402
import parse  # noqa: E402
import predicate as pred  # noqa: E402
from primitive import (  # noqa: E402
    CAPABILITY,
    CONSTRAINT,
    FEEDBACK,
    FEEDFORWARD,
    LadderError,
    Primitive,
    rung_number,
    validate,
)

RULE = """---
id: name-the-swallow
description: A broad except says what it is swallowing and why
why: A gate that fails silently on its own bug stops the factory invisibly.
rung: [3, 4]
paths: ["workers/**"]
escape: swallow-ok
---

The body is the primitive's own prose, and it survives a promotion.
"""


def never(_rule, _write):
    return []


def always(reason="a finding"):
    def run(_rule, write):
        return [pred.Finding(path=write.path, why=reason)]
    return run


def rule(**kwargs) -> Primitive:
    base = {"id": "x", "kind": "rule", "why": "w", "script": "x.py", "rungs": (3,)}
    return Primitive(**{**base, **kwargs})


# ------------------------------------------------------- the five axes

class TheAxesAreDerived(unittest.TestCase):
    """Only the layer is written down. A field can disagree with its file."""

    def test_the_kind_decides_the_side(self):
        self.assertEqual(parse.parse("---\nid: a\nwhy: w\n---\n", kind="rule").side, CONSTRAINT)
        for kind in ("command", "skill", "agent", "mcp", "eval"):
            p = parse.parse("---\nid: a\nwhy: w\n---\n", kind=kind)
            self.assertEqual(p.side, CAPABILITY, f"{kind} should be a capability")

    def test_a_script_beside_the_file_is_the_whole_declaration(self):
        told = parse.parse("---\nid: a\nwhy: w\n---\n", kind="rule", layer="project")
        run = parse.parse("---\nid: a\nwhy: w\n---\n", kind="rule", layer="project",
                          script="a.py")
        self.assertEqual(told.direction, FEEDFORWARD)
        self.assertEqual(run.direction, FEEDBACK)
        # And the rung follows, with nothing else edited.
        self.assertEqual(told.rungs, (0,), "prose")
        self.assertEqual(run.rungs, (2,), "hook: a project rule that runs")

    def test_deterministic_and_inferential_are_both_feedback(self):
        code = rule(script="a.py", grades="")
        judged = rule(script="", grades="whether the summary names the risk")
        self.assertEqual(code.determinism, "deterministic")
        self.assertEqual(judged.determinism, "inferential")
        self.assertEqual(judged.direction, FEEDBACK)
        self.assertEqual(rule(script="", grades="").determinism, "")

    def test_a_level_is_a_layer_under_another_name(self):
        self.assertEqual(rule(layer="team").level, "harness")
        self.assertEqual(rule(layer="org").level, "factory")
        self.assertEqual(rule(layer="project").level, "charter")


class WhereAPrimitiveLandsWithNoRung(unittest.TestCase):
    """The level decides, plus whether there is a script."""

    def test_the_constraint_defaults(self):
        cases = {("project", True): 2, ("project", False): 0,
                 ("team", True): 3, ("team", False): 0,
                 ("org", True): 4, ("org", False): 0}
        for (layer, scripted), expected in cases.items():
            p = parse.parse("---\nid: a\nwhy: w\n---\n", kind="rule", layer=layer,
                            script="a.py" if scripted else "")
            self.assertEqual(p.rungs, (expected,), f"{layer} scripted={scripted}")

    def test_ci_is_never_implied(self):
        # It runs outside entirely, so putting something there is a choice
        # somebody makes rather than a default they fall into.
        for layer in ("project", "team", "org"):
            p = parse.parse("---\nid: a\nwhy: w\n---\n", kind="rule", layer=layer,
                            script="a.py")
            self.assertNotIn(5, p.rungs)

    def test_a_capabilitys_rung_is_its_layer(self):
        for layer, expected in (("project", 1), ("team", 2), ("org", 3)):
            p = parse.parse("---\nid: a\nwhy: w\n---\n", kind="skill", layer=layer)
            self.assertEqual(p.rungs, (expected,))

    def test_a_declared_rung_is_marked_as_a_departure(self):
        default = parse.parse("---\nid: a\nwhy: w\n---\n", kind="rule", layer="team")
        departed = parse.parse("---\nid: a\nwhy: w\nrung: ci\n---\n", kind="rule", layer="team")
        self.assertFalse(default.declared_rungs)
        self.assertTrue(departed.declared_rungs)
        self.assertEqual(departed.rungs, (5,))


class Rungs(unittest.TestCase):
    def test_a_rung_is_written_either_way(self):
        self.assertEqual(rung_number(3), rung_number("turn"))
        self.assertEqual(rung_number("3"), 3)

    def test_the_two_ladders_have_different_names_at_the_same_number(self):
        self.assertEqual(rung_number("hook", CONSTRAINT), 2)
        self.assertEqual(rung_number("team", CAPABILITY), 2)

    def test_a_level_name_reaches_the_capability_ladder(self):
        self.assertEqual(rung_number("harness", CAPABILITY), 2)

    def test_a_rung_outside_the_ladder_is_refused(self):
        with self.assertRaises(LadderError):
            rung_number(9)


class Validation(unittest.TestCase):
    def test_a_mechanical_rung_with_nothing_that_runs_is_refused(self):
        # The check that matters most: such a rule reports itself, refuses
        # nothing, and looks enforced on every dashboard.
        problems = validate(rule(script="", grades="", rungs=(3,)))
        self.assertTrue(any("nothing here runs" in p for p in problems))

    def test_prose_needs_no_script(self):
        self.assertEqual(validate(rule(script="", rungs=(0,))), [])

    def test_ask_is_only_available_at_rung_three(self):
        self.assertTrue(any("rung 3" in p for p in validate(
            rule(rungs=(4,), policy="ask"))))
        self.assertEqual(validate(rule(rungs=(3,), policy="ask")), [])

    def test_rung_one_that_withholds_nothing_takes_nothing_away(self):
        self.assertTrue(any("takes nothing away" in p
                            for p in validate(rule(rungs=(1,), script=""))))
        self.assertEqual(validate(rule(rungs=(1,), script="", withholds=("Write",))), [])

    def test_a_capability_cannot_disagree_with_its_own_layer(self):
        p = Primitive(id="s", kind="skill", layer="team", why="w", rungs=(3,))
        self.assertTrue(any("its layer" in x for x in validate(p)))

    def test_a_derived_kind_cannot_be_authored(self):
        self.assertTrue(any("derived" in x for x in validate(
            Primitive(id="h", kind="hook", why="w", rungs=(2,)))))

    def test_no_why_means_it_can_never_be_removed_on_evidence(self):
        self.assertTrue(any("why" in p for p in validate(rule(why=""))))


class Deciding(unittest.TestCase):
    def setUp(self):
        self.rule = parse.parse(RULE, kind="rule", layer="team", script="x.py")
        self.write = gate.Write(path="workers/a.py", content="except: pass")

    def test_a_satisfied_rule_allows(self):
        self.assertTrue(gate.decide([self.rule], self.write, 3, never).allowed)

    def test_a_broken_rule_refuses_in_its_own_words(self):
        decision = gate.decide([self.rule], self.write, 3, always("bare except"))
        self.assertEqual(decision.action, gate.DENY)
        self.assertIn("A broad except", decision.reason)
        self.assertIn("Why:", decision.reason, "the why did not reach the model")
        self.assertIn("swallow-ok", decision.reason, "the escape hatch was not named")

    def test_a_rule_is_silent_about_paths_it_does_not_govern(self):
        outside = gate.Write(path="docs/readme.md", content="except: pass")
        self.assertTrue(gate.decide([self.rule], outside, 3, always()).allowed)

    def test_a_rule_is_silent_at_a_rung_it_does_not_name(self):
        self.assertTrue(gate.decide([self.rule], self.write, 5, always()).allowed)

    def test_the_escape_hatch_allows_and_travels_with_the_code(self):
        excused = gate.Write(path="workers/a.py", content="except: pass  # swallow-ok")
        self.assertTrue(gate.decide([self.rule], excused, 3, always()).allowed)

    def test_ask_holds_rather_than_denying(self):
        self.assertEqual(
            gate.decide([rule(policy="ask")], self.write, 3, always()).action, gate.HOLD)

    def test_warn_allows_and_is_counted_separately(self):
        warner = rule(policy="warn")
        self.assertTrue(gate.decide([warner], self.write, 3, always()).allowed)
        self.assertEqual(len(gate.warnings([warner], self.write, 3, always())), 1)

    def test_rung_four_sees_text_no_tool_wrote(self):
        # A commit message and a pull request body are neither written by a tool
        # nor part of any diff, so no rung below 4 can see them at all.
        publishing = gate.Write(publishing="Co-Authored-By: an agent")
        self.assertFalse(gate.decide([rule(rungs=(4,))], publishing, 4, always()).allowed)


class TheLifecycle(unittest.TestCase):
    """One verb moves either side."""

    def test_promoting_a_constraint_changes_its_number(self):
        plan = lifecycle.plan_move(rule(rungs=(0,), script="x.py"), "promote", to="turn")
        self.assertTrue(plan.ok)
        self.assertEqual(plan.now, (3,))
        self.assertEqual([s.action for s in plan.steps], ["write"])

    def test_promoting_a_capability_moves_its_files(self):
        skill = Primitive(id="triage", kind="skill", layer="project", why="w", rungs=(1,),
                          source="/repo/.claude/skills/triage.md")
        plan = lifecycle.plan_move(skill, "promote", to="team",
                                   layer_roots={"team": "/ladder/team"})
        self.assertTrue(plan.ok)
        self.assertEqual([s.action for s in plan.steps], ["move"])
        self.assertIn("/ladder/team", plan.steps[0].to)

    def test_carrying_adds_a_rung_and_keeps_the_rest(self):
        plan = lifecycle.plan_move(rule(rungs=(3,)), "carry", at="delivery")
        self.assertEqual(plan.now, (3, 4))
        self.assertTrue(any("BOUNDARIES" in n for n in plan.notes))

    def test_dropping_the_last_rung_is_a_deletion_and_says_so(self):
        plan = lifecycle.plan_move(rule(rungs=(3,)), "drop", at="turn")
        self.assertFalse(plan.ok)
        self.assertIn("say `remove`", plan.problems[0])

    def test_promoting_to_a_mechanical_rung_with_no_script_is_refused(self):
        plan = lifecycle.plan_move(rule(rungs=(0,), script=""), "promote", to="turn")
        self.assertFalse(plan.ok)
        self.assertTrue(any("nothing here runs" in p for p in plan.problems))
        self.assertIn("the missing half is the work, not a flag", plan.notes)

    def test_moving_to_rung_two_generates_the_hook(self):
        # A rung changed in the file and not in the generated hook is how a rule
        # ends up at rung 2 with nothing mounted.
        plan = lifecycle.plan_move(rule(rungs=(0,), script="x.py"), "promote", to="hook")
        self.assertIn("generate-hook", [s.action for s in plan.steps])

    def test_moving_off_rung_two_removes_it(self):
        plan = lifecycle.plan_move(rule(rungs=(2,), script="x.py"), "promote", to="turn")
        self.assertIn("remove-hook", [s.action for s in plan.steps])

    def test_a_locked_primitive_refuses_without_force(self):
        plan = lifecycle.plan_move(rule(locked=True), "promote", to="delivery")
        self.assertFalse(plan.ok)
        self.assertTrue(lifecycle.plan_move(
            rule(locked=True, script="x.py"), "promote", to="delivery", force=True).ok)

    def test_removing_takes_the_script_with_it(self):
        plan = lifecycle.plan_move(rule(source="a.md", script="a.py"), "remove")
        self.assertEqual([s.action for s in plan.steps], ["delete", "delete"])
        self.assertTrue(any("nobody does unprompted" in n for n in plan.notes))

    def test_adding_lands_on_the_rung_its_level_and_script_imply(self):
        plan = lifecycle.plan_add("no-secrets", "rule", "team", has_script=True, why="w")
        self.assertEqual(plan.now, (3,))
        self.assertEqual(len(plan.steps), 2, "both halves are scaffolded")

    def test_adding_without_a_why_warns_rather_than_refusing(self):
        plan = lifecycle.plan_add("x", "rule", "team", has_script=False)
        self.assertTrue(plan.ok)
        self.assertTrue(any("demoted or removed on evidence" in n for n in plan.notes))

    def test_a_team_move_says_it_reaches_every_repository(self):
        plan = lifecycle.plan_move(rule(layer="team", rungs=(3,)), "carry", at="delivery")
        self.assertTrue(any("every repository" in n for n in plan.notes))


class LoadingFromDirectories(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        (self.root / "team" / "rules").mkdir(parents=True)
        (self.root / "team" / "skills").mkdir(parents=True)
        (self.root / "repo" / ".claude" / "rules").mkdir(parents=True)

    def tearDown(self):
        self.tmp.cleanup()

    def write(self, path: str, text: str):
        (self.root / path).write_text(text)

    def load(self):
        return loader.load(
            repo=str(self.root / "repo"), ladder_home=str(self.root),
            roots={"org": [], "team": ["{ladder}/team"], "project": ["{repo}/.claude"]})

    def test_the_directory_names_the_kind_and_the_layer(self):
        self.write("team/rules/a.md", "---\nid: a\nwhy: w\n---\n")
        self.write("team/skills/b.md", "---\nid: b\nwhy: w\n---\n")
        loaded = self.load()
        self.assertEqual(len(loaded.constraints), 1)
        self.assertEqual(len(loaded.capabilities), 1)
        self.assertEqual(loaded.by_id("a").layer, "team")

    def test_a_script_beside_the_file_is_found(self):
        self.write("team/rules/a.md", "---\nid: a\nwhy: w\n---\n")
        self.write("team/rules/a.py", "def check(p, c, x): return []\n")
        self.assertTrue(self.load().by_id("a").measured)

    def test_a_project_rule_adapts_a_team_rule_by_taking_its_id(self):
        self.write("team/rules/a.md", "---\nid: a\nwhy: team\n---\n")
        self.write("repo/.claude/rules/a.md", "---\nid: a\nwhy: ours\n---\n")
        loaded = self.load()
        self.assertEqual(loaded.by_id("a").why, "ours")
        self.assertIn("a", loaded.adapted)

    def test_a_locked_rule_refuses_adaptation_and_records_the_attempt(self):
        self.write("team/rules/a.md", "---\nid: a\nwhy: team\nlocked: true\n---\n")
        self.write("repo/.claude/rules/a.md", "---\nid: a\nwhy: ours\n---\n")
        loaded = self.load()
        self.assertEqual(loaded.by_id("a").why, "team", "the shipped one should stand")
        self.assertIn("a", loaded.refused_adaptations)
        self.assertTrue(any("does not forbid saying how" in p for p in loaded.problems))

    def test_a_specialisation_may_not_go_below_its_standard(self):
        self.write("team/rules/std.md", "---\nid: std\nwhy: w\nrung: turn\n---\n")
        self.write("repo/.claude/rules/ours.md",
                   "---\nid: ours\nwhy: w\nimplements: std\nrung: prose\n---\n")
        self.assertTrue(any("never lower" in p for p in self.load().problems))

    def test_a_specialisation_of_nothing_is_reported(self):
        self.write("repo/.claude/rules/ours.md",
                   "---\nid: ours\nwhy: w\nimplements: ghost\n---\n")
        self.assertTrue(any("nothing holds" in p for p in self.load().problems))

    def test_one_bad_file_does_not_take_the_rest_with_it(self):
        self.write("team/rules/bad.md", "---\nid: bad\nno closing fence\n")
        self.write("team/rules/good.md", "---\nid: good\nwhy: w\n---\n")
        loaded = self.load()
        self.assertIsNotNone(loaded.by_id("good"))
        self.assertTrue(loaded.problems)

    def test_the_measured_share_is_reported_rather_than_fixed(self):
        self.write("team/rules/told.md", "---\nid: told\nwhy: w\n---\n")
        self.write("team/rules/run.md", "---\nid: run\nwhy: w\n---\n")
        self.write("team/rules/run.py", "def check(p, c, x): return []\n")
        self.assertAlmostEqual(self.load().measured_share, 0.5)

    def test_rung_one_withholding_is_collected_across_rules(self):
        self.write("team/rules/w.md",
                   "---\nid: w\nwhy: w\nrung: grant\nwithholds: [Write, Edit]\n---\n")
        self.assertEqual(self.load().withheld(), {"Write", "Edit"})


class WhenTheRepositoryCannotBeSeen(unittest.TestCase):
    """The failure this loader used to report as good news.

    A microVM with only this worker's source mounted has no target repository in
    it, so every project primitive and every `permissions` entry silently stops
    existing and the ladder reports a repository that constrains nothing. That is
    indistinguishable from a repository whose rules are all satisfied, and it is
    the exact shape the whole model exists to refuse.
    """

    def test_an_absent_repository_is_a_problem_rather_than_an_empty_ladder(self):
        loaded = loader.load(repo="/no/such/checkout", ladder_home=".", roots={})
        self.assertTrue(any("cannot see the repository" in p for p in loaded.problems))

    def test_a_repository_that_is_there_says_nothing(self):
        with tempfile.TemporaryDirectory() as tmp:
            loaded = loader.load(repo=tmp, ladder_home=".", roots={})
            self.assertFalse(any("cannot see" in p for p in loaded.problems))

    def test_supplied_permissions_are_read_instead_of_the_filesystem(self):
        """So a caller that CAN see the repository can hand them over."""
        loaded = loader.load(
            repo="/no/such/checkout", ladder_home=".", roots={},
            permissions='{"permissions": {"deny": ["Bash(php *)"]}}')
        self.assertEqual(loaded.permissions.refused, ["Bash(php *)"])
        self.assertIsNotNone(loaded.by_id("repo-permissions-Bash(php *)"))

    def test_supplying_nothing_is_not_the_same_as_supplying_empty(self):
        """`{}` means "I looked, there are none". `None` means "I did not look"."""
        looked = loader.load(repo="/no/such/checkout", ladder_home=".", roots={},
                             permissions="{}")
        self.assertIn("supplied", looked.permissions.source)
        did_not = loader.load(repo="/no/such/checkout", ladder_home=".", roots={})
        self.assertEqual(did_not.permissions.source, "")


class WhenAPredicateIsBroken(unittest.TestCase):
    """Whether the gates work cannot be asked of the gates."""

    def test_a_raising_predicate_is_a_finding_not_a_pass(self):
        with tempfile.TemporaryDirectory() as tmp:
            broken = Path(tmp) / "p.py"
            broken.write_text("def check(path, content, context):\n    raise RuntimeError('boom')\n")
            findings = pred.run_file(broken, "a.py", "x")
        self.assertEqual(len(findings), 1)
        self.assertIn("RuntimeError", findings[0].why)
        self.assertIn("fails open", findings[0].why)

    def test_a_predicate_with_no_check_function_says_so(self):
        with tempfile.TemporaryDirectory() as tmp:
            empty = Path(tmp) / "p.py"
            empty.write_text("# nothing here\n")
            self.assertIn("enforces nothing", pred.run_file(empty, "a.py", "x")[0].why)

    def test_findings_come_back_in_whatever_shape_the_author_used(self):
        self.assertEqual(len(pred.normalise("just a string", "a.py")), 1)
        self.assertEqual(pred.normalise([{"line": 2, "reason": "x"}], "a.py")[0].why, "x")
        self.assertEqual(pred.normalise(None, "a.py"), [])


class RoundTrip(unittest.TestCase):
    def test_a_file_survives_being_rewritten(self):
        original = parse.parse(RULE, kind="rule", layer="team", script="x.py")
        again = parse.parse(parse.unparse(original), kind="rule", layer="team", script="x.py")
        self.assertEqual(again.rungs, original.rungs)
        self.assertEqual(again.body, original.body)
        self.assertEqual(again.escape, original.escape)

    def test_a_derived_rung_is_not_written_back(self):
        # Writing it would turn every promotion into a permanent departure from
        # the default, and the dagger in a listing would stop meaning anything.
        p = parse.parse("---\nid: a\nwhy: w\n---\n", kind="rule", layer="team")
        self.assertNotIn("rung:", parse.unparse(p))

    def test_a_fourth_layer_is_narrowed_to_project_and_told_so(self):
        p = parse.parse("---\nid: x\nlayer: personal\nwhy: w\n---\n", kind="rule")
        self.assertEqual(p.layer, "project")
        self.assertEqual(p.narrowed_from, "personal")
        self.assertFalse(p.travels)


if __name__ == "__main__":
    unittest.main()
