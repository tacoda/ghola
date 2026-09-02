"""Rung 0: the repository's own instructions, assembled for one turn.

The charter is what a project says about itself. It reaches the model through the
`pre-generate` seam rather than being pasted into the brief, which is what lets
it be assembled per turn instead of pasted per prompt.

**ghola assembles less of this than it used to.** Three other workers are already
on that hook and each owns a piece:

| worker | what it contributes |
|---|---|
| `directory` | the repository's skills, prompts and system prompts |
| `memory` | its banks' rules, injected whole into every turn |
| `ladder` | the constraint prose, per layer and per rung |
| ghola | `CLAUDE.md` and its imports, which nothing else reads |

So what is here is the assembly and the one file nobody else claims. Everything
in this module is pure: it takes text and returns text, and the caller does the
reading. That is what lets the whole charter be tested without a repository.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

# `@path` on its own line imports another file. Claude Code's own convention, so
# a repository that already uses it needs no second spelling.
IMPORT = re.compile(r"^@([^\s]+)\s*$", re.MULTILINE)

# The standard, and it is one plain markdown file: https://agents.md. No
# required fields, no schema, and it is stewarded by the Agentic AI Foundation
# at the Linux Foundation rather than by any one vendor.
STANDARD = "AGENTS.md"

# **Not read. Reported.** ghola reads the standard and nothing else, so there is
# one file to author and no second copy to go stale. A repository that has only
# the older file is told to symlink it, which is the migration the standard
# itself recommends and the one thing that also keeps Claude Code working:
#
#     ln -s AGENTS.md CLAUDE.md
#
# Claude Code loads `CLAUDE.md` and does not load `AGENTS.md` on its own. The
# symlink is what makes one authored file serve both, and it belongs in the
# repository rather than in a generator here.
SUPERSEDED = "CLAUDE.md"

# Where a repository keeps everything else it tells agents. **All of it is
# charter.** The directories under it are named after the concept they hold,
# which is the convention the ladder already reads its kinds by, so
# `.agents/architecture/` is about architecture and needs nothing to declare it.
CHARTER_DIR = ".agents"

# The concepts the LADDER owns. Their prose already reaches the model through
# `ladder::list`, which takes the description and the why and adds the rung, so
# reading the same files here would put every rule in the prompt twice.
#
# Mirrors `load.KIND_DIRS` rather than importing it: this module is in
# ghola-core and that one is a separate worker. A test asserts the two agree,
# because a kind added there and missed here would be a rule stated twice.
LADDER_DIRS = ("rules", "commands", "skills", "agents", "mcps", "evals", "hooks")

# `hooks/` is in that list for a different reason than the rest. It holds the
# scripts a `.agents/settings.json` entry points at, and a shell script is not
# prose. The ladder reports the hook; the file it runs is not charter.
SCRIPT_DIRS = ("hooks",)


def concept_of(relative: str) -> str:
    """The concept a charter file belongs to, which is the directory holding it.

    `architecture/queues.md` is about architecture. A file sitting directly in
    `.agents/` is its own concept, so `domain.md` is about the domain.
    """
    parts = [p for p in str(relative).replace("\\", "/").split("/") if p]
    if len(parts) > 1:
        return " / ".join(parts[:-1] + [parts[-1].removesuffix(".md")])
    return parts[0].removesuffix(".md") if parts else ""


def is_ladders(relative: str) -> bool:
    """Whether this path is one the ladder already speaks for."""
    parts = [p for p in str(relative).replace("\\", "/").split("/") if p]
    return bool(parts) and parts[0] in LADDER_DIRS

# How deep an import chain may go. A charter that needs five levels of include
# is a charter nobody can read, and the cycle guard below matters more than the
# depth: a file importing itself is the common accident.
MAX_DEPTH = 3


@dataclass
class Piece:
    """One part of the charter, with where it came from.

    The source travels because a model told something surprising should be able
    to find out who told it, and because an operator asking "why did it do that"
    is asking about provenance.
    """

    title: str
    body: str
    source: str = ""
    # Paths this piece governs. Empty means it always applies.
    paths: tuple[str, ...] = ()

    def applies_to(self, touched: tuple[str, ...]) -> bool:
        """Whether this piece is about anything the turn has gone near.

        A piece with no paths is always on. A piece with paths waits until the
        turn touches one, because loading every scoped rule into every turn is
        how a charter becomes the thing diluting the attention it wanted.
        """
        if not self.paths:
            return True
        if not touched:
            return False
        import fnmatch
        return any(fnmatch.fnmatch(t, p) for p in self.paths for t in touched)


@dataclass
class Charter:
    """Everything this repository has to say, before it is narrowed to a turn."""

    pieces: list[Piece] = field(default_factory=list)
    problems: list[str] = field(default_factory=list)

    def take(self, touched: tuple[str, ...] = ()) -> str:
        """The charter for a turn that has touched these paths.

        Returned as one markdown document with `###` headings, because the
        harness appends it to a system prompt and a heading is the only structure
        that survives that.
        """
        arriving = [p for p in self.pieces if p.applies_to(touched)]
        if not arriving:
            return ""
        return "\n\n".join(f"### {p.title}\n\n{p.body.strip()}" for p in arriving)

    def count(self, touched: tuple[str, ...] = ()) -> int:
        return sum(1 for p in self.pieces if p.applies_to(touched))


def resolve_imports(text: str, read, seen: frozenset[str] = frozenset(),
                    depth: int = 0) -> tuple[str, list[str]]:
    """Inline every `@path` line, depth-first.

    `read(path) -> str | None` is handed in rather than imported, so this stays
    pure and a test needs a dict rather than a directory.

    A cycle is reported and left as the literal line. Silently dropping it would
    make a charter that imports itself look like a charter with a missing
    section, which is the harder bug to find.
    """
    problems: list[str] = []

    def replace(match: re.Match) -> str:
        path = match.group(1)
        if path in seen:
            problems.append(f"{path}: import cycle, left as written")
            return match.group(0)
        if depth >= MAX_DEPTH:
            problems.append(f"{path}: import nested deeper than {MAX_DEPTH}, not followed")
            return match.group(0)

        body = read(path)
        if body is None:
            problems.append(f"{path}: imported by the charter and not found")
            return match.group(0)

        nested, nested_problems = resolve_imports(body, read, seen | {path}, depth + 1)
        problems.extend(nested_problems)
        return nested

    return IMPORT.sub(replace, text), problems


def which(present) -> tuple[str, tuple[str, ...]]:
    """The charter file to read, and what to say about what was not read.

    `present` is whichever of the candidate names exist in the repository. Pure,
    so the precedence is a set in a test rather than a directory on disk.

    **Only the standard is read.** A repository holding both files gets its
    `AGENTS.md`, and its `CLAUDE.md` is not consulted at all: two files read
    into one prompt is the charter twice over when the second is a pointer, and
    an argument nobody adjudicates when it is not.

    A repository holding ONLY the older file gets no charter, and a problem
    saying so with the one command that fixes it. That is the case worth being
    loud about, because a silent empty charter looks exactly like a repository
    that never wrote one.
    """
    present = set(present)
    if STANDARD in present:
        return STANDARD, ()
    if SUPERSEDED in present:
        return "", (
            f"{SUPERSEDED} is here and {STANDARD} is not, so this repository has "
            f"no charter: ghola reads {STANDARD}. Rename it and symlink the old "
            f"name, which keeps Claude Code working from the same one file: "
            f"`git mv {SUPERSEDED} {STANDARD} && ln -s {STANDARD} {SUPERSEDED}`",)
    return "", ()


def build(charter_text: str | None, read, rules: list[dict] | None = None,
          repo: str = "", origin: str = STANDARD,
          extras: tuple[tuple[str, str], ...] = ()) -> Charter:
    """The charter, from this repository's own files and the ladder's rules.

    `origin` is the file the text came from, and it travels because a model told
    something surprising should be able to find out which file said it. It used
    to be hardcoded to `CLAUDE.md`, which was a lie the moment `AGENTS.md`
    became the file ghola reads first.

    `extras` is everything else under `.agents/`, as `(relative path, text)`
    pairs the caller has already filtered. Each becomes its own piece titled by
    its concept, because a directory named after what it holds is a heading
    somebody already wrote.

    `rules` is what `ladder::list` returned. Only the prose is taken: a rule's
    enforcement is the ladder's job at whatever rung it is carried, and repeating
    the mechanism here would be a second implementation of one rule, which is
    the seam an agent finds first.
    """
    charter = Charter()

    if charter_text:
        body, problems = resolve_imports(charter_text, read)
        charter.problems.extend(problems)
        charter.pieces.append(Piece(title="This repository's own instructions",
                                    body=body, source=f"{repo}/{origin}"))

    for relative, text in extras:
        if not str(text or "").strip():
            continue
        body, problems = resolve_imports(text, read)
        charter.problems.extend(problems)
        charter.pieces.append(Piece(title=concept_of(relative), body=body,
                                    source=f"{repo}/{CHARTER_DIR}/{relative}"))

    for rule in rules or []:
        # The prose is the description and the why. A rule carried at a
        # mechanical rung still says its piece here, because a model told the
        # reason in advance writes different code than one refused afterwards.
        text = rule.get("description") or ""
        if rule.get("why"):
            text = f"{text}\n\nWhy: {rule['why']}"
        if not text.strip():
            continue

        rungs = ", ".join(str(r.get("name") or r.get("number")) for r in rule.get("rungs", []))
        title = f"{rule['id']} ({rule.get('layer', 'project')}, carried at {rungs})"
        charter.pieces.append(Piece(title=title, body=text,
                                    source=rule.get("source", ""),
                                    paths=tuple(rule.get("paths") or ())))

    return charter
