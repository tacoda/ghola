"""Starting a phase, and hearing when it finished.

A phase is a turn on iii's `harness` worker. ghola starts it with `harness::send`
and hears about it on that worker's own `harness::turn-completed` event. Nothing
here owns a loop, a transcript, a retry, or a token budget.

The session id carries the job and the phase, because the completion event is
about a session and the factory needs to know which piece of work finished. It
also buys what a transcript store would: a revision sends into the same session,
so the model continues rather than starting again.

Every function here is pure except `send`, which does one trigger. That is
deliberate: it is what lets the whole seam be tested without an engine.
"""

import fnmatch
import re
import time

import phase_settings

SESSION = re.compile(r"^s_(?P<job>[0-9a-z]+)_(?P<phase>[a-z0-9-]+)$")


def session_for(job_id: str, phase: str) -> str:
    """One session per job and phase, named so a completion traces back.

    Ours rather than the harness's, because the alternative is a lookup table
    that has to be written before the turn starts and survive whatever restarts
    it.
    """
    cleaned = re.sub(r"[^0-9a-z]", "", (job_id or "").lower())
    return f"s_{cleaned or 'anon'}_{phase}"


def as_id(hexed: str) -> str:
    """The job id back out of a session name.

    Identity, because `jobs.new_id` mints `uuid4().hex` — no dashes — and a job
    record is a file named after exactly that string.

    This function used to re-insert UUID dashes on a 32-character id, inherited
    from a design whose ids carried them. The result was that every completion
    for a real job looked up `a48bf8ec-92ac-...`, found no file, and returned
    quietly: the turn finished, the job never advanced, and nothing said why.
    The session name and the record's filename have to agree, and this is the
    one place that can make them disagree.
    """
    return hexed


def phase_of(event: dict) -> tuple[str, str]:
    """The job and phase a completion event belongs to, or two empty strings.

    A session this cannot parse belongs to something else on the same engine, and
    the caller drops it rather than guessing which of its jobs it was.
    """
    session = SESSION.match(str(event.get("session_id") or ""))
    if not session:
        return "", ""
    return as_id(session.group("job")), session.group("phase")


def granted(allowed: list[str], withheld: list[str]) -> tuple[list[str], list[str]]:
    """Rung 1, applied where the grant is actually built.

    Returns the functions this phase may call, and the ones a constraint took
    away. The second half is returned rather than logged because a rung that
    cannot say what it removed is a rung nobody can check, and this is the exact
    place a previous design had a rule that was written, tested, and called by
    nothing: `phases.yaml` omitted the editors by hand, the rule said it withheld
    them, and the two agreed only because somebody kept them agreeing.

    A withheld name is matched against the glob a phase granted, so withholding
    `coder::create-file` takes it away from a phase granted `coder::*`.
    """
    if not withheld:
        return list(allowed), []

    kept, taken = [], []
    for pattern in allowed:
        hits = [w for w in withheld if fnmatch.fnmatch(w, pattern) or w == pattern]
        if hits and not any(ch in pattern for ch in "*?["):
            # An exact grant of a withheld function. Drop it.
            taken.extend(hits)
            continue
        kept.append(pattern)
        # A glob that would reach a withheld function stays, because narrowing it
        # here would silently rewrite what the phase asked for. The `deny` list
        # below is what actually stops the call, and the harness honours a deny
        # over any allow-glob match.
        taken.extend(hits)

    return kept, sorted(set(taken))


def payload_for(phase: str, prompt: str, *, job_id: str = "", workspace: str = "",
                model: str = "", config: dict | None = None,
                withheld: list[str] | None = None) -> dict:
    """The whole `harness::send` payload, as a pure function of its arguments.

    Built here rather than inline in `send` so a test can assert what a phase
    sends without an engine to send it to. Every rung-1 grant in this system is
    one key of this dict, and a test that cannot see it cannot check it.
    """
    session_id = session_for(job_id, phase)
    options = phase_settings.send_options(phase, config)

    # Rung 1. The ladder says what a constraint withholds; this is where it is
    # subtracted from the grant, and the `deny` list is what makes it stick: the
    # harness refuses a call on "no allow-glob match OR a deny-glob match", so a
    # deny beats an allow whatever the glob said.
    if withheld:
        grant = dict(options.get("functions") or {})
        kept, taken = granted(grant.get("allow") or [], withheld)
        if taken:
            grant["allow"] = kept
            grant["deny"] = sorted(set((grant.get("deny") or []) + taken))
            options["functions"] = grant
    # Handed back verbatim to every callback the harness invokes. The policy
    # worker holds no session state, so this dict is the only thing telling a
    # callback which piece of work it is inside.
    options["metadata"] = {
        "job_id": job_id,
        "phase": phase,
        "workspace": workspace,
        # So a callback can ask the harness about its own turn: the single-writer
        # rule needs to know whether this session has a live child, and a hook is
        # told nothing else that would let it find out.
        "session_id": session_id,
    }

    # **The turn's filesystem scope.** Without this the harness defaults it to
    # the engine's own working directory, so a turn reads the target
    # repository's charter and then edits ghola's files. The first real job
    # caught it: the plan turn refused to touch anything because the repository
    # it could see was not the one its instructions described.
    #
    # This is how the `worktree` worker isolates parallel agents — they work
    # inside a minted worktree through this root — so it is also what makes two
    # jobs on one repository safe.
    if workspace:
        options["metadata"]["fs_scope"] = {"root": workspace}
        options.setdefault("fs_scope", {"root": workspace})
    return {
        "session_id": session_id,
        "message": {
            "role": "user",
            "content": [{"type": "text", "text": prompt}],
            "timestamp": int(time.time() * 1000),
        },
        "model": phase_settings.model_for(phase, model, config),
        "options": options,
    }


def withheld_by_ladder(worker, workspace: str) -> list[str]:
    """What rung 1 takes away, asked of the `ladder` worker.

    A failure is an empty list rather than an exception. The ladder is a separate
    worker and may be down; a turn granted too much is a worse outcome than no
    turn only if nothing else is watching, and rungs 2 through 5 still are. The
    caller reports the shortfall rather than pretending it did not happen.
    """
    if worker is None:
        return []
    try:
        answer = worker.trigger({"function_id": "ladder::list", "timeout_ms": 8000,
                                 "payload": {"repo": workspace}}) or {}
        body = answer.get("payload") or answer
        return list(body.get("withheld") or [])
    except Exception:  # noqa: BLE001 — a missing ladder must not fail the turn
        return []


def send(worker, phase: str, prompt: str, *, job_id: str = "", workspace: str = "",
         model: str = "", timeout_ms: int = 60000,
         withheld: list[str] | None = None) -> str:
    """Start one phase as a turn. Returns the session it runs in.

    A lookup and a trigger, and it is meant to stay that way. Everything that is
    a number or a name came from `phases.yaml`; everything that is a judgment
    happens in a callback the harness invokes.
    """
    if withheld is None:
        withheld = withheld_by_ladder(worker, workspace)
    payload = payload_for(phase, prompt, job_id=job_id, workspace=workspace,
                          model=model, withheld=withheld)
    worker.trigger({"function_id": "harness::send", "timeout_ms": timeout_ms,
                    "payload": payload})
    return payload["session_id"]


def outcome(event: dict) -> tuple[str, str, dict]:
    """A terminal turn event, as the job id, the phase, and a result shape.

    The four keys every result handler reads, so a change to what the harness
    emits stops at this function rather than reaching the state machine.
    """
    job_id, phase = phase_of(event)
    if not job_id:
        return "", "", {}

    failed = event.get("status") != "completed"
    error = event.get("result_error") or event.get("reason") or ""
    return job_id, phase, {
        "ok": not failed,
        "text": str(event.get("result") or ""),
        "cost_usd": float(event.get("session_cost_usd") or 0.0),
        "error": str(error)[:600] if failed else "",
    }
