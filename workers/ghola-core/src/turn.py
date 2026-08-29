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

    Every id ghola mints is a uuid4, so the dashes are a format rather than
    information: 32 hex characters go back to `8-4-4-4-12`, and anything else is
    returned as it came.
    """
    if len(hexed) != 32:
        return hexed
    return "-".join((hexed[:8], hexed[8:12], hexed[12:16], hexed[16:20], hexed[20:]))


def phase_of(event: dict) -> tuple[str, str]:
    """The job and phase a completion event belongs to, or two empty strings.

    A session this cannot parse belongs to something else on the same engine, and
    the caller drops it rather than guessing which of its jobs it was.
    """
    session = SESSION.match(str(event.get("session_id") or ""))
    if not session:
        return "", ""
    return as_id(session.group("job")), session.group("phase")


def payload_for(phase: str, prompt: str, *, job_id: str = "", workspace: str = "",
                model: str = "", config: dict | None = None) -> dict:
    """The whole `harness::send` payload, as a pure function of its arguments.

    Built here rather than inline in `send` so a test can assert what a phase
    sends without an engine to send it to. Every rung-1 grant in this system is
    one key of this dict, and a test that cannot see it cannot check it.
    """
    session_id = session_for(job_id, phase)
    options = phase_settings.send_options(phase, config)
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


def send(worker, phase: str, prompt: str, *, job_id: str = "", workspace: str = "",
         model: str = "", timeout_ms: int = 60000) -> str:
    """Start one phase as a turn. Returns the session it runs in.

    A lookup and a trigger, and it is meant to stay that way. Everything that is
    a number or a name came from `phases.yaml`; everything that is a judgment
    happens in a callback the harness invokes.
    """
    payload = payload_for(phase, prompt, job_id=job_id, workspace=workspace, model=model)
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
