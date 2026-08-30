"""The example configurations, checked the way a real one is.

**A broken example is worse than no example.** Somebody copies it into
`settings/`, the pipeline stops parsing, and the first thing they learn about
ghola is that its own documentation does not run. So every example here goes
through the same `graph.parse` a live pipeline does, and has to come back with
no problems.
"""

import sys
import unittest
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "workers" / "ghola-core" / "src"))

import defaults  # noqa: E402
import graph as g  # noqa: E402
import oversight  # noqa: E402
import phase_settings  # noqa: E402

EXAMPLES = sorted(p for p in (ROOT / "examples").iterdir() if p.is_dir())


def read(path: Path) -> dict:
    return yaml.safe_load(path.read_text()) or {}


class EveryExampleRuns(unittest.TestCase):
    def test_there_are_examples_at_both_ends(self):
        self.assertEqual([p.name for p in EXAMPLES], ["minimal", "strict"])

    def test_every_pipeline_parses_with_no_problems(self):
        for example in EXAMPLES:
            found = g.parse(read(example / "settings" / "pipeline.yaml"))
            self.assertEqual(found.problems, [], example.name)

    def test_every_pipeline_can_reach_a_terminal_state(self):
        # A graph whose last stage points at nothing is a job that stalls rather
        # than one that fails, and stalling is the harder failure to notice.
        for example in EXAMPLES:
            found = g.parse(read(example / "settings" / "pipeline.yaml"))
            reachable = set()
            for stage in found.stages.values():
                reachable.update([stage.next, *(t for _, t in stage.outcomes)])
            self.assertTrue(reachable & set(g.TERMINAL), example.name)

    def test_every_requirement_is_produced_by_an_earlier_stage(self):
        for example in EXAMPLES:
            found = g.parse(read(example / "settings" / "pipeline.yaml"))
            produced = {"spec"}
            for name in found.stages:
                stage = found.get(name)
                for needed in stage.requires:
                    self.assertIn(needed, produced,
                                  f"{example.name}: `{name}` requires `{needed}` "
                                  "and nothing before it produces one")
                produced.update(stage.produces)

    def test_every_action_named_is_one_that_exists(self):
        # An example naming an action nobody implements would fail at the stage
        # rather than when the pipeline is read.
        for example in EXAMPLES:
            found = g.parse(read(example / "settings" / "pipeline.yaml"))
            for stage in found.stages.values():
                if stage.action:
                    self.assertIn(stage.action, g.BUILTIN_ACTIONS,
                                  f"{example.name}: `{stage.action}`")

    def test_every_oversight_level_is_a_real_one(self):
        for example in EXAMPLES:
            path = example / "settings" / "oversight.yaml"
            if not path.exists():
                continue
            config = read(path)
            levels = [config.get("default")] + list((config.get("stages") or {}).values())
            for level in [x for x in levels if x]:
                self.assertIn(level, oversight.SETTINGS, f"{example.name}: {level}")

    def test_a_stage_named_in_oversight_exists_in_the_pipeline(self):
        # Naming a stage that is not there is a setting nobody notices doing
        # nothing, which is the failure this repository keeps finding.
        for example in EXAMPLES:
            path = example / "settings" / "oversight.yaml"
            if not path.exists():
                continue
            found = g.parse(read(example / "settings" / "pipeline.yaml"))
            for name in (read(path).get("stages") or {}):
                self.assertIn(name, found.stages, f"{example.name}: `{name}`")

    def test_a_phase_named_in_phases_is_one_the_pipeline_runs(self):
        for example in EXAMPLES:
            path = example / "settings" / "phases.yaml"
            if not path.exists():
                continue
            found = g.parse(read(example / "settings" / "pipeline.yaml"))
            for name in (read(path).get("phases") or {}):
                self.assertIn(name, set(found.phases()), f"{example.name}: `{name}`")

    def test_setting_one_key_keeps_the_rest_of_that_phase(self):
        # `strict` sets `review.thinking_level` and nothing else. If the merge
        # replaced the block, the review phase would lose its tool grant, and a
        # phase with no grant is a phase that can do nothing.
        config = read(ROOT / "examples" / "strict" / "settings" / "phases.yaml")
        review = phase_settings.for_phase(
            "review", phase_settings.load(config))
        self.assertEqual(review["thinking_level"], "xhigh")
        self.assertEqual(review["functions"],
                         defaults.PHASES["review"]["functions"])

    def test_a_phase_that_does_not_exist_built_in_is_simply_added(self):
        config = read(ROOT / "examples" / "strict" / "settings" / "phases.yaml")
        security = phase_settings.for_phase(
            "security", phase_settings.load(config))
        self.assertEqual(security["model"], "claude-opus-5")
        # Replaced wholesale rather than merged: a check granted an editor by
        # merge order is the whole reason that rule exists.
        self.assertNotIn("coder::update-file", security["functions"]["allow"])


class TheyDisagreeAboutSomething(unittest.TestCase):
    """Two examples that configured the same thing would be one example."""

    def pipeline(self, name: str):
        return g.parse(read(ROOT / "examples" / name / "settings" / "pipeline.yaml"))

    def test_minimal_runs_one_turn_and_strict_runs_several(self):
        self.assertEqual(len(self.pipeline("minimal").phases()), 1)
        self.assertGreater(len(self.pipeline("strict").phases()), 3)

    def test_they_sit_on_opposite_sides_of_the_dial(self):
        levels = {}
        for name in ("minimal", "strict"):
            config = read(ROOT / "examples" / name / "settings" / "oversight.yaml")
            levels[name] = config["default"]
        self.assertEqual(levels, {"minimal": "dark", "strict": "attended"})

    def test_neither_of_them_merges_anything(self):
        # The gate is not how much was checked before it. It is that a person
        # decides, and no configuration is allowed to remove that.
        for name in ("minimal", "strict"):
            found = self.pipeline(name)
            self.assertIn("waiting", found.stages, name)
            self.assertEqual(found.get("waiting").action, "watch_pull_request", name)

    def test_neither_of_them_skips_the_delivery_gate(self):
        # Rung 4 is the repository's own commit hook. A configuration that
        # skipped it would ship what the repository itself refuses.
        for name in ("minimal", "strict"):
            actions = [s.action for s in self.pipeline(name).stages.values()]
            self.assertIn("commit_and_push", actions, name)


if __name__ == "__main__":
    unittest.main()
