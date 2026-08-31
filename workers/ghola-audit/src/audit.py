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

Everything in this module is pure. The writer is a dozen lines in `audit_log.py`,
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


@dataclass
class Event:
    """What happened, as the caller describes it.

    Kept apart from where it lands in the chain, because that half belongs to the
    log and this half belongs to the caller. Nothing here can be derived from the
    entries around it, and nothing about the chain position can be derived from
    here.

    `actor` is who or what decided: a worker name, a rule id, a person. `subject`
    is what it was about: a job, a session, a path. Both are strings rather than
    a nested shape because an audit log is read by grep at least as often as by
    a program.
    """

    kind: str
    at: int
    actor: str = ""
    subject: str = ""
    detail: dict = field(default_factory=dict)


def entry(seq: int, previous: str, event: Event) -> dict:
    """One audit entry, hashed and chained to its predecessor."""
    body = {
        "v": VERSION,
        "seq": seq,
        "prev": previous,
        "kind": event.kind,
        "at": event.at,
        "actor": event.actor,
        "subject": event.subject,
        "detail": event.detail or {},
    }
    # The hash covers everything above INCLUDING `prev`, which is what makes the
    # chain a chain rather than a list of independently signed rows.
    return {**body, "hash": digest(body)}


def next_entry(previous_entry: dict | None, kind: str, at: int, **fields) -> dict:
    """The next entry after this one, or the first.

    The front door. A caller names what happened; where it goes is worked out
    here, which is the only place that can know.
    """
    event = Event(kind, at, **fields)
    if previous_entry is None:
        return entry(0, GENESIS, event)
    return entry(int(previous_entry["seq"]) + 1, str(previous_entry["hash"]), event)


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


def verify(entries: list[dict], kinds: tuple[str, ...] = ()) -> Verification:
    """Check the chain. Reports the first break rather than only a boolean.

    A verifier that answers yes or no is useless in an audit, where the question
    is always "what exactly are you claiming, and from when". This names the
    entry, so a reader knows which decisions still stand.

    `kinds` is the vocabulary this deployment declared, and an empty one turns
    the check off rather than making everything unknown. Nobody said what counts
    as a known kind here, so there is nothing to report — the same distinction
    between "I looked and found none" and "I did not look".
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
        if kinds and item.get("kind") not in kinds:
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

def tally(entries: list[dict], by: str = "kind", kind: str = "") -> dict[str, int]:
    """Counts, for the analysis half of what this log is for.

    The audit and the statistics are the same data read two ways, which is the
    argument for one log rather than a log and a metrics pipeline that disagree.

    `by` reads a top-level field or, failing that, one out of `detail`, so a
    caller counts its own vocabulary without this module having to know it.
    `kind` narrows first: counting rungs across every entry and counting them
    across refusals are different questions, and only the second has an answer.
    """
    counts: dict[str, int] = {}
    for item in entries:
        if kind and item.get("kind") != kind:
            continue
        key = str(item.get(by) or item.get("detail", {}).get(by) or "")
        if key:
            counts[key] = counts.get(key, 0) + 1
    return dict(sorted(counts.items(), key=lambda kv: (-kv[1], kv[0])))
