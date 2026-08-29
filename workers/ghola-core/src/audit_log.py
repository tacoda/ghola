"""Writing the audit log. The only part of it that touches a disk.

Kept apart from `audit.py` so the chain, the hashing and the verification stay
pure and testable without a filesystem. What is here is a dozen lines of I/O and
one lock, and it is deliberately boring.

**Files, not the `state` worker.** This is the one store in ghola that is
deliberately not a worker, and the reason is the requirement itself: an audit log
has to survive the thing it is auditing. A worker that can restart, be
reconfigured, or have its retention policy changed by the same operator whose
actions it records is not an independent record. A file with an fsync and a hash
chain is.

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
# log this repository produced.
#
# Two WORKERS append here — the policy worker records what the ladder and the
# approval gate decided, the factory records stage transitions — and they are
# separate processes. Each held its own in-memory tail, so their `prev` hashes
# interleaved and the chain failed its own verification. Multi-writer is the
# normal case here, not an edge case.
#
# So: a thread lock for threads, and an `flock` on a lock file for processes.
# The tail is re-read from disk INSIDE the lock, because another process may
# have appended since this one last looked.
_LOCK = threading.Lock()
LOCK_NAME = ".audit.lock"

# 64 MB, then seal and start another. Chosen so a file stays greppable and loads
# into memory for verification, not for any storage reason.
ROTATE_BYTES = 64 * 1024 * 1024


class AuditLog:
    """An append-only chained log in a directory of sealed JSONL files."""

    def __init__(self, folder: str | Path, rotate_bytes: int = ROTATE_BYTES):
        self.folder = Path(folder)
        self.rotate_bytes = rotate_bytes
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
        result = audit.verify(entries)
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
               detail: dict | None = None, at: int | None = None) -> dict:
        """Add one entry. Returns it, chained and hashed.

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
                        self._tail(), kind,
                        at if at is not None else int(time.time() * 1000),
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


def summary(folder: str | Path) -> dict:
    """What the log says, for `make audit`.

    Both halves of what this log is for: whether it can be trusted, and what it
    counts. An auditor asks the first and an engineer asks the second, and they
    are the same file read two ways.
    """
    log = AuditLog(folder)
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
        "by_kind": audit.tally(entries),
        "refusals_by_rung": audit.refusals_by_rung(entries),
        "by_actor": audit.tally(entries, by="actor"),
    }


def as_json(folder: str | Path) -> str:
    return json.dumps(summary(folder), indent=2)
