"""Running a rule's predicate, whichever of the two kinds it is.

A predicate answers one question: does this content, at this path, break the
rule? It returns findings, and an empty list means the rule is satisfied.

**Two kinds, and the second is why this is a worker.**

1. A **Python file**: `predicates/no_secrets.py`, with a `check(path, content,
   context) -> list`. It imports nothing from ladder, so it runs standalone.
2. A **function id**: `ladder::predicate::...` or anything else on the bus, so a
   predicate can be written in Rust or TypeScript and shared between projects.

The dispatcher below runs the first kind and hands the second back to the caller,
because calling a function on the bus needs the engine and this module is pure
apart from reading one file.

**A predicate that throws is a finding, not a pass.** Every gate here fails open
on its own bug otherwise, which is the one failure mode a gate may not have: a
rule that stops working silently is worse than a rule that was never written,
because the dashboard still says it is enforced.
"""

from __future__ import annotations

import importlib.util
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Finding:
    """One reason a rule refused, in words the model can act on."""

    path: str = ""
    line: int = 0
    why: str = ""

    def __str__(self) -> str:
        where = f"{self.path}:{self.line}" if self.line else self.path
        return f"{where}: {self.why}" if where else self.why


def is_function_id(predicate: str) -> bool:
    """Whether this predicate is a function on the bus rather than a file."""
    return "::" in predicate


def normalise(results, path: str = "") -> list[Finding]:
    """Whatever a predicate returned, as findings.

    Deliberately generous about shape. A predicate is somebody else's code,
    often written in five minutes, and rejecting a dict because it used `reason`
    instead of `why` would make the strict thing the annoying thing.
    """
    if not results:
        return []
    if isinstance(results, (str, Finding)):
        results = [results]

    findings = []
    for item in results:
        if isinstance(item, Finding):
            findings.append(item)
        elif isinstance(item, str):
            findings.append(Finding(path=path, why=item))
        elif isinstance(item, dict):
            findings.append(Finding(
                path=str(item.get("path") or path),
                line=int(item.get("line") or 0),
                why=str(item.get("why") or item.get("reason") or item.get("message") or ""),
            ))
        else:
            findings.append(Finding(path=path, why=str(item)))
    return [f for f in findings if f.why]


def load_module(predicate_path: Path):
    """Import a predicate file without putting it on `sys.path`.

    By path rather than by name, so two projects can each have a
    `predicates/no_secrets.py` and neither shadows the other.
    """
    spec = importlib.util.spec_from_file_location(
        f"ladder_predicate_{predicate_path.stem}", predicate_path)
    if spec is None or spec.loader is None:
        raise ImportError(f"cannot load {predicate_path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def run_file(predicate_path: Path, path: str, content: str,
             context: dict | None = None) -> list[Finding]:
    """Run one Python predicate. A raise is a finding, never a pass."""
    try:
        module = load_module(predicate_path)
        check = getattr(module, "check", None)
        if check is None:
            return [Finding(path=path, why=(
                f"the predicate {predicate_path.name} defines no `check` function, "
                "so this rule enforces nothing"))]
        return normalise(check(path, content, context or {}), path)
    except Exception as exc:  # noqa: BLE001
        # Reported rather than swallowed. Whether the gates work cannot be asked
        # of the gates, so a broken predicate has to be loud somewhere, and the
        # only place anybody is looking is the refusal itself.
        return [Finding(path=path, why=(
            f"the predicate {predicate_path.name} raised "
            f"{type(exc).__name__}: {exc}. Treated as a finding, because a gate "
            "that fails open on its own bug stops working invisibly"))]
