"""Rung 0, tested without a repository.

`build` takes a reader function rather than a path, which is what lets every
question about the charter be answered with a dict.
"""

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "workers" / "ghola-core" / "src"))

import charter as charter_lib  # noqa: E402


def files(**contents):
    """A reader over a dict, for tests that never touch a filesystem."""
    return lambda path: contents.get(path)


class Imports(unittest.TestCase):
    def test_an_at_line_is_inlined(self):
        text, problems = charter_lib.resolve_imports(
            "before\n@rules/style.md\nafter", files(**{"rules/style.md": "STYLE"}))
        self.assertIn("STYLE", text)
        self.assertIn("before", text)
        self.assertEqual(problems, [])

    def test_imports_nest(self):
        text, _ = charter_lib.resolve_imports(
            "@a", files(a="top\n@b", b="bottom"))
        self.assertIn("top", text)
        self.assertIn("bottom", text)

    def test_a_missing_import_is_reported_and_left_as_written(self):
        # Silently dropping it makes a charter with a missing section, which is
        # the harder bug to find.
        text, problems = charter_lib.resolve_imports("@gone.md", files())
        self.assertIn("@gone.md", text)
        self.assertEqual(len(problems), 1)
        self.assertIn("not found", problems[0])

    def test_a_cycle_is_reported_rather_than_hanging(self):
        text, problems = charter_lib.resolve_imports("@a", files(a="@a"))
        self.assertTrue(any("cycle" in p for p in problems))
        self.assertIn("@a", text)

    def test_a_mutual_cycle_terminates(self):
        _text, problems = charter_lib.resolve_imports("@a", files(a="@b", b="@a"))
        self.assertTrue(any("cycle" in p for p in problems))

    def test_depth_is_bounded_and_says_so(self):
        chain = {f"f{i}": f"@f{i + 1}" for i in range(6)}
        _text, problems = charter_lib.resolve_imports("@f0", files(**chain))
        self.assertTrue(any("nested deeper" in p for p in problems))

    def test_an_at_sign_mid_line_is_not_an_import(self):
        # `email@example.com` and `@mentions` in prose are not imports, and a
        # charter that inlined them would be unusable.
        text, problems = charter_lib.resolve_imports(
            "write to me@example.com about @things", files())
        self.assertEqual(problems, [])
        self.assertIn("me@example.com", text)


class Assembly(unittest.TestCase):
    def test_claude_md_becomes_a_piece(self):
        charter = charter_lib.build("house style: no em dashes", files(), repo="/r")
        self.assertEqual(len(charter.pieces), 1)
        self.assertIn("no em dashes", charter.take())

    def test_no_charter_at_all_is_empty_rather_than_an_error(self):
        self.assertEqual(charter_lib.build(None, files()).take(), "")

    def test_rule_prose_arrives_with_its_why(self):
        charter = charter_lib.build(None, files(), rules=[{
            "id": "name-the-swallow", "layer": "team",
            "description": "A broad except says what it is swallowing",
            "why": "A gate that fails silently stops the factory invisibly.",
            "rungs": [{"name": "turn"}]}])
        text = charter.take()
        self.assertIn("A broad except", text)
        self.assertIn("Why:", text)
        self.assertIn("team", text, "the layer should be visible to the model")

    def test_a_rule_with_no_prose_contributes_nothing(self):
        charter = charter_lib.build(None, files(), rules=[
            {"id": "x", "description": "", "why": "", "rungs": []}])
        self.assertEqual(charter.pieces, [])

    def test_pieces_are_headed_so_they_survive_a_system_prompt(self):
        charter = charter_lib.build("body", files())
        self.assertTrue(charter.take().startswith("### "))


class Scoping(unittest.TestCase):
    """A scoped piece waits until the turn goes near what it is about."""

    def setUp(self):
        self.charter = charter_lib.build(None, files(), rules=[
            {"id": "always", "description": "everywhere", "why": "w",
             "rungs": [], "paths": []},
            {"id": "scoped", "description": "only workers", "why": "w",
             "rungs": [], "paths": ["workers/**"]},
        ])

    def test_an_unscoped_piece_is_always_on(self):
        self.assertIn("everywhere", self.charter.take(touched=()))

    def test_a_scoped_piece_waits_for_a_touch(self):
        # Loading every scoped rule into every turn is how a charter becomes the
        # thing diluting the attention it wanted.
        self.assertNotIn("only workers", self.charter.take(touched=()))
        self.assertNotIn("only workers", self.charter.take(touched=("docs/a.md",)))

    def test_a_scoped_piece_arrives_once_touched(self):
        self.assertIn("only workers", self.charter.take(touched=("workers/a.py",)))

    def test_the_count_matches_what_arrived(self):
        self.assertEqual(self.charter.count(touched=()), 1)
        self.assertEqual(self.charter.count(touched=("workers/a.py",)), 2)


if __name__ == "__main__":
    unittest.main()
