"""Finding the Python a team drops in, and the functions they name instead.

Two mechanisms, and the first covers most cases:

1. **A file in a named directory.** `actions/deploy.py` is `action: deploy`,
   `guards/needs_review.py` is `guard: needs_review`. Found by filename, no
   registration, no import to add. Hyphens and underscores are the same name,
   because a stage written `deploy-to-staging` should find `deploy_to_staging.py`.
2. **A function id on the bus.** Any extension point that takes a module also
   takes `worker::function`, so an extension can be written in Rust or
   TypeScript. Python is the easy path; a worker is the one that scales.

**A named extension that resolves to nothing is an error, not a no-op.** A stage
whose action silently does nothing is a job that walks past the step it existed
for, and nothing says so. This module reports what it could not find rather than
returning `None` and letting the caller shrug.
"""

from __future__ import annotations

import importlib.util
from dataclasses import dataclass, field
from pathlib import Path

# One directory per extension point, and the function each module must define.
KINDS = {
    "actions": "run",
    "guards": "check",
    "parsers": "parse",
    "predicates": "check",
}


class ExtensionError(LookupError):
    """A named extension that is not there, or is there and unusable."""


@dataclass
class Found:
    """What is available, and what was asked for and missing."""

    modules: dict[str, Path] = field(default_factory=dict)
    problems: list[str] = field(default_factory=list)

    def names(self) -> list[str]:
        return sorted(self.modules)


def normalise(name: str) -> str:
    """`deploy-to-staging` and `deploy_to_staging` are one name."""
    return name.strip().replace("-", "_").lower()


def is_function_id(name: str) -> bool:
    return "::" in name


def discover(root: str | Path, kind: str) -> Found:
    """Every module in one extension directory.

    A missing directory is empty rather than an error: a team that writes no
    custom actions should not have to create `actions/` to say so.
    """
    found = Found()
    folder = Path(root) / kind
    if not folder.is_dir():
        return found

    wanted = KINDS.get(kind, "run")
    for path in sorted(folder.glob("*.py")):
        if path.name.startswith("_"):
            continue
        found.modules[normalise(path.stem)] = path

    return found


def load(path: Path, kind: str):
    """Import one extension by path, without putting it on `sys.path`.

    By path rather than by name, so two projects can each have an
    `actions/deploy.py` and neither shadows the other.
    """
    wanted = KINDS.get(kind, "run")
    spec = importlib.util.spec_from_file_location(f"ghola_{kind}_{path.stem}", path)
    if spec is None or spec.loader is None:
        raise ExtensionError(f"cannot load {path}")

    module = importlib.util.module_from_spec(spec)
    try:
        spec.loader.exec_module(module)
    except Exception as exc:  # noqa: BLE001
        raise ExtensionError(
            f"{path.name} raised while loading: {type(exc).__name__}: {exc}") from exc

    entry = getattr(module, wanted, None)
    if entry is None:
        raise ExtensionError(
            f"{path.name} defines no `{wanted}` function, so naming it does "
            "nothing. Every extension has one entry point and this is its name")
    return entry


def resolve(name: str, root: str | Path, kind: str):
    """One extension, as something callable, or an error saying why not.

    Returns `(callable, function_id)`. Exactly one is set: a Python module gives
    the first, a function id gives the second and the caller triggers it.
    """
    if not name:
        return None, ""
    if is_function_id(name):
        # Not verified here. Whether the function exists is the engine's answer
        # and asking for it needs a connection this module deliberately lacks.
        return None, name

    found = discover(root, kind)
    path = found.modules.get(normalise(name))
    if path is None:
        available = ", ".join(found.names()) or "nothing"
        raise ExtensionError(
            f"no {kind[:-1]} called `{name}`. Put it in {kind}/{normalise(name)}.py, "
            f"or name a function id on the bus. Available: {available}")
    return load(path, kind), ""


def check(names: dict[str, str], root: str | Path) -> list[str]:
    """Resolve every extension a configuration names, and report what is missing.

    Called at load rather than at use. A stage whose action cannot be found
    should fail when the pipeline is read, not two turns into a job that has
    already paid for a worktree and a plan.
    """
    problems = []
    for kind, name in names.items():
        if not name:
            continue
        try:
            resolve(name, root, kind)
        except ExtensionError as exc:
            problems.append(str(exc))
    return problems
