"""The forge seam: where a request for review goes.

A *forge* is whoever hosts the repository — GitHub, GitLab, Gitea, or nobody.
Until this module existed, `github::pr::create` was written into the publish
action, so a team on anything else had a fork rather than a setting.

The property this file protects: **the gate that decides what a human did is
forge-agnostic.** `derive_outcome` reads `state`, `merged`, `createdAt` and
`comments`, and every driver must produce those four whatever its host calls
them. A driver that got this wrong would deliver work nobody merged.
"""

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "workers" / "ghola-core" / "src"))
sys.path.insert(0, str(ROOT / "workers" / "ghola-factory" / "src"))

import actions  # noqa: E402
import forge  # noqa: E402


def job(**fields) -> dict:
    return {"id": "a" * 32, "repo": "/tmp/repo", "branch": "ghola/x",
            "title": "Do the thing", "repo_settings": {"base": "main"}, **fields}


def answer(value) -> dict:
    return {"ok": True, "value": value}


class WhichDriver(unittest.TestCase):
    def test_github_is_the_default(self):
        self.assertEqual(forge.for_job({}), "github")

    def test_the_job_carries_its_own(self):
        # Copied off `repos.toml` when the job was created, so a repository that
        # moved forge last month does not change how a rework of an old job is
        # delivered.
        self.assertEqual(forge.for_job({"repo_settings": {"forge": "local"}}), "local")

    def test_the_job_beats_its_settings(self):
        self.assertEqual(
            forge.for_job({"forge": "local", "repo_settings": {"forge": "github"}}),
            "local")

    def test_an_unknown_name_resolves_to_nothing_rather_than_a_default(self):
        # Falling back to GitHub would open a pull request against a forge the
        # operator did not name, which is a worse answer than an error.
        self.assertIsNone(forge.named("bitbucket"))


class EveryDriverAnswersTheSameQuestions(unittest.TestCase):
    """The seam is only a seam if both sides fit it."""

    def test_both_built_ins_implement_the_whole_interface(self):
        for name, driver in forge.BUILT_IN.items():
            for part in ("ready", "open_calls", "opened", "view_calls", "state",
                         "comment_calls", "comments", "say_calls"):
                self.assertTrue(callable(getattr(driver, part)), f"{name}.{part}")

    def test_state_always_produces_what_the_gate_reads(self):
        # `derive_outcome` is the one decision this seam exists to keep
        # forge-agnostic, and it reads exactly these.
        for name, driver in forge.BUILT_IN.items():
            state = driver.state(job(), [answer({}), answer({})])
            for key in ("state", "merged"):
                self.assertIn(key, state, f"{name} produced no `{key}`")

    def test_a_driver_names_what_it_calls_the_thing(self):
        self.assertEqual(forge.GITHUB.noun, "pull request")
        self.assertEqual(forge.LOCAL.noun, "request")


class TheTitle(unittest.TestCase):
    def test_a_markdown_heading_does_not_become_a_stray_hash(self):
        self.assertEqual(forge.title_of({"title": "# Do the thing"}), "Do the thing")

    def test_it_is_bounded(self):
        self.assertLessEqual(len(forge.title_of({"title": "x" * 300})), 70)


class GitHub(unittest.TestCase):
    def test_opening_names_the_stock_worker(self):
        calls = forge.GITHUB.open_calls(job(repo_slug="o/n"), "the body")
        self.assertEqual(calls[0]["function_id"], "github::pr::create")
        self.assertEqual(calls[0]["payload"]["head"], "ghola/x")
        self.assertEqual(calls[0]["payload"]["base"], "main")

    def test_it_refuses_without_a_slug_and_says_where_to_put_one(self):
        self.assertIn("repos.toml", forge.GITHUB.ready(job()))
        self.assertEqual(forge.GITHUB.ready(job(repo_slug="o/n")), "")

    def test_the_number_comes_out_of_the_url_when_the_worker_omits_it(self):
        # Without this the record has no `pr_number` and the reconciler answers
        # "no pull request to watch" forever, which looks exactly like a card
        # nobody has acted on.
        opened = forge.GITHUB.opened(
            job(), [answer({"output": "https://github.com/o/n/pull/7\n"})])
        self.assertEqual(opened["pr_number"], 7)

    def test_a_number_the_worker_did_give_is_kept(self):
        opened = forge.GITHUB.opened(job(), [answer({"number": 3, "url": "u"})])
        self.assertEqual(opened["pr_number"], 3)

    def test_comments_come_from_two_endpoints(self):
        # `github::pr::view` returns none of them. A reconciler reading it alone
        # sees a request nobody has ever commented on.
        calls = forge.GITHUB.comment_calls(job(repo_slug="o/n", pr_number=7))
        paths = [c["payload"]["path"] for c in calls]
        self.assertEqual(paths, ["repos/o/n/issues/7/comments",
                                 "repos/o/n/pulls/7/comments"])

    def test_either_endpoint_may_be_empty_without_failing_the_read(self):
        # A repository can legitimately have neither kind of comment.
        self.assertTrue(all(c["allow_failure"]
                            for c in forge.GITHUB.comment_calls(job(repo_slug="o/n"))))

    def test_a_line_comment_keeps_where_it_was(self):
        # Most of what makes a review comment actionable is the place.
        found = forge.GITHUB.comments([answer([
            {"id": 1, "body": "wrong", "path": "app.py", "line": 9,
             "created_at": "2026-01-01"}])])
        self.assertEqual(found[0]["body"], "app.py:9 — wrong")

    def test_comments_arriving_as_json_text_still_parse(self):
        found = forge.GITHUB.comments([answer('[{"id": 2, "body": "hi"}]')])
        self.assertEqual(found[0]["body"], "hi")

    def test_they_come_back_oldest_first(self):
        found = forge.GITHUB.comments([answer([
            {"id": 2, "body": "second", "created_at": "2026-02-01"},
            {"id": 1, "body": "first", "created_at": "2026-01-01"}])])
        self.assertEqual([c["body"] for c in found], ["first", "second"])


class NoForgeAtAll(unittest.TestCase):
    """`local` is the proof the seam is a seam rather than a rename.

    It is also the answer for a repository with no forge account behind it,
    which is most of what somebody trying this on their own machine has.
    """

    def test_the_request_is_a_file_in_the_repository(self):
        calls = forge.LOCAL.open_calls(job(), "the body")
        self.assertEqual(calls[0]["function_id"], "coder::create-file")
        path = calls[0]["payload"]["files"][0]["path"]
        self.assertEqual(path, "/tmp/repo/.ghola/requests/ghola-x.md")

    def test_it_is_written_to_the_main_checkout_not_the_worktree(self):
        # The worktree is released when the job ends, and the record of what was
        # asked should outlive it.
        calls = forge.LOCAL.open_calls(job(workspace="/tmp/wt_ab12"), "body")
        self.assertNotIn("wt_ab12", calls[0]["payload"]["files"][0]["path"])

    def test_the_file_says_how_to_answer_it(self):
        # Nobody can act on a request whose conventions are undocumented, and
        # the file is the only place a local reviewer will look.
        content = forge.LOCAL.open_calls(job(), "body")[0]["payload"]["files"][0]["content"]
        self.assertIn("merge the branch", content)
        self.assertIn("`closed`", content)
        self.assertIn(forge.HEADING, content)

    def test_it_needs_a_branch_and_says_so(self):
        self.assertIn("branch", forge.LOCAL.ready(job(branch="")))
        self.assertEqual(forge.LOCAL.ready(job()), "")

    def test_merge_is_asked_of_git_rather_than_of_a_forge(self):
        calls = forge.LOCAL.view_calls(job())
        self.assertEqual(calls[1]["function_id"], "shell::exec")
        self.assertEqual(calls[1]["payload"]["args"],
                         ["merge-base", "--is-ancestor", "ghola/x", "main"])

    def test_an_ancestor_branch_reads_as_merged(self):
        state = forge.LOCAL.state(job(), [answer({"content": "- status: open"}),
                                          answer({"exit_code": 0})])
        self.assertTrue(state["merged"])

    def test_a_branch_that_is_not_an_ancestor_does_not(self):
        state = forge.LOCAL.state(job(), [answer({"content": "- status: open"}),
                                          answer({"exit_code": 1})])
        self.assertFalse(state["merged"])

    def test_a_missing_request_file_is_not_a_merged_one(self):
        # The read is allowed to fail, and reading nothing as "landed" would
        # land work nobody looked at.
        state = forge.LOCAL.state(job(), [{"ok": False, "error": "no such file"},
                                          answer({"exit_code": 1})])
        self.assertFalse(state["merged"])
        self.assertNotEqual(state["state"], "merged")

    def test_a_human_closing_it_reads_as_closed(self):
        state = forge.LOCAL.state(job(), [answer({"content": "- status: closed"}),
                                          answer({"exit_code": 1})])
        self.assertEqual(state["state"], "closed")

    def test_the_comments_are_read_from_the_same_file(self):
        # Reading it twice would be two reads of one thing.
        self.assertEqual(forge.LOCAL.comment_calls(job()), [])

    def test_what_a_person_wrote_under_the_heading_is_a_comment(self):
        document = ("# t\n\n- status: open\n\nbody\n\n## comments\n\n"
                    f"{forge.CONVERSATION}\n"
                    "<!-- Write below this line. -->\n\nuse Decimal for money\n")
        found = forge.LOCAL.comments([answer({"content": document})])
        self.assertEqual([c["body"] for c in found], ["use Decimal for money"])

    def test_the_instruction_ghola_wrote_is_not_a_comment(self):
        document = f"# t\n\n{forge.CONVERSATION}\n<!-- Write below this line. -->\n"
        self.assertEqual(forge.LOCAL.comments([answer({"content": document})]), [])

    def test_the_request_cannot_read_its_own_document_as_feedback(self):
        # What actually happened. ghola's instruction line said "write under
        # `## comments`", so the split matched THAT occurrence, everything after
        # it — spec, plan, proof, review — came back as one reviewer comment, and
        # the job reworked itself against its own document. The conversation
        # starts at a marker for exactly this reason: prose gets quoted.
        content = forge.LOCAL.open_calls(job(), "the body")[0]["payload"]["files"][0]["content"]
        self.assertEqual(content.count(forge.CONVERSATION), 1)
        self.assertEqual(forge.LOCAL.comments([answer({"content": content})]), [])

    def test_a_reviewer_writing_the_heading_does_not_break_the_split(self):
        document = (f"{forge.CONVERSATION}\n"
                    "the ## comments heading should say more")
        found = forge.LOCAL.comments([answer({"content": document})])
        self.assertEqual(len(found), 1)

    def test_nothing_above_the_heading_is_a_comment(self):
        # The spec is in the body, and reading it back as feedback would rework
        # the job against its own request.
        document = f"# t\n\n- status: open\n\nthe whole spec\n\n{forge.CONVERSATION}\n"
        self.assertEqual(forge.LOCAL.comments([answer({"content": document})]), [])

    def test_three_dashes_separate_two_comments(self):
        document = f"{forge.CONVERSATION}\nfirst thing\n\n---\n\nsecond thing\n"
        found = forge.LOCAL.comments([answer({"content": document})])
        self.assertEqual([c["body"] for c in found], ["first thing", "second thing"])

    def test_the_same_words_are_the_same_comment(self):
        # `answered_comment` is how a rework stops reworking, and a file has no
        # per-comment id to use instead.
        document = f"{forge.CONVERSATION}\nuse Decimal\n"
        first = forge.LOCAL.comments([answer({"content": document})])
        again = forge.LOCAL.comments([answer({"content": document})])
        self.assertEqual(first[0]["id"], again[0]["id"])

    def test_editing_a_comment_makes_it_a_new_one(self):
        one = forge.LOCAL.comments(
            [answer({"content": f"{forge.CONVERSATION}\nuse Decimal"})])
        two = forge.LOCAL.comments(
            [answer({"content": f"{forge.CONVERSATION}\nuse Rational"})])
        self.assertNotEqual(one[0]["id"], two[0]["id"])

    def test_it_admits_it_has_nowhere_to_reply(self):
        # A driver that claimed to have said something it did not is worse than
        # one that says the channel does not exist.
        self.assertEqual(forge.LOCAL.say_calls(job(), "acknowledged"), [])


class TheGateDoesNotKnowWhichForgeItIs(unittest.TestCase):
    """`derive_outcome` over what each driver produced, rather than over a fixture."""

    def merged(self, driver, answers):
        return actions.derive_outcome(job(), {**driver.state(job(), answers),
                                              "comments": []})

    def test_a_merged_request_lands_on_either_forge(self):
        self.assertEqual(
            self.merged(forge.LOCAL, [answer({"content": "- status: open"}),
                                      answer({"exit_code": 0})])["outcome"], "merge")
        self.assertEqual(
            self.merged(forge.GITHUB, [answer({"merged": True})])["outcome"], "merge")

    def test_a_closed_request_closes_on_either(self):
        self.assertEqual(
            self.merged(forge.LOCAL, [answer({"content": "- status: closed"}),
                                      answer({"exit_code": 1})])["outcome"], "close")
        self.assertEqual(
            self.merged(forge.GITHUB, [answer({"state": "closed"})])["outcome"], "close")

    def test_an_untouched_request_waits_on_either(self):
        for driver, answers in ((forge.LOCAL, [answer({"content": "- status: open"}),
                                               answer({"exit_code": 1})]),
                                (forge.GITHUB, [answer({"state": "open"})])):
            self.assertEqual(self.merged(driver, answers)["outcome"], "")

    def test_a_local_comment_becomes_a_brief(self):
        document = f"{forge.CONVERSATION}\nfix it"
        state = forge.LOCAL.state(job(), [answer({"content": document}),
                                          answer({"exit_code": 1})])
        state["comments"] = forge.LOCAL.comments([answer({"content": document})])
        found = actions.derive_outcome(job(), state)
        self.assertEqual(found["outcome"], "comment")
        self.assertEqual(found["brief"], "fix it")

    def test_gholas_own_comment_is_never_a_brief(self):
        # It pushes with the operator's credentials and IS the request's author,
        # so telling its own comments apart by author would find none.
        document = f"{forge.CONVERSATION}\n{forge.MARKER}\nanswer pushed"
        state = {"state": "open",
                 "comments": forge.LOCAL.comments([answer({"content": document})])}
        self.assertEqual(actions.derive_outcome(job(), state)["outcome"], "")


class PushingIsAlsoTheForgesAnswer(unittest.TestCase):
    """A repository with no forge has no remote, and the branch is already in
    the checkout the reviewer will open.

    The first live run against a no-forge repository planned, ran, proved and
    reviewed, and then failed at the commit stage with `'origin' does not appear
    to be a git repository`.
    """

    class Engine:
        def __init__(self):
            self.ran = []

        def trigger(self, request):
            payload = request.get("payload") or {}
            if request["function_id"] == "shell::exec":
                self.ran.append([payload.get("command")] + list(payload.get("args") or []))
                # `git log <ref>..HEAD` has to report a commit or the stage
                # refuses the branch as empty.
                return {"exit_code": 0, "stdout": "abc123 did the thing"}
            return {"allowed": True}

    def commit(self, forge_name: str):
        engine = self.Engine()
        job_record = job(forge=forge_name, repo_slug="o/n", workspace="/tmp/wt",
                         title="Do it")
        result = actions.commit_and_push(engine, job_record,
                                         {"repo_settings": {"base": "main"}})
        return engine, result

    def test_github_pushes_to_origin(self):
        engine, result = self.commit("github")
        self.assertTrue(result["ok"], result)
        self.assertIn(["git", "push", "-u", "origin", "ghola/x"], engine.ran)

    def test_local_pushes_nowhere(self):
        engine, result = self.commit("local")
        self.assertTrue(result["ok"], result)
        self.assertFalse(result["pushed"])
        self.assertFalse([c for c in engine.ran if "push" in c])

    def test_the_empty_branch_check_names_a_ref_that_exists(self):
        # `origin/main` does not resolve without a remote. The comparison failed,
        # and a failed comparison skipped the check rather than reporting it.
        engine, _ = self.commit("local")
        logs = [c for c in engine.ran if c[:2] == ["git", "log"]]
        self.assertEqual(logs[0][-1], "main..HEAD")

    def test_the_delivery_gate_reads_the_whole_diff_either_way(self):
        for name, ref in (("github", "origin/main...HEAD"), ("local", "main...HEAD")):
            engine, _ = self.commit(name)
            diffs = [c for c in engine.ran if c[:2] == ["git", "diff"] and "--cached" not in c]
            self.assertEqual(diffs[0][2], ref, name)


class Extending(unittest.TestCase):
    def test_forges_is_an_extension_directory(self):
        import extensions
        self.assertEqual(extensions.KINDS["forges"], "driver")

    def test_a_name_nothing_defines_says_where_to_put_it(self):
        found, problem = actions.driver_for({"forge": "gitea"}, {})
        self.assertIsNone(found)
        self.assertIn("forges/gitea.py", problem)

    def test_a_function_id_is_refused_with_the_reason(self):
        # Every other extension point takes one, and a forge cannot: it answers
        # four questions and one call would have to switch on which.
        found, problem = actions.driver_for({"forge": "acme::forge"}, {})
        self.assertIsNone(found)
        self.assertIn("module rather than one call", problem)

    def test_a_built_in_resolves_without_touching_the_filesystem(self):
        found, problem = actions.driver_for({"forge": "local"}, {})
        self.assertEqual(problem, "")
        self.assertIs(found, forge.LOCAL)


if __name__ == "__main__":
    unittest.main()
