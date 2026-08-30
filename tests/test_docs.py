"""The documentation, checked against the thing it documents.

M8's bar is that somebody who has never seen this repository gets a pull request
out of it by following the README. Nobody can test comprehension. What is
testable is the class of defect that breaks a reader hardest and hides best: a
page telling you to run a target that does not exist, or linking to a file that
is not there.

Every `make` command and every relative link in the docs is checked here, so a
renamed target fails in seconds rather than in somebody's first hour.
"""

import re
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "workers" / "ghola-core" / "src"))

PAGES = sorted([ROOT / "README.md", *(ROOT / "docs").glob("*.md"),
                *(ROOT / "examples").rglob("*.md")])

LINK = re.compile(r"\[[^\]]*\]\(([^)#\s]+)(?:#[^)]*)?\)")
FENCE = re.compile(r"```.*?```", re.DOTALL)
INLINE = re.compile(r"`([^`\n]+)`")
MAKE = re.compile(r"(?:^|\s)make\s+([a-z][a-z-]*)")


def commands(text: str) -> set[str]:
    """Every `make <target>` a page tells you to run.

    Read only from code fences and inline code, because prose says things like
    "make an unattended process auditable" and a checker that could not tell
    those apart would be a checker nobody leaves switched on.
    """
    found = set()
    for block in FENCE.findall(text) + INLINE.findall(text):
        found.update(MAKE.findall(block))
    return found


def targets() -> set[str]:
    """Every target the Makefile declares, from `.PHONY` and from the rules."""
    text = (ROOT / "Makefile").read_text()
    found = set(re.findall(r"^([a-z][a-z-]*):", text, re.MULTILINE))
    for line in re.findall(r"^\.PHONY:(.*(?:\\\n.*)*)", text, re.MULTILINE):
        found.update(re.findall(r"[a-z][a-z-]*", line.replace("\\\n", " ")))
    return found


class EveryCommandExists(unittest.TestCase):
    def test_the_makefile_declares_the_targets_the_docs_promise(self):
        known = targets()
        for page in PAGES:
            for name in commands(page.read_text()):
                self.assertIn(name, known,
                              f"{page.relative_to(ROOT)} says `make {name}`, "
                              "and the Makefile has no such target")

    def test_every_phony_target_is_reachable(self):
        # A target declared and never written is a command that fails with
        # "no rule to make target", which reads like a broken install.
        text = (ROOT / "Makefile").read_text()
        written = set(re.findall(r"^([a-z][a-z-]*):", text, re.MULTILINE))
        for line in re.findall(r"^\.PHONY:(.*(?:\\\n.*)*)", text, re.MULTILINE):
            for name in re.findall(r"[a-z][a-z-]*", line.replace("\\\n", " ")):
                self.assertIn(name, written, f"`.PHONY: {name}` has no rule")


class EveryLinkResolves(unittest.TestCase):
    def test_no_page_points_at_a_file_that_is_not_there(self):
        for page in PAGES:
            for href in LINK.findall(page.read_text()):
                if href.startswith(("http://", "https://", "mailto:")):
                    continue
                target = (page.parent / href).resolve()
                self.assertTrue(target.exists(),
                                f"{page.relative_to(ROOT)} links to `{href}`, "
                                "which does not exist")

    def test_every_page_is_reachable_from_an_index(self):
        # A page nobody links to is a page nobody reads, and it rots first.
        indexed = set()
        for index in (ROOT / "README.md", ROOT / "docs" / "README.md",
                      ROOT / "examples" / "README.md"):
            for href in LINK.findall(index.read_text()):
                if not href.startswith("http"):
                    indexed.add((index.parent / href).resolve())

        for page in PAGES:
            if page.name == "README.md":
                continue
            self.assertIn(page.resolve(), indexed,
                          f"nothing links to {page.relative_to(ROOT)}")


class TheThingsTheDocsNameByPath(unittest.TestCase):
    def test_the_spec_the_docs_tell_you_to_submit_exists(self):
        # `make submit SPEC=specs/document-the-ports.md` is the first command a
        # reader runs against a real repository.
        self.assertTrue((ROOT / "specs" / "document-the-ports.md").is_file())

    def test_the_example_settings_the_docs_tell_you_to_copy_exist(self):
        for name in ("minimal", "strict"):
            found = list((ROOT / "examples" / name / "settings").glob("*.yaml"))
            self.assertTrue(found, name)

    def test_repos_toml_is_a_template_and_names_nobodys_home_directory(self):
        # It is tracked. An absolute path from somebody's machine in it means
        # every clone starts with a diff nobody wants to commit.
        text = (ROOT / "repos.toml").read_text()
        for line in text.splitlines():
            if line.strip().startswith("#") or not line.strip():
                continue
            self.assertNotIn("/Users/", line)
            self.assertNotIn("/home/", line)

    def test_repos_toml_configures_no_repository(self):
        import tomllib
        config = tomllib.loads((ROOT / "repos.toml").read_text())
        self.assertEqual(config.get("repos", {}), {},
                         "repos.toml is the shared template. Machine-specific "
                         "entries belong in repos.local.toml, which is ignored")

    def test_the_local_file_is_git_ignored(self):
        ignored = (ROOT / ".gitignore").read_text()
        self.assertIn("repos.local.toml", ignored)


class TheDocsAgreeWithTheCode(unittest.TestCase):
    """A number in prose is a number that drifts. These are the ones that would
    mislead somebody rather than merely age."""

    def test_the_forges_named_in_the_docs_are_the_ones_that_ship(self):
        import forge
        text = (ROOT / "docs" / "CUSTOMIZING.md").read_text() \
            + (ROOT / "README.md").read_text()
        for name in forge.BUILT_IN:
            self.assertIn(f"`{name}`", text, f"no page mentions the {name} forge")

    def test_the_oversight_levels_named_in_the_docs_all_exist(self):
        import oversight
        text = (ROOT / "docs" / "LIMITATIONS.md").read_text()
        for level in re.findall(r"`(manual|attended|supervised|dark)`", text):
            self.assertIn(level, oversight.SETTINGS)

    def test_the_graders_the_evals_page_lists_are_the_ones_registered(self):
        import evaluators
        text = (ROOT / "docs" / "EVALS.md").read_text()
        for name in evaluators.EVALUATORS:
            self.assertIn(f"`{name}`", text,
                          f"docs/EVALS.md does not mention the `{name}` grader")

    def test_the_extension_directories_the_docs_list_are_the_real_ones(self):
        import extensions
        text = (ROOT / "docs" / "CUSTOMIZING.md").read_text()
        for kind, entry in extensions.KINDS.items():
            self.assertIn(f"`{kind}/`", text, kind)
            self.assertIn(f"`{entry}`", text, f"{kind} entry point `{entry}`")


if __name__ == "__main__":
    unittest.main()
