"""Where eval cases come from.

`evals/` in this repository, plus any directory `settings/evals.yaml` names.
That second half is the whole point: **a team's cases and graders need no
fork.** A suite lives in the team's own repository, versioned with the prompts
it grades, and ghola reads it from wherever it is.

Pure. Given a configuration and a root, it says which files are cases and what
is wrong with the ones it could not find — because a suite directory that moved
should be reported rather than silently contributing nothing, which is exactly
what a green run with no cases looks like.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

# Read alongside the repository's own, never instead of it. A team that wants
# only its own cases deletes `evals/`.
BUILT_IN = "evals"


@dataclass
class Suites:
    cases: list[Path] = field(default_factory=list)
    problems: list[str] = field(default_factory=list)

    def names(self) -> list[str]:
        return [p.stem for p in self.cases]


def expand(place: str, root: Path) -> Path:
    """A configured path, absolute. `~` and `$VARS` both work.

    Relative paths resolve against the repository rather than the working
    directory, because `make eval` runs from wherever the operator is standing.
    """
    text = os.path.expandvars(str(place)).strip()
    path = Path(text).expanduser()
    return path if path.is_absolute() else (root / path)


def places(config: dict | None, root: Path) -> list[Path]:
    """Every directory to read cases from, the built-in one first."""
    config = config or {}
    found = [root / BUILT_IN]
    for place in (config.get("suites") or []):
        path = expand(place, root)
        if path not in found:
            found.append(path)
    return found


def gather(config: dict | None, root: Path, only: str = "") -> Suites:
    """Every case, and every suite that is not where it said it would be."""
    out = Suites()
    for place in places(config, root):
        if not place.is_dir():
            # Not fatal, and not silent. A suite nobody can find contributes
            # nothing, and a run of nothing reports as a run that passed.
            if place != root / BUILT_IN:
                out.problems.append(
                    f"no eval suite at `{place}`. Fix the path in "
                    "settings/evals.yaml, or remove the line")
            continue
        for path in sorted(place.glob("*.json")):
            if not only or path.stem == only:
                out.cases.append(path)

    if only and not out.cases:
        out.problems.append(
            f"no eval case called `{only}`. Looked in: "
            + ", ".join(str(p) for p in places(config, root)))
    return out


def graders(config: dict | None) -> list[str]:
    """Function ids a team registered as their own evaluators.

    Named here so `make config` can list them, and so a case referring to one
    that nobody registered is a question somebody can answer. ghola does not
    call these: the `eval` worker does, by the id in the case file.
    """
    return [str(name) for name in ((config or {}).get("graders") or [])]
