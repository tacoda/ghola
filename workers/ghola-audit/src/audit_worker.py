"""ghola-audit: one process owns the record, so the chain cannot interleave.

**Why this is a worker.** The first real job produced a log that failed its own
verification, and nothing had tampered with it. Two workers append here — the
policy worker records what the ladder and the approval gate decided, the factory
records stage transitions — and they are separate processes. Each held its own
in-memory tail, so their `prev` hashes interleaved. A hash chain has exactly one
writer or it has none, and a thread lock cannot make that true across processes.

A worker makes it true by construction rather than by discipline.

**What this does not change.** The store is still a directory of plain JSONL
files that this worker owns. The earlier argument against putting the audit log
in the `state` worker stands and was never about who writes: it was that a store
whose retention policy the audited operator can reconfigure is not an
independent record. This worker is a separate *process* from everything it
records, which is more independent than a library both of them import.

The `flock` stays. A worker makes a second writer unlikely rather than
impossible, and an invariant this design depends on should be enforced rather
than assumed — which is the whole argument of the repository it serves.
"""

from __future__ import annotations

import os
import sys
import threading
from pathlib import Path

from iii import InitOptions, register_worker

ROOT = Path(os.environ.get("GHOLA_ROOT", Path(__file__).resolve().parents[3]))
sys.path.insert(0, str(ROOT / "workers" / "ghola-core" / "src"))

import audit  # noqa: E402
import audit_log  # noqa: E402

FOLDER = Path(os.environ.get("GHOLA_AUDIT_DIR") or ROOT / "audit")
LOG = audit_log.AuditLog(FOLDER)


def fn_append(payload: dict) -> dict:
    """Record one decision. The only way anything gets into the log.

    Returns the entry, so a caller that wants to prove it recorded something has
    the sequence number and the hash to name.
    """
    data = payload.get("payload") or payload
    kind = str(data.get("kind") or "")
    if not kind:
        return {"error": "an entry with no kind cannot be found later"}
    if kind not in audit.KINDS:
        # Not refused: an unknown kind is a newer caller, not a bad one, and a
        # log that rejects events it has not heard of is a log that stops
        # recording the day something new happens. It is reported instead.
        pass

    try:
        entry = LOG.append(
            kind,
            actor=str(data.get("actor") or ""),
            subject=str(data.get("subject") or ""),
            detail=dict(data.get("detail") or {}),
        )
    except Exception as exc:  # noqa: BLE001
        # The caller has already acted on the decision this was meant to record.
        # Failing loudly here is the only thing left that helps.
        print(f"AUDIT WRITE FAILED ({kind}): {type(exc).__name__}: {exc}")
        return {"error": f"{type(exc).__name__}: {exc}"}

    return {"seq": entry["seq"], "hash": entry["hash"], "kind": kind,
            "known_kind": kind in audit.KINDS}


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
    return audit_log.summary(FOLDER)


def fn_read(payload: dict) -> dict:
    """Entries, newest last. `kind` and `subject` narrow it."""
    data = payload.get("payload") or payload
    entries, problems = LOG.read()

    if data.get("kind"):
        entries = [e for e in entries if e.get("kind") == data["kind"]]
    if data.get("subject"):
        entries = [e for e in entries if e.get("subject") == data["subject"]]

    limit = int(data.get("limit") or 200)
    return {"entries": entries[-limit:], "total": len(entries), "problems": problems}


def main() -> None:
    url = os.environ.get("III_URL", "ws://localhost:49154")
    worker = register_worker(url, InitOptions(worker_name="ghola-audit"))

    for function_id, handler, description in (
        ("audit::append", fn_append,
         "Record one decision in the append-only, hash-chained log."),
        ("audit::verify", fn_verify,
         "Is the chain intact, and from which entry is it not."),
        ("audit::summary", fn_summary,
         "What the log says: whether it verifies, and what it counts."),
        ("audit::read", fn_read, "Entries, optionally narrowed by kind or subject."),
    ):
        worker.register_function(function_id, handler, description=description)

    check = LOG.verify()
    print(f"ghola-audit started on {url}")
    print(f"  log     : {FOLDER}")
    print(f"  entries : {check.entries} ({'intact' if check.ok else 'BROKEN'})")
    print("  one writer, by construction: this process owns the chain")
    for problem in check.problems[:5]:
        print(f"  PROBLEM: {problem}")
    threading.Event().wait()


if __name__ == "__main__":
    main()
