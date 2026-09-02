"""Job records on disk.

Files rather than the `state` worker, and the tests reflect why: the properties
that matter are the ones a misconfigured store loses silently.
"""

import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "workers" / "ghola-core" / "src"))

import graph as g  # noqa: E402
import jobs  # noqa: E402


class Records(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.store = jobs.Store(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def test_a_created_job_is_readable_immediately(self):
        job = self.store.create("add a flag", "/repo", "prepare")
        self.assertEqual(self.store.read(job["id"])["spec"], "add a flag")

    def test_it_survives_a_new_store_object(self):
        # The whole point of files: nothing is held in a process.
        job = self.store.create("x", "/repo", "prepare")
        self.assertIsNotNone(jobs.Store(self.tmp.name).read(job["id"]))

    def test_an_unknown_job_reads_as_none(self):
        self.assertIsNone(self.store.read("nosuchjob"))

    def test_a_job_id_cannot_escape_its_directory(self):
        for bad in ("../outside", "a/b", "", ".hidden"):
            with self.assertRaises(ValueError, msg=bad):
                self.store.path(bad)

    def test_a_corrupt_file_is_skipped_rather_than_fatal(self):
        self.store.create("good", "/repo", "prepare")
        (Path(self.tmp.name) / "broken.json").write_text("{not json")
        self.assertEqual(len(self.store.list()), 1)

    def test_the_write_is_atomic(self):
        # A half-written record is a job in a state that never existed. The
        # observable half of atomicity: no temp files are left behind.
        job = self.store.create("x", "/repo", "prepare")
        self.store.write({**job, "stage": "run"})
        leftovers = [p.name for p in Path(self.tmp.name).iterdir()
                     if p.name.endswith(".tmp") or p.name.startswith(".")]
        self.assertEqual(leftovers, [])

    def test_jobs_list_newest_first(self):
        first = self.store.create("first", "/repo", "prepare")
        second = self.store.create("second", "/repo", "prepare")
        second["created_at"] = first["created_at"] + 1000
        self.store.write(second)
        self.assertEqual(self.store.list()[0]["spec"], "second")

    def test_waiting_finds_what_the_reconciler_needs(self):
        self.store.create("a", "/repo", "waiting")
        self.store.create("b", "/repo", "run")
        self.assertEqual(len(self.store.waiting()), 1)


class Advancing(unittest.TestCase):
    """Pure: it returns the new record and writes nothing."""

    def setUp(self):
        self.job = {"id": "abc", "stage": "plan", "revisions": 0, "history": []}

    def test_it_records_where_it_came_from(self):
        moved = jobs.advance(self.job, "run", why="plan finished")
        self.assertEqual(moved["stage"], "run")
        self.assertEqual(moved["history"][-1]["from"], "plan")
        self.assertEqual(moved["history"][-1]["why"], "plan finished")

    def test_it_does_not_mutate_the_original(self):
        jobs.advance(self.job, "run")
        self.assertEqual(self.job["stage"], "plan")

    def test_a_revision_counts_and_is_marked(self):
        moved = jobs.advance(self.job, "run", revision=True)
        self.assertEqual(moved["revisions"], 1)
        self.assertEqual(moved["reason"], "revision")

    def test_history_accumulates(self):
        moved = jobs.advance(jobs.advance(self.job, "run"), "prove")
        self.assertEqual(len(moved["history"]), 2)


class WithTheGraph(unittest.TestCase):
    """The store and the state machine, together, without an engine."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.store = jobs.Store(self.tmp.name)
        import defaults
        self.graph = g.parse(defaults.pipeline())

    def tearDown(self):
        self.tmp.cleanup()

    def test_a_job_walks_the_whole_pipeline(self):
        job = self.store.create("add a flag", "/repo", self.graph.first)
        seen = [job["stage"]]

        for _ in range(20):
            move = g.next_stage(job, self.graph, {"ok": True})
            job = self.store.write(jobs.advance(job, move.to, move.why))
            seen.append(move.to)
            if move.to == "waiting":
                break

        # No `refine`: it is optional and this job did not ask for it, which is
        # the common case — most work arrives as a spec somebody wrote.
        self.assertEqual(seen, ["prepare", "plan", "run", "prove", "review",
                                "commit", "publish", "waiting"])
        self.assertEqual(self.store.read(job["id"])["stage"], "waiting")

    def test_a_revision_loop_terminates(self):
        job = self.store.create("x", "/repo", "run")
        for _ in range(10):
            move = g.next_stage(job, self.graph,
                                {"refused": True, "refusal": f"try {job['revisions']}"})
            job = self.store.write(
                jobs.advance(job, move.to, move.why, revision=move.revision,
                             last_refusal=f"try {job['revisions']}"))
            if move.terminal:
                break
        self.assertEqual(job["stage"], "failed")
        self.assertLessEqual(job["revisions"], 3)

    def test_the_history_is_the_audit_of_where_it_went(self):
        job = self.store.create("x", "/repo", "prepare")
        move = g.next_stage(job, self.graph, {"ok": True})
        job = self.store.write(jobs.advance(job, move.to, move.why))
        self.assertEqual(job["history"][0]["from"], "prepare")
        self.assertEqual(job["history"][0]["to"], "plan")

    def test_a_job_that_asked_to_be_refined_walks_one_stage_more(self):
        job = self.store.create("a rough idea", "/repo", self.graph.first)
        job["want_refine"] = True
        seen = [job["stage"]]
        for _ in range(20):
            move = g.next_stage(job, self.graph, {"ok": True})
            job = self.store.write(jobs.advance(job, move.to, move.why))
            seen.append(move.to)
            if move.to == "waiting":
                break
        self.assertEqual(seen[:3], ["prepare", "refine", "plan"])


class WhoHoldsARepository(unittest.TestCase):
    """The concurrency limit, as a list and a number.

    `repos.toml` carried a `concurrency` key that nothing read: three places in
    `repos.py` parsed it and no code asked for the value. The worktree claim was
    said to cover it, and it covers one checkout rather than one repository.
    """

    def job(self, ident, repo="/a", stage="run"):
        return {"id": ident, "repo": repo, "stage": stage}

    def test_the_job_asking_is_never_its_own_holder(self):
        # At-least-once delivery means prepare can be handed the same job twice.
        # A job blocked by itself would never start.
        live = [self.job("me")]
        self.assertEqual(jobs.holding(live, "/a", exclude="me"), [])

    def test_another_repositorys_jobs_do_not_count(self):
        live = [self.job("other", repo="/b")]
        self.assertEqual(jobs.holding(live, "/a"), [])

    def test_a_finished_job_holds_nothing(self):
        for stage in jobs.RELEASED:
            with self.subTest(stage=stage):
                self.assertEqual(jobs.holding([self.job("x", stage=stage)], "/a"), [])

    def test_an_open_pull_request_still_holds_the_environment(self):
        # `waiting` is NOT released: `teardown` runs the repository's `cleanup`
        # and it is called on a terminal state only, so the ports are still up.
        held = jobs.holding([self.job("x", stage="waiting")], "/a")
        self.assertEqual([j["id"] for j in held], ["x"])

    def test_a_job_that_asked_a_question_still_holds_it(self):
        held = jobs.holding([self.job("x", stage="blocked")], "/a")
        self.assertEqual([j["id"] for j in held], ["x"])

    def test_released_matches_the_graphs_terminal_states(self):
        # The one drift that would matter: a terminal state missing from
        # RELEASED lets a finished job hold a repository forever.
        self.assertEqual(set(jobs.RELEASED), set(g.TERMINAL))


if __name__ == "__main__":
    unittest.main()
