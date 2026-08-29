"""The job store has to survive the worker that holds it.

This is M4's gate, and it exists because the repository ghola is rebuilt from
lost a live job here: it used the `state` worker, the worker restarted mid-run,
and the job went with it. That repository concluded the worker was the wrong
store and moved to files.

**That conclusion was wrong, and this test is the correction.** The worker
persists fine. Its `store_method` DEFAULTS to `in_memory`, which the worker's own
schema describes as "volatile, process-lifetime storage, lost on shutdown — not
for production". The scar was a configuration default, not a defect.

Which is a worse failure than a broken worker, because nothing announces it. A
factory storing jobs in a default in-memory adapter works perfectly until the
first restart, and the first restart is usually the one during a long job.

So the check is not "does the store work" but "is it configured to survive",
and it runs against the real engine because that is the only place the answer
is real.
"""

import json
import os
import subprocess
import time
import unittest

PORT = os.environ.get("GHOLA_MGR_PORT", "49154")
SCOPE = "ghola.test.durability"


def trigger(function_id: str, payload: dict | None = None, timeout: int = 60) -> dict:
    command = ["iii", "trigger", function_id, "--port", PORT]
    if payload is not None:
        command += ["--json", json.dumps(payload)]
    done = subprocess.run(command, capture_output=True, text=True, timeout=timeout)
    if done.returncode != 0:
        raise RuntimeError(f"{function_id}: {done.stderr.strip()[:300]}")
    return json.loads(done.stdout or "{}")


def engine_is_up() -> bool:
    try:
        trigger("router::provider::list", timeout=15)
        return True
    except Exception:  # noqa: BLE001
        return False


ENGINE = engine_is_up()

if not ENGINE and not os.environ.get("GHOLA_LIVE_OPTIONAL"):
    raise SystemExit(
        f"no engine on port {PORT}. Start one with `make up`, or set "
        "GHOLA_LIVE_OPTIONAL=1 to skip these instead of failing.")


@unittest.skipUnless(ENGINE, "no engine, and GHOLA_LIVE_OPTIONAL is set")
class TheStoreIsConfiguredToSurvive(unittest.TestCase):
    """The cheap check, and the one that would have caught wipp's loss."""

    def test_the_adapter_is_not_the_volatile_default(self):
        config = trigger("configuration::get", {"id": "state"}).get("value") or {}
        method = ((config.get("adapter") or {}).get("config") or {}).get("store_method")
        self.assertEqual(
            method, "file_based",
            "the state worker is on its in_memory default, which the worker's own "
            "schema calls 'not for production'. Every job record is lost on the "
            "next restart, and nothing will say so until it happens")

    def test_a_flush_cadence_is_set(self):
        config = trigger("configuration::get", {"id": "state"}).get("value") or {}
        cadence = ((config.get("adapter") or {}).get("config") or {}).get("save_interval_ms")
        self.assertIsNotNone(cadence, "no flush cadence: the window in which a "
                                      "crash loses a record is undefined")
        self.assertLessEqual(int(cadence), 5000)


@unittest.skipUnless(ENGINE, "no engine, and GHOLA_LIVE_OPTIONAL is set")
class TheStoreActuallySurvives(unittest.TestCase):
    """The expensive check. Restarts a worker, so it is slow on purpose."""

    KEY = "survives-a-restart"

    def tearDown(self):
        try:
            trigger("state::delete", {"scope": SCOPE, "key": self.KEY})
        except Exception:  # noqa: BLE001
            pass

    def test_a_record_written_before_a_restart_is_readable_after_it(self):
        trigger("state::set", {"scope": SCOPE, "key": self.KEY,
                               "value": {"stage": "run", "written": "before"}})
        # Longer than the flush cadence, or this measures the buffer rather than
        # the store.
        time.sleep(2)

        subprocess.run(["iii", "worker", "restart", "state"],
                       capture_output=True, text=True, timeout=180)
        for _ in range(30):
            try:
                found = trigger("state::get", {"scope": SCOPE, "key": self.KEY})
                if found:
                    break
            except Exception:  # noqa: BLE001
                pass
            time.sleep(1)

        self.assertEqual(found.get("stage"), "run",
                         "the job record did not survive a restart of the worker "
                         "holding it. This is the failure that made wipp move to "
                         "files; if it is back, do the same and say why")


if __name__ == "__main__":
    unittest.main()
