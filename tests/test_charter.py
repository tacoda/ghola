"""Rung 0, tested without a repository.

`build` takes a reader function rather than a path, which is what lets every
question about the charter be answered with a dict.
"""

import sys
import tempfile
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


class WhichFileIsTheCharter(unittest.TestCase):
    """`AGENTS.md`, and only that.

    The standard is one plain markdown file, stewarded by the Agentic AI
    Foundation. ghola reads it and enforces the result itself, so there is one
    file to author and no vendor copy to go stale.
    """

    def test_the_standard_is_what_gets_read(self):
        origin, problems = charter_lib.which({"AGENTS.md"})
        self.assertEqual(origin, "AGENTS.md")
        self.assertEqual(problems, ())

    def test_the_older_file_is_not_read_even_when_it_is_the_only_one(self):
        # The swap is a swap. A repository that has not migrated gets no
        # charter, which is why it gets a loud reason instead.
        origin, problems = charter_lib.which({"CLAUDE.md"})
        self.assertEqual(origin, "")
        self.assertEqual(len(problems), 1)
        self.assertIn("ln -s AGENTS.md CLAUDE.md", problems[0])

    def test_a_repository_holding_both_is_read_once(self):
        # `CLAUDE.md -> AGENTS.md` is the recommended migration, so the common
        # case of "both" is one file twice. Reading the pair would double it.
        origin, problems = charter_lib.which({"AGENTS.md", "CLAUDE.md"})
        self.assertEqual(origin, "AGENTS.md")
        self.assertEqual(problems, ())

    def test_neither_file_is_silent(self):
        # A repository that never wrote a charter is not a problem to report.
        self.assertEqual(charter_lib.which(set()), ("", ()))

    def test_the_source_names_the_file_the_text_came_from(self):
        # It was hardcoded to CLAUDE.md, which became a lie the moment AGENTS.md
        # was the file being read. A model told something surprising should be
        # able to find out which file said it.
        charter = charter_lib.build("body", files(), repo="/r",
                                    origin=charter_lib.STANDARD)
        self.assertEqual(charter.pieces[0].source, "/r/AGENTS.md")


class EverythingUnderTheAgentsDirectory(unittest.TestCase):
    """The charter is all of `.agents/`, and a directory names its concept."""

    def test_a_directory_names_the_concept_it_holds(self):
        self.assertEqual(charter_lib.concept_of("architecture/queues.md"),
                         "architecture / queues")

    def test_a_file_at_the_top_is_its_own_concept(self):
        self.assertEqual(charter_lib.concept_of("domain.md"), "domain")

    def test_the_ladders_own_directories_are_left_to_the_ladder(self):
        # Their prose arrives through `ladder::list` with the rung attached.
        # Reading them here as well would state every rule twice, and the
        # second copy would have lost the rung it is carried at.
        for dirname in charter_lib.LADDER_DIRS:
            with self.subTest(dirname=dirname):
                self.assertTrue(charter_lib.is_ladders(f"{dirname}/a.md"))

    def test_a_concept_the_ladder_has_no_kind_for_is_not_skipped(self):
        self.assertFalse(charter_lib.is_ladders("architecture/a.md"))
        self.assertFalse(charter_lib.is_ladders("domain.md"))

    def test_each_extra_arrives_as_its_own_titled_piece(self):
        charter = charter_lib.build(None, files(), repo="/r", extras=(
            ("domain.md", "a stay is not a reservation"),
            ("architecture/queues.md", "every transition is a queue message"),
        ))
        text = charter.take()
        self.assertIn("### domain", text)
        self.assertIn("### architecture / queues", text)
        self.assertIn("a stay is not a reservation", text)

    def test_an_extra_carries_where_it_came_from(self):
        charter = charter_lib.build(None, files(), repo="/r",
                                    extras=(("domain.md", "body"),))
        self.assertEqual(charter.pieces[0].source, "/r/.agents/domain.md")

    def test_an_empty_file_contributes_nothing(self):
        charter = charter_lib.build(None, files(), extras=(("empty.md", "  \n"),))
        self.assertEqual(charter.pieces, [])

    def test_an_extra_follows_its_own_imports(self):
        charter = charter_lib.build(None, files(shared="the shared bit"),
                                    extras=(("domain.md", "@shared"),))
        self.assertIn("the shared bit", charter.take())

    def test_the_skip_list_covers_every_directory_the_ladder_owns(self):
        # The one drift that matters: a kind added to the ladder and missed here
        # would have its rules read twice, once with the rung and once without.
        sys.path.insert(0, str(ROOT / "workers" / "ghola-ladder" / "src"))
        import load as loader

        self.assertEqual(set(charter_lib.LADDER_DIRS),
                         set(loader.KIND_DIRS) | set(loader.SCRIPT_DIRS))

    def test_the_hooks_directory_is_skipped_as_scripts_not_prose(self):
        # It holds what a `.agents/settings.json` entry points at. A shell
        # script is not charter, and neither is a README sitting beside one.
        self.assertIn("hooks", charter_lib.SCRIPT_DIRS)
        self.assertTrue(charter_lib.is_ladders("hooks/no-force-push.md"))


class ReadingTheAgentsDirectory(unittest.TestCase):
    """`under_charter_dir`, which is the one part of this that needs a disk."""

    def setUp(self):
        sys.path.insert(0, str(ROOT / "workers" / "ghola-policy" / "src"))
        sys.path.insert(0, str(ROOT / "workers" / "ghola-policy" / "src" / "callbacks"))
        import pre_generate

        self.read = pre_generate.under_charter_dir
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.agents = self.root / ".agents"

    def tearDown(self):
        self.tmp.cleanup()

    def write(self, relative: str, text: str = "body"):
        path = self.agents / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text)

    def test_no_directory_is_nothing_rather_than_an_error(self):
        self.assertEqual(self.read(self.root), ())

    def test_it_reaches_every_depth(self):
        self.write("domain.md")
        self.write("architecture/queues.md")
        self.write("architecture/deep/nested.md")
        self.assertEqual([r for r, _ in self.read(self.root)],
                         ["architecture/deep/nested.md", "architecture/queues.md",
                          "domain.md"])

    def test_the_ladders_directories_are_not_read_here(self):
        self.write("rules/no-secrets.md")
        self.write("skills/triage.md")
        self.write("domain.md")
        self.assertEqual([r for r, _ in self.read(self.root)], ["domain.md"])

    def test_only_markdown_is_charter(self):
        # A predicate script beside a rule is not prose, and neither is a JSON
        # settings file the ladder reads separately.
        self.write("domain.md")
        (self.agents / "settings.json").write_text("{}")
        (self.agents / "notes.txt").write_text("not markdown")
        self.assertEqual([r for r, _ in self.read(self.root)], ["domain.md"])

    def test_the_order_is_stable(self):
        for name in ("c.md", "a.md", "b.md"):
            self.write(name)
        self.assertEqual(self.read(self.root), self.read(self.root))


class Assembly(unittest.TestCase):
    def test_the_charter_file_becomes_a_piece(self):
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
