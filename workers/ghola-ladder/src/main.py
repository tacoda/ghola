"""ladder: constraints and capabilities on one ladder, as an iii worker.

A **constraint** is what an agent may not do. A **capability** is what it may.
They are the same shape: a ladder of decreasing reliance on a model choosing
correctly, owned by one of three levels, carried either by telling or by running.

This worker binds `ladder::gate` on the harness's `pre-trigger` hook, the same
way `approval-gate` does, and refuses a call in the primitive's own words. It
also serves the ladder as data: what is carried where, how much of it is measured
rather than hoped for, and what moving one would do.

Every decision is made in `gate.py` and `lifecycle.py`, which are pure. This file
is the wiring.

**This is a bundled copy, and it is meant to be swappable.** ghola ships it so
that one clone is the whole thing, rather than three repositories a reader has to
find and keep in step. The upstream is `tacoda/ladder`, which is where this
becomes a public worker other projects install, because the rung is the one idea
here that is worth having without the rest of ghola.

The seam is the function id, not an import. Nothing in ghola imports this
package: every caller triggers `ladder::list`, `ladder::evaluate`, `ladder::move`
or `ladder::explain` over the bus, and `ladder::gate` binds itself to the
harness's `pre-trigger` hook. So pointing `LADDER` at a checkout of the upstream
swaps the provider, and no call site changes, because there is no call site to
change. Keep that true. A shortcut that imports this code directly would weld the
two together and take the swap away.
"""

from __future__ import annotations

import json
import os
import sys
import threading
from pathlib import Path

from iii import InitOptions, register_worker
from iii.triggers import TriggerHandler

import gate
import lifecycle
import load as loader
import permissions as perms_lib
import predicate as pred
from parse import unparse
from primitive import RUNGS, SEES, Primitive, rung_number, validate

HOME = Path(__file__).resolve().parents[1]

# The harness spells its hook trigger types with HYPHENS on the shipped build.
# The tech spec writes them with underscores, and an underscore binding
# registers without error and never fires: a ladder that looks wired and
# enforces nothing is the exact failure this worker exists to prevent, so the
# name is pinned here and asserted by a live test.
PRE_TRIGGER = "harness::hook::pre-trigger"

# Counted per rung, because a primitive carried at two rungs has to show which
# one is doing the work. A backstop that starts catching everything is a signal
# about how turns are writing, not an argument for tightening anything.
CATCHES: dict[tuple[str, int], int] = {}
USES: dict[str, int] = {}
ESCAPES: dict[str, int] = {}

WORKER = None

# Siblings bound to `ladder::refused`. A gate that decides and tells nobody is
# half a mechanism: the deciding is this worker's job and the REMEMBERING is
# somebody else's, because an audit log that lives inside the thing it audits is
# not independent of it. So a refusal is announced and whoever cares records it.
SUBSCRIBERS: list[str] = []

REFUSED_TYPE = {
    "id": "ladder::refused",
    "description": (
        "A constraint refused or held a call. Carries the primitive, the rung "
        "that caught it, the reason given to the model, and what the call was "
        "about. Bind an audit or notification worker here."),
}


def announce(decision: gate.Decision, write: gate.Write, repo: str) -> None:
    """Tell whoever is listening that a constraint fired.

    Fire-and-forget, and never on the critical path: a subscriber that is down
    must not turn a refusal into a failed turn. The refusal already happened;
    this is only the telling.
    """
    if WORKER is None or not SUBSCRIBERS or decision.allowed:
        return
    payload = {
        "primitive": decision.rule_id,
        "rung": decision.rung,
        "action": decision.action,
        "reason": decision.reason,
        "repo": repo,
        "function_id": write.function_id,
        "path": write.path,
        "findings": [{"path": f.path, "line": f.line, "why": f.why}
                     for f in decision.findings],
    }
    for function_id in list(SUBSCRIBERS):
        try:
            WORKER.trigger({"function_id": function_id, "timeout_ms": 5000,
                            "payload": payload})
        except Exception as exc:  # noqa: BLE001
            print(f"ladder::refused -> {function_id} failed: "
                  f"{type(exc).__name__}: {exc}")


class RefusedSubscribers(TriggerHandler):
    """Who is listening for refusals.

    The SDK hands a trigger type's owner a handler object rather than a
    function, and AWAITS it when a sibling binds or unbinds, so both methods are
    async. A synchronous one registers without complaint and fails at the first
    subscription with "object NoneType can't be used in 'await' expression",
    which is a binding that looks wired and is not. Tracking the
    function ids here is what lets `announce` dispatch: iii routes a *call* to a
    function, and a trigger type's owner is the thing that decides which
    functions a fired event reaches.
    """

    async def register_trigger(self, config) -> None:
        function_id = str(getattr(config, "function_id", "") or "")
        if function_id and function_id not in SUBSCRIBERS:
            SUBSCRIBERS.append(function_id)
            print(f"  ladder::refused -> {function_id}")

    async def unregister_trigger(self, config) -> None:
        function_id = str(getattr(config, "function_id", "") or "")
        if function_id in SUBSCRIBERS:
            SUBSCRIBERS.remove(function_id)


def config() -> dict:
    """Where things are. Every key has a convention behind it, so a
    single-project deployment configures nothing at all."""
    return {
        "repo": os.environ.get("LADDER_REPO", os.getcwd()),
        "home": os.environ.get("LADDER_HOME", str(HOME)),
        "roots": None,
    }


def ladder(repo: str = "", permissions: str | None = None) -> loader.Loaded:
    """Load fresh on every call, so editing a file changes the next call rather
    than the next restart. A ladder you have to restart to change is a ladder
    people work around.

    `permissions` is the target repository's `.agents/settings.json`, as text,
    for a caller that can see it when this worker cannot.
    """
    settings = config()
    return loader.load(repo or settings["repo"], settings["home"], settings["roots"],
                       permissions=permissions)


def asked(data: dict) -> tuple[str, str | None]:
    """The repository a call is about, and the permissions it brought with it."""
    supplied = data.get("permissions")
    return str(data.get("repo") or ""), None if supplied is None else str(supplied)


def runner(repo: str):
    """How this deployment runs a check.

    Three kinds, and the second is why ladder is a worker rather than a library:

    1. a Python script beside the primitive, which is the convention
    2. a **function id** on the bus, so a check can be written in any language
    3. an inferential `grades:` description, which nothing here can run — it is
       carried to whoever is grading, and reports no finding by itself
    """
    def run(p: Primitive, write: gate.Write) -> list[pred.Finding]:
        if p.grades and not p.script:
            # Inferential feedback. A model decides this, not us. Returning no
            # finding is correct: refusing on a judgment nobody made would be
            # the strongest rung carrying the weakest evidence.
            return []
        if not p.script:
            return []

        if pred.is_function_id(p.script):
            if WORKER is None:
                return [pred.Finding(path=write.path, why=(
                    f"the check {p.script} is a function on the bus and this "
                    "ladder is not connected to an engine"))]
            try:
                answer = WORKER.trigger({
                    "function_id": p.script, "timeout_ms": 10000,
                    "payload": {"path": write.path, "content": write.content,
                                "function_id": write.function_id,
                                "arguments": write.arguments,
                                "publishing": write.publishing},
                }) or {}
                body = answer.get("payload") or answer
                return pred.normalise(body.get("findings") or body.get("value"), write.path)
            except Exception as exc:  # noqa: BLE001
                return [pred.Finding(path=write.path, why=(
                    f"the check {p.script} could not be reached: "
                    f"{type(exc).__name__}: {exc}. Treated as a finding, because a "
                    "gate that fails open on its own bug stops working invisibly"))]

        # As written first, then relative to the repository. A shipped rule's
        # script sits beside the rule wherever that shipped from, and only a
        # project rule's script is relative to the checkout being judged.
        path = Path(p.script)
        if not path.exists() and not path.is_absolute():
            path = Path(repo) / path
        return pred.run_file(path, write.path, write.content, {"primitive": p.id})

    return run


# --------------------------------------------------------------- the hook

# Which call arguments name a path and which name content. Stock `coder::*` and
# `shell::fs::*` are covered; anything else is added here rather than guessed.
PATH_KEYS = ("path", "file", "file_path", "target", "to")
CONTENT_KEYS = ("content", "text", "body", "new_string", "replacement")


def write_of(call: dict) -> gate.Write:
    """What a proposed call is about to do, as far as one call can tell.

    Deliberately shallow. It reads the arguments; it does not parse a shell
    command to guess what file that command would write. A matcher that tried
    would be a different rule wearing this one's authority, which is exactly why
    a constraint that matters names rung 4 as well.
    """
    arguments = call.get("arguments") or {}
    path = next((str(arguments[k]) for k in PATH_KEYS if arguments.get(k)), "")
    content = next((str(arguments[k]) for k in CONTENT_KEYS if arguments.get(k)), "")

    # Batched edits: `coder::update-file` takes a `files` list, and reading only
    # the top level would wave every batch through.
    files = arguments.get("files")
    if isinstance(files, list) and files and isinstance(files[0], dict):
        path = path or str(files[0].get("path") or "")
        content = content or str(files[0].get("content") or "")

    return gate.Write(path=path, content=content,
                      function_id=str(call.get("function_id") or ""),
                      arguments=arguments)


def rung_two(loaded: loader.Loaded, write: gate.Write) -> gate.Decision | None:
    """The repository's own `permissions`, as a decision.

    One function so the hook and `ladder::evaluate` cannot answer differently
    about the same call. They did, briefly: the hook enforced this and evaluate
    did not, so a test asking the ladder whether a call was allowed got `yes`
    about a call the ladder would have refused. Two implementations of one rule
    disagree, and the agent finds the seam first.
    """
    entry = perms_lib.refuses(loaded.permissions, write.function_id, write.arguments)
    if not entry:
        return None
    return gate.Decision(
        action=gate.DENY,
        reason=(f"This repository's `permissions` in {loaded.permissions.source} say "
                f"deny for `{entry}`, and this call matches it. Use whatever the "
                "repository offers instead, usually a make target, or say in your "
                "summary why the work cannot be done without it."),
        rule_id="repo-permissions",
        rung=2)


def handle_gate(payload: dict) -> dict:
    """`harness::hook::pre-trigger`. Rungs 2 and 3, in front of every call.

    This mount is what makes reaching for stock tools safe: it sits in front of
    calls to workers nobody here wrote, so a turn that writes through a shell
    heredoc meets the same constraint as one that uses an editing tool.

    Rung 2 is asked first. A repository's own `permissions` are what it already
    wrote down, so honouring them before our rules means a project is never
    refused by a team rule for something it had already forbidden itself.
    """
    data = payload.get("payload") or payload
    call = data.get("call") or {}
    metadata = data.get("metadata") or {}
    repo = str(metadata.get("workspace")
               or (metadata.get("fs_scope") or {}).get("root") or "")

    write = write_of(call)
    if not write.function_id:
        return {"decision": gate.CONTINUE}

    loaded = ladder(repo)

    # Rung 2, over the CALL. Checked before the "is this a write" question
    # below, because `Bash(rm -rf *)` has neither a path nor content and
    # skipping it here is how the entry that matters most goes unenforced.
    refusal = rung_two(loaded, write)
    if refusal:
        CATCHES[("repo-permissions", 2)] = CATCHES.get(("repo-permissions", 2), 0) + 1
        announce(refusal, write, repo)
        return refusal.as_hook_response()

    # Rung 3, over the write. A read is not a write, and refusing one on the
    # basis of a rule about writes is how a ladder becomes a thing people
    # disable.
    if not write.path and not write.content:
        USES[write.function_id] = USES.get(write.function_id, 0) + 1
        return {"decision": gate.CONTINUE}

    decision = gate.decide(loaded.governing(write.path, write.function_id),
                           write, rung=3, run=runner(repo or config()["repo"]))
    if decision.rule_id:
        CATCHES[(decision.rule_id, decision.rung)] = \
            CATCHES.get((decision.rule_id, decision.rung), 0) + 1
        announce(decision, write, repo)
    else:
        # A use is recorded AFTER the ladder: a capability the turn was refused
        # is not one the turn used.
        USES[write.function_id] = USES.get(write.function_id, 0) + 1
    return decision.as_hook_response()


# ------------------------------------------------------------- the surface

def described(p: Primitive) -> dict:
    return {
        "id": p.id,
        "kind": p.kind,
        "side": p.side,
        "layer": p.layer + ("*" if p.narrowed_from else ""),
        "level": p.level,
        "description": p.description,
        "why": p.why,
        "rungs": [{"number": n, "name": RUNGS[p.side][n], "sees": SEES[p.side][n],
                   "catches": CATCHES.get((p.id, n), 0)} for n in p.rungs],
        # A departure from the default rung is reported rather than buried.
        "departs_from_default": p.declared_rungs,
        "direction": p.direction,
        "determinism": p.determinism,
        "measured": p.measured,
        "policy": p.policy if p.side == "constraint" else "",
        "paths": list(p.paths),
        "withholds": list(p.withholds),
        "implements": p.implements,
        "escape": p.escape,
        "escapes_used": ESCAPES.get(p.id, 0),
        "locked": p.locked,
        "travels": p.travels,
        "script": p.script,
        "grades": p.grades,
        "source": p.source,
        "problems": validate(p),
    }


def fn_list(payload: dict) -> dict:
    """Everything on the ladder, both sides, with what each rung has caught."""
    data = payload.get("payload") or payload
    loaded = ladder(*asked(data))
    side = str(data.get("side") or "")
    chosen = [p for p in loaded.primitives if not side or p.side == side]
    return {
        "primitives": [described(p) for p in chosen],
        "constraints": len(loaded.constraints),
        "capabilities": len(loaded.capabilities),
        # This does not make feedforward reliable. It makes the gap visible and
        # counted, which is what the ladder is for.
        "measured_share": round(loaded.measured_share, 3),
        # The join between the two ladders: what rung 1 takes away, ready for a
        # caller to subtract from a phase's grant.
        "withheld": sorted(loaded.withheld()),
        "permissions": {
            "source": loaded.permissions.source,
            "withheld": loaded.permissions.withheld,
            "refused": loaded.permissions.refused,
            "unresolved": loaded.permissions.unresolved,
        },
        "problems": loaded.problems,
        "adapted": {k: v.source for k, v in loaded.adapted.items()},
        "refused_adaptations": sorted(loaded.refused_adaptations),
    }


def fn_explain(payload: dict) -> dict:
    """One primitive, and what each rung it names can actually see.

    The question this answers is the one people get wrong: not "is this strict
    enough" but "can the mechanism carrying it see the thing it is about".
    """
    data = payload.get("payload") or payload
    loaded = ladder(*asked(data))
    p = loaded.by_id(str(data.get("id") or ""))
    if p is None:
        return {"error": f"nothing called {data.get('id')!r}",
                "known": [x.id for x in loaded.primitives]}
    out = described(p)
    out["refusal"] = p.says("<the finding goes here>") if p.side == "constraint" else ""
    return out


def fn_evaluate(payload: dict) -> dict:
    """Ask the ladder about a proposed write, without being a turn.

    The same decision the hook makes, callable directly. A delivery gate uses
    this at rung 4, and a test uses it to assert a constraint fires.
    """
    data = payload.get("payload") or payload
    repo = str(data.get("repo") or "")
    write = gate.Write(
        path=str(data.get("path") or ""),
        content=str(data.get("content") or ""),
        function_id=str(data.get("function_id") or ""),
        arguments=dict(data.get("arguments") or {}),
        publishing=str(data.get("publishing") or ""),
    )
    rung = rung_number(data.get("rung", 3))
    loaded = ladder(*asked(data))
    run = runner(repo or config()["repo"])
    governing = loaded.governing(write.path, write.function_id)

    decision = rung_two(loaded, write) if rung == 2 else None
    if decision is None:
        decision = gate.decide(governing, write, rung=rung, run=run)
    warned = gate.warnings(governing, write, rung=rung, run=run)
    return {
        "action": decision.action,
        "allowed": decision.allowed,
        "reason": decision.reason,
        "primitive": decision.rule_id,
        "rung": decision.rung,
        "findings": [{"path": f.path, "line": f.line, "why": f.why}
                     for f in decision.findings],
        "warnings": [{"primitive": w.rule_id, "reason": w.reason} for w in warned],
    }


def apply_steps(steps, source_primitive: Primitive) -> list[str]:
    """Carry out a lifecycle plan. Returns what actually happened."""
    done = []
    for step in steps:
        path = Path(step.path)
        if step.action == "write":
            path.write_text(unparse(source_primitive))
            done.append(f"wrote {path}")
        elif step.action == "move":
            destination = Path(step.to)
            destination.parent.mkdir(parents=True, exist_ok=True)
            path.rename(destination)
            done.append(f"moved {path} -> {destination}")
        elif step.action == "delete":
            path.unlink(missing_ok=True)
            done.append(f"deleted {path}")
        else:
            # generate-hook and remove-hook write into the TARGET repository's
            # own configuration, which this worker does not own. Reported so the
            # caller does it rather than silently skipped, because a rung 2 with
            # nothing mounted is the failure this whole model is against.
            done.append(f"TODO {step.action}: {step.why}")
    return done


def fn_move(payload: dict) -> dict:
    """Move a primitive: promote, demote, carry, drop or remove.

    One verb moves either side. A constraint climbs by having its number
    changed; a capability climbs by having its files moved outward. Which
    happens is decided by what the name turns out to be.

    Nothing is committed. A change to a primitive is a change to a repository and
    goes through whatever that repository does with changes.
    """
    data = payload.get("payload") or payload
    loaded = ladder(*asked(data))
    p = loaded.by_id(str(data.get("id") or ""))
    if p is None:
        return {"error": f"nothing called {data.get('id')!r}",
                "known": [x.id for x in loaded.primitives]}

    plan = lifecycle.plan_move(
        p, str(data.get("move") or "promote"),
        to=data.get("to"), at=data.get("at"), force=bool(data.get("force")),
        layer_roots=data.get("layer_roots") or {})

    out = {
        "primitive": p.id, "side": p.side, "move": plan.move,
        "was": list(plan.was), "now": list(plan.now),
        "steps": [{"action": s.action, "path": s.path, "to": s.to, "why": s.why}
                  for s in plan.steps],
        "notes": plan.notes, "problems": plan.problems, "ok": plan.ok,
    }
    if not plan.ok or data.get("dry_run"):
        return out

    moved = Primitive(**{**p.__dict__, "rungs": plan.now, "declared_rungs": True})
    out["applied"] = apply_steps(plan.steps, moved)
    out["note"] = "nothing was committed. This is a change to a repository"
    return out


def fn_add(payload: dict) -> dict:
    """A new primitive, landing on the rung its level and its script imply."""
    data = payload.get("payload") or payload
    plan = lifecycle.plan_add(
        str(data.get("id") or ""), str(data.get("kind") or "rule"),
        str(data.get("layer") or "project"), bool(data.get("script")),
        why=str(data.get("why") or ""),
        description=str(data.get("description") or ""),
        layer_roots=data.get("layer_roots") or {})
    return {"primitive": plan.primitive, "side": plan.side, "rungs": list(plan.now),
            "steps": [{"action": s.action, "path": s.path, "why": s.why} for s in plan.steps],
            "notes": plan.notes, "problems": plan.problems, "ok": plan.ok}


# --------------------------------------------------------------- offline

# Everything here except the hook decides with a loader and a pure function, so
# an engine is a way to REACH them rather than a thing they need. The lifecycle
# is the half of this model worth trying before adopting it, and requiring a
# running engine to try it puts the cost in the wrong place.
#
# Dispatched to the same handlers the bus calls. A second local implementation
# would answer differently the first time one of them changed, which is the
# failure `rung_two` already exists to prevent.
OFFLINE = {
    "list": fn_list,
    "explain": fn_explain,
    "evaluate": fn_evaluate,
    "move": fn_move,
    "add": fn_add,
}


def summarise(repo: str = "") -> int:
    """`make check`: what this deployment would load, in one screen.

    Exits non-zero on a problem, so it works as a pre-commit step rather than
    only as something to read.
    """
    answer = fn_list({"repo": repo})
    print(f"{answer['constraints']} constraints, {answer['capabilities']} capabilities, "
          f"{answer['measured_share']:.0%} measured — the rest is hoped for")
    for p in answer["primitives"]:
        rungs = ",".join(str(r["number"]) for r in p["rungs"]) or "-"
        print(f"  {p['side'][:4]:4}  rung {rungs:5}  {p['layer']:8}  {p['id']}")
    for problem in answer["problems"]:
        print(f"  PROBLEM: {problem}")
    return 1 if answer["problems"] else 0


def cli(argv: list[str]) -> int:
    """`key=value` tokens, because that is how `iii trigger` takes a payload.

    What you type here is what you would send over the bus, so a command that
    worked locally is a command that works against a running engine.
    """
    command = argv[0] if argv else "check"
    if command == "check":
        return summarise(argv[1] if len(argv) > 1 else "")

    handler = OFFLINE.get(command)
    if handler is None:
        print(f"no offline command {command!r}. Try: check, "
              f"{', '.join(sorted(OFFLINE))}")
        return 2

    data = dict(token.split("=", 1) for token in argv[1:] if "=" in token)
    # A move applies unless told otherwise on the bus, and the opposite here: a
    # command line is where somebody is trying the lifecycle out, and finding out
    # what a promotion does by having it happen is the wrong way round.
    if command == "move" and data.pop("apply", "") not in ("1", "true", "yes"):
        data["dry_run"] = True

    answer = handler(data)
    print(json.dumps(answer, indent=2, default=str))
    return 1 if answer.get("error") or answer.get("problems") else 0


def main() -> None:
    global WORKER
    url = os.environ.get("III_URL", "ws://localhost:49134")
    WORKER = register_worker(address=url, options=InitOptions(worker_name="ladder"))

    for function_id, handler, description in (
        ("ladder::gate", handle_gate,
         "pre-trigger hook: refuse a call that breaks a constraint, in its own words"),
        ("ladder::list", fn_list,
         "Everything on the ladder, both sides, with rungs, direction and catches"),
        ("ladder::explain", fn_explain,
         "One primitive, and what each rung it names can actually see"),
        ("ladder::evaluate", fn_evaluate,
         "Ask the ladder about a proposed write at a given rung, without being a turn"),
        ("ladder::move", fn_move,
         "promote, demote, carry, drop or remove. One verb moves either side"),
        ("ladder::add", fn_add,
         "Scaffold a new primitive on the rung its level and its script imply"),
    ):
        WORKER.register_function(function_id, handler, description=description)

    WORKER.register_trigger_type(REFUSED_TYPE, RefusedSubscribers())

    WORKER.register_trigger({
        "type": PRE_TRIGGER,
        "function_id": "ladder::gate",
        # Fail-closed, which is the harness's default and the right one: a
        # crashed gate must not wave writes through.
        "config": {"priority": 60, "timeout_ms": 15000},
    })

    loaded = ladder()
    print(f"ladder ready on {url}")
    print(f"  constraints  : {len(loaded.constraints)}")
    print(f"  capabilities : {len(loaded.capabilities)}")
    print(f"  measured     : {loaded.measured_share:.0%} runs, the rest is hoped for")
    print(f"  bound        : {PRE_TRIGGER} -> ladder::gate")
    print("  emits        : ladder::refused")
    for problem in loaded.problems:
        print(f"  PROBLEM: {problem}")
    threading.Event().wait()


if __name__ == "__main__":
    # No argument is the worker. Anything else is a question asked offline, so
    # `make run` and `make check` are the same file and cannot disagree.
    if sys.argv[1:]:
        raise SystemExit(cli(sys.argv[1:]))
    main()
