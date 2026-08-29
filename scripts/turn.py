"""One turn, without a factory.

The harness and the factory are two products, and a developer usually wants the
first one: what do my settings, and my rules, do to a turn? That needs the engine
and the policy worker, and no factory at all.

    make policy                                  # terminal 2
    make turn PHASE=plan PROMPT="why is this slow?" WORKSPACE=../other-repo

A turn here gets what a job's turn gets: the same `settings/phases.yaml`, so rung
1 withholds the same functions, and the same callbacks, so the ladder refuses the
same calls.

**It edits the workspace as it is.** This is not a worktree, so a `run` phase
writes to the files you are looking at. The factory's worktrees arrive in M4 and
are the `worktree` worker's, not this script's.
"""

import argparse
import os
import queue
import sys
import threading
import time
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "workers" / "ghola-core" / "src"))

from iii import InitOptions, register_worker  # noqa: E402

import phase_settings  # noqa: E402
import turn as turnlib  # noqa: E402

DONE: "queue.Queue[dict]" = queue.Queue()


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--phase", required=True)
    ap.add_argument("--prompt", default="")
    ap.add_argument("--workspace", default="")
    ap.add_argument("--model", default="")
    ap.add_argument("--timeout", type=int, default=900)
    args = ap.parse_args()

    known = phase_settings.phases()
    if args.phase not in known:
        print(f"no phase {args.phase!r}. Known: {', '.join(known)}")
        return 2
    if not args.prompt.strip():
        print("nothing to ask. Pass PROMPT=\"...\"")
        return 2

    workspace = str(Path(args.workspace or ".").resolve())
    settings = phase_settings.for_phase(args.phase)
    allowed = (settings.get("functions") or {}).get("allow") or []
    model = phase_settings.model_for(args.phase, args.model)

    print(f"phase     {args.phase}")
    print(f"model     {model}  thinking={settings.get('thinking_level')} "
          f"max_turns={settings.get('max_turns')}")
    print(f"workspace {workspace}")
    print(f"rung 1    {len(allowed)} function(s) granted")
    print()

    url = os.environ.get("III_URL", "ws://localhost:49154")
    worker = register_worker(url, InitOptions(worker_name=f"ghola-turn-{os.getpid()}"))

    # A fresh session per invocation. `session_for("", phase)` is `s_anon_plan`
    # every time, so two `make turn` runs share one session: the second inherits
    # the first's transcript, and a session left `failed` by a provider outage
    # poisons every later run with an error that has nothing to do with them.
    # The factory does not have this problem, because a job id is unique.
    #
    # The id is threaded into `send` rather than only used here: `send` derives
    # the session from the job id itself, so computing one locally and not
    # passing it would listen on a session nothing sent to.
    job_id = uuid.uuid4().hex
    session_id = turnlib.session_for(job_id, args.phase)

    def on_completed(payload: dict) -> dict:
        event = payload.get("payload") or payload
        if str(event.get("session_id") or "") == session_id:
            DONE.put(event)
        return {}

    worker.register_function("ghola-turn::completed", on_completed)
    # `config: {}` and filter in the handler, rather than
    # `config: {"session_id": …}`. The event config documents a `session_id`
    # filter and this build delivers NOTHING when one is set: the first live
    # turn here failed at the provider and this script waited ten minutes for a
    # completion that had already happened. A binding that silently matches
    # nothing looks exactly like a hung engine, which is the same failure the
    # underscore hook names cause one layer down.
    worker.register_trigger({
        "type": "harness::turn-completed",
        "function_id": "ghola-turn::completed",
        "config": {},
    })
    # The binding is asynchronous. Sending before it lands is how a turn runs to
    # completion and reports nothing, which reads exactly like a hung engine.
    time.sleep(1.5)

    sent = turnlib.send(worker, args.phase, args.prompt, job_id=job_id,
                        workspace=workspace, model=args.model)
    assert sent == session_id, f"listening on {session_id}, sent to {sent}"
    print(f"session   {session_id}")
    print("working…  (the console's turn waterfall is on port 3133)\n")

    try:
        event = DONE.get(timeout=args.timeout)
    except queue.Empty:
        print(f"no completion in {args.timeout}s. The turn may still be running:")
        print(f"  make call FN=harness::status JSON='{{\"session_id\":\"{session_id}\"}}'")
        return 1

    _job, _phase, result = turnlib.outcome({**event, "session_id": session_id})
    print("-" * 72)
    print(result["text"] or "(no text)")
    print("-" * 72)
    status = "completed" if result["ok"] else "FAILED"
    print(f"--- {status}, ${result['cost_usd']:.4f}")
    if result["error"]:
        print(f"--- {result['error']}")

    # The SDK starts a telemetry thread that outlives this function and retries
    # forever, so a script that returns normally never exits and the caller sees
    # a completed turn followed by an endless reconnect log. Nothing here needs
    # a clean shutdown: the result is printed and the engine owns the session.
    sys.stdout.flush()
    os._exit(0 if result["ok"] else 1)


if __name__ == "__main__":
    threading.current_thread().name = "ghola-turn"
    raise SystemExit(main())
