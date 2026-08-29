"""The improve lane: read what went wrong, propose what would have prevented it.

Everything the lane decides is pure and lives in `ghola-core` — `trouble.py`
reads the evidence, `proposals.py` says what a proposal is and what accepting
one produces. This module is the impure half: it asks the audit worker and the
ladder worker what they know, sends one turn, and writes files.

**Nothing is applied.** Accepting a proposal writes a spec into `specs/` and
stops. The exception is a promotion or a demotion, which is one number in a
file, and even that becomes a pull request a person merges — the ladder worker
changes the repository and commits nothing.

That is the whole design constraint: the improve lane may not edit the charter,
the harness or the factory on its own authority. Otherwise it is the one thing
in this system escaping the gate everything else goes through.
"""

from __future__ import annotations

import json
import time
import uuid
from pathlib import Path

import proposals as proposalslib
import prompts as promptslib
import trouble
import turn as turnlib

PHASE = "improve"


def folder(root: Path) -> Path:
    return root / "state" / "proposals"


def run_path(root: Path, run_id: str) -> Path:
    return folder(root) / f"{run_id}.json"


def new_run_id() -> str:
    """Short, and shaped like a job id, because it rides the same session name.

    `turn.session_for` strips everything but lowercase alphanumerics, so an id
    with a dash in it would come back out of a completion event as a different
    string — which is exactly the bug that once made every completion look up a
    job no file was named after.
    """
    return uuid.uuid4().hex[:12]


# ------------------------------------------------------------- the evidence

def ask(worker, function_id: str, payload: dict) -> dict:
    """One read of another worker, where a failure is an empty answer.

    A missing ladder or a missing audit log narrows what the lane can see; it
    should not stop it from reporting what it can. What is missing is named in
    the answer rather than being quietly indistinguishable from "nothing went
    wrong", which is the whole failure mode `trouble.quiet` exists to avoid.
    """
    if worker is None:
        return {}
    try:
        answer = worker.trigger({"function_id": function_id, "timeout_ms": 20000,
                                 "payload": payload}) or {}
        return answer.get("payload") or answer
    except Exception as exc:  # noqa: BLE001
        print(f"improve: {function_id} unavailable: {type(exc).__name__}: {exc}")
        return {}


def evidence(worker, jobs: list[dict], repo: str, limit: int = 500) -> dict:
    """What the record says went wrong, gathered from where it already is."""
    log = ask(worker, "audit::read", {"limit": limit})
    rungs = ask(worker, "ladder::list", {"repo": repo}) if repo else {}

    entries = list(log.get("entries") or [])
    rules = [p for p in (rungs.get("primitives") or [])
             if p.get("side") == "constraint"]

    signals = trouble.gather(jobs, entries, rules)
    missing = []
    if not entries:
        missing.append("the audit log had nothing to say")
    if repo and not rules:
        missing.append(f"the ladder listed no constraints for {repo}")

    return {
        "signals": signals,
        "entries": len(entries),
        "rules": len(rules),
        "missing": missing,
        "brief": trouble.as_brief(signals, jobs),
        "quiet": trouble.quiet(jobs, signals),
    }


# ------------------------------------------------------------- the turn

def start(worker, root: Path, jobs: list[dict], repo: str) -> dict:
    """Gather the evidence and send one turn. Returns the run.

    Refuses to run on a clean record. An improve lane that always finds three
    things is a lane nobody believes by the third time, and a turn handed no
    evidence will produce proposals anyway — that is what a model does.
    """
    found = evidence(worker, jobs, repo)
    if found["quiet"]:
        return {"skipped": "nothing on record cost anything",
                "jobs": len(jobs), "entries": found["entries"]}

    run_id = new_run_id()
    session = turnlib.session_for(run_id, PHASE)
    brief = promptslib.brief(PHASE, {"evidence": found["brief"], "repo": repo,
                                     "home": str(root), "phase": PHASE})

    # **This lane reads two repositories.** A charter proposal is about the
    # target repo, which is the workspace; a harness or factory proposal is
    # about ghola's own prompts, settings and pipeline, which are here. Scoped
    # to one, the turn hits the filesystem boundary on the other, the approval
    # hook parks the call for a person, and nothing tells that person it is
    # waiting: the first live run sat in `awaiting_functions` for ten minutes
    # holding two reads of this directory.
    grant(worker, session, str(root))

    save(root, {
        "id": run_id, "started": int(time.time()), "repo": repo,
        "signals": [s.kind for s in found["signals"]],
        "evidence": found["brief"], "missing": found["missing"],
        "jobs": [str(j.get("id") or "") for j in jobs],
        "state": "running", "proposals": [], "problems": [],
    })

    turnlib.send(worker, PHASE, brief, job_id=run_id, workspace=repo)
    return {"run": run_id, "session": session, "repo": repo,
            "reads": [repo, str(root)],
            "signals": len(found["signals"]), "missing": found["missing"]}


def grant(worker, session_id: str, root: str) -> bool:
    """A second filesystem root for one session, read through the harness.

    `harness::filesystem::grant` is the framework's own mechanism for this and
    it is durable per session, so it is asked for before the turn starts rather
    than after the first refused read.
    """
    if worker is None:
        return False
    answer = ask(worker, "harness::filesystem::grant",
                 {"session_id": session_id, "root": root})
    return bool(answer) and not answer.get("error")


def completed(root: Path, run_id: str, result: dict) -> dict:
    """A turn finished. Parse it into staged proposals.

    A proposal that cannot be traced to evidence is dropped and the reason kept:
    the run records what it refused as well as what it staged, because a lane
    that silently discards half its output looks like a lane that found less.
    """
    run = read(root, run_id)
    if run is None:
        return {}

    if not result.get("ok"):
        run.update(state="failed", problems=[str(result.get("error") or "the turn failed")])
        save(root, run)
        return run

    found, problems = proposalslib.parse(str(result.get("text") or ""))
    run.update(
        state="staged",
        finished=int(time.time()),
        proposals=[as_record(p) for p in found],
        problems=problems,
        distribution=proposalslib.lane_distribution(found),
    )
    note = proposalslib.distribution_note(run["distribution"])
    if note:
        run["problems"] = list(run["problems"]) + [note]
    save(root, run)
    return run


def as_record(proposal: proposalslib.Proposal) -> dict:
    return {"title": proposal.title, "lane": proposal.lane, "kind": proposal.kind,
            "action": proposal.action, "target": proposal.target,
            "why": proposal.why, "rung": proposal.rung,
            "evidence": list(proposal.evidence), "body": proposal.body,
            "accepted": "", "spec": ""}


def as_proposal(record: dict) -> proposalslib.Proposal:
    return proposalslib.Proposal(
        title=str(record.get("title") or ""), lane=str(record.get("lane") or ""),
        kind=str(record.get("kind") or ""), action=str(record.get("action") or ""),
        target=str(record.get("target") or ""), why=str(record.get("why") or ""),
        rung=str(record.get("rung") or ""), body=str(record.get("body") or ""),
        evidence=tuple(record.get("evidence") or ()))


# ------------------------------------------------------------- accepting one

def accept(worker, root: Path, run_id: str, index: int, repo: str = "") -> dict:
    """Take one staged proposal seriously. Writes a spec; applies nothing.

    A promotion or a demotion is the exception, because it is one number in a
    file rather than a change somebody has to design. The ladder worker makes
    it and commits nothing, so it still reaches a person as a diff.
    """
    run = read(root, run_id)
    if run is None:
        return {"error": f"no improve run {run_id!r}"}

    staged = list(run.get("proposals") or [])
    if not 0 <= index < len(staged):
        return {"error": f"run {run_id} has {len(staged)} proposal(s), "
                         f"so there is no proposal {index}"}

    record = staged[index]
    if record.get("accepted"):
        # Accepting twice would write a second spec for one decision.
        return {"already": record["accepted"], "spec": record.get("spec") or "",
                "proposal": record}

    proposal = as_proposal(record)
    if proposal.is_move:
        answer = move(worker, proposal, repo or str(run.get("repo") or ""))
        record["accepted"] = "moved" if answer.get("ok") else ""
        save(root, run)
        return {"moved": answer, "proposal": record,
                "note": "the ladder changed a file and committed nothing. "
                        "It reaches a person as a diff, like any other change"}

    path = write_spec(root, proposal)
    record["accepted"] = "spec"
    record["spec"] = str(path)
    save(root, run)
    return {
        "spec": str(path), "proposal": record,
        "note": "nothing was applied. Submit this spec like any other work: "
                f"`make submit SPEC={path}`",
    }


def write_spec(root: Path, proposal: proposalslib.Proposal) -> Path:
    """The spec an accepted proposal becomes, in `specs/` beside every other."""
    folder = root / "specs"
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / f"{proposalslib.slug(proposal)}.md"
    # A second proposal with the same title should not overwrite the first one's
    # spec, which somebody may already have submitted.
    if path.exists():
        path = folder / f"{proposalslib.slug(proposal)}-{new_run_id()[:6]}.md"
    path.write_text(proposalslib.as_spec(proposal))
    return path


def move(worker, proposal: proposalslib.Proposal, repo: str) -> dict:
    """A promotion or a demotion, asked of the worker that owns the ladder."""
    if worker is None:
        return {"ok": False, "error": "no engine connection"}
    answer = ask(worker, "ladder::move", {
        "repo": repo, "id": proposal.target, "move": proposal.action,
        "to": proposal.rung})
    return {"ok": bool(answer.get("ok")) and not answer.get("error"), **answer}


# ------------------------------------------------------------- the store

def save(root: Path, run: dict) -> None:
    place = folder(root)
    place.mkdir(parents=True, exist_ok=True)
    path = run_path(root, str(run["id"]))
    # Written beside and renamed, so a reader never sees half a run.
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(run, indent=2))
    temporary.replace(path)


def read(root: Path, run_id: str) -> dict | None:
    try:
        return json.loads(run_path(root, run_id).read_text())
    except (OSError, ValueError):
        return None


def runs(root: Path) -> list[dict]:
    """Every improve run, newest first."""
    place = folder(root)
    if not place.is_dir():
        return []
    found = []
    for path in place.glob("*.json"):
        try:
            found.append(json.loads(path.read_text()))
        except ValueError:
            continue
    return sorted(found, key=lambda r: int(r.get("started") or 0), reverse=True)
