"""Rung 0, at the seam the harness gives it.

The repository's own instructions reach the model here rather than being pasted
into the brief. That is what lets the charter be assembled per turn: the always-on
pieces on the first generate, and a scoped piece once the turn has gone near what
it is about.

**ghola is not alone on this hook**, and each participant owns a piece:
`directory::pre-generate` serves the repository's skills and prompts,
`memory::hook::pre-generate` injects its banks, `fp::inject-guidance` its own. What
is left for ghola is `CLAUDE.md`, which nothing else reads, and the assembly.

The constraint prose comes from `ladder::list` rather than from a rules directory
here, because the ladder owns rules now. Taking only the prose is deliberate: a
rule's enforcement is the ladder's job at whatever rung it is carried, and
implementing it twice is the seam an agent finds first.
"""

from pathlib import Path

import charter as charter_lib

import context

# Read fresh per turn. A charter cached at import is a charter you restart a
# worker to change, which is a charter people work around.
#
# What to LOOK for, which is not the same as what gets read: `charter.which`
# reads `AGENTS.md` and reports the other. This used to be a first-match tuple
# with `CLAUDE.md` first, so a repository that had migrated to `AGENTS.md` and
# kept the old file had its `AGENTS.md` ignored by the file it replaced.
CHARTER_FILES = (charter_lib.STANDARD, charter_lib.SUPERSEDED)


def reader(root: Path):
    """How an `@path` import is resolved: relative to the repository, and never
    outside it.

    The containment check is not decoration. `@../../../etc/passwd` in a target
    repository's CLAUDE.md would otherwise put that file into a system prompt,
    and the repository is the thing ghola is pointed at rather than the thing it
    trusts.
    """
    def read(path: str) -> str | None:
        try:
            candidate = (root / path).resolve()
            candidate.relative_to(root.resolve())
            return candidate.read_text() if candidate.is_file() else None
        except (OSError, ValueError):
            return None
    return read


def rules_for(workspace: str) -> list[dict]:
    """What the ladder says governs this repository.

    A failure here is not a failed turn. The ladder is a separate worker and it
    may be down; a charter missing its constraint prose is worse than no charter
    and better than no turn, and rungs 1 through 5 still enforce whatever the
    prose would have said.
    """
    if context.WORKER is None:
        return []
    try:
        answer = context.WORKER.trigger({
            "function_id": "ladder::list",
            "timeout_ms": 8000,
            "payload": {"repo": workspace},
        }) or {}
        body = answer.get("payload") or answer
        return list(body.get("primitives") or [])
    except Exception:  # noqa: BLE001 — a missing ladder must not fail the turn
        return []


def under_charter_dir(root: Path) -> tuple[tuple[str, str], ...]:
    """Every markdown under `.agents/` that the ladder does not already speak for.

    **All of it is charter.** A repository separates its ideas by directory, so
    `.agents/architecture/queues.md` arrives titled `architecture / queues` and
    needs nothing to declare what it is about.

    `rules/`, `skills/` and the other kind directories are skipped here because
    `ladder::list` already carries their prose, with the rung each is enforced
    at attached. Reading them twice would state every rule twice and the second
    copy would have lost the rung.

    Sorted, so a charter is the same document twice in a row. An unreadable file
    is skipped rather than fatal: it is the target repository's file, and ghola
    is a guest in it.
    """
    folder = root / charter_lib.CHARTER_DIR
    if not folder.is_dir():
        return ()

    found = []
    for path in sorted(folder.rglob("*.md")):
        relative = path.relative_to(folder).as_posix()
        if charter_lib.is_ladders(relative):
            continue
        try:
            found.append((relative, path.read_text()))
        except OSError:
            continue
    return tuple(found)


def handle(payload: dict) -> dict:
    call = context.of(payload)
    if not call.known:
        return context.CONTINUE

    root = Path(call.workspace or ".")
    # `is_file` follows a symlink, which is the point: `CLAUDE.md -> AGENTS.md`
    # is the migration the standard recommends, and the target is what gets read.
    origin, missing = charter_lib.which(
        name for name in CHARTER_FILES if (root / name).is_file())
    text = (root / origin).read_text() if origin else None

    charter = charter_lib.build(
        text, reader(root),
        rules=[r for r in rules_for(call.workspace) if r.get("side") == "constraint"],
        repo=str(root), origin=origin or charter_lib.STANDARD,
        extras=under_charter_dir(root))
    charter.problems.extend(missing)

    # Touched paths arrive with the factory in M4, which is what tracks them.
    # Until then every scoped piece waits, and the always-on pieces travel.
    arriving = charter.take(touched=())

    # Nothing to say AND nothing to report is the only silent case. A repository
    # with a `CLAUDE.md` and no `AGENTS.md` has no charter and a reason why, and
    # returning early on the empty charter would throw the reason away.
    if not arriving and not charter.problems:
        return context.CONTINUE

    for problem in charter.problems:
        print(f"charter: {problem}")

    answer = {
        "decision": "continue",
        "annotations": {
            "ghola.charter_pieces": charter.count(),
            "ghola.charter_problems": len(charter.problems),
        },
    }
    if arriving:
        answer["mutations"] = {"system_prompt": arriving}
    return answer
