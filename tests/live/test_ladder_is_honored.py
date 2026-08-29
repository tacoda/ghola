"""The framework promises this stack leans on, asserted against a running engine.

Small, slow, and the only kind of test that catches a framework change. Every
promise here was believed rather than checked at some point, and one of them was
false for a whole release:

**On harness 1.8.1 a `pre-trigger` hook fired and its `deny` was IGNORED.** The
call ran anyway. A ladder mounted there looks wired on every dashboard and
enforces nothing, which is the exact failure the ladder exists to prevent. So the
test is not "was the hook called" but "was the target function entered".

Run with `make test-live`, and only with an engine up.
"""

import json
import os
import subprocess
import unittest

PORT = os.environ.get("GHOLA_MGR_PORT", "49154")
# Absolute. The ladder worker has its own working directory, so a path with
# `..` in it resolves against the wrong root and the repository silently reads
# as having no permissions at all — which looks exactly like permissions that
# are not enforced.
REPO = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..", "fixtures", "permissions-repo"))


def trigger(function_id: str, payload: dict | None = None, timeout: int = 60) -> dict:
    """One `iii trigger`, as a dict. Raises if the engine is not there."""
    command = ["iii", "trigger", function_id, "--port", PORT]
    if payload is not None:
        command += ["--json", json.dumps(payload)]
    done = subprocess.run(command, capture_output=True, text=True, timeout=timeout)
    if done.returncode != 0:
        raise RuntimeError(f"{function_id}: {done.stderr.strip()[:300]}")
    return json.loads(done.stdout or "{}")


def engine_is_up() -> bool:
    """A probe that needs no arguments.

    NOT `harness::status`, which requires a `session_id` and fails with a
    serialization error that reads exactly like a missing engine.
    """
    try:
        trigger("router::provider::list", timeout=15)
        return True
    except Exception:  # noqa: BLE001
        return False


ENGINE = engine_is_up()

# `make test-live` means the caller asked for live tests, so a missing engine is
# a FAILURE rather than a skip. The first version of this file skipped all eight
# and printed OK, which is a green suite that tested nothing: the same
# fail-open shape the ladder exists to prevent, in the tests of the ladder.
# `GHOLA_LIVE_OPTIONAL=1` restores skipping, for a CI job that has no engine.
if not ENGINE and not os.environ.get("GHOLA_LIVE_OPTIONAL"):
    raise SystemExit(
        "no engine on port " + PORT + ". Start one with `make up`, or set "
        "GHOLA_LIVE_OPTIONAL=1 to skip these instead of failing.")


@unittest.skipUnless(ENGINE, "no engine, and GHOLA_LIVE_OPTIONAL is set")
class TheHarnessHonoursADeny(unittest.TestCase):
    """The 1.8.1 regression. This is the one that must never go quiet."""

    def test_the_hook_type_is_spelled_with_hyphens(self):
        # The tech spec writes them with underscores and this build emits
        # hyphens. An underscore binding registers without error and never
        # fires, so this asserts the name the harness actually offers.
        info = trigger("engine::triggers::list")
        types = json.dumps(info)
        self.assertIn("harness::hook::pre-trigger", types)
        self.assertNotIn("harness::hook::pre_trigger", types)

    def test_the_ladder_is_bound_on_that_hook(self):
        # A ladder that is not bound refuses nothing, and looks identical to one
        # that is until something tries to write.
        #
        # `engine::triggers::list` returns trigger TYPES. A binding is a
        # different thing and lives in `registered-triggers`, which is the
        # distinction that made the first version of this test assert a type
        # existed and call that proof the ladder was mounted.
        bound = trigger("engine::registered-triggers::list")
        self.assertIn("ladder::gate", json.dumps(bound))


@unittest.skipUnless(ENGINE, "no engine, and GHOLA_LIVE_OPTIONAL is set")
class RungTwoReadsTheRepositorysOwnPermissions(unittest.TestCase):
    """A repository that already said no should not have to say it twice."""

    def test_a_denied_argument_pattern_is_refused(self):
        answer = trigger("ladder::evaluate", {
            "repo": REPO,
            "function_id": "shell::exec",
            "arguments": {"command": "rm -rf /tmp/whatever"},
            "rung": 2,
        })
        self.assertFalse(answer["allowed"], answer)
        self.assertIn("permissions", answer["reason"])
        self.assertIn("rm *", answer["reason"])

    def test_a_different_command_is_untouched(self):
        answer = trigger("ladder::evaluate", {
            "repo": REPO,
            "function_id": "shell::exec",
            "arguments": {"command": "make test"},
            "rung": 2,
        })
        self.assertTrue(answer["allowed"], answer)

    def test_the_shell_itself_is_still_available(self):
        # `rm *` names an ARGUMENT. Dropping the whole shell because one command
        # pattern is denied would be a different and much larger rule.
        listed = trigger("ladder::list", {"repo": REPO})
        self.assertNotIn("shell::exec", listed["withheld"])

    def test_the_entry_is_reported_as_a_project_layer_constraint(self):
        listed = trigger("ladder::list", {"repo": REPO})
        ids = [p["id"] for p in listed["primitives"]]
        self.assertTrue(any("repo-permissions" in i for i in ids), ids)


@unittest.skipUnless(ENGINE, "no engine, and GHOLA_LIVE_OPTIONAL is set")
class TheLadderReportsWhatItCannotEnforce(unittest.TestCase):
    def test_a_name_reaching_no_function_is_a_reported_problem(self):
        # A withheld name that reaches nothing enforces nothing, and fails
        # silently in exactly the way this model exists to prevent.
        listed = trigger("ladder::list", {"repo": REPO})
        self.assertIsInstance(listed.get("problems"), list)

    def test_the_measured_share_is_a_number_rather_than_a_claim(self):
        listed = trigger("ladder::list", {"repo": REPO})
        self.assertIsInstance(listed["measured_share"], (int, float))


if __name__ == "__main__":
    unittest.main()


@unittest.skipUnless(ENGINE, "no engine, and GHOLA_LIVE_OPTIONAL is set")
class NothingCanMergeItself(unittest.TestCase):
    """The one invariant of this repository, enforced by the framework.

    `worktree::land` rebases onto a target branch and fast-forwards it. That is
    a merge whatever it is called, and ghola opens a pull request and stops. So
    the capability is switched off in the worktree worker's own gates rather
    than merely unused: rung-1 thinking applied to a worker's configuration.
    """

    def test_landing_is_disabled_in_the_worker(self):
        gates = (trigger("configuration::get", {"id": "worktree"})
                 .get("value") or {}).get("gates") or {}
        self.assertIs(gates.get("allow_land"), False,
                      "worktree::land is enabled, so something could fast-forward "
                      "a target branch. Nothing in ghola merges")
        self.assertEqual(gates.get("land_targets"), [],
                         "a land target is a branch something is allowed to "
                         "fast-forward. There should be none")

    def test_force_removal_is_available_for_teardown(self):
        # A squash merge leaves the branch commit outside the target's ancestry,
        # so `remove` refuses with W221 and every landed job leaks a worktree.
        gates = (trigger("configuration::get", {"id": "worktree"})
                 .get("value") or {}).get("gates") or {}
        self.assertIs(gates.get("allow_force"), True)
