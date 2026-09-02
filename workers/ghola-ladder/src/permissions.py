"""A repository's own `permissions`, read as constraints on the ladder.

A repository that uses Claude Code has already written down what it does not
want an agent doing, in `.agents/settings.json`:

    {"permissions": {"deny": ["Bash", "Bash(php *)"], "ask": ["Write(prod/**)"]}}

Those are constraints. They are not rule files, they have no `why` and no rung,
and honouring them is the difference between a ladder that respects what a
project already said and one that makes the project say it again.

**They land at two different rungs, because the entries are two different kinds
of thing.**

`Bash` names a whole tool, so it is *withheld*: rung 1, the capability is not
there, nothing to refuse and nothing to argue past. `Bash(php *)` names an
argument, and dropping the shell because one command pattern is denied would be
a different and much larger rule, so it is carried at rung 2 and the matching
call is refused.

`ask` subtracts like `deny`. There is no human inside an unattended turn, and a
factory reading "ask" as "yes" has answered a question nobody put. A deployment
with a person watching can lift that by carrying the entry at rung 3 with
`policy: ask`, which is what the approval worker is for.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field

import toolnames
from primitive import Primitive

# `allow` is not read. An allow list in a repository's settings says what Claude
# Code may do there, not what this ladder must permit, and reading it as a grant
# would let a repository widen its own permissions by writing a file.
SUBTRACTING = ("deny", "ask")


@dataclass
class Permissions:
    """What a repository's settings take away, sorted by which rung can do it."""

    withheld: list[str] = field(default_factory=list)      # rung 1: whole tools
    refused: list[str] = field(default_factory=list)       # rung 2: argument patterns
    unresolved: list[str] = field(default_factory=list)    # names reaching nothing
    source: str = ""

    @property
    def empty(self) -> bool:
        return not (self.withheld or self.refused)


def parse(text: str, source: str = "") -> Permissions:
    """Read `.agents/settings.json`. A missing or malformed file is empty.

    Malformed is deliberately not an error. This file belongs to the target
    repository and ghola is a guest in it; refusing to run because somebody's
    settings have a trailing comma would be the wrong failure.
    """
    result = Permissions(source=source)
    try:
        block = (json.loads(text) or {}).get("permissions") or {}
    except (json.JSONDecodeError, TypeError, AttributeError):
        return result

    seen: set[str] = set()
    for key in SUBTRACTING:
        for entry in block.get(key) or []:
            entry = str(entry).strip()
            if not entry or entry in seen:
                continue
            seen.add(entry)

            if not toolnames.functions_for(entry.split("(")[0].strip()):
                # A name reaching no function enforces nothing. Reported, because
                # failing silently here is the exact shape this model is against.
                result.unresolved.append(entry)
                continue

            # The whole tool, or one of its arguments. That distinction is the
            # only thing deciding which rung can carry it.
            (result.refused if "(" in entry else result.withheld).append(entry)

    return result


def withheld_functions(perms: Permissions) -> list[str]:
    """Every iii function a rung-1 entry takes away.

    This is the join between the two ladders: a constraint withholding `Write`
    and a phase never granted `coder::create-file` are one mechanism seen from
    opposite ends.
    """
    functions: list[str] = []
    for entry in perms.withheld:
        functions.extend(toolnames.functions_for(entry))
    return sorted(set(functions))


def as_primitives(perms: Permissions) -> list[Primitive]:
    """The entries, as constraints the rest of the ladder can reason about.

    Synthesised rather than authored, so they carry a `why` explaining where they
    came from. Without one they would be the only primitives on the ladder that
    cannot be demoted or removed on evidence, and `validate` would report every
    one of them as a problem the operator cannot fix.
    """
    made: list[Primitive] = []

    if perms.withheld:
        made.append(Primitive(
            id="repo-permissions-withheld",
            kind="rule",
            layer="project",
            description=("This repository's own settings withhold "
                         f"{', '.join(perms.withheld)}"),
            why=("The repository wrote this in .agents/settings.json to keep an "
                 "agent away from something. Honouring it is the difference "
                 "between a ladder that respects what a project already said and "
                 "one that makes the project say it again."),
            rungs=(1,),
            withholds=tuple(withheld_functions(perms)),
            source=perms.source,
            declared_rungs=True,
        ))

    for entry in perms.refused:
        made.append(Primitive(
            id=f"repo-permissions-{entry}",
            kind="rule",
            layer="project",
            description=(f"This repository's `permissions` say deny for `{entry}`"),
            why=("The repository wrote this in .agents/settings.json. Use whatever "
                 "it offers instead, usually a make target, or say in your summary "
                 "why the work cannot be done without this."),
            rungs=(2,),
            functions=tuple(toolnames.functions_for(entry.split("(")[0].strip())),
            # The pattern travels in `paths` because that is where the rest of the
            # ladder looks for "what is this about". It is matched by `refuses`
            # below rather than by path globbing.
            paths=(),
            source=perms.source,
            declared_rungs=True,
        ))

    return made


def refuses(perms: Permissions, function_id: str, arguments: dict) -> str:
    """The entry refusing this call, or an empty string.

    Rung 2's decision. Kept as a function rather than a predicate file because
    there is nothing to write to disk: the rule is the repository's settings, and
    this is the mechanism reading them.
    """
    for entry in perms.refused:
        if toolnames.matches(entry, function_id, arguments):
            return entry
    return ""
