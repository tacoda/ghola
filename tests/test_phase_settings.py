"""Configuration is optional, and rung 1 is the merge.

Two claims are tested here because both are load-bearing and neither is obvious
from reading the code: ghola works with no settings file at all, and a phase that
names its own functions gets those and not those-plus-the-defaults.
"""

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "workers" / "ghola-core" / "src"))

import defaults  # noqa: E402
import phase_settings  # noqa: E402


class WithNoSettingsFile(unittest.TestCase):
    """The convention-over-configuration claim, made checkable."""

    def test_every_built_in_phase_still_resolves(self):
        config = defaults.config()
        for phase in ("plan", "run", "prove", "review", "draft"):
            settings = phase_settings.for_phase(phase, config)
            self.assertTrue(settings.get("model"), f"{phase} has no model")
            self.assertTrue(settings.get("max_turns"), f"{phase} has no turn cap")

    def test_a_phase_that_does_not_exist_falls_back_to_the_defaults(self):
        settings = phase_settings.for_phase("no-such-phase", defaults.config())
        self.assertEqual(settings["model"], defaults.DEFAULTS["model"])

    def test_the_built_in_defaults_are_a_fresh_copy_each_time(self):
        first = defaults.config()
        first["phases"]["plan"]["model"] = "mutated"
        self.assertNotEqual(defaults.config()["phases"]["plan"]["model"], "mutated")


class MergingAFile(unittest.TestCase):
    def setUp(self):
        self.config = defaults.config()

    def test_one_key_does_not_replace_the_whole_phase(self):
        given = {"phases": {"plan": {"max_turns": 9}}}
        self.config["phases"]["plan"].update(given["phases"]["plan"])
        settings = phase_settings.for_phase("plan", self.config)
        self.assertEqual(settings["max_turns"], 9)
        self.assertEqual(settings["model"], "claude-opus-5", "the built-in model was lost")

    def test_functions_is_replaced_wholesale_not_merged(self):
        # Rung 1 read as an accident of merge order is how a check ends up
        # holding an editor, so this is the test that stops that.
        self.config["phases"]["review"]["functions"] = {"allow": ["coder::read-file"]}
        allowed = phase_settings.for_phase("review", self.config)["functions"]["allow"]
        self.assertEqual(allowed, ["coder::read-file"])

    def test_a_phase_the_file_invents_is_added(self):
        self.config["phases"]["threat-model"] = {"model": "claude-opus-5"}
        self.assertIn("threat-model", phase_settings.phases(self.config))


class Rung1(unittest.TestCase):
    """The grants are the whole of rung 1, so their shape is a test."""

    def test_no_check_is_ever_handed_an_editor(self):
        # "Checks do not repair" needs no predicate: it is expressed entirely by
        # what these phases are not granted.
        for phase in ("review", "prove", "plan", "draft"):
            allowed = phase_settings.for_phase(phase, defaults.config())["functions"]["allow"]
            for editor in defaults.EDITING:
                self.assertNotIn(editor, allowed, f"{phase} was handed {editor}")

    def test_review_cannot_run_commands(self):
        allowed = phase_settings.for_phase("review", defaults.config())["functions"]["allow"]
        self.assertNotIn("shell::exec", allowed)

    def test_prove_can_run_commands_because_that_is_its_whole_job(self):
        allowed = phase_settings.for_phase("prove", defaults.config())["functions"]["allow"]
        self.assertIn("shell::exec", allowed)

    def test_every_phase_can_read_a_function_contract(self):
        # The agent's surface is a discovery loop, and rung 1 gates discovery as
        # well as use. A phase given tools and not the ability to read their
        # contracts has been given nothing.
        for phase in phase_settings.phases(defaults.config()):
            allowed = phase_settings.for_phase(phase, defaults.config())["functions"]["allow"]
            self.assertIn("engine::functions::info", allowed, f"{phase} cannot read a contract")

    def test_ghola_grants_no_tools_of_its_own(self):
        # If this fails, something was reimplemented that the shell worker ships.
        for phase in phase_settings.phases(defaults.config()):
            allowed = phase_settings.for_phase(phase, defaults.config())["functions"]["allow"]
            for name in allowed:
                self.assertFalse(name.startswith("ghola::tool::"),
                                 f"{phase} grants {name}; the tools are coder::* and shell::*")


class SendOptions(unittest.TestCase):
    def test_only_keys_the_harness_names_are_passed_through(self):
        config = defaults.config()
        config["phases"]["plan"]["nonsense_key"] = 1
        self.assertNotIn("nonsense_key", phase_settings.send_options("plan", config))

    def test_the_model_is_not_a_send_option(self):
        # `model` is a top-level field of harness::send, not an option. Passing
        # it in both places is how a phase silently runs on the wrong one.
        self.assertNotIn("model", phase_settings.send_options("plan", defaults.config()))

    def test_the_callers_model_wins_over_the_setting(self):
        self.assertEqual(
            phase_settings.model_for("plan", "claude-sonnet-5", defaults.config()),
            "claude-sonnet-5")


if __name__ == "__main__":
    unittest.main()
