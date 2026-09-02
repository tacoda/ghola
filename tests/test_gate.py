"""The pull-request gate, tested without a pull request.

`derive_outcome` is one pure function of the job record and what the forge
returned, which is what lets every branch of the gate be exercised here. wipp
proved this was worth extracting: its whole gate is a decision over two dicts,
and it is the part of a factory most expensive to test any other way.
"""

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "workers" / "ghola-core" / "src"))
sys.path.insert(0, str(ROOT / "workers" / "ghola-factory" / "src"))

import actions  # noqa: E402
import diffs  # noqa: E402


def pr(state="open", merged=False, comments=(), created="2026-01-01T00:00:00Z"):
    return {"state": state, "merged": merged, "createdAt": created,
            "comments": list(comments)}


def comment(body, when="2026-01-02T00:00:00Z", ident=None):
    return {"body": body, "createdAt": when, "id": ident or when}


class WhatTheHumanDid(unittest.TestCase):
    def test_a_merge_is_a_merge(self):
        self.assertEqual(actions.derive_outcome({}, pr(merged=True))["outcome"], "merge")

    def test_a_merged_state_counts_too(self):
        self.assertEqual(actions.derive_outcome({}, pr(state="MERGED"))["outcome"],
                         "merge")

    def test_a_close_is_a_close(self):
        self.assertEqual(actions.derive_outcome({}, pr(state="closed"))["outcome"],
                         "close")

    def test_a_comment_is_a_brief(self):
        found = actions.derive_outcome({}, pr(comments=[comment("please rename this")]))
        self.assertEqual(found["outcome"], "comment")
        self.assertEqual(found["brief"], "please rename this")

    def test_nothing_is_a_legitimate_answer(self):
        # The card waits. This is the common case and it must not look like a
        # failure.
        self.assertEqual(actions.derive_outcome({}, pr())["outcome"], "")


class WhoseCommentIsIt(unittest.TestCase):
    """ghola pushes with the operator's credentials and IS the PR's author."""

    def test_gholas_own_comments_are_not_feedback(self):
        # Telling them apart by author would find none of them.
        found = actions.derive_outcome(
            {}, pr(comments=[comment(f"{actions.MARKER}\nopened by ghola")]))
        self.assertEqual(found["outcome"], "")

    def test_a_real_comment_after_gholas_own_is_feedback(self):
        found = actions.derive_outcome({}, pr(comments=[
            comment(f"{actions.MARKER} opened", "2026-01-02T00:00:00Z"),
            comment("this needs a test", "2026-01-03T00:00:00Z"),
        ]))
        self.assertEqual(found["brief"], "this needs a test")

    def test_a_comment_older_than_the_pull_request_is_not_feedback(self):
        found = actions.derive_outcome({}, pr(
            created="2026-01-05T00:00:00Z",
            comments=[comment("from a previous life", "2026-01-01T00:00:00Z")]))
        self.assertEqual(found["outcome"], "")

    def test_a_comment_already_answered_is_not_feedback_again(self):
        # Otherwise the gate reworks the same comment forever.
        found = actions.derive_outcome(
            {"answered_comment": "c1"},
            pr(comments=[comment("please rename", ident="c1")]))
        self.assertEqual(found["outcome"], "")

    def test_the_newest_unanswered_comment_wins(self):
        found = actions.derive_outcome({"answered_comment": "c1"}, pr(comments=[
            comment("old", "2026-01-02T00:00:00Z", ident="c1"),
            comment("new", "2026-01-03T00:00:00Z", ident="c2"),
        ]))
        self.assertEqual(found["brief"], "new")

    def test_the_comment_id_travels_so_it_can_be_marked_answered(self):
        found = actions.derive_outcome({}, pr(comments=[comment("x", ident="c9")]))
        self.assertEqual(found["comment_id"], "c9")


class MergeBeatsEverything(unittest.TestCase):
    def test_a_merged_pull_request_with_comments_still_lands(self):
        # A review arriving after a merge is a note in a closed room.
        found = actions.derive_outcome({}, pr(merged=True, comments=[comment("late")]))
        self.assertEqual(found["outcome"], "merge")


class EveryOutcomeIsAGraphEdge(unittest.TestCase):
    """The gate and the graph have to agree on the vocabulary."""

    def test_the_outcomes_match_what_the_pipeline_declares(self):
        import defaults
        import graph as g
        waiting = g.parse(defaults.pipeline()).get("waiting")
        declared = {name for name, _ in waiting.outcomes}
        for outcome in ("merge", "close", "comment"):
            self.assertIn(outcome, declared,
                          f"the gate can return `{outcome}` and the graph has no "
                          "edge for it, so a job would sit in `waiting` forever")




class TheCommitMessage(unittest.TestCase):
    """No AI attribution, and it is a rule rather than a preference."""

    def test_it_carries_no_tool_attribution(self):
        # The operator is the author. Not adding it here means rung 4 never has
        # to remove it.
        message = actions.commit_message({"title": "add a --version flag"})
        for tell in ("Co-Authored-By", "Generated with", "claude", "Claude", "ghola-bot"):
            self.assertNotIn(tell, message)

    def test_it_is_one_line_and_bounded(self):
        message = actions.commit_message({"title": "x" * 200 + "\nsecond line"})
        self.assertNotIn("\n", message)
        self.assertLessEqual(len(message), 72)

    def test_a_job_with_no_title_still_commits(self):
        self.assertTrue(actions.commit_message({}))

    def test_a_specs_heading_marker_does_not_reach_the_subject(self):
        # A spec's first line is `# Do the thing`, and `git commit -m` keeps the
        # hash: every commit in the first no-forge run read as a heading.
        self.assertEqual(actions.commit_message({"title": "# Do the thing"}),
                         "Do the thing")



class BranchNaming(unittest.TestCase):
    """The repository's convention, not the worktree worker's default."""

    def test_it_uses_the_repos_prefix(self):
        name = actions.branch_name({"title": "Document the make targets",
                                    "id": "abcdef123456"},
                                   {"branch_prefix": "feature/"})
        self.assertTrue(name.startswith("feature/document-the-make-targets"))

    def test_a_title_becomes_a_readable_slug(self):
        # A person reading a list of branches should be able to tell which is
        # which, which `iii/wt_ab12cd` does not allow.
        name = actions.branch_name({"title": "Add a --version flag!",
                                    "id": "abcdef123456"}, {})
        self.assertEqual(name, "ghola/add-a-version-flag-abcdef12")

    def test_two_jobs_from_one_spec_do_not_collide(self):
        # Without the suffix the second run of any spec fails at
        # worktree::create with `W120: branch already exists`.
        first = actions.branch_name({"title": "same spec", "id": "aaaaaaaa1111"}, {})
        second = actions.branch_name({"title": "same spec", "id": "bbbbbbbb2222"}, {})
        self.assertNotEqual(first, second)

    def test_a_job_with_no_title_falls_back_to_its_id(self):
        name = actions.branch_name({"id": "abcdef123456"}, {})
        self.assertEqual(name, "ghola/abcdef12")

    def test_a_long_title_is_bounded(self):
        name = actions.branch_name({"title": "x " * 200}, {"branch_prefix": "p/"})
        self.assertLessEqual(len(name), 55)



class ThePullRequestNumber(unittest.TestCase):
    """Without it the reconciler answers "no pull request to watch" forever,
    which looks exactly like a card nobody has acted on."""

    def test_it_is_parsed_from_the_url_gh_prints(self):
        class Forge:
            def trigger(self, req):
                return {"output": "https://github.com/o/r/pull/42"}
        result = actions.open_pull_request(
            Forge(), {"repo_slug": "o/r", "branch": "b", "title": "t"}, {})
        self.assertEqual(result["pr_number"], 42)

    def test_a_url_with_no_number_does_not_invent_one(self):
        class Forge:
            def trigger(self, req):
                return {"output": "https://github.com/o/r/pull/"}
        result = actions.open_pull_request(
            Forge(), {"repo_slug": "o/r", "branch": "b", "title": "t"}, {})
        self.assertIsNone(result["pr_number"])

    def test_no_slug_is_refused_with_a_reason(self):
        result = actions.open_pull_request(object(), {"branch": "b"}, {})
        self.assertFalse(result["ok"])
        self.assertIn("owner/name", result["error"])



class ShellExecIsNotAShell(unittest.TestCase):
    """The bug that pushed a branch with no commits on it.

    `shell::exec` spawns a program directly: `command` is the program name and
    `args` is a list. Passing `git add -A && git commit -m x` as `command` tries
    to spawn a program with that literal name.

    And `exit_code` comes back in the payload rather than raising, so a command
    that ran and FAILED reads as ok — which is the exact shape the repository's
    own commit hook refusing takes.
    """

    class Shell:
        """Records what it was asked to run, and fails only the command named.

        Per-command rather than blanket, because `commit_and_push` runs several
        and a fake that fails all of them never reaches the one under test.
        """

        def __init__(self, fails="", code=0, stdout="", stderr=""):
            self.calls = []
            self.fails, self.code = fails, code
            self.stdout, self.stderr = stdout, stderr

        def trigger(self, request):
            payload = request.get("payload") or {}
            function_id = request.get("function_id", "")

            if function_id != "shell::exec":
                # worktree::status, ladder::evaluate and friends: unremarkable.
                return {}

            self.calls.append(payload)
            args = payload.get("args") or []
            if self.fails and args and args[0] == self.fails:
                return {"exit_code": self.code or 1, "stdout": self.stdout,
                        "stderr": self.stderr}
            return {"exit_code": 0, "stdout": "", "stderr": ""}

    def test_the_program_and_its_arguments_are_separate(self):
        shell = self.Shell()
        actions.run(shell, "git", ["add", "-A"], "/w")
        self.assertEqual(shell.calls[0]["command"], "git")
        self.assertEqual(shell.calls[0]["args"], ["add", "-A"])

    def test_no_shell_operators_are_ever_put_in_command(self):
        shell = self.Shell()
        actions.run(shell, "git", ["commit", "-m", "a && b"], "/w")
        self.assertNotIn("&&", shell.calls[0]["command"])

    def test_a_non_zero_exit_is_a_failure(self):
        shell = self.Shell(fails="commit", stderr="hook refused: no secrets")
        result = actions.run(shell, "git", ["commit"], "/w")
        self.assertFalse(result["ok"])
        self.assertIn("hook refused", result["error"])

    def test_the_repositorys_own_hook_refusal_becomes_a_refusal(self):
        # Verbatim, because summarising it throws away the only specific thing
        # anybody said about the work.
        shell = self.Shell(fails="commit",
                           stderr="pre-commit: line 4 has a bare except")
        result = actions.commit_and_push(
            shell, {"id": "j", "workspace": "/w", "branch": "b", "title": "t"}, {})
        self.assertTrue(result.get("refused"))
        self.assertIn("bare except", result["refusal"])

    def test_committing_nothing_is_not_a_refusal(self):
        # A branch with no commits cannot become a pull request, and sending it
        # back to `run` would loop on a turn that had nothing to do.
        shell = self.Shell(fails="commit",
                           stdout="nothing to commit, working tree clean")
        result = actions.commit_and_push(
            shell, {"id": "j", "workspace": "/w", "branch": "b", "title": "t"}, {})
        self.assertFalse(result["ok"])
        self.assertFalse(result.get("refused"))
        self.assertIn("nothing to publish", result["error"])

    def test_a_repo_command_line_gets_an_explicit_shell(self):
        # `prepare = "make up && make migrate"` is a shell string a person
        # wrote, so it gets `sh -c` explicitly rather than by hoping.
        shell = self.Shell()
        actions.run_command(shell, "make up && make migrate", "/w")
        self.assertEqual(shell.calls[0]["command"], "sh")
        self.assertEqual(shell.calls[0]["args"][0], "-c")


TWO_FILES = """diff --git a/app/models/user.rb b/app/models/user.rb
@@ -1 +1 @@
-old
+new
diff --git a/README.md b/README.md
@@ -1 +1 @@
-a
+b
"""


class SplittingADiff(unittest.TestCase):
    """`per_file` is pure, so the gate's hardest input is a string."""

    def test_each_file_comes_back_with_its_patch(self):
        found = diffs.per_file(TWO_FILES)
        self.assertEqual([p for p, _ in found],
                         ["app/models/user.rb", "README.md"])
        self.assertIn("+new", dict(found)["app/models/user.rb"])
        self.assertNotIn("+new", dict(found)["README.md"])

    def test_the_new_name_travels_not_the_old_one(self):
        # A rename is the case: a path-scoped rule is about where the file is
        # going, and `governs_path` is asked with one path.
        renamed = "diff --git a/old/name.rb b/app/models/name.rb\n@@ -0,0 +1 @@\n+x\n"
        self.assertEqual(diffs.per_file(renamed)[0][0], "app/models/name.rb")

    def test_a_path_with_a_space_in_it_survives(self):
        spaced = "diff --git a/doc/my notes.md b/doc/my notes.md\n@@ -1 +1 @@\n+x\n"
        self.assertEqual(diffs.per_file(spaced)[0][0], "doc/my notes.md")

    def test_a_file_in_two_diffs_is_one_entry(self):
        # The gate reads `against...HEAD` and `--cached`, and a file loose in
        # both would otherwise be shown to a predicate half at a time.
        twice = TWO_FILES + "\n" + TWO_FILES
        found = diffs.per_file(twice)
        self.assertEqual(len(found), 2)
        self.assertEqual(dict(found)["README.md"].count("diff --git"), 2)

    def test_anything_before_the_first_header_is_dropped(self):
        self.assertEqual(diffs.per_file("noise\n\n" + TWO_FILES)[0][0],
                         "app/models/user.rb")

    def test_no_diff_is_no_files_rather_than_one_empty_one(self):
        self.assertEqual(diffs.per_file(""), [])
        self.assertEqual(diffs.per_file("\n"), [])


class TheDeliveryGateFailsClosed(unittest.TestCase):
    """Rung 4, and the three ways it used to wave a change through.

    It cut the diff at 200,000 characters with no marker, it read an
    unreachable ladder as "not refused", and it read a failed `git diff` as an
    empty change. All three ended in a commit, and the ladder states the
    principle they broke in its own predicate runner: a predicate that throws is
    a finding, not a pass.
    """

    class Worker:
        """Answers `shell::exec` and `ladder::evaluate`, and records both."""

        def __init__(self, diff=TWO_FILES, refuse="", unreachable=False,
                     diff_fails=False):
            self.diff, self.refuse = diff, refuse
            self.unreachable, self.diff_fails = unreachable, diff_fails
            self.asked, self.ran = [], []

        def trigger(self, request):
            function_id = request.get("function_id", "")
            payload = request.get("payload") or {}

            if function_id == "shell::exec":
                args = payload.get("args") or []
                self.ran.append(args)
                if args[:1] == ["diff"]:
                    if self.diff_fails:
                        return {"exit_code": 128, "stderr": "not a git repository"}
                    # `--cached` is empty: the work is committed already.
                    out = "" if "--cached" in args else self.diff
                    return {"exit_code": 0, "stdout": out}
                return {"exit_code": 0, "stdout": ""}

            if function_id == "ladder::evaluate":
                if self.unreachable:
                    raise RuntimeError("that worker is not up")
                self.asked.append(payload)
                if self.refuse and payload.get("path") == self.refuse:
                    return {"allowed": False,
                            "reason": f"no-secrets: {self.refuse}:1 an API key"}
                return {"allowed": True}

            return {}

        def paths(self):
            return [str(p.get("path") or "") for p in self.asked]

        def committed(self):
            return any(a[:1] == ["commit"] for a in self.ran)

    def gate(self, worker, text="a commit message"):
        return actions.rung_four(worker, {"id": "j"}, "/w", text, "origin/main")

    def test_the_ladder_is_asked_once_per_file_with_the_real_path(self):
        # The bug this replaces: one call with `path: ""`, which skips the path
        # filter in `Loaded.governing` and in `gate.decide` both, so a rule
        # scoped to `app/models/**` was asked about README.md as well.
        worker = self.Worker()
        self.assertEqual(self.gate(worker), ("", ""))
        self.assertEqual(worker.paths(), ["app/models/user.rb", "README.md"])

    def test_a_file_is_shown_its_own_patch_and_not_the_others(self):
        worker = self.Worker()
        self.gate(worker)
        first = dict(zip(worker.paths(), [p["content"] for p in worker.asked]))
        self.assertIn("+new", first["app/models/user.rb"])
        self.assertNotIn("README", first["app/models/user.rb"])

    def test_a_refusal_on_any_file_refuses_the_change(self):
        worker = self.Worker(refuse="README.md")
        refusal, problem = self.gate(worker)
        self.assertEqual(problem, "")
        self.assertIn("no-secrets", refusal)

    def test_an_unreachable_ladder_is_a_problem_and_not_a_pass(self):
        worker = self.Worker(unreachable=True)
        refusal, problem = self.gate(worker)
        self.assertEqual(refusal, "")
        self.assertIn("nothing has checked this change", problem)

    def test_a_failed_git_diff_is_a_problem_and_not_an_empty_change(self):
        worker = self.Worker(diff_fails=True)
        refusal, problem = self.gate(worker)
        self.assertEqual(refusal, "")
        self.assertIn("could not read the change", problem)
        self.assertEqual(worker.asked, [],
                         "the ladder was asked about a diff nobody could read")

    def test_an_empty_diff_still_gets_the_publishing_text_checked(self):
        # A rule about what a pull request may say does not need a file to have
        # been touched to be broken.
        worker = self.Worker(diff="")
        self.assertEqual(self.gate(worker, "Co-Authored-By: a tool"), ("", ""))
        self.assertEqual(len(worker.asked), 1)
        self.assertEqual(worker.asked[0]["publishing"], "Co-Authored-By: a tool")

    def test_the_publishing_text_goes_with_every_file(self):
        # `gate.escaped` reads an escape hatch out of the commit message, so a
        # file evaluated without it would be refused by a rule already escaped.
        worker = self.Worker()
        self.gate(worker, "ladder-escape: vendored")
        self.assertEqual([p["publishing"] for p in worker.asked],
                         ["ladder-escape: vendored"] * 2)

    def test_an_oversized_file_is_bounded_and_says_so(self):
        big = ("diff --git a/vendor/big.js b/vendor/big.js\n"
               + "+x" * actions.PER_FILE_LIMIT)
        worker = self.Worker(diff=big)
        self.assertEqual(self.gate(worker), ("", ""))
        content = worker.asked[0]["content"]
        self.assertIn("truncated at", content)
        self.assertLess(len(content), len(big))

    def test_too_many_files_is_a_problem_rather_than_thousands_of_calls(self):
        # The whole-diff cut used to bound this by accident. Per file it does
        # not, and one call per file at a 60-second timeout is a factory that
        # grinds rather than one that answers.
        wide = "".join(f"diff --git a/f{n}.rb b/f{n}.rb\n+x\n"
                       for n in range(actions.MAX_FILES + 1))
        worker = self.Worker(diff=wide)
        refusal, problem = self.gate(worker)
        self.assertEqual(refusal, "")
        self.assertIn(str(actions.MAX_FILES + 1), problem)
        self.assertEqual(worker.asked, [])

    def test_a_change_at_the_limit_still_goes_through(self):
        wide = "".join(f"diff --git a/f{n}.rb b/f{n}.rb\n+x\n"
                       for n in range(actions.MAX_FILES))
        worker = self.Worker(diff=wide)
        self.assertEqual(self.gate(worker), ("", ""))
        self.assertEqual(len(worker.asked), actions.MAX_FILES)

    def test_a_gate_that_could_not_answer_never_reaches_a_commit(self):
        # The whole point, at the level the caller sees: a problem is `ok: False`
        # rather than a refusal, because no rework brings a worker back up.
        worker = self.Worker(unreachable=True)
        result = actions.commit_and_push(
            worker, {"id": "j", "workspace": "/w", "branch": "b", "title": "t"}, {})
        self.assertFalse(result["ok"])
        self.assertFalse(result.get("refused"))
        self.assertFalse(worker.committed())


if __name__ == "__main__":
    unittest.main()
