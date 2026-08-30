"""What a callback knows, from the send's metadata and nothing else.

The policy worker holds no session state. Everything a callback needs to know
about which piece of work it is inside arrives in the `options.metadata` the
factory attached to `harness::send`, and the harness hands that back verbatim on
every hook call.

That property is what makes the worker restartable mid-job. It is also why this
module is a parser and not a store.
"""

from dataclasses import dataclass, field


@dataclass(frozen=True)
class Call:
    """One hook invocation, as the fields ghola actually uses.

    A hook payload carries more than this. Naming the subset here means a change
    to the harness's envelope shows up as one failing parse rather than as six
    callbacks reading a key that moved.
    """

    job_id: str = ""
    phase: str = ""
    workspace: str = ""
    session_id: str = ""
    function_id: str = ""
    arguments: dict = field(default_factory=dict)
    depth: int = 0
    step: int = 0

    @property
    def known(self) -> bool:
        """Whether this turn belongs to ghola at all.

        A hook of ours is asked about every turn on this engine, including turns
        nobody here started: a chat in the console, another project's agent. Those
        have no ghola metadata, and the honest answer to a question about them is
        to let them through untouched.
        """
        return bool(self.phase)


def of(payload: dict) -> Call:
    """Parse a hook payload into what a callback is allowed to rely on."""
    data = payload.get("payload") or payload
    metadata = data.get("metadata") or {}
    call = data.get("call") or {}
    return Call(
        job_id=str(metadata.get("job_id") or ""),
        phase=str(metadata.get("phase") or ""),
        workspace=str(metadata.get("workspace") or ""),
        # The harness's own session id wins when present; the metadata copy is
        # what the factory put there so a callback can ask the harness about its
        # own turn.
        session_id=str(data.get("session_id") or metadata.get("session_id") or ""),
        function_id=str(call.get("function_id") or ""),
        arguments=dict(call.get("arguments") or {}),
        depth=int(data.get("depth") or 0),
        step=int(data.get("step") or 0),
    )


# Set by boot.py once the worker is connected, so a callback can ask another
# worker something. The policy worker still holds no SESSION state: this is a
# connection, not a memory of which job is running.
WORKER = None

def record(kind: str, actor: str = "", subject: str = "", **detail) -> None:
    """Append one audit entry, through the worker that owns the chain.

    **Not written directly.** A hash chain has exactly one writer or it has
    none: this worker and the factory both record, they are separate processes,
    and appending from both produced a log that failed its own verification
    while nothing had tampered with it. The `audit-log` worker owns the file.

    A failed write must not fail a turn, but it must not be silent either: an
    audit log that quietly stops recording is worse than none, because the
    absence of an entry then means nothing. So the failure is printed, which is
    the loudest thing available from inside a callback.
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

CONTINUE = {"decision": "continue"}


def refuse(reason: str) -> dict:
    """Refuse a call, in the rule's own words.

    A refusal comes back to the model as a function result, so it reads the
    reason and adapts rather than dying. That is the whole argument for rung 3
    living at `pre-trigger`: the model is told what it may not do by the thing
    that will not let it, and it is told in prose rather than in an error code.
    """
    return {"decision": "deny", "reason": reason}
