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

import improve as improvelib  # noqa: E402  (needs ghola-core on the path)

import contracts as contractslib  # noqa: E402
import document as doclib  # noqa: E402
import defaults  # noqa: E402
import extensions  # noqa: E402
import graph as graphlib  # noqa: E402
import jobs as jobslib  # noqa: E402
import oversight as oversightlib  # noqa: E402
import paths  # noqa: E402
import prompts as promptslib  # noqa: E402
import repos as reposlib  # noqa: E402
import turn as turnlib  # noqa: E402
import yaml  # noqa: E402

NAME = "ghola"
QUEUE = "ghola.stage"
# Six-field cron: once a minute. A card that waits a minute longer than it had
# to has cost nothing; one that waits forever is the reconciler not existing.
POLL = "0 * * * * *"

WORKER = None
STORE = jobslib.Store(ROOT / "state" / "jobs")


def record(kind: str, actor: str = "", subject: str = "", **detail) -> None:
    """Append to the audit log, through the worker that owns the chain.

    **Not written directly.** A hash chain has exactly one writer or it has
    none: this worker and the policy worker both record, they are separate
    processes, and appending from both produced a log that failed its own
    verification while nothing had tampered with it.
    """
    if WORKER is None:
        print(f"AUDIT NOT RECORDED ({kind}): no engine connection")
        return
    try:
        WORKER.trigger({"function_id": "audit::append", "timeout_ms": 10000,
                        "payload": {"kind": kind, "actor": actor,
                                    "subject": subject, "detail": detail}})
    except Exception as exc:  # noqa: BLE001
        print(f"AUDIT WRITE FAILED ({kind}): {type(exc).__name__}: {exc}")


DOCS = ROOT / "state" / "documents"


def doc_path(job_id: str) -> Path:
    """Where a job's accumulating document lives.

    Beside the job record rather than in the worktree: it outlives the worktree,
    which is torn down when the job ends, and a reviewer asking what happened
    should still be able to read it.
    """
    return DOCS / f"{job_id}.md"


def document_of(job: dict) -> doclib.Document:
    path = doc_path(str(job.get("id") or ""))
    try:
        return doclib.read(path.read_text())
    except OSError:
        # No document yet: start one from the authored spec, which is never
        # rewritten and lives in specs/.
        return doclib.start(str(job.get("spec") or ""), str(job.get("title") or ""))


def write_document(job: dict, doc: doclib.Document) -> None:
    DOCS.mkdir(parents=True, exist_ok=True)
    doc_path(str(job["id"])).write_text(doc.text)


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
    idea = str(data.get("idea") or "").strip()
    repo_path = str(data.get("repo") or "").strip()

    # An IDEA is the rough version somebody typed; a SPEC is something written
    # carefully. Refining a spec somebody wrote would be rewriting their words;
    # building from an idea nobody refined is how the wrong thing gets built
    # confidently. So which one arrived decides whether `refine` runs.
    wants_refine = bool(idea) or bool(data.get("refine"))
    spec = spec or idea

    if not spec:
        return {"error": "no spec and no idea. Pass `spec` for something written, "
                         "or `idea` for something rough that needs refining first"}
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
        want_refine=wants_refine,
        spec=spec, repo=str(Path(repo_path).expanduser()), stage=graph.first,
        # The call may name it; otherwise repos.toml does. Neither guesses it
        # from a git remote.
        repo_slug=str(data.get("repo_slug") or settings.slug or ""),
        title=str(data.get("title") or spec.splitlines()[0][:70] if spec else ""),
        **settings.as_job_fields())

    # The idea is kept beside the spec rather than replaced by it, so a reviewer
    # can see what was asked for AND what it was refined into. A refinement that
    # drifted is only visible if both are there.
    doc = doclib.start(spec, str(job.get("title") or ""))
    if idea:
        doc = doc.add("idea", idea)
    write_document(job, doc)

    record("stage.entered", actor="ghola::submit", subject=job["id"],
           stage=graph.first, repo=job["repo"], refine=wants_refine)
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


def fn_improve(payload: dict) -> dict:
    """Read what went wrong and propose what would have prevented it.

    Not a stage. The pipeline delivers work; this lane reads the record of work
    already delivered, and it runs when somebody asks rather than on every job.

    **It proposes and applies nothing.** What comes back is staged, and
    accepting one writes a spec that goes through the same pipeline and the same
    pull request as any other change.
    """
    data = payload.get("payload") or payload
    found = STORE.list()
    if data.get("repo"):
        found = [j for j in found if j.get("repo") == data["repo"]]

    repo = str(data.get("repo") or "")
    if not repo and found:
        # Every proposal is about a repository's own configuration, and a turn
        # with no workspace would be proposing changes to files it cannot read.
        repo = str(found[0].get("repo") or "")

    started = improvelib.start(WORKER, ROOT, found, repo)
    if started.get("run"):
        record("improve.started", actor="ghola::improve", subject=started["run"],
               repo=repo, jobs=len(found), signals=started.get("signals", 0))
    return started


def fn_proposals(payload: dict) -> dict:
    """What the improve lane has staged, newest run first."""
    data = payload.get("payload") or payload
    if data.get("run"):
        run = improvelib.read(ROOT, str(data["run"]))
        return run or {"error": f"no improve run {data['run']!r}"}

    # The listing drops the evidence brief, which is thousands of words and the
    # reason to name a run rather than read them all.
    return {"runs": [{k: v for k, v in run.items() if k != "evidence"}
                     for run in improvelib.runs(ROOT)]}


def fn_accept(payload: dict) -> dict:
    """Take one staged proposal seriously.

    Writes a spec into `specs/` and stops there, except a move on the ladder,
    which is a rung in a file and is asked of the ladder worker. Neither commits
    anything: the change reaches a person as a diff.
    """
    data = payload.get("payload") or payload
    run_id = str(data.get("run") or "")
    if not run_id:
        return {"error": "no run. Pass `run` and `proposal` (its index)"}

    answer = improvelib.accept(WORKER, ROOT, run_id,
                               int(data.get("proposal") or 0),
                               repo=str(data.get("repo") or ""))
    if answer.get("spec") and not answer.get("already"):
        record("proposal.accepted", actor="ghola::accept", subject=run_id,
               proposal=int(data.get("proposal") or 0), spec=answer["spec"])
    return answer


def fn_tick(payload: dict) -> dict:
    """Look at every job waiting on a human. Bound to cron.

    **Without this the reconciler is dead.** A job reaches `waiting` and stays
    there: the stage exists, its outcomes are declared, `derive_outcome` is
    tested, and nothing ever calls it. That is the exact failure this repository
    keeps finding in other clothes — a mechanism that is written, correct, and
    connected to nothing.

    A tick enqueues rather than acting, so the same stage guard and the same
    at-least-once handling apply to a poll as to a transition.
    """
    waiting = STORE.waiting()
    for job in waiting:
        enqueue(job["id"], "waiting")
    return {"ticked": len(waiting)}


# ------------------------------------------------------------- the dispatch

def enqueue(job_id: str, stage: str) -> None:
    """One durable message per transition, so a crash resumes rather than restarts.

    `iii::durable::publish` rather than `engine::queue::enqueue`: the latter is
    the engine's internal provider for `TriggerAction::Enqueue` and takes a
    message receipt id, which a caller does not have.
    """
    if WORKER is None:
        return
    try:
        WORKER.trigger({"function_id": "iii::durable::publish", "timeout_ms": 15000,
                        "payload": {"topic": QUEUE,
                                    "data": {"job_id": job_id, "stage": stage}}})
    except Exception as exc:  # noqa: BLE001
        # A job that cannot be enqueued has stopped, and a stopped job that
        # looks queued is the worst version of that. Say so loudly.
        print(f"ENQUEUE FAILED for {job_id} at {stage}: {type(exc).__name__}: {exc}")
        record("stage.left", actor="ghola::enqueue", subject=job_id,
               to="stalled", why=f"could not enqueue: {exc}")


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
        # Entry criteria. A phase whose inputs are missing would run on nothing
        # and produce something confident about it, which costs a turn and
        # reads like an answer.
        entry = doclib.may_start(document_of(job), stage.requires)
        if not entry.ok:
            return advance(job, graph, {
                "ok": False, "error": f"`{stage.name}` {entry.why}"})
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

    # The publishing actions need the document, which lives beside the record
    # rather than on it: it is a file, and a job record carrying a copy would be
    # two of one thing.
    job["document"] = document_of(job).text

    result = handler(WORKER, job, job)

    # A reviewer's comment becomes the brief for the next turn, and is
    # acknowledged on the pull request so they know it was read rather than
    # watching a branch change under them. The comment id is recorded so the
    # next poll does not rework the same comment forever.
    if result.get("outcome") == "comment" and result.get("brief"):
        builtin_actions.acknowledge(WORKER, job, str(result["brief"]))
        job["brief"] = str(result["brief"])
        job["answered_comment"] = str(result.get("comment_id") or "")
        job["reason"] = "rework"
        record("stage.entered", actor="a reviewer", subject=job["id"],
               stage="rework", comment=str(result.get("comment_id") or ""))

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
    """What this phase is asked to do: its prompt, filled in.

    A refusal or a reviewer's comment is already a brief and replaces the spec
    rather than being appended to it.
    """
    doc = document_of(job)
    return promptslib.brief(stage.phase, {
        # The document, not the raw spec: it carries what earlier phases
        # produced, which is the whole point of the interface being a file.
        "spec": doc.get("spec") or job.get("spec"),
        "plan": doc.get("plan"),
        # The ref, not the diff. A reviewer with `shell::exec` can get the whole
        # change itself, and the ref is what stops it grading a different one
        # than the delivery gate will read.
        "base": builtin_actions.base_ref(job),
        "brief": job.get("brief"),
        "document": doc.text,
        "repo": job.get("repo"),
        "branch": job.get("branch"),
        "phase": stage.phase,
    })


def advance(job: dict, graph: graphlib.Graph, result: dict) -> dict:
    """Apply the transition the graph decided, and enqueue the next step.

    **A transition to the same stage is not a transition.** `waiting -> waiting`
    is the normal answer when nobody has acted on a pull request yet, and
    treating it as movement re-enqueues immediately: the first version spun 2020
    history entries in 75 seconds, burning a queue message and a forge call on
    each one. A card that waits is a card that does nothing, including nothing
    to its own record.
    """
    move = graphlib.next_stage(job, graph, result)

    if move.to == job.get("stage"):
        # Stay put, silently. The next tick will look again.
        return {"job": job["id"], "stage": move.to, "why": move.why, "waiting": True}
    moved = jobslib.advance(job, move.to, move.why, revision=move.revision,
                            **{k: v for k, v in result.items()
                               if k in ("workspace", "worktree_id", "pull_request",
                                        "pr_number", "brief", "plan", "last_refusal",
                                        "answered_comment", "verdict", "proven",
                                        "findings", "verdict_downgraded",
                                        "verdict_downgraded_from",
                                        "proven_downgraded",
                                        "proven_downgraded_from")})
    STORE.write(moved)

    record("stage.left", actor="ghola::step", subject=job["id"],
           **{"from": job.get("stage"), "to": move.to, "why": move.why})

    if move.to in graph.terminal:
        # A job that lands and keeps its worktree leaks one per job. Nothing
        # routes to `teardown` as a stage, because every terminal state needs it
        # and a stage would need an edge from each of them.
        finish(moved, move.to)
        return {"job": job["id"], "stage": move.to, "why": move.why}

    if move.to == graphlib.BLOCKED:
        return {"job": job["id"], "stage": move.to, "why": move.why}

    enqueue(job["id"], move.to)
    return {"job": job["id"], "stage": move.to, "why": move.why}


def finish(job: dict, stage: str) -> None:
    """Everything a terminal job still owes: a word on the pull request, the
    repository's cleanup, and the worktree back.

    Best-effort throughout. The work has already landed or been closed by a
    human, and failing to tidy is not a reason to reopen their decision.
    """
    try:
        if stage == "landed":
            builtin_actions.announce_landing(WORKER, job)
        result = builtin_actions.teardown(WORKER, job, job)
        record("stage.left", actor="ghola::teardown", subject=job["id"],
               to=stage, did=result.get("did"))
    except Exception as exc:  # noqa: BLE001
        print(f"teardown after {stage} failed for {job['id'][:8]}: "
              f"{type(exc).__name__}: {exc}")


def fn_turn_completed(payload: dict) -> dict:
    """A phase finished. Turn it into a transition."""
    event = payload.get("payload") or payload
    job_id, phase, result = turnlib.outcome(event)
    if not job_id:
        return {}                       # somebody else's turn on this engine

    # The improve lane rides the same session naming and the same completion
    # event, and its run is not a job. Checked before the store, because looking
    # it up as a job would find nothing and report a lost turn.
    if phase == improvelib.PHASE:
        run = improvelib.completed(ROOT, job_id, result)
        if run:
            record("improve.completed", actor="phase:improve", subject=job_id,
                   staged=len(run.get("proposals") or []),
                   dropped=len(run.get("problems") or []))
        return run or {}

    job = STORE.read(job_id)
    if job is None:
        # A completion for a job with no record. Either somebody else's turn on
        # a session that happens to parse, or the id and the filename have come
        # apart — which is silent, so it is said out loud.
        print(f"turn completed for `{job_id}` ({phase}) and no such job record")
        return {}

    record("turn.completed", actor=f"phase:{phase}", subject=job_id,
           ok=result["ok"], cost_usd=result["cost_usd"])

    graph = pipeline()
    stage = graph.get(str(job.get("stage") or ""))
    outcome = interpret(result, phase, contract_for(stage) if stage else {})

    # File what the phase produced into the document, then check it actually
    # produced it. A phase that finishes without its exit criteria has returned
    # something nobody downstream can use.
    if stage and stage.produces and outcome.get("ok") and not outcome.get("blocked"):
        doc = document_of(job)
        for name in stage.produces:
            doc = doc.add(name, str(outcome.get("text") or ""))
        write_document(job, doc)

        finished = doclib.is_finished(doc, stage.produces)
        if not finished.ok:
            outcome = {"ok": False, "error": f"`{stage.name}` {finished.why}"}

    return advance(job, graph, outcome)


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
        parsed = contractslib.as_result(answer, phase)
        # Both `prove` and `review` answer with a `verdict` key, so storing it
        # under one name means the second check overwrites the first and the
        # pull request reports only whichever ran last. Each lands under its own
        # contract's name.
        name = str(contract.get("name") or ("proven" if phase == "prove" else "verdict"))
        return {**result, **parsed, "text": text,
                name: parsed["verdict"],
                f"{name}_downgraded": parsed["downgraded"],
                f"{name}_downgraded_from": parsed["downgraded_from"]}

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
        (f"{NAME}::improve", fn_improve,
         "Read what went wrong and propose what would have prevented it."),
        (f"{NAME}::proposals", fn_proposals, "What the improve lane has staged."),
        (f"{NAME}::accept", fn_accept,
         "Take one staged proposal seriously. Writes a spec; applies nothing."),
        (f"{NAME}::step", fn_step, "Internal: run one stage. Bound to the queue."),
        (f"{NAME}::tick", fn_tick,
         "Look at every job waiting on a human. Bound to cron."),
        (f"{NAME}::turn-completed", fn_turn_completed, "Internal: a phase finished."),
    ):
        WORKER.register_function(function_id, handler, description=description)

    WORKER.register_trigger({"type": "harness::turn-completed",
                             "function_id": f"{NAME}::turn-completed",
                             "config": {}})

    # Without this the factory enqueues transitions that nothing consumes: every
    # job would submit, write its first record, and stop, looking exactly like a
    # job that was still working.
    WORKER.register_trigger({"type": "durable:subscriber",
                             "function_id": f"{NAME}::step",
                             "config": {"queue": QUEUE, "max_retries": 3}})

    # Every minute, six-field cron. A pull request can be merged at any time and
    # nothing tells ghola; the only way to find out is to look.
    WORKER.register_trigger({"type": "cron",
                             "function_id": f"{NAME}::tick",
                             "config": {"expression": POLL}})

    graph = pipeline()
    print(f"ghola-factory started on {url}")
    print(f"  jobs   : {STORE.folder}")
    print(f"  stages : {' -> '.join(graph.stages) or 'none'}")
    print("  audit  : through audit-log, which owns the chain")
    print(f"  queue  : {QUEUE} -> {NAME}::step")
    print(f"  poll   : {POLL} -> {NAME}::tick ({len(STORE.waiting())} waiting)")
    print("  the console is the UI: invoke ghola::submit from it")
    for problem in graph.problems:
        print(f"  PIPELINE PROBLEM: {problem}")
    threading.Event().wait()


if __name__ == "__main__":
    main()
