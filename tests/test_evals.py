"""Where eval cases come from.

A team's cases and graders need no fork: a suite lives in the team's own
repository and ghola reads it from wherever it is. The property worth
protecting is the failure mode, not the feature — **a suite that is not where
it said it would be must be reported**, because a run of no cases prints
exactly like a run that passed.
"""

import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "workers" / "ghola-core" / "src"))

import evals  # noqa: E402


class Scratch(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        (self.root / "evals").mkdir()
        self.case("ours")
        self.addCleanup(self.tmp.cleanup)

    def case(self, name: str, where: str = "evals") -> Path:
        folder = self.root / where
        folder.mkdir(parents=True, exist_ok=True)
        path = folder / f"{name}.json"
        path.write_text("{}")
        return path


class Gathering(Scratch):
    def test_the_repositorys_own_cases_need_no_configuration(self):
        self.assertEqual(evals.gather({}, self.root).names(), ["ours"])

    def test_a_configured_suite_is_read_as_well_not_instead(self):
        self.case("theirs", "elsewhere/cases")
        found = evals.gather({"suites": ["elsewhere/cases"]}, self.root)
        self.assertEqual(sorted(found.names()), ["ours", "theirs"])

    def test_an_absolute_path_outside_the_repository_works(self):
        with tempfile.TemporaryDirectory() as outside:
            (Path(outside) / "theirs.json").write_text("{}")
            found = evals.gather({"suites": [outside]}, self.root)
            self.assertIn("theirs", found.names())

    def test_a_home_relative_path_is_expanded(self):
        self.assertTrue(evals.expand("~/x", self.root).is_absolute())
        self.assertNotIn("~", str(evals.expand("~/x", self.root)))

    def test_an_environment_variable_is_expanded(self):
        import os
        os.environ["GHOLA_TEST_SUITE"] = "/tmp/theirs"
        self.addCleanup(os.environ.pop, "GHOLA_TEST_SUITE", None)
        self.assertEqual(evals.expand("$GHOLA_TEST_SUITE", self.root),
                         Path("/tmp/theirs"))

    def test_a_relative_path_resolves_against_the_repository(self):
        # `make eval` runs from wherever the operator is standing, and a suite
        # that resolved against the working directory would be found or not
        # depending on which directory somebody typed the command in.
        self.assertEqual(evals.expand("cases", self.root), self.root / "cases")

    def test_one_case_by_name(self):
        self.case("other")
        self.assertEqual(evals.gather({}, self.root, only="other").names(), ["other"])

    def test_a_suite_listed_twice_contributes_its_cases_once(self):
        found = evals.gather({"suites": ["evals", "evals"]}, self.root)
        self.assertEqual(found.names(), ["ours"])


class SilenceIsTheFailureMode(Scratch):
    def test_a_suite_that_is_not_there_is_reported(self):
        found = evals.gather({"suites": ["/nowhere/cases"]}, self.root)
        self.assertTrue(found.problems)
        self.assertIn("/nowhere/cases", found.problems[0])

    def test_the_report_says_where_to_fix_it(self):
        found = evals.gather({"suites": ["/nowhere"]}, self.root)
        self.assertIn("settings/evals.yaml", found.problems[0])

    def test_the_other_suites_still_contribute(self):
        # One bad path must not take a working suite down with it.
        found = evals.gather({"suites": ["/nowhere"]}, self.root)
        self.assertEqual(found.names(), ["ours"])

    def test_a_case_name_nobody_has_says_where_it_looked(self):
        found = evals.gather({"suites": ["/nowhere"]}, self.root, only="typo")
        self.assertTrue(any("typo" in p for p in found.problems))
        self.assertTrue(any("evals" in p for p in found.problems))

    def test_a_missing_evals_directory_is_not_a_problem_to_report(self):
        # A team that wants only its own cases deletes `evals/`, and being told
        # about it on every run would be noise.
        with tempfile.TemporaryDirectory() as bare:
            found = evals.gather({}, Path(bare))
            self.assertEqual(found.problems, [])


class Graders(unittest.TestCase):
    def test_they_are_listed_rather_than_called(self):
        # ghola does not call these. The `eval` worker does, by the id in the
        # case file; this list exists so `make config` can show them.
        self.assertEqual(evals.graders({"graders": ["acme::eval::x"]}),
                         ["acme::eval::x"])

    def test_no_configuration_is_no_graders(self):
        self.assertEqual(evals.graders(None), [])


class TheShippedTemplate(unittest.TestCase):
    def test_it_configures_nothing_by_default(self):
        # Every line is commented, so a fresh clone runs its own cases and
        # reports no missing suites.
        import yaml
        config = yaml.safe_load((ROOT / "settings" / "evals.yaml").read_text())
        self.assertIn(config, ({}, None))

    def test_the_repositorys_own_cases_are_still_found_with_it_present(self):
        found = evals.gather({}, ROOT)
        self.assertTrue(found.names())
        self.assertEqual(found.problems, [])


if __name__ == "__main__":
    unittest.main()
