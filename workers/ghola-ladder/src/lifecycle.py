"""What happens to a primitive after it exists: promote, demote, carry, drop,
add, remove.

**One verb moves either side.** A constraint climbs by having its number changed,
and its generated hook follows. A capability climbs by having its files moved
outward, and its declared layer follows. Both end up further out of reach of the
thing they govern, which is the only thing a rung has ever measured. Which of the
two happens is decided by what the name turns out to be, because a person moving
a thing knows what they are moving and should not have to remember which command
that makes it.

Everything here is a pure function returning a **plan**: the file operations that
would happen, and why. The worker applies it. That split is what lets every
branch of the lifecycle be tested without a filesystem, and it is what lets
`dry_run` be honest rather than a second code path.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from primitive import (
    CAPABILITY,
    CAPABILITY_RUNG_OF_LAYER,
    CONSTRAINT,
    KIND_SIDE,
    LAYERS,
    RUNGS,
    Primitive,
    default_rungs,
    rung_number,
    validate,
)

# A constraint at no rung has been deleted without saying so.
# A capability at no layer has nowhere to ship from.
MOVES = ("promote", "demote", "carry", "drop", "add", "remove")


@dataclass
class Step:
    """One file operation, with the reason it is happening."""

    action: str            # write, move, delete, generate-hook, remove-hook
    path: str
    to: str = ""
    content: str = ""
    why: str = ""


@dataclass
class Plan:
    """What a move would do, before it does it."""

    move: str = ""
    primitive: str = ""
    side: str = ""
    was: tuple = ()
    now: tuple = ()
    steps: list[Step] = field(default_factory=list)
    problems: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.problems

    def refuse(self, why: str) -> "Plan":
        self.problems.append(why)
        return self


def target_rung(p: Primitive, move: str, to=None, at=None) -> tuple[int, ...]:
    """The rungs a primitive would have after this move."""
    if move in ("promote", "demote"):
        return (rung_number(to, p.side),)
    if move == "carry":
        return tuple(sorted(set(p.rungs) | {rung_number(at, p.side)}))
    if move == "drop":
        return tuple(r for r in p.rungs if r != rung_number(at, p.side))
    return p.rungs


def layer_for_rung(rung: int) -> str:
    """A capability's layer, from the rung it is moving to."""
    for layer, number in CAPABILITY_RUNG_OF_LAYER.items():
        if number == rung:
            return layer
    return ""


def plan_move(p: Primitive, move: str, to=None, at=None, force: bool = False,
              layer_roots: dict[str, str] | None = None) -> Plan:
    """The whole lifecycle, as a plan.

    What it refuses, and why each refusal is not a flag to pass:

    - **A mechanical rung with nothing that runs.** It would report itself,
      refuse nothing, and look enforced. The missing half is the work.
    - **`ask` anywhere but rung 3.** Only `pre-trigger` can hold a call, so the
      policy would silently become something else.
    - **Dropping the last rung.** That is a deletion wearing a move's clothes;
      `remove` says it out loud.
    - **A locked primitive.** It is meant to be a deviation somebody sees.
    """
    plan = Plan(move=move, primitive=p.id, side=p.side, was=p.rungs)

    if move not in MOVES:
        return plan.refuse(f"no move {move!r}. Try one of: {', '.join(MOVES)}")
    if p.locked and not force:
        return plan.refuse(
            f"{p.id} is locked. Pass force; it is meant to be a deviation somebody sees")

    if move == "remove":
        plan.now = ()
        plan.steps.append(Step("delete", p.source, why="removed"))
        if p.script:
            plan.steps.append(Step("delete", p.script, why="its script goes with it"))
        plan.notes.append(
            "removal is half the work and the one nobody does unprompted. A "
            "primitive nothing enforces is still loaded into every turn that "
            "touches what it is about")
        return plan

    rungs = target_rung(p, move, to, at)
    plan.now = rungs

    if not rungs:
        return plan.refuse(
            f"{p.id} would be carried by nothing. That is a deletion; say `remove`")
    if rungs == p.rungs:
        plan.notes.append("already there; nothing to do")
        return plan

    moved = Primitive(**{**p.__dict__, "rungs": rungs, "declared_rungs": True})

    # A capability's rung IS its layer, so moving it means moving its files.
    # The rung was never written in them, which is what makes the move the
    # entire edit.
    if p.side == CAPABILITY:
        layer = layer_for_rung(rungs[0])
        if not layer:
            return plan.refuse(
                f"capability rung {rungs[0]} is not a layer. `described` and `tool` "
                "are questions about direction, not about where a file ships from")
        moved = Primitive(**{**moved.__dict__, "layer": layer})
        roots = layer_roots or {}
        if roots.get(layer):
            destination = f"{roots[layer]}/{p.kind}s/{p.id}.md"
            plan.steps.append(Step("move", p.source, to=destination,
                                   why=f"a capability ships from its layer; {layer} is rung {rungs[0]}"))
            if p.script:
                plan.steps.append(Step("move", p.script,
                                       to=destination.replace(".md", ".py"),
                                       why="the script travels with it"))
        else:
            plan.problems.append(
                f"no directory configured for the {layer} layer, so there is "
                "nowhere to move this to")
        plan.notes.append(f"now a {layer} capability: {moved.sees(rungs[0])}")
        return plan

    problems = validate(moved)
    if problems and not force:
        plan.problems.extend(problems)
        plan.notes.append("the missing half is the work, not a flag")
        return plan

    plan.steps.append(Step("write", p.source, content="<the rewritten file>",
                           why=f"rung {list(p.rungs)} becomes {list(rungs)}"))

    # Rung 2 is a hook in the project's own configuration, and a rung changed in
    # the file but not in the generated hook is how a rule ends up at rung 2
    # with nothing mounted. Editing the number by hand skips this, which is the
    # whole reason this move is a function rather than a text editor.
    if 2 in rungs and 2 not in p.rungs:
        plan.steps.append(Step("generate-hook", p.source,
                               why="rung 2 runs from the project's own settings"))
    if 2 in p.rungs and 2 not in rungs:
        plan.steps.append(Step("remove-hook", p.source,
                               why="no longer carried at rung 2"))

    if p.travels:
        plan.notes.append(
            f"this is a {p.layer} primitive: the change reaches every repository")
    for rung in rungs:
        plan.notes.append(f"rung {rung} ({RUNGS[p.side][rung]}) sees {moved.sees(rung)}")
    if len(rungs) > 1:
        plan.notes.append(
            "two rungs is two BOUNDARIES, not two strictnesses. Rungs that differ "
            "only in how hard they push are redundancy that also destroys the "
            "ability to tell which one is working")
    return plan


def plan_add(primitive_id: str, kind: str, layer: str, has_script: bool,
             why: str = "", description: str = "",
             layer_roots: dict[str, str] | None = None) -> Plan:
    """A new primitive, landing on the rung its level and its script imply.

    Both halves are scaffolded when a script is asked for, because a rule and its
    predicate are two files with one name and creating one without the other is
    how a mechanical rung ends up enforcing nothing.
    """
    plan = Plan(move="add", primitive=primitive_id, side=KIND_SIDE.get(kind, CONSTRAINT))
    if kind not in KIND_SIDE:
        return plan.refuse(f"no kind {kind!r}. Try one of: {', '.join(KIND_SIDE)}")
    if layer not in LAYERS:
        return plan.refuse(f"layer must be one of {', '.join(LAYERS)}")
    if not why:
        plan.notes.append(
            "no `why` given. A primitive without one cannot later be demoted or "
            "removed on evidence, because nothing survives contact with it")

    rungs = default_rungs(layer, plan.side, has_script)
    plan.now = rungs

    root = (layer_roots or {}).get(layer, f"rules/{layer}")
    base = f"{root}/{primitive_id}"
    plan.steps.append(Step("write", f"{base}.md", why=f"the {kind}, in prose"))
    if has_script:
        plan.steps.append(Step("write", f"{base}.py",
                               why="the script beside it. Its presence is what makes "
                                   "this feedback rather than feedforward"))
    plan.notes.append(
        f"lands at rung {rungs[0]} ({RUNGS[plan.side][rungs[0]]}), because a "
        f"{layer} primitive {'with' if has_script else 'without'} a script does")
    return plan
