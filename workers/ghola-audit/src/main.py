"""audit-log: an append-only, tamper-evident record, as an iii worker.

**Why this is a worker.** A hash chain has exactly one writer or it has none. The
first real log this code produced failed its own verification with nothing having
tampered with it: two workers appended from separate processes, each held its own
in-memory tail, and their `prev` hashes interleaved. A thread lock cannot make
one writer true across processes. A worker makes it true by construction rather
than by discipline.

**Why it owns its storage.** Sequencing needs an authoritative tail, and
durability means an fsync before the caller is told the entry landed. Neither
survives being split from the store, so this worker is the store. What it can do
is tell everybody afterwards, which is what `audit::recorded` is for.

**The deciding is somebody else's job; the remembering is this one's.** A record
that lives inside the thing it records is not independent of it, so nothing here
decides anything. Callers append; this worker chains, fsyncs, and announces.

Every decision is made in `audit.py`, which is pure. `audit_log.py` is the I/O.
This file is the wiring.

**This is a bundled copy, and it is meant to be swappable.** ghola ships it so
that one clone is the whole thing, rather than three repositories a reader has to
find and keep in step. The upstream is `tacoda/audit-log`, which is where this
becomes a public worker other projects install.

The seam is the function id, not an import. Nothing in ghola imports this
package: every caller triggers `audit::append`, `audit::read` or `audit::verify`
over the bus. So pointing `AUDITLOG` at a checkout of the upstream swaps the
provider, and no call site changes, because there is no call site to change. Keep
that true. A shortcut that imports this code directly would weld the two together
and take the swap away.
"""

from __future__ import annotations

import json
import os
import sys
import threading
from pathlib import Path

from iii import InitOptions, register_worker
from iii.triggers import TriggerHandler

import audit
import audit_log

HOME = Path(__file__).resolve().parents[1]

WORKER = None

# Siblings bound to `audit::recorded`. Fan-out happens AFTER the fsync and off
# the critical path, which is the only place it can happen without weakening the
# record: a subscriber that is down must not turn a recorded decision into a
# failed call, and an entry delivered before it is durable is an entry that may
# never have existed.
SUBSCRIBERS: list[str] = []

RECORDED_TYPE = {
    "id": "audit::recorded",
    "description": (
        "One entry was sealed into the chain. Carries the whole entry, including "
        "its sequence number and hash. Bind an observability, alerting or "
        "shipping worker here. Subscribers are told, never asked: this fires "
        "after the entry is durable and cannot refuse it."),
}


def config() -> dict:
    """Where the log is, and what vocabulary it expects.

    `AUDIT_LOG_KINDS` is a comma-separated list of the event kinds this
    deployment uses. Unset means no vocabulary was declared and no kind is
    reported as unknown, which is the honest answer: nobody said what counts.
    """
    declared = os.environ.get("AUDIT_LOG_KINDS", "")
    return {
        "folder": Path(os.environ.get("AUDIT_LOG_DIR") or HOME / "audit"),
        "kinds": tuple(k.strip() for k in declared.split(",") if k.strip()),
    }


SETTINGS = config()
FOLDER = SETTINGS["folder"]
KINDS = SETTINGS["kinds"]
LOG = audit_log.AuditLog(FOLDER, kinds=KINDS)


def announce(item: dict) -> None:
    """Tell whoever is listening that an entry landed.

    Fire-and-forget, and never on the critical path. The entry is already
    durable; this is only the telling, and a subscriber that is down is a
    subscriber that missed something rather than a write that failed.
    """
    if WORKER is None or not SUBSCRIBERS:
        return
    for function_id in list(SUBSCRIBERS):
        try:
            WORKER.trigger({"function_id": function_id, "timeout_ms": 5000,
                            "payload": item})
        except Exception as exc:  # noqa: BLE001
            print(f"audit::recorded -> {function_id} failed: "
                  f"{type(exc).__name__}: {exc}")


class RecordedSubscribers(TriggerHandler):
    """Who is listening for entries.

    The SDK hands a trigger type's owner a handler object rather than a function,
    and awaits it when a sibling binds or unbinds, so both methods are async. A
    synchronous one registers without complaint and fails at the first
    subscription, which is a binding that looks wired and is not.
    """

    async def register_trigger(self, config) -> None:
        function_id = str(getattr(config, "function_id", "") or "")
        if function_id and function_id not in SUBSCRIBERS:
            SUBSCRIBERS.append(function_id)
            print(f"  audit::recorded -> {function_id}")

    async def unregister_trigger(self, config) -> None:
        function_id = str(getattr(config, "function_id", "") or "")
        if function_id in SUBSCRIBERS:
            SUBSCRIBERS.remove(function_id)


# ------------------------------------------------------------- the surface

def asked(payload: dict) -> dict:
    """The payload, whether it arrived wrapped or bare."""
    return payload.get("payload") or payload


def text(data: dict, key: str) -> str:
    """One string field, defaulting to empty rather than to `None`.

    Every field here is optional and every absent one means the same thing, so
    the coercion lives in one place instead of at each call site.
    """
    return str(data.get(key) or "")


def fn_append(payload: dict) -> dict:
    """Record one decision. The only way anything gets into the log.

    Returns the entry's sequence number and hash, so a caller that wants to prove
    it recorded something has both to name.
    """
    data = asked(payload)
    kind = text(data, "kind")
    if not kind:
        return {"error": "an entry with no kind cannot be found later"}

    try:
        item = LOG.append(kind, actor=text(data, "actor"),
                          subject=text(data, "subject"),
                          detail=dict(data.get("detail") or {}))
    except Exception as exc:  # noqa: BLE001
        # The caller has already acted on the decision this was meant to record.
        # Failing loudly here is the only thing left that helps.
        print(f"AUDIT WRITE FAILED ({kind}): {type(exc).__name__}: {exc}")
        return {"error": f"{type(exc).__name__}: {exc}"}

    announce(item)
    # An unknown kind is a newer caller, not a bad one. A log that rejected
    # events it had not heard of would stop recording the day something new
    # happened, so this is reported rather than refused.
    return {"seq": item["seq"], "hash": item["hash"], "kind": kind,
            "known_kind": not KINDS or kind in KINDS}


def fn_verify(payload: dict) -> dict:
    """Is the chain intact, and from where is it not.

    A verifier that answers only yes or no is useless in an audit, where the
    question is what exactly is being claimed and from when.
    """
    check = LOG.verify()
    return {
        "ok": check.ok,
        "entries": check.entries,
        "verified_through": check.verified_through,
        "problems": check.problems,
        "folder": str(FOLDER),
    }


def fn_summary(payload: dict) -> dict:
    """Both halves from one file: whether it can be trusted, and what it counts."""
    data = asked(payload)
    fields = tuple(data.get("by") or ()) or ("kind", "actor")
    return audit_log.summary(FOLDER, kinds=KINDS, breakdowns=fields)


def fn_read(payload: dict) -> dict:
    """Entries, newest last. `kind` and `subject` narrow it."""
    data = asked(payload)
    entries, problems = LOG.read()

    for field in ("kind", "subject"):
        wanted = text(data, field)
        if wanted:
            entries = [e for e in entries if e.get(field) == wanted]

    limit = int(data.get("limit") or 200)
    return {"entries": entries[-limit:], "total": len(entries), "problems": problems}


def fn_tally(payload: dict) -> dict:
    """Count entries by any field, narrowed to one kind.

    A deployment's interesting breakdowns are its own vocabulary. Counting
    `detail.rung` across every entry and counting it across refusals are
    different questions, and only the second has an answer worth reading.
    """
    data = asked(payload)
    entries, _ = LOG.read()
    return {"counts": audit.tally(entries, by=text(data, "by") or "kind",
                                  kind=text(data, "kind")),
            "total": len(entries)}


# --------------------------------------------------------------- offline

# Reading and verifying a chain needs no engine, and the person most likely to
# want them is an auditor, who is the person least likely to have one running.
# Dispatched to the same handlers the bus calls, so the two answers cannot
# differ. Appending is deliberately absent: one writer is the whole guarantee,
# and a command line that appends beside a running worker is a second one.
OFFLINE = {
    "verify": fn_verify,
    "summary": fn_summary,
    "read": fn_read,
    "tally": fn_tally,
}


def summarise() -> int:
    """`make check`: whether the log can be trusted, and what it holds.

    Exits non-zero on a broken chain, so it works as a cron job or a CI step
    rather than only as something to read.
    """
    check = LOG.verify()
    counts = audit.tally(LOG.read()[0])
    print(f"{check.entries} entries in {FOLDER}")
    print(f"  chain    : {'intact' if check.ok else 'BROKEN'}, "
          f"verified through {check.verified_through}")
    for kind, count in counts.items():
        print(f"  {count:6}  {kind}")
    for problem in check.problems:
        print(f"  PROBLEM: {problem}")
    return 0 if check.ok else 1


def cli(argv: list[str]) -> int:
    """`key=value` tokens, because that is how `iii trigger` takes a payload."""
    command = argv[0] if argv else "check"
    if command == "check":
        return summarise()

    handler = OFFLINE.get(command)
    if handler is None:
        print(f"no offline command {command!r}. Try: check, "
              f"{', '.join(sorted(OFFLINE))}")
        return 2

    answer = handler(dict(t.split("=", 1) for t in argv[1:] if "=" in t))
    print(json.dumps(answer, indent=2, default=str))
    return 1 if answer.get("error") else 0


def main() -> None:
    global WORKER
    url = os.environ.get("III_URL", "ws://localhost:49134")
    WORKER = register_worker(url, InitOptions(worker_name="audit-log"))

    for function_id, handler, description in (
        ("audit::append", fn_append,
         "Record one decision in the append-only, hash-chained log"),
        ("audit::verify", fn_verify,
         "Is the chain intact, and from which entry is it not"),
        ("audit::summary", fn_summary,
         "What the log says: whether it verifies, and what it counts"),
        ("audit::read", fn_read, "Entries, optionally narrowed by kind or subject"),
        ("audit::tally", fn_tally, "Count entries by any field, narrowed to one kind"),
    ):
        WORKER.register_function(function_id, handler, description=description)

    WORKER.register_trigger_type(RECORDED_TYPE, RecordedSubscribers())

    check = LOG.verify()
    print(f"audit-log ready on {url}")
    print(f"  log      : {FOLDER}")
    print(f"  entries  : {check.entries} ({'intact' if check.ok else 'BROKEN'})")
    print(f"  kinds    : {', '.join(KINDS) if KINDS else 'undeclared, nothing checked'}")
    print("  emits    : audit::recorded")
    print("  one writer, by construction: this process owns the chain")
    for problem in check.problems[:5]:
        print(f"  PROBLEM: {problem}")
    threading.Event().wait()


if __name__ == "__main__":
    # No argument is the worker. Anything else is a question asked offline, so
    # `make run` and `make check` are the same file and cannot disagree.
    if sys.argv[1:]:
        raise SystemExit(cli(sys.argv[1:]))
    main()
