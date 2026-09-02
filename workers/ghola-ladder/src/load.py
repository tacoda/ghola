"""Finding primitives, and deciding which one wins when two share an id.

The only module here that touches a filesystem. Everything it produces is a plain
`Primitive`, so every question about what the ladder *means* is answered without
a directory existing.

**A primitive is two files with one name**, sitting next to each other:

    rules/no-secrets.md      the constraint, in prose
    rules/no-secrets.py      def check(path, content, context) -> list

That pairing is the whole declaration. No `predicate:` line, no registration
list, no second place to keep in step. Dropping the `.py` beside the `.md` moves
the rule from prose to hook and from feedforward to feedback, with nothing else
edited.

**Three levels, three trees, no exceptions for any kind.** A project's primitives
live in the repository that owns them, a team's travel with the team, and an
org's ship with the org.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import hooks as hooks_lib
import permissions as perms_lib
from parse import parse
from primitive import KIND_SIDE, LAYERS, Primitive, validate

# Where a repository already wrote down what it does not want an agent doing.
# The SHAPE of this file is Claude Code's `permissions` block, which no standard
# covers. The location is `.agents/`, because that is where a repository keeps
# what it tells agents.
SETTINGS_FILES = (".agents/settings.json", ".agents/settings.local.json")

# Convention, and every path is optional. A repository with no `.agents/rules`
# still gets the team and org primitives, which is what makes them standards
# rather than suggestions.
#
# The kind is the directory name, singular, so `rules/` holds rules and
# `skills/` holds skills. Nothing declares it because the directory already has.
#
# **`.agents/` rather than `.claude/`.** ghola reads the repository's agent
# files and implements the result itself, at whatever rung carries each rule, so
# it reads from the vendor-neutral directory and not from one tool's. Every
# primitive kind is unchanged: `rules/`, `skills/`, `agents/`, `commands/`,
# `mcps/` and `evals/` mean here exactly what they meant under `.claude/`.
#
# `.ladder/` stays, and it is ghola's own: a repository that wants its rungs
# separate from everything else it tells an agent has somewhere to put them.
# `.agents/` is second, and the later root wins.
DEFAULT_ROOTS = {
    "org": ["{ladder}/org"],
    "team": ["{ladder}/team"],
    "project": ["{repo}/.ladder", "{repo}/.agents"],
}

# Loaded least specific first, so a project primitive adapting a team one is the
# later of the two.
ORDER = ("org", "team", "project")

KIND_DIRS = {f"{kind}s": kind for kind in KIND_SIDE}

# `hooks/` holds the scripts a settings entry points at, not primitives. A hook
# is declared in `.agents/settings.json` the way Claude Code declares one, and
# `hooks.py` turns that block into rung-2 constraints the same way `permissions`
# becomes rung 1 and 2. Named here so the charter reader skips the directory:
# shell scripts are not prose, and a README beside them is not a constraint.
SCRIPT_DIRS = ("hooks",)


@dataclass
class Loaded:
    """Every primitive that applies here, and what is wrong with the rest."""

    primitives: list[Primitive] = field(default_factory=list)
    problems: list[str] = field(default_factory=list)
    adapted: dict[str, Primitive] = field(default_factory=dict)
    refused_adaptations: dict[str, Primitive] = field(default_factory=dict)
    # The repository's own `permissions`, kept whole as well as synthesised into
    # primitives, because rung 2 needs the argument patterns rather than the
    # description of them.
    permissions: perms_lib.Permissions = field(default_factory=perms_lib.Permissions)
    # The other key in the same settings file, kept whole for the same reason:
    # `ladder::list` reports the mechanism and the event it binds to.
    hooks: hooks_lib.Hooks = field(default_factory=hooks_lib.Hooks)

    @property
    def constraints(self) -> list[Primitive]:
        return [p for p in self.primitives if p.side == "constraint"]

    @property
    def capabilities(self) -> list[Primitive]:
        return [p for p in self.primitives if p.side == "capability"]

    def by_id(self, primitive_id: str) -> Primitive | None:
        return next((p for p in self.primitives if p.id == primitive_id), None)

    def at_rung(self, rung: int, side: str = "constraint") -> list[Primitive]:
        return [p for p in self.primitives if p.side == side and rung in p.rungs]

    def governing(self, path: str = "", function_id: str = "") -> list[Primitive]:
        """The constraints with something to say about this path or this call.

        Specialisations are included alongside the standard they implement,
        because a specialisation says HOW the higher one is met here and both
        stay in force. Only an adaptation replaces, and that already happened in
        `load`.
        """
        return [
            p for p in self.constraints
            if (not path or p.governs_path(path))
            and (not function_id or p.governs_function(function_id))
        ]

    def withheld(self) -> set[str]:
        """Every function some rung-1 constraint takes away.

        Constraint rung 1 and the capability floor are one mechanism seen from
        opposite ends: withholding a function and never granting it both resolve
        to "is this in the allow list".
        """
        names: set[str] = set()
        for p in self.constraints:
            if 1 in p.rungs:
                names.update(p.withholds)
        return names

    @property
    def measured_share(self) -> float:
        """The share of this ladder that runs rather than hopes.

        This does not make feedforward reliable. It makes the gap visible and
        counted, which is what the ladder is for.
        """
        if not self.primitives:
            return 0.0
        return sum(1 for p in self.primitives if p.measured) / len(self.primitives)


def resolve(patterns: list[str], repo: str, ladder_home: str) -> list[Path]:
    """Expand `{repo}` and `{ladder}`, and make the result ABSOLUTE.

    Absolute is load-bearing. A shipped rule's script is found relative to the
    directory the rule was read from, and if that directory is relative the
    script path is too: the runner then resolves it against the TARGET
    repository and a team rule looks for its own predicate inside somebody
    else's checkout. It fails closed, so the write is still refused, but for the
    wrong reason and with a FileNotFoundError in the message the model reads.
    """
    return [Path(p.replace("{repo}", repo).replace("{ladder}", ladder_home))
            .expanduser().resolve()
            for p in patterns]


def read_kind_dir(folder: Path, kind: str, layer: str) -> tuple[list[Primitive], list[str]]:
    """Every `.md` in one kind's directory, paired with its script if there is one."""
    found, problems = [], []
    if not folder.is_dir():
        return found, problems

    for path in sorted(folder.glob("*.md")):
        script = path.with_suffix(".py")
        try:
            p = parse(path.read_text(), kind=kind, layer=layer, source=str(path),
                      script=str(script) if script.exists() else "")
        except Exception as exc:  # noqa: BLE001 — one bad file must not take the rest
            problems.append(f"{path}: {exc}")
            continue

        # The id defaults to the filename, because making somebody write
        # `id: no-secrets` in `no-secrets.md` is a second place to keep in step.
        if not p.id:
            p = Primitive(**{**p.__dict__, "id": path.stem})

        for problem in validate(p):
            problems.append(f"{p.id} ({path.name}): {problem}")
        found.append(p)

    return found, problems


def read_root(root: Path, layer: str) -> tuple[list[Primitive], list[str]]:
    """Every kind under one layer's root directory."""
    found, problems = [], []
    for dirname, kind in KIND_DIRS.items():
        kind_found, kind_problems = read_kind_dir(root / dirname, kind, layer)
        found.extend(kind_found)
        problems.extend(kind_problems)
    return found, problems


def load(repo: str = ".", ladder_home: str = ".",
         roots: dict[str, list[str]] | None = None,
         permissions: str | None = None) -> Loaded:
    """Every primitive that applies to this repository, with conflicts resolved.

    **Adaptation** is taking a higher primitive's id and replacing it: "we
    disagree, and here is ours instead". `locked` decides whether that is
    allowed, and either outcome is recorded rather than silent. A layering that
    could not be adapted locally would be routed around within a week.

    **Specialisation** is different in kind. `implements: <id>` says how the
    higher one is met here, and both stay in force. A specialisation inherits the
    standard's rung as a floor and may go higher, never lower, because that is a
    repository quietly weakening a standard by implementing it badly.

    **`permissions` is the settings file's text**, for a caller that can see the
    repository when this loader cannot. Supplying it overrides the read below;
    omitting it keeps the convention.
    """
    roots = roots or DEFAULT_ROOTS
    result = Loaded()
    winning: dict[str, Primitive] = {}

    result.problems.extend(check_repository(repo))

    for layer in ORDER:
        for root in resolve(roots.get(layer) or [], repo, ladder_home):
            found, problems = read_root(root, layer)
            result.problems.extend(problems)

            for p in found:
                existing = winning.get(p.id)
                if existing is None:
                    winning[p.id] = p
                    continue
                if existing.locked:
                    result.refused_adaptations[p.id] = existing
                    result.problems.append(
                        f"{p.id}: {p.source} tries to adapt a locked {existing.layer} "
                        "primitive. The shipped one stands. Locking forbids "
                        "disagreement; it does not forbid saying how, which is "
                        "`implements:`")
                    continue
                result.adapted[p.id] = existing
                winning[p.id] = p

    # A repository's own settings are the project layer speaking in another
    # vocabulary, so they are read last and land beside its rule files.
    result.permissions = permissions_of(repo, permissions)
    for made in perms_lib.as_primitives(result.permissions):
        winning.setdefault(made.id, made)
    for entry in result.permissions.unresolved:
        result.problems.append(
            f"{result.permissions.source}: `{entry}` names no tool this engine has, "
            "so it takes nothing away")

    # The other key in the same file, and the other half of parity with what a
    # repository has already written down. `setdefault` for the same reason
    # permissions use it: an authored rule with the same id is the repository
    # saying it more precisely, and it wins.
    result.hooks = hooks_of(repo, permissions)
    for made in hooks_lib.as_primitives(result.hooks):
        winning.setdefault(made.id, made)
    result.problems.extend(result.hooks.problems)
    result.problems.extend(hooks_lib.missing_scripts(
        result.hooks, lambda p: (Path(repo).expanduser() / p).exists()))

    result.primitives = sorted(winning.values(), key=lambda p: (p.side, p.kind, p.id))
    result.problems.extend(check_specialisations(result.primitives))
    return result


def check_repository(repo: str) -> list[str]:
    """Whether the checkout being judged is actually there.

    An empty project layer and an unreadable one produce the same ladder and mean
    opposite things, and only one of them is safe to act on. A managed worker runs
    in a microVM with its own source mounted and nothing else, so the target
    repository is simply absent there and every project primitive and every
    permission entry silently stops existing.
    """
    if not repo or Path(repo).expanduser().is_dir():
        return []
    return [f"cannot see the repository at {repo}. Its project primitives and its "
            "own `permissions` are not on this ladder, so what is reported here is "
            "what SHIPPED, not what applies. Run where the repository is, or pass "
            "its permissions in"]


def hooks_of(repo: str, supplied: str | None) -> hooks_lib.Hooks:
    """The repository's own `hooks`, read here or handed over.

    Same file and same argument as `permissions_of`, because they are two keys
    in one settings file and a caller that could read it for one could read it
    for the other.
    """
    if supplied is None:
        return read_hooks(Path(repo))
    return hooks_lib.parse(supplied,
                           source=f"{repo}/.agents/settings.json (supplied)")


def read_hooks(repo: Path) -> hooks_lib.Hooks:
    """The first settings file this repository has, if it has one."""
    for name in SETTINGS_FILES:
        path = repo / name
        if path.is_file():
            try:
                return hooks_lib.parse(path.read_text(), source=str(path))
            except OSError:
                continue
    return hooks_lib.Hooks()


def permissions_of(repo: str, supplied: str | None) -> perms_lib.Permissions:
    """The repository's own `permissions`, read here or handed over.

    `None` means nobody looked; a string means somebody did and this is what they
    found, which is why an empty string is not the same answer as no argument.
    """
    if supplied is None:
        return read_permissions(Path(repo))
    return perms_lib.parse(supplied,
                           source=f"{repo}/.agents/settings.json (supplied)")


def read_permissions(repo: Path) -> perms_lib.Permissions:
    """The first settings file this repository has, if it has one."""
    for name in SETTINGS_FILES:
        path = repo / name
        if path.is_file():
            try:
                return perms_lib.parse(path.read_text(), source=str(path))
            except OSError:
                continue
    return perms_lib.Permissions()


def check_specialisations(primitives: list[Primitive]) -> list[str]:
    """A specialisation may go higher than its standard, never lower."""
    problems = []
    index = {p.id: p for p in primitives}
    for p in primitives:
        if not p.implements:
            continue
        standard = index.get(p.implements)
        if standard is None:
            problems.append(f"{p.id}: implements {p.implements!r}, which nothing holds")
            continue
        if p.rungs and standard.rungs and min(p.rungs) < min(standard.rungs):
            problems.append(
                f"{p.id}: implements {standard.id} at rung {min(p.rungs)}, below the "
                f"standard's {min(standard.rungs)}. A specialisation may go higher, "
                "never lower: that is a repository quietly weakening a standard by "
                "implementing it badly")
    return problems
