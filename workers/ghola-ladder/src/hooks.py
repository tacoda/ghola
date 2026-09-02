"""A repository's own hooks, read as constraints on the ladder.

The sibling of `permissions.py`, over the other key in the same file. A
repository that uses Claude Code has already declared its hooks in
`.agents/settings.json`, in Claude Code's own shape:

    {"hooks": {"PreToolUse": [
        {"matcher": "Bash",
         "hooks": [{"type": "command", "command": ".agents/hooks/no-force-push.sh"}]}
    ]}}

Those are rung 2. A hook is the definition of that rung on this model: the
repository's own mechanism, given whatever the tool hands it, refusing before
the target runs. Reading them is the difference between a ladder that shows
every mechanism a repository has and one that shows only the mechanisms ghola
happens to own.

**ghola does not run them, and says so in every `why` it writes.** These are
carried by whichever harness the repository runs them under, and a ghola turn is
not that harness. So the rung is real and the runner is somebody else, which is
exactly the case `measured` exists to distinguish: the primitive is feedback,
and no predicate of ours is behind it.

Reading a hook whose command ghola cannot see is worse than not reading it, so a
missing script is reported the way an unresolved permission entry is.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field

from primitive import Primitive

# The events a hook can bind to. Claude Code's set, because the point is to read
# what a repository already wrote rather than to invent a vocabulary for it. An
# event outside this list is reported instead of dropped: a typo in an event name
# is a hook that silently never fires.
EVENTS = (
    "PreToolUse",
    "PostToolUse",
    "UserPromptSubmit",
    "Notification",
    "Stop",
    "SubagentStop",
    "SessionStart",
    "SessionEnd",
    "PreCompact",
)

# The one event that can refuse anything. The rest observe, and a constraint
# that cannot refuse is a rung 0 constraint whatever file it was declared in.
REFUSING = ("PreToolUse",)


@dataclass
class Hook:
    """One command, and what it is bound to."""

    event: str = ""
    matcher: str = ""
    command: str = ""

    @property
    def id(self) -> str:
        """Stable, and readable in `ladder::list`.

        The matcher travels because two hooks on one event are the normal case
        and an id that collapsed them would hide one.
        """
        tail = self.matcher.strip() or "any"
        return f"repo-hook-{self.event}-{tail}".replace(" ", "-").lower()


@dataclass
class Hooks:
    """Every hook a repository declared, and what is wrong with the rest."""

    found: list[Hook] = field(default_factory=list)
    problems: list[str] = field(default_factory=list)
    source: str = ""

    @property
    def empty(self) -> bool:
        return not self.found


def parse(text: str, source: str = "") -> Hooks:
    """Read the `hooks` block. A missing or malformed file is empty.

    Malformed is deliberately not an error, for the reason `permissions.parse`
    gives: this file belongs to the target repository and ghola is a guest in
    it. Refusing to run because somebody's settings have a trailing comma would
    be the wrong failure.
    """
    result = Hooks(source=source)
    try:
        block = (json.loads(text) or {}).get("hooks") or {}
    except (json.JSONDecodeError, TypeError, AttributeError):
        return result
    if not isinstance(block, dict):
        return result

    for event, entries in block.items():
        event = str(event).strip()
        if event not in EVENTS:
            result.problems.append(
                f"{source}: `{event}` is not a hook event, so nothing it lists "
                f"will ever fire. One of: {', '.join(EVENTS)}")
            continue

        for entry in entries or []:
            if not isinstance(entry, dict):
                continue
            matcher = str(entry.get("matcher") or "").strip()
            for command in entry.get("hooks") or []:
                if not isinstance(command, dict):
                    continue
                line = str(command.get("command") or "").strip()
                if not line:
                    result.problems.append(
                        f"{source}: a {event} hook has no `command`, so it is a "
                        "declaration with nothing behind it")
                    continue
                result.found.append(Hook(event=event, matcher=matcher, command=line))

    return result


def as_primitives(hooks: Hooks) -> list[Primitive]:
    """The hooks, as constraints the rest of the ladder can reason about.

    Synthesised rather than authored, so each carries a `why` naming where it
    came from and who runs it. Without one they would be the only primitives on
    the ladder that cannot be demoted or removed on evidence, which is the same
    reason `permissions.as_primitives` writes one.

    A refusing event lands at rung 2. Everything else observes, so it lands at
    rung 0: a hook that cannot say no is prose about a mechanism, and putting it
    at 2 would be the ladder claiming enforcement nothing performs.
    """
    made: list[Primitive] = []

    for hook in hooks.found:
        refuses = hook.event in REFUSING
        about = f"`{hook.matcher}`" if hook.matcher else "every call"
        made.append(Primitive(
            id=hook.id,
            kind="rule",
            layer="project",
            description=(f"This repository runs `{hook.command}` on "
                         f"{hook.event} for {about}"),
            why=("The repository declared this hook in .agents/settings.json. "
                 "ghola does not run it: whichever harness the repository uses "
                 "does, and a ghola turn is not that harness. It is on the "
                 "ladder so the mechanism is visible rather than assumed."),
            rungs=(2,) if refuses else (0,),
            source=hooks.source,
            declared_rungs=True,
        ))

    return made


def missing_scripts(hooks: Hooks, exists) -> list[str]:
    """Hooks whose command names a file that is not there.

    `exists(path) -> bool` is handed in so this stays testable without a
    repository. Only a command that looks like a path is checked: `jq .` is a
    program on the PATH and not this module's business.
    """
    problems = []
    for hook in hooks.found:
        first = hook.command.split()[0] if hook.command.split() else ""
        if not first.startswith((".", "/")) or exists(first):
            continue
        problems.append(
            f"{hooks.source}: the {hook.event} hook points at `{first}`, which is "
            "not there. It is declared and it cannot run")
    return problems
