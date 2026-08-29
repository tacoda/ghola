"""An append-only, tamper-evident record of everything that was decided.

Session transcripts are not this. They are prunable, they are scoped to a
session, and they record what was *said* rather than what was *decided*. An
external auditor asking "who allowed this to ship, and on what evidence" cannot
be answered from a store that a retention policy is allowed to empty.

Three properties, and the third is the one people skip:

1. **Append-only.** Entries are added and never rewritten. Rotation seals a file
   and starts another; it does not delete one.
2. **Durable.** Each line is flushed and fsynced before the caller is told the
   entry landed, because an audit entry lost in a page cache during a crash is
   an audit entry that never existed.
3. **Chained.** Each entry carries the hash of the one before it. **An
   append-only file you can edit is not an audit log**, and without the chain the
   honest claim is "nothing here has been changed as far as we know", which is
   not a claim an auditor accepts. With it, any edit, reorder or deletion breaks
   verification at a nameable line.

Everything in this module is pure. The writer is a dozen lines in the caller,
which is what lets the chain be verified in a test without a filesystem.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field

# Bumped when the entry shape changes in a way that would break an old reader.
# An audit log spanning a format change has to say where the change happened.
VERSION = 1

# The chain starts somewhere, and it has to be a constant rather than a random
# value, or two logs cannot be compared and a truncated log cannot be told from
# a fresh one.
GENESIS = "0" * 64

# What gets recorded. Not an exhaustive list of events, but the ones a governed
# system must be able to answer for: who decided, what was refused, what shipped.
KINDS = (
    "turn.started",
    "turn.completed",
    "ladder.refused",       # a constraint refused a call, and which rung
    "ladder.warned",
    "approval.held",        # a call parked for a person
    "approval.resolved",    # and what they said
    "governance.verified",  # a promote-class call proved itself
    "governance.denied",
    "stage.entered",
    "stage.left",
    "published",            # a pull request, a comment, a branch landed
    "config.changed",       # somebody moved a rung, or the oversight dial
)


def canonical(payload: dict) -> str:
    """The bytes a hash is taken over.

    Sorted keys and no incidental whitespace, so the same entry hashes the same
    on any machine and in any Python version. A chain that depends on dict
    ordering is a chain that breaks when somebody upgrades.
    """
    return json.dumps(payload, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=False, default=str)


def digest(payload: dict) -> str:
    return hashlib.sha256(canonical(payload).encode("utf-8")).hexdigest()


def entry(seq: int, previous: str, kind: str, at: int, actor: str = "",
          subject: str = "", detail: dict | None = None) -> dict:
    """One audit entry, hashed and chained to its predecessor.

    `actor` is who or what decided: a worker name, a rule id, a person. `subject`
    is what it was about: a job, a session, a path. Both are strings rather than
    a nested shape because an audit log is read by grep at least as often as by
    a program.
    """
    body = {
        "v": VERSION,
        "seq": seq,
        "prev": previous,
        "kind": kind,
        "at": at,
        "actor": actor,
        "subject": subject,
        "detail": detail or {},
    }
    # The hash covers everything above INCLUDING `prev`, which is what makes the
    # chain a chain rather than a list of independently signed rows.
    return {**body, "hash": digest(body)}


def next_entry(previous_entry: dict | None, kind: str, at: int, **fields) -> dict:
    """The next entry after this one, or the first."""
    if previous_entry is None:
        return entry(0, GENESIS, kind, at, **fields)
    return entry(int(previous_entry["seq"]) + 1, str(previous_entry["hash"]),
                 kind, at, **fields)


@dataclass
class Verification:
    """What a reader can say about a log, and where it stops being able to."""

    entries: int = 0
    ok: bool = True
    problems: list[str] = field(default_factory=list)
    # The last sequence number that verified. Everything after it is unproven
    # rather than proven false, and saying so is the honest report.
    verified_through: int = -1

    def fail(self, seq: int, why: str) -> "Verification":
        self.ok = False
        self.problems.append(f"entry {seq}: {why}")
        return self


def verify(entries: list[dict]) -> Verification:
    """Check the chain. Reports the first break rather than only a boolean.

    A verifier that answers yes or no is useless in an audit, where the question
    is always "what exactly are you claiming, and from when". This names the
    entry, so a reader knows which decisions still stand.
    """
    result = Verification(entries=len(entries))
    expected_prev = GENESIS

    for index, item in enumerate(entries):
        seq = item.get("seq", index)

        if item.get("seq") != index:
            result.fail(seq, f"out of order: expected seq {index}")
            return result
        if item.get("prev") != expected_prev:
            result.fail(seq, "does not follow the entry before it. Something was "
                             "inserted, removed, or reordered")
            return result

        body = {k: v for k, v in item.items() if k != "hash"}
        if digest(body) != item.get("hash"):
            result.fail(seq, "its contents do not match its hash. It was edited")
            return result
        if item.get("kind") not in KINDS:
            # Not fatal. An unknown kind is a newer writer, not a tampered
            # entry, and refusing to verify a log because it mentions an event
            # this reader has not heard of would make the format unupgradeable.
            result.problems.append(f"entry {seq}: unknown kind {item.get('kind')!r}")

        expected_prev = str(item["hash"])
        result.verified_through = index

    return result


def parse(text: str) -> tuple[list[dict], list[str]]:
    """Read a JSONL log. A malformed line is reported and skipped.

    Skipped rather than fatal, because a truncated last line is what a crash
    mid-append looks like, and refusing to read the whole log because of it
    would lose every entry that did land.
    """
    entries, problems = [], []
    for number, line in enumerate(text.splitlines(), 1):
        line = line.strip()
        if not line:
            continue
        try:
            entries.append(json.loads(line))
        except json.JSONDecodeError as exc:
            problems.append(f"line {number}: not valid JSON ({exc.msg}). Skipped, "
                            "which is what a crash mid-append looks like")
    return entries, problems


def as_line(item: dict) -> str:
    """One entry as a JSONL line, ready to append."""
    return canonical(item) + "\n"


# ------------------------------------------------------------- statistics

def tally(entries: list[dict], by: str = "kind") -> dict[str, int]:
    """Counts, for the analysis half of what this log is for.

    The audit and the statistics are the same data read two ways, which is the
    argument for one log rather than a log and a metrics pipeline that disagree.
    """
    counts: dict[str, int] = {}
    for item in entries:
        key = str(item.get(by) or item.get("detail", {}).get(by) or "")
        if key:
            counts[key] = counts.get(key, 0) + 1
    return dict(sorted(counts.items(), key=lambda kv: (-kv[1], kv[0])))


def refusals_by_rung(entries: list[dict]) -> dict[str, int]:
    """What each rung actually caught.

    The number the ladder is for. A rung carried as a backstop that starts doing
    all the work is a signal about how turns are writing, not an argument for
    tightening anything, and neither reading is available without this count.
    """
    counts: dict[str, int] = {}
    for item in entries:
        if item.get("kind") != "ladder.refused":
            continue
        rung = str(item.get("detail", {}).get("rung", "?"))
        counts[rung] = counts.get(rung, 0) + 1
    return dict(sorted(counts.items()))
