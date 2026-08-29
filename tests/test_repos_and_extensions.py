"""Per-repo settings, and the Python a team drops in.

Both are the customization claim made checkable: a team changes what ghola does
to their repository without editing ghola, and adds behavior without registering
anything.
"""

import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "workers" / "ghola-core" / "src"))

import extensions  # noqa: E402
import repos  # noqa: E402

CONFIG = {
    "defaults": {"branch_prefix": "team/", "max_revisions": 3},
    "repos": {
        "/code/app": {"branch_prefix": "feature/", "prepare": "make up",
                      "env": {"DATABASE_URL": "postgres://localhost/test"}},
    },
}


class Precedence(unittest.TestCase):
    def test_the_repos_own_entry_wins(self):
        found = repos.resolve("/code/app", CONFIG, environ={})
        self.assertEqual(found.branch_prefix, "feature/")

    def test_defaults_apply_to_a_repo_with_no_entry(self):
        found = repos.resolve("/code/other", CONFIG, environ={})
        self.assertEqual(found.branch_prefix, "team/")
        self.assertEqual(found.max_revisions, 3)

    def test_built_ins_apply_with_no_file_at_all(self):
        found = repos.resolve("/code/other", {}, environ={})
        self.assertEqual(found.branch_prefix, "ghola/")
        self.assertEqual(found.max_revisions, 2)

    def test_the_environment_sits_below_the_file(self):
        found = repos.resolve("/code/app", CONFIG,
                              environ={"GHOLA_BRANCH_PREFIX": "env/"})
        self.assertEqual(found.branch_prefix, "feature/", "the file should win")

    def test_the_environment_beats_the_built_in(self):
        found = repos.resolve("/code/other", {},
                              environ={"GHOLA_BRANCH_PREFIX": "env/"})
        self.assertEqual(found.branch_prefix, "env/")

    def test_where_each_value_came_from_is_recorded(self):
        # An operator should never be guessing which layer won.
        found = repos.resolve("/code/app", CONFIG, environ={})
        self.assertIn("repos.toml", found.source["branch_prefix"])
        self.assertEqual(found.source["cleanup"], "built-in")

    def test_a_repo_may_be_keyed_by_directory_name(self):
        config = {"repos": {"app": {"prepare": "make up"}}}
        self.assertEqual(repos.resolve("/anywhere/app", config, environ={}).prepare,
                         "make up")


class BadInput(unittest.TestCase):
    def test_a_non_numeric_count_falls_back_and_says_so(self):
        config = {"defaults": {"max_revisions": "lots"}}
        found = repos.resolve("/code/app", config, environ={})
        self.assertEqual(found.max_revisions, 2)
        self.assertIn("not a number", found.source["max_revisions"])

    def test_a_missing_file_reads_as_empty(self):
        self.assertEqual(repos.load("/nowhere/repos.toml"), {})

    def test_malformed_toml_reads_as_empty_rather_than_failing(self):
        # Refusing to start because one entry has a typo would take every other
        # repository down with it.
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "repos.toml"
            path.write_text("[defaults\nbroken")
            self.assertEqual(repos.load(path), {})


class WhatTravelsOntoAJob(unittest.TestCase):
    def test_the_settings_are_copied_not_referenced(self):
        # A rework months later rebuilds the environment the job was born in,
        # rather than whatever repos.toml says by then.
        found = repos.resolve("/code/app", CONFIG, environ={})
        fields = found.as_job_fields()["repo_settings"]
        self.assertEqual(fields["prepare"], "make up")
        self.assertEqual(fields["env"]["DATABASE_URL"], "postgres://localhost/test")

    def test_provenance_does_not_travel(self):
        fields = repos.resolve("/code/app", CONFIG, environ={}).as_job_fields()
        self.assertNotIn("source", fields["repo_settings"])

    def test_the_base_branch_is_empty_until_the_forge_is_asked(self):
        # wipp hardcoded `main`, and a repository on `develop` branched from
        # nothing.
        self.assertEqual(repos.resolve("/code/app", CONFIG, environ={}).base, "")


class Branches(unittest.TestCase):
    def test_the_prefix_is_the_repositorys_convention(self):
        found = repos.resolve("/code/app", CONFIG, environ={})
        self.assertTrue(repos.branch_for(found, "abc123").startswith("feature/"))

    def test_a_slug_is_used_when_there_is_one(self):
        found = repos.resolve("/code/app", CONFIG, environ={})
        self.assertEqual(repos.branch_for(found, "abc", "add-a-flag"),
                         "feature/add-a-flag")

    def test_a_long_slug_is_bounded(self):
        found = repos.resolve("/code/app", CONFIG, environ={})
        self.assertLessEqual(len(repos.branch_for(found, "abc", "x" * 200)), 60)


class Extensions(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        (self.root / "actions").mkdir()
        (self.root / "actions" / "deploy_to_staging.py").write_text(
            "def run(job, config):\n    return {'ok': True, 'did': 'deploy'}\n")

    def tearDown(self):
        self.tmp.cleanup()

    def test_a_file_is_found_by_its_name(self):
        run, function_id = extensions.resolve("deploy_to_staging", self.root, "actions")
        self.assertEqual(function_id, "")
        self.assertEqual(run({}, {})["did"], "deploy")

    def test_hyphens_and_underscores_are_one_name(self):
        run, _ = extensions.resolve("deploy-to-staging", self.root, "actions")
        self.assertIsNotNone(run)

    def test_a_function_id_is_passed_through_untouched(self):
        run, function_id = extensions.resolve("myworker::deploy", self.root, "actions")
        self.assertIsNone(run)
        self.assertEqual(function_id, "myworker::deploy")

    def test_a_missing_extension_is_an_error_naming_what_exists(self):
        # A stage whose action silently does nothing is a job that walks past
        # the step it existed for, and nothing says so.
        with self.assertRaises(extensions.ExtensionError) as caught:
            extensions.resolve("nosuchthing", self.root, "actions")
        self.assertIn("deploy_to_staging", str(caught.exception))

    def test_a_module_with_no_entry_point_says_which_name_it_wanted(self):
        (self.root / "actions" / "empty.py").write_text("# nothing\n")
        with self.assertRaises(extensions.ExtensionError) as caught:
            extensions.resolve("empty", self.root, "actions")
        self.assertIn("`run`", str(caught.exception))

    def test_a_module_that_raises_while_loading_is_reported(self):
        (self.root / "actions" / "broken.py").write_text("raise ValueError('boom')\n")
        with self.assertRaises(extensions.ExtensionError) as caught:
            extensions.resolve("broken", self.root, "actions")
        self.assertIn("boom", str(caught.exception))

    def test_a_missing_directory_is_empty_rather_than_an_error(self):
        self.assertEqual(extensions.discover(self.root, "guards").names(), [])

    def test_underscore_prefixed_files_are_not_extensions(self):
        (self.root / "actions" / "_helper.py").write_text("def run(j, c): pass\n")
        self.assertNotIn("_helper", extensions.discover(self.root, "actions").names())

    def test_check_reports_everything_missing_at_once(self):
        problems = extensions.check(
            {"actions": "nosuchaction", "guards": "nosuchguard"}, self.root)
        self.assertEqual(len(problems), 2)

    def test_check_is_silent_when_everything_resolves(self):
        self.assertEqual(
            extensions.check({"actions": "deploy_to_staging"}, self.root), [])


if __name__ == "__main__":
    unittest.main()
