"""Writing the audit log. The only part of it that touches a disk.

Kept apart from `audit.py` so the chain, the hashing and the verification stay
pure and testable without a filesystem. What is here is a dozen lines of I/O and
one lock, and it is deliberately boring.

**Files, not a store worker.** An audit log has to survive the thing it is
auditing. A store that can restart, be reconfigured, or have its retention policy
changed by the same operator whose actions it records is not an independent
record. A file with an fsync and a hash chain is.

**The chain and the store cannot be separated**, which is why this worker owns
both. Sequencing needs an authoritative tail, and the tail is re-read from disk
inside the lock below; a chain worker that shipped entries to somebody else's
store would have no such tail, and keeping one in memory is the bug that broke
the first real log this code produced. Durability is worse: property 2 is an
fsync *before* the caller is told the entry landed, and nothing fire-and-forget
can promise that. Fan-out belongs after the write, not instead of it.

Rotation seals a file and starts another. It never deletes one, and the chain
continues across the boundary so a sealed file plus its successors verify as one
history.
"""

from __future__ import annotations

import fcntl
import json
import os
import threading
import time
from pathlib import Path

import audit

# A thread lock is NOT enough, and assuming it was is what broke the first real
# log this code produced. Two workers appended from separate processes, each held
# its own in-memory tail, and their `prev` hashes interleaved: the chain failed
# its own verification while nothing had tampered with it.
#
# One worker owns the chain now, so a second appending process is a deployment
# mistake rather than the normal case. The `flock` stays anyway. A worker makes a
# second writer unlikely rather than impossible, and an invariant this design
# depends on should be enforced rather than assumed.
#
# So: a thread lock for threads, and an `flock` on a lock file for processes. The
# tail is re-read from disk INSIDE the lock, because another process may have
# appended since this one last looked.
_LOCK = threading.Lock()
LOCK_NAME = ".audit.lock"

# 64 MB, then seal and start another. Chosen so a file stays greppable and loads
# into memory for verification, not for any storage reason.
ROTATE_BYTES = 64 * 1024 * 1024


class AuditLog:
    """An append-only chained log in a directory of sealed JSONL files."""

    def __init__(self, folder: str | Path, rotate_bytes: int = ROTATE_BYTES,
                 kinds: tuple[str, ...] = ()):
        self.folder = Path(folder)
        self.rotate_bytes = rotate_bytes
        # The vocabulary this deployment declared, for the unknown-kind note in
        # `verify`. Empty means nobody declared one and nothing is reported.
        self.kinds = kinds
        self._last: dict | None = None
        self._loaded = False

    # ----------------------------------------------------------- reading

    def files(self) -> list[Path]:
        """Every log file, oldest first. The names sort chronologically."""
        if not self.folder.is_dir():
            return []
        return sorted(self.folder.glob("audit-*.jsonl"))  # the lock file is not one

    def current(self) -> Path:
        """The file being appended to, creating the directory if needed."""
        self.folder.mkdir(parents=True, exist_ok=True)
        existing = self.files()
        if existing and existing[-1].stat().st_size < self.rotate_bytes:
            return existing[-1]
        return self.folder / f"audit-{len(existing):05d}.jsonl"

    def read(self) -> tuple[list[dict], list[str]]:
        """The whole history, across every sealed file, in order."""
        entries: list[dict] = []
        problems: list[str] = []
        for path in self.files():
            found, trouble = audit.parse(path.read_text())
            entries.extend(found)
            problems.extend(f"{path.name}: {p}" for p in trouble)
        return entries, problems

    def verify(self) -> audit.Verification:
        """Check the chain across the whole history."""
        entries, problems = self.read()
        result = audit.verify(entries, self.kinds)
        result.problems.extend(problems)
        if problems:
            result.ok = False
        return result

    # ----------------------------------------------------------- writing

    def _tail(self) -> dict | None:
        """The last entry written, so the next one can chain to it.

        Read once from disk on first use rather than kept only in memory,
        because a restarted process that started a fresh chain would produce a
        log whose verification fails at exactly the restart.
        """
        if self._loaded:
            return self._last
        entries, _ = self.read()
        self._last = entries[-1] if entries else None
        self._loaded = True
        return self._last

    def append(self, kind: str, actor: str = "", subject: str = "",
               detail: dict | None = None) -> dict:
        """Add one entry, stamped now. Returns it, chained and hashed.

        The clock is this method's, not the caller's. An entry timed by whoever
        asked for it is an entry whose order the log cannot vouch for, and the
        sequence number is the ordering that matters anyway. `audit.entry` still
        takes an explicit `at`, which is what a replay or an import would use.

        Held under a cross-process lock, and the tail is re-read from disk
        inside it: another worker may have appended since this one last looked,
        and chaining onto a stale tail is how two correct writers produce one
        broken log.

        The write is flushed and fsynced before returning, because an entry lost
        in a page cache during a crash is an entry that never existed, and the
        caller has already acted on the decision it records.
        """
        with _LOCK:
            self.folder.mkdir(parents=True, exist_ok=True)
            with (self.folder / LOCK_NAME).open("a+") as guard:
                fcntl.flock(guard.fileno(), fcntl.LOCK_EX)
                try:
                    # Always from disk. The in-memory tail is an optimisation
                    # that is wrong the moment a second writer exists.
                    self._loaded = False
                    item = audit.next_entry(
                        self._tail(), kind, int(time.time() * 1000),
                        actor=actor, subject=subject, detail=detail or {})

                    path = self.current()
                    with path.open("a", encoding="utf-8") as handle:
                        handle.write(audit.as_line(item))
                        handle.flush()
                        os.fsync(handle.fileno())

                    self._last = item
                    self._loaded = True
                    return item
                finally:
                    fcntl.flock(guard.fileno(), fcntl.LOCK_UN)


def summary(folder: str | Path, kinds: tuple[str, ...] = (),
            breakdowns: tuple[str, ...] = ("kind", "actor")) -> dict:
    """What the log says.

    Both halves of what this log is for: whether it can be trusted, and what it
    counts. An auditor asks the first and an engineer asks the second, and they
    are the same file read two ways.

    `breakdowns` names the fields to count by, because the interesting ones are a
    deployment's own vocabulary rather than anything this module can guess. Each
    is read from the top level of an entry or out of its `detail`.
    """
    log = AuditLog(folder, kinds=kinds)
    entries, _problems = log.read()
    check = log.verify()
    return {
        "entries": len(entries),
        "files": [p.name for p in log.files()],
        "verified": check.ok,
        "verified_through": check.verified_through,
        "problems": check.problems,
        "first_at": entries[0]["at"] if entries else None,
        "last_at": entries[-1]["at"] if entries else None,
        "by": {field: audit.tally(entries, by=field) for field in breakdowns},
    }


def as_json(folder: str | Path, **kwargs) -> str:
    return json.dumps(summary(folder, **kwargs), indent=2)
