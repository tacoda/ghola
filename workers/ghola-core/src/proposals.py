"""What the improve lane produces, and what it is not allowed to do.

A proposal names three things — **where** it goes, **what** it is about, and
**what happens to it** — plus the jobs it came from. Everything else is prose.

**Nothing is applied.** Accepting a proposal writes a spec into `specs/` and
stops there, except a promotion or demotion, which is one number in a file and
becomes a pull request. To become real it goes through the same pipeline as any
other work, gated by the same pull request.

That is the one rule keeping this from being the single thing escaping the
factory's own gate: **the improve lane may not edit the charter, the harness or
the factory on its own authority.**
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

# Where a change goes, and how often you should expect one. Proposals should
# thin out with distance from the project's own code: a run that proposes three
# factory changes and no charter ones is describing the lane distribution being
# wrong, not the factory.
LANES = {
    "charter": ("the TARGET repository's own configuration — CLAUDE.md, its "
                "rules, hooks, skills, commands",
                "constantly. Projects have opinions, and most of what goes "
                "wrong is a thing the repo wanted and never said"),
    "harness": ("how a turn happens — prompts, tool policy, phases, budgets",
                "when the way we build changes: real, rarer, usually an edge "
                "case nobody had hit"),
    "factory": ("how work is delivered — stages, guards, ordering, gates",
                "rarely. Process should be boring; a proposal here is an "
                "improvement to the workflow, not a first resort"),
}

# The primitives a lane is made of.
KINDS = {
    "charter": ("rule", "hook", "skill", "command", "agent", "predicate",
                "convention", "doc"),
    "harness": ("prompt", "tool", "policy", "budget", "context", "phase"),
    "factory": ("stage", "gate", "guard", "ordering", "record"),
}
# A measurement, for what no rule can decide. Valid in any lane.
ANY_LANE = ("eval",)

# Improvement is not only addition, and `remove` is the one nobody does
# unprompted.
ACTIONS = {
    "add": "it was missing",
    "improve": "it exists and is not doing its job",
    "remove": "it costs more than it earns",
    "migrate": "the form is wrong everywhere at once",
    "promote": "a constraint is carried too low to be relied on",
    "demote": "a constraint is carried higher than it earns",
}

# Only these two are applied directly, because each is one number in a file and
# becomes a pull request a human merges. Everything else becomes a spec.
MOVES = ("promote", "demote")

HEADING = re.compile(r"^\s*#{2,3}\s*(?:PROPOSAL\b[:.]?)?\s*(.+?)\s*$", re.MULTILINE)
FIELD = re.compile(r"^\s*[-*]\s*\*{0,2}(lane|kind|action|target|why|evidence|rung)"
                   r"\*{0,2}\s*[:=]\s*(.+?)\s*$", re.MULTILINE | re.IGNORECASE)


@dataclass
class Proposal:
    """One suggested change, traceable to the evidence that raised it."""

    title: str = ""
    lane: str = ""
    kind: str = ""
    action: str = ""
    target: str = ""
    why: str = ""
    evidence: tuple[str, ...] = ()
    rung: str = ""
    body: str = ""

    @property
    def is_move(self) -> bool:
        return self.action in MOVES

    @property
    def prose(self) -> str:
        """The proposal itself, without the fields already read out of it.

        A spec that repeated `- lane: charter` above its own What section would
        be making the reader parse the metadata twice.
        """
        return FIELD.sub("", self.body).strip()

    def problems(self) -> list[str]:
        """Everything that makes this proposal unusable, as sentences."""
        found = []
        if not self.title:
            found.append("no title")
        if self.lane not in LANES:
            found.append(f"lane must be one of {', '.join(LANES)}")
        if self.action not in ACTIONS:
            found.append(f"action must be one of {', '.join(ACTIONS)}")
        if self.lane in KINDS and self.kind not in KINDS[self.lane] + ANY_LANE:
            found.append(f"kind `{self.kind}` is not a {self.lane} primitive. "
                         f"Try: {', '.join(KINDS[self.lane] + ANY_LANE)}")
        if not self.target:
            found.append("no target: a proposal that does not name what it "
                         "changes cannot be acted on")
        if not self.why:
            found.append("no why")
        # The rule that keeps this honest. A proposal nobody can trace back to
        # something that happened is a suggestion, and this lane exists to turn
        # evidence into suggestions rather than the other way round.
        if not self.evidence:
            found.append("no evidence: a proposal that cannot be traced to a "
                         "job or a signal is dropped rather than repaired")
        if self.is_move and not self.rung:
            found.append(f"`{self.action}` needs a rung to move to")
        return found

    @property
    def usable(self) -> bool:
        return not self.problems()


def parse(text: str) -> tuple[list[Proposal], list[str]]:
    """Read proposals out of a turn's answer.

    Deliberately forgiving about shape and strict about content: a proposal
    missing a field is reported by name, and one that cannot be traced to
    evidence is dropped rather than repaired.
    """
    text = str(text or "")
    blocks = split(text)
    found, problems = [], []

    for title, body in blocks:
        fields = {name.lower(): value for name, value in FIELD.findall(body)}
        proposal = Proposal(
            title=title.strip(),
            lane=fields.get("lane", "").strip().lower().strip("`"),
            kind=fields.get("kind", "").strip().lower().strip("`"),
            action=fields.get("action", "").strip().lower().strip("`"),
            target=fields.get("target", "").strip().strip("`"),
            why=fields.get("why", "").strip(),
            rung=fields.get("rung", "").strip().strip("`"),
            evidence=tuple(v.strip() for v in
                           re.split(r"[,;]", fields.get("evidence", ""))
                           if v.strip()),
            body=body.strip(),
        )
        if proposal.usable:
            found.append(proposal)
        else:
            problems.append(f"{title or '(untitled)'}: "
                            f"{'; '.join(proposal.problems())}")

    return found, problems


def split(text: str) -> list[tuple[str, str]]:
    """Headed blocks, each one a proposal."""
    marks = list(HEADING.finditer(text))
    blocks = []
    for index, mark in enumerate(marks):
        end = marks[index + 1].start() if index + 1 < len(marks) else len(text)
        blocks.append((mark.group(1), text[mark.end():end]))
    return blocks


def lane_distribution(found: list[Proposal]) -> dict[str, int]:
    """How many proposals landed in each lane.

    **Proposals should thin out with distance from the project's own code.** A
    run proposing three factory changes and no charter ones is describing the
    lane distribution being wrong rather than the factory.
    """
    counts = {lane: 0 for lane in LANES}
    for proposal in found:
        counts[proposal.lane] = counts.get(proposal.lane, 0) + 1
    return counts


def distribution_note(counts: dict[str, int]) -> str:
    charter, factory = counts.get("charter", 0), counts.get("factory", 0)
    if factory > charter and factory > 1:
        return ("More factory proposals than charter ones. Most of what goes "
                "wrong is a thing the target repository wanted and never said, "
                "so this distribution is usually a sign the lane was picked "
                "wrongly rather than that the process is at fault.")
    return ""


def as_spec(proposal: Proposal) -> str:
    """A proposal, as the spec accepting it writes into `specs/`.

    Accepting does not apply anything. It writes this, and the change goes
    through the same pipeline and the same pull request as any other work.
    """
    return f"""# {proposal.title}

## What

{proposal.action.title()} `{proposal.target}` in the **{proposal.lane}** layer.

{proposal.prose}

## Why

{proposal.why}

## Where this came from

Raised by ghola's improve lane from: {', '.join(proposal.evidence)}.

Nothing was applied. This spec goes through the same pipeline and the same pull
request as any other work, which is the rule that keeps the improve lane from
being the one thing escaping the factory's own gate.

## Acceptance criteria

- `{proposal.target}` reflects the change described above.
- The reason is written down where the next person will find it.
"""


def slug(proposal: Proposal) -> str:
    """The filename a spec gets."""
    stem = re.sub(r"[^a-z0-9]+", "-", proposal.title.lower()).strip("-")
    return (stem or "proposal")[:60]
