"""A repository's own `permissions`, landing at two rungs.

The entries are two different kinds of thing and that is the whole design:
`Bash` names a tool and is withheld at rung 1; `Bash(php *)` names an argument
and is refused at rung 2. Dropping the shell because one command pattern is
denied would be a different and much larger rule.
"""

import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "workers" / "ghola-ladder" / "src"))

import permissions as perms  # noqa: E402
import toolnames  # noqa: E402


def settings(**block) -> str:
    return json.dumps({"permissions": block})


class TwoRungs(unittest.TestCase):
    def test_a_whole_tool_is_withheld_at_rung_one(self):
        p = perms.parse(settings(deny=["Bash"]))
        self.assertEqual(p.withheld, ["Bash"])
        self.assertEqual(p.refused, [])

    def test_an_argument_pattern_is_refused_at_rung_two(self):
        p = perms.parse(settings(deny=["Bash(php *)"]))
        self.assertEqual(p.refused, ["Bash(php *)"])
        self.assertEqual(p.withheld, [])

    def test_withholding_reaches_every_function_the_tool_names(self):
        # A rule withholding `Write` from a phase granted `coder::create-file`
        # takes nothing away unless something knows they are the same thing.
        functions = perms.withheld_functions(perms.parse(settings(deny=["Write"])))
        self.assertIn("coder::create-file", functions)
        self.assertIn("shell::fs::write", functions)

    def test_ask_subtracts_like_deny(self):
        # There is no human inside an unattended turn, and a factory reading
        # "ask" as "yes" has answered a question nobody put.
        p = perms.parse(settings(ask=["Bash"]))
        self.assertEqual(p.withheld, ["Bash"])

    def test_allow_is_not_read(self):
        # Reading it as a grant would let a repository widen its own permissions
        # by writing a file.
        p = perms.parse(settings(allow=["Bash"]))
        self.assertTrue(p.empty)


class TheRungTwoMatcher(unittest.TestCase):
    def setUp(self):
        self.perms = perms.parse(settings(deny=["Bash(php *)"]))

    def test_a_matching_command_is_refused(self):
        self.assertEqual(
            perms.refuses(self.perms, "shell::exec", {"command": "php --version"}),
            "Bash(php *)")

    def test_a_different_command_is_not(self):
        self.assertEqual(
            perms.refuses(self.perms, "shell::exec", {"command": "make test"}), "")

    def test_it_does_not_parse_the_shell(self):
        # `make test && php artisan migrate` does NOT match `php *` and is not
        # refused, for the same reason a rung-3 callback does not guess what
        # `sed -i` will write: a matcher that tried would be a different rule
        # wearing this one's authority. That is exactly why a constraint that
        # matters names rung 4 as well.
        self.assertEqual(
            perms.refuses(self.perms, "shell::exec",
                          {"command": "make test && php artisan migrate"}), "")

    def test_a_different_tool_is_untouched(self):
        self.assertEqual(
            perms.refuses(self.perms, "coder::read-file", {"path": "a.php"}), "")

    def test_a_bare_prefix_is_treated_as_a_pattern(self):
        p = perms.parse(settings(deny=["Bash(rm)"]))
        self.assertTrue(perms.refuses(p, "shell::exec", {"command": "rm -rf /"}))


class NamesThatReachNothing(unittest.TestCase):
    """A withheld name reaching no function is a rule enforcing nothing."""

    def test_an_unknown_tool_is_reported_rather_than_ignored(self):
        p = perms.parse(settings(deny=["Telepathy"]))
        self.assertEqual(p.unresolved, ["Telepathy"])
        self.assertTrue(p.empty)

    def test_an_iii_function_id_may_be_named_directly(self):
        # A repository should not have to learn the equivalence table to
        # withhold something.
        p = perms.parse(settings(deny=["worktree::land"]))
        self.assertEqual(p.withheld, ["worktree::land"])
        self.assertEqual(perms.withheld_functions(p), ["worktree::land"])


class MalformedInput(unittest.TestCase):
    def test_broken_json_is_empty_rather_than_fatal(self):
        # This file belongs to the target repository and the ladder is a guest in
        # it. Refusing to run because somebody's settings have a trailing comma
        # would be the wrong failure.
        self.assertTrue(perms.parse("{not json,,}").empty)

    def test_no_permissions_block_is_empty(self):
        self.assertTrue(perms.parse('{"other": 1}').empty)

    def test_a_duplicate_entry_is_counted_once(self):
        p = perms.parse(settings(deny=["Bash"], ask=["Bash"]))
        self.assertEqual(p.withheld, ["Bash"])


class AsPrimitives(unittest.TestCase):
    def test_the_synthesised_rules_carry_a_why(self):
        # Without one they would be the only primitives on the ladder that
        # cannot be demoted or removed on evidence.
        made = perms.as_primitives(perms.parse(settings(deny=["Bash", "Bash(php *)"])))
        self.assertEqual(len(made), 2)
        for p in made:
            self.assertTrue(p.why, f"{p.id} has no why")
            self.assertEqual(p.layer, "project")

    def test_they_land_on_the_rungs_their_shape_implies(self):
        made = perms.as_primitives(perms.parse(settings(deny=["Bash", "Bash(php *)"])))
        by_id = {p.id: p for p in made}
        self.assertEqual(by_id["repo-permissions-withheld"].rungs, (1,))
        self.assertEqual(by_id["repo-permissions-Bash(php *)"].rungs, (2,))


class Equivalences(unittest.TestCase):
    def test_a_function_maps_back_to_its_tool_name(self):
        self.assertEqual(toolnames.name_for("shell::exec"), "Bash")

    def test_an_unmapped_function_is_its_own_name(self):
        self.assertEqual(toolnames.name_for("worktree::land"), "worktree::land")

    def test_unresolved_reports_names_that_reach_nothing(self):
        self.assertEqual(toolnames.unresolved(["Bash", "Telepathy"]), ["Telepathy"])


if __name__ == "__main__":
    unittest.main()
