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


def build(claude_md: str | None, read, rules: list[dict] | None = None,
          repo: str = "") -> Charter:
    """The charter, from this repository's own files and the ladder's rules.

    `rules` is what `ladder::list` returned. Only the prose is taken: a rule's
    enforcement is the ladder's job at whatever rung it is carried, and repeating
    the mechanism here would be a second implementation of one rule, which is
    the seam an agent finds first.
    """
    charter = Charter()

    if claude_md:
        body, problems = resolve_imports(claude_md, read)
        charter.problems.extend(problems)
        charter.pieces.append(Piece(title="This repository's own instructions",
                                    body=body, source=f"{repo}/CLAUDE.md"))

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
