"""What ghola listens to, so the audit log records decisions it did not make.

The observability half of the governance pair. Three workers decide things about
a turn and each announces what it decided; none of them keeps a permanent
record, and none of them should:

| worker | announces | why it does not keep the record |
|---|---|---|
| `ladder` | `ladder::refused` | a log inside the thing it audits is not independent of it |
| `approval-gate` | `approval::pending-created` / `-resolved` | it keeps **no** resolved history by design; the transcript is its audit trail |
| `opengantry` | `gantry::verdict` | it is the hot path only |

So ghola binds to all of them and appends to one append-only, hash-chained log.
That is the whole design: **the deciding is distributed and the remembering is
in one place**, because an auditor asking "who allowed this, on what evidence"
should not have to reconcile four stores that were pruned on different schedules.

Every handler here fails open. A recorder that can fail a turn is a recorder that
gets removed the first time it does.
"""

from __future__ import annotations

import context

# Trigger types this worker subscribes to, and how each maps onto an audit kind.
# A list rather than four near-identical modules, because they differ only in
# which fields carry the interesting part.
SOURCES = {
    "ladder::refused": "ladder.refused",
    "approval::pending-created": "approval.held",
    "approval::pending-resolved": "approval.resolved",
    "gantry::verdict": "governance.verified",
}


def body(payload: dict) -> dict:
    return payload.get("payload") or payload


def on_ladder_refused(payload: dict) -> dict:
    """A constraint refused or held a call.

    The `actor` is the primitive rather than the worker, because "who refused
    this" is answered by the rule's id and not by the fact that a ladder exists.
    """
    data = body(payload)
    context.record(
        "ladder.refused",
        actor=str(data.get("primitive") or "ladder"),
        subject=str(data.get("repo") or ""),
        rung=data.get("rung"),
        action=data.get("action"),
        function_id=data.get("function_id"),
        path=data.get("path"),
        # The reason, not the content it was about. The content is what a
        # credential would be hiding in.
        reason=str(data.get("reason") or "")[:400],
    )
    return {}


def on_approval_held(payload: dict) -> dict:
    """A call parked for a person.

    Recorded when it is parked as well as when it is answered, because the
    interesting number is often how long it waited and whether anybody came.
    """
    data = body(payload)
    context.record(
        "approval.held",
        actor=str(data.get("function_id") or "approval-gate"),
        subject=str(data.get("session_id") or ""),
        function_call_id=data.get("function_call_id"),
        # NOT `kind=`. `record` takes the audit kind as its first parameter and
        # collects everything else as detail, so an event carrying its own
        # `kind` raised `got multiple values for argument 'kind'` — inside a
        # trigger handler, where nothing failed loudly. Every approval hold this
        # system has ever recorded was lost to it, and the log looked like a log
        # of a system that never held anything.
        held_kind=data.get("kind"),
    )
    return {}


def on_approval_resolved(payload: dict) -> dict:
    """And what the person said.

    `approval-gate` keeps no resolved history: a record exists only while a call
    is held. This is the only place the answer survives, which is exactly the
    gap this module was written to close.
    """
    data = body(payload)
    context.record(
        "approval.resolved",
        actor=str(data.get("resolved_by") or data.get("actor") or "a person"),
        subject=str(data.get("session_id") or ""),
        function_call_id=data.get("function_call_id"),
        decision=data.get("decision") or data.get("outcome"),
        reason=str(data.get("reason") or "")[:400],
    )
    return {}


def on_verdict(payload: dict) -> dict:
    """A promote-class call proved itself, or did not."""
    data = body(payload)
    passed = bool(data.get("passed", data.get("ok", False)))
    context.record(
        "governance.verified" if passed else "governance.denied",
        actor="opengantry",
        subject=str(data.get("repo_root") or data.get("mission") or ""),
        passed=passed,
        mission=data.get("mission"),
        reason=str(data.get("reason") or "")[:400],
    )
    return {}


HANDLERS = {
    "ladder::refused": ("ghola::record::ladder-refused", on_ladder_refused),
    "approval::pending-created": ("ghola::record::approval-held", on_approval_held),
    "approval::pending-resolved": ("ghola::record::approval-resolved",
                                   on_approval_resolved),
    "gantry::verdict": ("ghola::record::verdict", on_verdict),
}


def bind(worker) -> list[str]:
    """Subscribe to every source that exists on this engine.

    A missing source is not an error. `opengantry` is optional and a deployment
    without it should not fail to start; what it must not do is silently record
    nothing and look identical to one that is recording. So what bound is
    printed, and what did not is printed with the reason.
    """
    bound = []
    for trigger_type, (function_id, handler) in HANDLERS.items():
        try:
            worker.register_function(function_id, handler)
            worker.register_trigger({"type": trigger_type,
                                     "function_id": function_id,
                                     "config": {}})
            bound.append(trigger_type)
        except Exception as exc:  # noqa: BLE001
            print(f"  not recording {trigger_type}: {type(exc).__name__}: {exc}")
    return bound
