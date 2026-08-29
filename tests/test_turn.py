"""The seam between a phase and a turn, tested without an engine.

`payload_for` exists as a separate function from `send` precisely so this file
can assert what a phase sends. Every rung-1 grant is one key of that dict, and a
test that cannot see the dict cannot check the grant.
"""

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "workers" / "ghola-core" / "src"))

import defaults  # noqa: E402
import turn  # noqa: E402


class SessionNames(unittest.TestCase):
    def test_a_session_carries_the_job_and_the_phase(self):
        self.assertEqual(turn.session_for("abc123", "plan"), "s_abc123_plan")

    def test_a_dashed_id_does_not_survive_and_that_is_why_ids_are_hex(self):
        # A session name strips everything that is not hex, so a dashed uuid
        # cannot come back out of one. `jobs.new_id` mints `uuid4().hex` for
        # exactly this reason: the session name and the record's filename have
        # to be the same string.
        dashed = "4d7541a2-beba-4a05-ad6a-2b9be4894e6d"
        recovered, phase = turn.phase_of({"session_id": turn.session_for(dashed, "run")})
        self.assertEqual(phase, "run")
        self.assertNotEqual(recovered, dashed)
        self.assertEqual(recovered, dashed.replace("-", ""))

    def test_a_session_from_another_project_is_not_claimed(self):
        # A hook of ours is asked about every turn on this engine. Guessing which
        # of our jobs an unparseable session belongs to is worse than dropping it.
        self.assertEqual(turn.phase_of({"session_id": "sess_1"}), ("", ""))
        self.assertEqual(turn.phase_of({}), ("", ""))

    def test_a_job_id_with_no_hex_still_produces_a_valid_session(self):
        self.assertEqual(turn.session_for("", "plan"), "s_anon_plan")


class WhatAPhaseSends(unittest.TestCase):
    def setUp(self):
        self.payload = turn.payload_for(
            "review", "look at this", job_id="abc", workspace="/tmp/w",
            config=defaults.config())

    def test_the_grant_travels_as_options_functions(self):
        allowed = self.payload["options"]["functions"]["allow"]
        self.assertIn("coder::read-file", allowed)
        self.assertNotIn("coder::update-file", allowed)

    def test_metadata_carries_what_a_callback_needs(self):
        # The policy worker holds no session state, so this dict is the only
        # thing telling a callback which piece of work it is inside.
        metadata = self.payload["options"]["metadata"]
        self.assertEqual(metadata["job_id"], "abc")
        self.assertEqual(metadata["phase"], "review")
        self.assertEqual(metadata["workspace"], "/tmp/w")
        self.assertEqual(metadata["session_id"], self.payload["session_id"])

    def test_the_message_is_a_user_content_block(self):
        message = self.payload["message"]
        self.assertEqual(message["role"], "user")
        self.assertEqual(message["content"][0]["text"], "look at this")

    def test_the_model_is_top_level_not_an_option(self):
        self.assertEqual(self.payload["model"], "claude-sonnet-5")
        self.assertNotIn("model", self.payload["options"])


class ReadingACompletion(unittest.TestCase):
    def test_a_completed_turn_is_ok_with_its_text(self):
        _job, phase, result = turn.outcome({
            "session_id": "s_abc_plan", "status": "completed",
            "result": "the plan", "session_cost_usd": 0.0071})
        self.assertEqual(phase, "plan")
        self.assertTrue(result["ok"])
        self.assertEqual(result["text"], "the plan")
        self.assertAlmostEqual(result["cost_usd"], 0.0071)

    def test_a_failed_turn_carries_its_reason(self):
        _job, _phase, result = turn.outcome({
            "session_id": "s_abc_run", "status": "failed",
            "result_error": "router::provider::resolve"})
        self.assertFalse(result["ok"])
        self.assertIn("router::provider::resolve", result["error"])

    def test_a_cancelled_turn_is_not_ok(self):
        _job, _phase, result = turn.outcome({
            "session_id": "s_abc_run", "status": "cancelled", "reason": "stopped"})
        self.assertFalse(result["ok"])

    def test_an_unpriced_model_reports_zero_rather_than_raising(self):
        # The router's catalogue prices claude-opus-5 and claude-sonnet-5 at
        # null today, so this is the live case rather than an edge one.
        _job, _phase, result = turn.outcome({
            "session_id": "s_abc_plan", "status": "completed", "result": "x"})
        self.assertEqual(result["cost_usd"], 0.0)

    def test_a_foreign_session_returns_nothing_to_act_on(self):
        self.assertEqual(turn.outcome({"session_id": "whatever"}), ("", "", {}))




class TheFilesystemScope(unittest.TestCase):
    """Without this a turn reads the target repo and edits ghola's own files.

    The first real job caught it: the plan turn refused to touch anything
    because the repository it could see was not the one its instructions
    described. It was right, and it was the harness defaulting the scope to the
    engine's working directory.
    """

    def test_the_workspace_becomes_the_filesystem_root(self):
        payload = turn.payload_for("run", "go", workspace="/repo/worktree",
                                   config=defaults.config())
        self.assertEqual(
            payload["options"]["metadata"]["fs_scope"]["root"], "/repo/worktree")

    def test_it_travels_as_an_option_too(self):
        payload = turn.payload_for("run", "go", workspace="/repo/worktree",
                                   config=defaults.config())
        self.assertEqual(payload["options"]["fs_scope"]["root"], "/repo/worktree")

    def test_no_workspace_sets_no_scope_rather_than_an_empty_one(self):
        # An empty root would be worse than none: it reads as "everywhere".
        payload = turn.payload_for("plan", "go", config=defaults.config())
        self.assertNotIn("fs_scope", payload["options"]["metadata"])



class TheSessionNameAndTheRecordMustAgree(unittest.TestCase):
    """The bug this file exists to prevent recurring.

    `as_id` used to re-insert UUID dashes on a 32-character id. Every completion
    for a real job then looked up an id no file was named after, found nothing,
    and returned quietly: the turn finished, the job never advanced, and nothing
    said why.
    """

    def test_a_hex_job_id_round_trips_unchanged(self):
        import uuid
        job_id = uuid.uuid4().hex
        session = turn.session_for(job_id, "plan")
        self.assertEqual(turn.phase_of({"session_id": session}), (job_id, "plan"))

    def test_the_round_trip_matches_what_the_store_names_a_file(self):
        import jobs
        job_id = jobs.new_id()
        recovered, _phase = turn.phase_of({"session_id": turn.session_for(job_id, "run")})
        self.assertEqual(recovered, job_id)
        # And the store can actually build a path from it.
        self.assertTrue(str(jobs.Store("/tmp").path(recovered)).endswith(f"{job_id}.json"))

if __name__ == "__main__":
    unittest.main()
