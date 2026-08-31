"""Every agent primitive, on one model.

A **constraint** is what an agent may not do. A **capability** is what it may.
They are usually built as unrelated features and they are the same shape: a
ladder of decreasing reliance on a model choosing correctly, owned by one of
three levels, carried either by telling or by running.

Every primitive answers five questions, and **only one of them is written down**.

| axis | question | values | how it is known |
|---|---|---|---|
| **kind** | what sort of thing? | rule, command, skill, agent, mcp, eval | the directory |
| **side** | may not, or may? | constraint, capability | follows from the kind |
| **layer** | whose is it? | project, team, org | the directory, or `layer:` |
| **rung** | where is it carried? | a number, per side | the layer, plus whether a script exists |
| **direction** | told, or run? | feedforward, feedback | whether a script exists |

The rest are derived because **a field can disagree with the file it is in**. A
`direction: feedback` on a rule with no script is exactly the claim this model
exists to make impossible, so nothing is allowed to make it. Dropping a `.py`
beside a `.md` moves a rule from prose to hook and from feedforward to feedback,
with nothing else edited. That pairing is the whole declaration.
"""

from __future__ import annotations

import fnmatch
from dataclasses import dataclass, field

# ------------------------------------------------------------------ sides

CONSTRAINT = "constraint"
CAPABILITY = "capability"

# The kind decides the side, so nothing declares it. A rule says what may not
# happen; everything else offers something the model may reach for.
KIND_SIDE = {
    "rule": CONSTRAINT,
    "command": CAPABILITY,
    "skill": CAPABILITY,
    "agent": CAPABILITY,
    "mcp": CAPABILITY,
    # A measurement, for what no rule can decide. It constrains nothing by
    # itself and reports on what happened, which makes it a capability whose
    # whole point is feedback.
    "eval": CAPABILITY,
}

# Two kinds nobody authors. They are the same file seen after it has been
# carried somewhere, which is why nothing can create one directly.
DERIVED_KINDS = {
    "hook": "a constraint's script, mounted in the project's own settings",
    "tool": "a capability's script, registered on the bus",
}

# --------------------------------------------------------------- the ladders

# What an agent may not do. Rung 0 is the only feedforward rung, which is
# exactly why it is 0: the one that cannot be counted, only hoped for.
CONSTRAINT_RUNGS = {
    0: "prose",
    1: "grant",
    2: "hook",
    3: "turn",
    4: "delivery",
    5: "ci",
}
CONSTRAINT_SEES = {
    0: "nothing. It is stated, and nothing enforces it",
    1: "nothing. The function was never granted, so there is no call to inspect",
    2: "whatever the project's own hook is given",
    3: "one function call and its arguments, before the target runs",
    4: "the finished diff, and what is about to be published",
    5: "the pull request, from outside the machine",
}

# What an agent may do. On this side **the rung is the level**, and that is the
# whole of it: `project`, `team` and `org` are the three places a capability can
# ship from. The two rungs outside that identity are not levels and never could
# be — `described` is a capability with no file, and `tool` is registered code.
CAPABILITY_RUNGS = {
    0: "described",
    1: "project",
    2: "team",
    3: "org",
    4: "tool",
}
CAPABILITY_SEES = {
    0: "text the model reads. It must choose to, and choose right",
    1: "the project's own files. The project can delete it",
    2: "the team's, travelling to every repository. A project cannot remove it",
    3: "the org's, running whether or not a turn wants it",
    4: "registered code. It does one thing, identically",
}

RUNGS = {CONSTRAINT: CONSTRAINT_RUNGS, CAPABILITY: CAPABILITY_RUNGS}
SEES = {CONSTRAINT: CONSTRAINT_SEES, CAPABILITY: CAPABILITY_SEES}

# The capability side's identity: a layer IS a rung. Promoting a capability
# means moving its files outward, and the rung was never written in them, which
# is exactly what makes the move the entire edit.
CAPABILITY_RUNG_OF_LAYER = {"project": 1, "team": 2, "org": 3}

# One axis, two vocabularies. `layer` answers "whose is this"; `level` answers
# "which of the three things carries it". Both spellings work everywhere.
LAYERS = ("project", "team", "org")
LEVEL_OF_LAYER = {"project": "charter", "team": "harness", "org": "factory"}
LAYER_OF_LEVEL = {v: k for k, v in LEVEL_OF_LAYER.items()}

# The rung a constraint lands on when it names none: the level decides, plus
# whether there is a script. `ci` is never implied — it runs outside entirely,
# so putting something there is a choice somebody makes rather than a default
# they fall into.
DEFAULT_CONSTRAINT_RUNG = {
    ("project", True): 2,   # hook
    ("project", False): 0,
    ("team", True): 3,      # turn
    ("team", False): 0,
    ("org", True): 4,       # delivery
    ("org", False): 0,
}

# ----------------------------------------------------------- direction

FEEDFORWARD = "feedforward"
FEEDBACK = "feedback"

# A feedback check is either code or a judgment. `deterministic` is a script:
# the answer does not depend on anybody's opinion. `inferential` is a model
# grading against a description, for what no predicate can decide — and it is
# weaker evidence, so it is named rather than blended in.
DETERMINISTIC = "deterministic"
INFERENTIAL = "inferential"

POLICIES = ("refuse", "ask", "warn")
HOLDABLE_RUNG = 3  # only `pre-trigger` can park a call and wait for a person


class LadderError(ValueError):
    """A primitive that cannot be trusted to mean what it says."""


def rung_number(value, side: str = CONSTRAINT) -> int:
    """A rung written either way. `3` and `turn` are one declaration.

    The number is what a record compares and the name is what a person reads.
    Insisting on the number made every command a lookup.
    """
    names = {name: number for number, name in RUNGS[side].items()}
    if isinstance(value, bool):
        raise LadderError(f"not a rung: {value!r}")
    if isinstance(value, int):
        if value not in RUNGS[side]:
            raise LadderError(f"no {side} rung {value}. Rungs are 0 to {max(RUNGS[side])}")
        return value
    name = str(value).strip().lower()
    if name.isdigit():
        return rung_number(int(name), side)
    if name in LAYER_OF_LEVEL:                      # `harness` means its layer
        name = LAYER_OF_LEVEL[name]
    if name in names:
        return names[name]
    raise LadderError(f"no {side} rung {value!r}. Try one of: {', '.join(names)}")


@dataclass(frozen=True)
class Primitive:
    """One rule, command, skill, agent, mcp or eval, as its files declare it."""

    id: str
    kind: str = "rule"
    layer: str = "project"
    description: str = ""
    why: str = ""
    body: str = ""

    # Derived from the filesystem, never declared. `script` is the path to the
    # `.py` sitting beside the `.md`, and its presence is what makes this
    # feedback rather than feedforward.
    script: str = ""
    # An inferential check names what a model should grade against instead of
    # shipping code. Both are feedback; only one is deterministic.
    grades: str = ""

    rungs: tuple[int, ...] = ()
    policy: str = "refuse"
    paths: tuple[str, ...] = ()
    functions: tuple[str, ...] = ()
    # Constraint rung 1 and the capability floor are one mechanism seen from
    # opposite ends: withholding a function and never granting it resolve to the
    # same question, "is this in the allow list".
    withholds: tuple[str, ...] = ()
    escape: str = ""
    locked: bool = False
    # Specialisation: this says HOW a higher rule is met here, and both stay in
    # force. Different in kind from adaptation, which replaces.
    implements: str = ""
    source: str = ""
    narrowed_from: str = ""
    declared_rungs: bool = False

    @property
    def side(self) -> str:
        return KIND_SIDE.get(self.kind, CONSTRAINT)

    @property
    def level(self) -> str:
        return LEVEL_OF_LAYER.get(self.layer, "charter")

    @property
    def direction(self) -> str:
        """Told, or run. Derived, so nothing can label itself measured."""
        return FEEDBACK if (self.script or self.grades) else FEEDFORWARD

    @property
    def determinism(self) -> str:
        """How much the feedback is worth. Feedforward has none to report."""
        if self.script:
            return DETERMINISTIC
        if self.grades:
            return INFERENTIAL
        return ""

    @property
    def measured(self) -> bool:
        """Whether anything at all checks this, rather than hoping."""
        return self.direction == FEEDBACK

    @property
    def travels(self) -> bool:
        return self.layer in ("team", "org")

    @property
    def rung_names(self) -> tuple[str, ...]:
        return tuple(RUNGS[self.side][r] for r in self.rungs)

    def sees(self, rung: int) -> str:
        return SEES[self.side].get(rung, "")

    def governs_path(self, path: str) -> bool:
        """A primitive with no `paths` governs everything, which is the right
        default: a rule about how code is written should not have to enumerate
        the tree."""
        return not self.paths or any(fnmatch.fnmatch(path, p) for p in self.paths)

    def governs_function(self, function_id: str) -> bool:
        return not self.functions or any(fnmatch.fnmatch(function_id, p) for p in self.functions)

    def carried_at(self, rung) -> bool:
        return rung_number(rung, self.side) in self.rungs

    def says(self, finding: str = "") -> str:
        """The refusal the model reads, in the primitive's own words.

        A refusal that only says "denied" teaches the model to retry. One that
        says what and why teaches it to adapt.
        """
        parts = [f"{self.description or self.id}."]
        if finding:
            parts.append(finding)
        if self.why:
            parts.append(f"Why: {self.why}")
        if self.escape:
            parts.append(f"If this is genuinely an exception, say so with "
                         f"`{self.escape}` and give the reason in your summary.")
        return " ".join(parts)


def default_rungs(layer: str, side: str, has_script: bool) -> tuple[int, ...]:
    """Where a primitive lands when it names no rung.

    A capability's rung IS its layer, so there is nothing to choose. A
    constraint's depends on the level and on whether a script exists.
    """
    if side == CAPABILITY:
        return (CAPABILITY_RUNG_OF_LAYER.get(layer, 1),)
    return (DEFAULT_CONSTRAINT_RUNG.get((layer, has_script), 0),)


def validate(p: Primitive) -> list[str]:
    """Everything wrong with a primitive, as sentences a person can act on.

    Returned rather than raised, so one bad file reports itself instead of
    stopping the loader and taking every other primitive with it.
    """
    problems = []

    if not p.id:
        problems.append("a primitive needs an id")
    if p.kind not in KIND_SIDE:
        if p.kind in DERIVED_KINDS:
            problems.append(f"`{p.kind}` is derived: {DERIVED_KINDS[p.kind]}. "
                            "It is not something anyone authors")
        else:
            problems.append(f"no kind {p.kind!r}. Try one of: {', '.join(KIND_SIDE)}")
    if p.layer not in LAYERS:
        problems.append(f"layer must be one of {', '.join(LAYERS)}")
    if not p.rungs:
        problems.append("carried by nothing")

    for rung in p.rungs:
        if rung not in RUNGS[p.side]:
            problems.append(f"rung {rung} is not on the {p.side} ladder")

    if p.side == CONSTRAINT:
        # The check that matters most. Such a rule reports itself, refuses
        # nothing, and looks enforced on every dashboard.
        mechanical = [r for r in p.rungs if r in (2, 3, 4, 5)]
        if mechanical and p.direction == FEEDFORWARD:
            carried = ", ".join(f"{r} ({CONSTRAINT_RUNGS[r]})" for r in mechanical)
            problems.append(
                f"rung {carried} enforces by running something, and nothing here "
                f"runs. Put a script beside {p.id}.md, or drop to prose")

        if p.policy not in POLICIES:
            problems.append(f"policy must be one of {', '.join(POLICIES)}")
        if p.policy == "ask" and tuple(p.rungs) != (HOLDABLE_RUNG,):
            problems.append(
                "policy `ask` parks a call until a person answers, and only rung 3 "
                "can hold a call. Carry it at rung 3, or use `refuse`")
        if 1 in p.rungs and not p.withholds:
            problems.append("rung 1 withholds a function and this names none, so it "
                            "takes nothing away")

    if p.side == CAPABILITY and p.rungs and p.rungs[0] in (1, 2, 3):
        expected = CAPABILITY_RUNG_OF_LAYER.get(p.layer)
        if expected and p.rungs[0] != expected:
            problems.append(
                f"a capability's rung is its layer: {p.layer} is rung {expected}, "
                f"not {p.rungs[0]}. Move the files to move the rung")

    if p.implements == p.id:
        problems.append("implements its own id")
    if not p.why:
        problems.append("no `why`, so it cannot be demoted or removed on evidence")

    return problems
