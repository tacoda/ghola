"""The factory: a spec goes in, a pull request comes out, nothing merges itself.

**It serves no HTTP.** The console is the UI: invoke `ghola::submit` from it,
watch the turn waterfall, read the queue. A bespoke dashboard would be a second
UI to maintain and a worse trace view than the one already there.

What this worker actually does is small, because everything else is a stock
worker:

- reads the stage graph and walks a job through it (`ghola-core/graph.py`)
- keeps the job record as a file (`ghola-core/jobs.py`)
- starts turns with `harness::send` and hears about them on `turn-completed`
- calls `worktree::*` and `github::*` for anything touching git or the forge

Every stage transition is a durable queue message, so a crash between stages
resumes rather than restarts, and every stage guards on the job's own recorded
stage, so at-least-once delivery does the work once.
"""

from __future__ import annotations

import os
import sys
import threading
from pathlib import Path

from iii import InitOptions, register_worker

import actions as builtin_actions

ROOT = Path(os.environ.get("GHOLA_ROOT", Path(__file__).resolve().parents[3]))
sys.path.insert(0, str(ROOT / "workers" / "ghola-core" / "src"))

import audit_log  # noqa: E402
import contracts as contractslib  # noqa: E402
import defaults  # noqa: E402
import extensions  # noqa: E402
import graph as graphlib  # noqa: E402
import jobs as jobslib  # noqa: E402
import oversight as oversightlib  # noqa: E402
import paths  # noqa: E402
import repos as reposlib  # noqa: E402
import turn as turnlib  # noqa: E402
import yaml  # noqa: E402

NAME = "ghola"
QUEUE = "ghola.stage"

WORKER = None
STORE = jobslib.Store(ROOT / "state" / "jobs")
AUDIT = audit_log.AuditLog(os.environ.get("GHOLA_AUDIT_DIR") or ROOT / "audit")


def record(kind: str, **fields) -> None:
    """Append to the audit log. Never raises, never silent."""
    try:
        AUDIT.append(kind, **fields)
    except Exception as exc:  # noqa: BLE001
        print(f"AUDIT WRITE FAILED ({kind}): {type(exc).__name__}: {exc}")


def read_yaml(name: str) -> dict:
    try:
        return yaml.safe_load(paths.settings(name).read_text()) or {}
    except (OSError, yaml.YAMLError):
        return {}


def pipeline() -> graphlib.Graph:
    """The stage graph, read fresh so editing it changes the next job."""
    return graphlib.parse(read_yaml("pipeline.yaml") or defaults.pipeline())


def oversight_for(stage: graphlib.Stage) -> oversightlib.Oversight:
    """How much a person watches this stage.

    A stage may name its own, because `run` and `review` want different answers:
    a review reads and reports, and holding its calls buys nothing.
    """
    if stage.oversight:
        return oversightlib.resolve(stage.oversight)
    return oversightlib.for_stage(read_yaml("oversight.yaml"), stage.name)


# ------------------------------------------------------------- the surface

def fn_submit(payload: dict) -> dict:
    """A spec, and the repository to do it in. Returns the job.

    The repository's settings are resolved here and **copied onto the record**,
    so a rework months later rebuilds the environment the job was born in.
    """
    data = payload.get("payload") or payload
    spec = str(data.get("spec") or "").strip()
    repo_path = str(data.get("repo") or "").strip()

    if not spec:
        return {"error": "no spec. Pass `spec` as text or a path under specs/"}
    if not repo_path:
        return {"error": "no repo. Pass `repo` as an absolute path"}

    spec_file = Path(spec)
    if spec_file.is_file():
        spec = spec_file.read_text()

    graph = pipeline()
    if graph.problems:
        return {"error": "the pipeline is not runnable", "problems": graph.problems}

    settings = reposlib.resolve(repo_path)
    job = STORE.create(
        spec=spec, repo=str(Path(repo_path).expanduser()), stage=graph.first,
        repo_slug=str(data.get("repo_slug") or ""),
        title=str(data.get("title") or spec.splitlines()[0][:70] if spec else ""),
        **settings.as_job_fields())

    record("stage.entered", actor="ghola::submit", subject=job["id"],
           stage=graph.first, repo=job["repo"])
    enqueue(job["id"], graph.first)
    return {"job": jobslib.summary(job)}


def fn_jobs(payload: dict) -> dict:
    """Every job, newest first. The console's list view."""
    data = payload.get("payload") or payload
    found = STORE.list()
    if data.get("stage"):
        found = [j for j in found if j.get("stage") == data["stage"]]
    return {"jobs": [jobslib.summary(j) for j in found]}


def fn_job(payload: dict) -> dict:
    """One job, whole, including where it has been."""
    data = payload.get("payload") or payload
    job = STORE.read(str(data.get("id") or ""))
    return job or {"error": f"no job {data.get('id')!r}"}


def fn_pipeline(payload: dict) -> dict:
    """The stage graph as it will actually run, with anything wrong with it.

    Read before submitting rather than discovered two stages in: a stage whose
    action cannot be found should fail when the pipeline is read, not after a
    job has already paid for a worktree and a plan.
    """
    graph = pipeline()
    named = {"actions": "", "guards": ""}
    problems = list(graph.problems)
    for stage in graph.stages.values():
        if stage.action and stage.action not in builtin_actions.BUILT_IN:
            problems.extend(extensions.check({"actions": stage.action}, ROOT))
        if stage.guard:
            problems.extend(extensions.check({"guards": stage.guard}, ROOT))

    return {
        "first": graph.first,
        "states": list(graph.states),
        "phases": list(graph.phases()),
        "stages": {name: {
            "phase": s.phase, "action": s.action, "next": s.next,
            "optional": s.optional, "skip_when": list(s.skip_when),
            "oversight": oversight_for(s).level,
            "outcomes": dict(s.outcomes),
        } for name, s in graph.stages.items()},
        "problems": problems,
        "runnable": not problems,
    }


# ------------------------------------------------------------- the dispatch

def enqueue(job_id: str, stage: str) -> None:
    """One durable message per transition, so a crash resumes rather than restarts."""
    if WORKER is None:
        return
    WORKER.trigger({"function_id": "queue::enqueue", "timeout_ms": 15000, "payload": {
        "topic": QUEUE, "message": {"job_id": job_id, "stage": stage}}})


def fn_step(payload: dict) -> dict:
    """Run one stage of one job. Bound to the queue.

    **Guarded on the job's own recorded stage.** At-least-once delivery means
    this can be handed the same message twice, and the guard is what makes the
    second one a no-op rather than a second worktree, a second turn, and a
    second pull request.
    """
    data = payload.get("payload") or payload
    job = STORE.read(str(data.get("job_id") or ""))
    if job is None:
        return {"skipped": "no such job"}

    wanted = str(data.get("stage") or "")
    if wanted and job.get("stage") != wanted:
        # The work already happened. This is the duplicate.
        return {"skipped": f"job is at `{job.get('stage')}`, not `{wanted}`"}

    graph = pipeline()
    stage = graph.get(str(job.get("stage") or ""))
    if stage is None:
        return advance(job, graph, {"ok": False, "error": "no such stage"})

    if stage.runs_a_turn:
        return start_turn(job, stage)
    return run_action(job, graph, stage)


def contract_for(stage: graphlib.Stage) -> dict:
    """The output contract this stage's answer is held to, if it has one."""
    if not stage.contract:
        return {}
    return contractslib.contract(stage.contract, read_yaml(f"contracts/{stage.contract}.yaml"))


def run_action(job: dict, graph: graphlib.Graph, stage: graphlib.Stage) -> dict:
    """A stage that does something rather than asking a model to."""
    handler = builtin_actions.BUILT_IN.get(stage.action)
    if handler is None:
        try:
            handler, function_id = extensions.resolve(stage.action, ROOT, "actions")
            if function_id:
                answer = builtin_actions.call(WORKER, function_id,
                                              {"job": job, "stage": stage.name})
                return advance(job, graph, answer.get("value") or answer)
        except extensions.ExtensionError as exc:
            return advance(job, graph, {"ok": False, "error": str(exc)})

    result = handler(WORKER, job, job)
    # An action may have learned something the record needs: a worktree id, a
    # pull request number. It mutates the job it was handed, so the write below
    # keeps it.
    STORE.write(job)
    return advance(job, graph, result)


def start_turn(job: dict, stage: graphlib.Stage) -> dict:
    """Send the phase and stop. The completion arrives as an event.

    The oversight level for this stage is applied to the session before the turn
    runs, because a mode set afterwards is a mode that did not apply to the
    calls already made.
    """
    watching = oversight_for(stage)
    session_id = turnlib.session_for(job["id"], stage.phase)

    try:
        WORKER.trigger({"function_id": "approval::set-mode", "timeout_ms": 15000,
                        "payload": {"session_id": session_id,
                                    "mode": watching.approval_mode}})
    except Exception as exc:  # noqa: BLE001
        # Not fatal: the deployment default still applies. But an operator who
        # asked for `manual` and silently got `full` would have no way to know.
        print(f"oversight: could not set {watching.approval_mode} on {session_id}: {exc}")

    record("stage.entered", actor=f"phase:{stage.phase}", subject=job["id"],
           stage=stage.name, oversight=watching.level)

    turnlib.send(WORKER, stage.phase, brief_for(job, stage),
                 job_id=job["id"], workspace=str(job.get("workspace") or job["repo"]))
    return {"started": session_id, "stage": stage.name}


def brief_for(job: dict, stage: graphlib.Stage) -> str:
    """What this phase is asked to do.

    A refusal or a reviewer's comment is already a brief and replaces the spec
    rather than being appended to it: re-stating the original alongside a
    specific complaint is how a turn ends up solving the wrong one.
    """
    if job.get("brief"):
        return str(job["brief"])
    spec = str(job.get("spec") or "")
    plan = str(job.get("plan") or "")
    return f"{spec}\n\n## The plan\n\n{plan}" if plan else spec


def advance(job: dict, graph: graphlib.Graph, result: dict) -> dict:
    """Apply the transition the graph decided, and enqueue the next step."""
    move = graphlib.next_stage(job, graph, result)
    moved = jobslib.advance(job, move.to, move.why, revision=move.revision,
                            **{k: v for k, v in result.items()
                               if k in ("workspace", "worktree_id", "pull_request",
                                        "brief", "plan", "last_refusal")})
    STORE.write(moved)

    record("stage.left", actor="ghola::step", subject=job["id"],
           **{"from": job.get("stage"), "to": move.to, "why": move.why})

    if move.to in graph.terminal or move.to == graphlib.BLOCKED:
        return {"job": job["id"], "stage": move.to, "why": move.why}
    enqueue(job["id"], move.to)
    return {"job": job["id"], "stage": move.to, "why": move.why}


def fn_turn_completed(payload: dict) -> dict:
    """A phase finished. Turn it into a transition."""
    event = payload.get("payload") or payload
    job_id, phase, result = turnlib.outcome(event)
    if not job_id:
        return {}                       # somebody else's turn on this engine

    job = STORE.read(job_id)
    if job is None:
        return {}

    record("turn.completed", actor=f"phase:{phase}", subject=job_id,
           ok=result["ok"], cost_usd=result["cost_usd"])

    graph = pipeline()
    stage = graph.get(str(job.get("stage") or ""))
    return advance(job, graph, interpret(result, phase, contract_for(stage) if stage else {}))


def interpret(result: dict, phase: str, contract: dict | None = None) -> dict:
    """What a turn's text means for the pipeline.

    Order matters. A turn that stopped to ask a question has not produced an
    answer to grade, so the interrupt is read first and the contract never sees
    a half-finished turn.
    """
    text = str(result.get("text") or "")

    question = contractslib.interrupt(text)
    if question:
        return {"blocked": True, "question": question}

    if contract:
        answer = contractslib.read(text, contract)
        return {**result, **contractslib.as_result(answer, phase), "text": text}

    if phase == "plan" and result.get("ok"):
        return {**result, "plan": text}
    return result


def main() -> None:
    global WORKER
    url = os.environ.get("III_URL", "ws://localhost:49154")
    WORKER = register_worker(url, InitOptions(worker_name="ghola-factory"))

    for function_id, handler, description in (
        (f"{NAME}::submit", fn_submit, "A spec and a repo. Returns the job."),
        (f"{NAME}::jobs", fn_jobs, "Every job, newest first."),
        (f"{NAME}::job", fn_job, "One job, whole, including where it has been."),
        (f"{NAME}::pipeline", fn_pipeline,
         "The stage graph as it will run, and anything wrong with it."),
        (f"{NAME}::step", fn_step, "Internal: run one stage. Bound to the queue."),
        (f"{NAME}::turn-completed", fn_turn_completed, "Internal: a phase finished."),
    ):
        WORKER.register_function(function_id, handler, description=description)

    WORKER.register_trigger({"type": "harness::turn-completed",
                             "function_id": f"{NAME}::turn-completed",
                             "config": {}})

    graph = pipeline()
    print(f"ghola-factory started on {url}")
    print(f"  jobs   : {STORE.folder}")
    print(f"  stages : {' -> '.join(graph.stages) or 'none'}")
    print(f"  audit  : {AUDIT.folder}")
    print("  the console is the UI: invoke ghola::submit from it")
    for problem in graph.problems:
        print(f"  PIPELINE PROBLEM: {problem}")
    threading.Event().wait()


if __name__ == "__main__":
    main()
