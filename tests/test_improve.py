"""The improve lane end to end, with a fake engine.

The invariant this file exists for: **accepting a proposal applies nothing.**
It writes a spec into `specs/` and stops, and that spec goes through the same
pipeline and the same pull request as any other work. A lane that could edit
the charter it proposes changes to would be the one thing in this system
escaping the gate everything else goes through.
"""

import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "workers" / "ghola-core" / "src"))
sys.path.insert(0, str(ROOT / "workers" / "ghola-factory" / "src"))

import improve  # noqa: E402
import proposals  # noqa: E402

ANSWER = """
## Say the money rule out loud

- lane: charter
- kind: rule
- action: add
- target: CLAUDE.md
- evidence: job aaaa
- why: two jobs used floats for money

Money is `Decimal`, everywhere.

## A proposal from nowhere

- lane: factory
- kind: stage
- action: add
- target: pipeline.yaml
- why: it feels like it would help

Nothing points at this.
"""


class Engine:
    """Enough of a worker to answer the two reads and record the sends."""

    def __init__(self, entries=None, rules=None, fail=()):
        self.entries = entries or []
        self.rules = rules or []
        self.fail = set(fail)
        self.sent = []

    def trigger(self, request):
        function_id = request["function_id"]
        self.sent.append((function_id, request.get("payload") or {}))
        if function_id in self.fail:
            raise RuntimeError("that worker is not up")
        if function_id == "audit::read":
            return {"entries": self.entries, "total": len(self.entries)}
        if function_id == "ladder::list":
            return {"primitives": self.rules}
        if function_id == "ladder::move":
            return {"ok": True, "primitive": "no-secrets", "was": [2], "now": [3]}
        return {}


def job(**fields) -> dict:
    return {"id": "a" * 32, "stage": "landed", "revisions": 0,
            "repo": "/tmp/repo", **fields}


def rule(name: str) -> dict:
    return {"id": name, "side": "constraint"}


class Scratch(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.addCleanup(self.tmp.cleanup)


class Starting(Scratch):
    def test_a_clean_record_starts_no_turn(self):
        # The lane refuses to run rather than handing a model no evidence and
        # taking whatever it says. A model given nothing still proposes things.
        engine = Engine()
        answer = improve.start(engine, self.root, [job()], "/tmp/repo")
        self.assertIn("skipped", answer)
        self.assertNotIn("harness::send", [f for f, _ in engine.sent])

    def test_trouble_on_the_record_starts_one(self):
        engine = Engine()
        answer = improve.start(engine, self.root, [job(revisions=1)], "/tmp/repo")
        self.assertIn("run", answer)
        self.assertIn("harness::send", [f for f, _ in engine.sent])

    def test_the_turn_is_handed_the_evidence(self):
        engine = Engine(entries=[{"kind": "ladder.refused", "actor": "no-secrets",
                                  "detail": {"rung": 3}}])
        improve.start(engine, self.root, [job()], "/tmp/repo")
        sent = dict(engine.sent)["harness::send"]
        text = sent["message"]["content"][0]["text"]
        self.assertIn("no-secrets", text)

    def test_the_turn_is_scoped_to_the_repository_it_is_about(self):
        # Every proposal is about a repository's own configuration, and a turn
        # pointed elsewhere would be proposing changes to files it cannot read.
        engine = Engine()
        improve.start(engine, self.root, [job(revisions=1)], "/tmp/repo")
        sent = dict(engine.sent)["harness::send"]
        self.assertEqual(sent["options"]["metadata"]["fs_scope"]["root"], "/tmp/repo")

    def test_it_can_read_ghola_as_well_as_the_target(self):
        # The lane reads two repositories: a charter proposal is about the
        # target, a harness or factory one is about ghola's own files. Scoped to
        # one, the turn hits the filesystem boundary on the other and the
        # approval hook parks the call for a person who is not watching. The
        # first live run sat in `awaiting_functions` for ten minutes doing that.
        engine = Engine()
        improve.start(engine, self.root, [job(revisions=1)], "/tmp/repo")
        granted = dict(engine.sent)["harness::filesystem::grant"]
        self.assertEqual(granted["root"], str(self.root))
        self.assertEqual(granted["session_id"], "s_" + granted["session_id"].split("_")[1]
                         + "_improve")

    def test_the_grant_is_asked_for_before_the_turn_starts(self):
        # A grant made after the first refused read is a grant that arrives one
        # parked call too late.
        engine = Engine()
        improve.start(engine, self.root, [job(revisions=1)], "/tmp/repo")
        called = [f for f, _ in engine.sent]
        self.assertLess(called.index("harness::filesystem::grant"),
                        called.index("harness::send"))

    def test_the_brief_names_both_places(self):
        engine = Engine()
        improve.start(engine, self.root, [job(revisions=1)], "/tmp/repo")
        text = dict(engine.sent)["harness::send"]["message"]["content"][0]["text"]
        self.assertIn("/tmp/repo", text)
        self.assertIn(str(self.root), text)

    def test_the_run_is_recorded_before_the_turn_returns(self):
        # A crash mid-turn should leave a run somebody can find, not nothing.
        engine = Engine()
        answer = improve.start(engine, self.root, [job(revisions=1)], "/tmp/repo")
        run = improve.read(self.root, answer["run"])
        self.assertEqual(run["state"], "running")

    def test_the_run_id_survives_the_session_name(self):
        # `session_for` strips everything but lowercase alphanumerics, so an id
        # it would rewrite comes back out of a completion as a different string.
        import turn as turnlib
        for _ in range(20):
            run_id = improve.new_run_id()
            session = turnlib.session_for(run_id, improve.PHASE)
            self.assertEqual(turnlib.phase_of({"session_id": session})[0], run_id)


class WhatItCannotSee(Scratch):
    """A worker being down narrows the evidence. It must not read as calm."""

    def test_a_missing_ladder_is_named_rather_than_silent(self):
        engine = Engine(fail={"ladder::list"})
        found = improve.evidence(engine, [job(revisions=1)], "/tmp/repo")
        self.assertTrue(any("ladder" in m for m in found["missing"]))

    def test_a_missing_audit_log_is_named_too(self):
        engine = Engine(fail={"audit::read"})
        found = improve.evidence(engine, [job(revisions=1)], "/tmp/repo")
        self.assertTrue(any("audit" in m for m in found["missing"]))

    def test_the_lane_still_runs_on_the_job_records_alone(self):
        engine = Engine(fail={"audit::read", "ladder::list"})
        answer = improve.start(engine, self.root, [job(revisions=1)], "/tmp/repo")
        self.assertIn("run", answer)


class Completing(Scratch):
    def start(self, engine=None):
        engine = engine or Engine()
        return improve.start(engine, self.root,
                             [job(revisions=1)], "/tmp/repo")["run"]

    def test_a_traceable_proposal_is_staged(self):
        run_id = self.start()
        run = improve.completed(self.root, run_id, {"ok": True, "text": ANSWER})
        self.assertEqual(len(run["proposals"]), 1)
        self.assertEqual(run["proposals"][0]["target"], "CLAUDE.md")

    def test_one_with_no_evidence_is_dropped_and_the_reason_kept(self):
        run_id = self.start()
        run = improve.completed(self.root, run_id, {"ok": True, "text": ANSWER})
        self.assertTrue(any("A proposal from nowhere" in p for p in run["problems"]))

    def test_a_failed_turn_is_a_failed_run_rather_than_an_empty_one(self):
        # Zero proposals from a failed turn and zero from a clean week look the
        # same on a list, and only one of them means nothing went wrong.
        run_id = self.start()
        run = improve.completed(self.root, run_id, {"ok": False, "error": "timeout"})
        self.assertEqual(run["state"], "failed")
        self.assertIn("timeout", run["problems"][0])

    def test_a_completion_for_a_run_that_does_not_exist_is_dropped(self):
        self.assertEqual(improve.completed(self.root, "nope", {"ok": True}), {})

    def test_the_lane_distribution_is_recorded(self):
        run_id = self.start()
        run = improve.completed(self.root, run_id, {"ok": True, "text": ANSWER})
        self.assertEqual(run["distribution"]["charter"], 1)


class Accepting(Scratch):
    def staged(self, text=ANSWER):
        engine = Engine()
        run_id = improve.start(engine, self.root, [job(revisions=1)], "/tmp/repo")["run"]
        improve.completed(self.root, run_id, {"ok": True, "text": text})
        return engine, run_id

    def test_accepting_writes_a_spec_and_nothing_else(self):
        engine, run_id = self.staged()
        before = list(engine.sent)
        answer = improve.accept(engine, self.root, run_id, 0)

        self.assertTrue(Path(answer["spec"]).is_file())
        self.assertIn("Nothing was applied", Path(answer["spec"]).read_text())
        # The whole invariant: accepting called nothing on the bus.
        self.assertEqual(engine.sent, before)

    def test_the_spec_lands_in_specs_beside_every_other(self):
        engine, run_id = self.staged()
        answer = improve.accept(engine, self.root, run_id, 0)
        self.assertEqual(Path(answer["spec"]).parent, self.root / "specs")

    def test_it_says_what_to_do_with_the_spec(self):
        engine, run_id = self.staged()
        self.assertIn("make submit", improve.accept(engine, self.root, run_id, 0)["note"])

    def test_accepting_twice_does_not_write_a_second_spec(self):
        engine, run_id = self.staged()
        first = improve.accept(engine, self.root, run_id, 0)
        again = improve.accept(engine, self.root, run_id, 0)
        self.assertEqual(again["already"], "spec")
        self.assertEqual(len(list((self.root / "specs").glob("*.md"))), 1)
        self.assertEqual(again["spec"], first["spec"])

    def test_two_proposals_with_one_title_do_not_overwrite_each_other(self):
        engine, run_id = self.staged(ANSWER + ANSWER.split("## A proposal")[0])
        improve.accept(engine, self.root, run_id, 0)
        improve.accept(engine, self.root, run_id, 1)
        self.assertEqual(len(list((self.root / "specs").glob("*.md"))), 2)

    def test_a_proposal_index_nobody_staged_is_refused_by_name(self):
        engine, run_id = self.staged()
        self.assertIn("no proposal 7", improve.accept(engine, self.root, run_id, 7)["error"])

    def test_an_unknown_run_is_refused(self):
        self.assertIn("no improve run", improve.accept(None, self.root, "nope", 0)["error"])


class Moving(Scratch):
    """The one exception, and the reason it is allowed: a promotion is one
    number in a file, and the ladder commits nothing."""

    PROMOTION = """
## Carry the secrets rule at rung 3

- lane: charter
- kind: rule
- action: promote
- target: no-secrets
- rung: 3
- evidence: job aaaa, refusal
- why: it refused eleven calls at rung 3 and the prose never stopped one

Prose is not stopping it.
"""

    def staged(self):
        engine = Engine(rules=[rule("no-secrets")])
        run_id = improve.start(engine, self.root, [job(revisions=1)], "/tmp/repo")["run"]
        improve.completed(self.root, run_id, {"ok": True, "text": self.PROMOTION})
        return engine, run_id

    CARRY = PROMOTION.replace("action: promote", "action: carry") \
                     .replace("- rung: 3", "- rung: delivery")

    def test_a_promotion_asks_the_ladder_rather_than_editing_a_file(self):
        engine, run_id = self.staged()
        improve.accept(engine, self.root, run_id, 0)
        called = dict(engine.sent)
        self.assertIn("ladder::move", called)
        self.assertEqual(called["ladder::move"]["id"], "no-secrets")
        self.assertEqual(called["ladder::move"]["move"], "promote")

    def test_a_promotion_names_the_rung_it_replaces(self):
        engine, run_id = self.staged()
        improve.accept(engine, self.root, run_id, 0)
        self.assertEqual(dict(engine.sent)["ladder::move"]["to"], "3")

    def test_a_carry_names_the_rung_it_adds_instead(self):
        """`carry` takes `at`, and `promote` takes `to`.

        Sending the wrong one is not an error at either end: ladder plans the
        move with no rung named and reports a success for a different move than
        the one proposed, which is the shape this whole model is against.
        """
        engine = Engine(rules=[rule("no-secrets")])
        run_id = improve.start(engine, self.root, [job(revisions=1)], "/tmp/repo")["run"]
        improve.completed(self.root, run_id, {"ok": True, "text": self.CARRY})
        improve.accept(engine, self.root, run_id, 0)
        sent = dict(engine.sent)["ladder::move"]
        self.assertEqual(sent["move"], "carry")
        self.assertEqual(sent["at"], "delivery")
        self.assertNotIn("to", sent)

    def test_it_writes_no_spec(self):
        engine, run_id = self.staged()
        answer = improve.accept(engine, self.root, run_id, 0)
        self.assertNotIn("spec", answer)
        self.assertFalse((self.root / "specs").exists())

    def test_it_says_the_change_still_reaches_a_person(self):
        engine, run_id = self.staged()
        self.assertIn("committed nothing",
                      improve.accept(engine, self.root, run_id, 0)["note"])

    def test_a_ladder_that_is_down_does_not_mark_it_accepted(self):
        engine, run_id = self.staged()
        engine.fail.add("ladder::move")
        improve.accept(engine, self.root, run_id, 0)
        run = improve.read(self.root, run_id)
        self.assertEqual(run["proposals"][0]["accepted"], "")


class TheStore(Scratch):
    def test_runs_come_back_newest_first(self):
        for started in (10, 30, 20):
            improve.save(self.root, {"id": f"r{started}", "started": started})
        self.assertEqual([r["id"] for r in improve.runs(self.root)],
                         ["r30", "r20", "r10"])

    def test_no_runs_at_all_is_an_empty_list(self):
        self.assertEqual(improve.runs(self.root), [])

    def test_a_half_written_file_does_not_break_the_listing(self):
        improve.save(self.root, {"id": "good", "started": 1})
        (improve.folder(self.root) / "bad.json").write_text("{ truncated")
        self.assertEqual([r["id"] for r in improve.runs(self.root)], ["good"])

    def test_a_run_is_written_whole_or_not_at_all(self):
        improve.save(self.root, {"id": "r", "started": 1, "proposals": []})
        self.assertEqual(json.loads(improve.run_path(self.root, "r").read_text())["id"], "r")
        self.assertEqual(list(improve.folder(self.root).glob("*.tmp")), [])


class TheRoundTrip(Scratch):
    def test_a_staged_proposal_reads_back_as_the_same_proposal(self):
        found, _ = proposals.parse(ANSWER)
        again = improve.as_proposal(improve.as_record(found[0]))
        self.assertEqual(again, found[0])


if __name__ == "__main__":
    unittest.main()
