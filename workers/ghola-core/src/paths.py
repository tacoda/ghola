"""Where the repository is, from anywhere inside it.

One answer, so a worker started from a Makefile, a test run from the root, and a
tool running inside a worktree all read the same settings. `GHOLA_ROOT` wins when
it is set, which is what lets a test point the whole stack at a fixture.
"""

import os
from pathlib import Path

# Installed as a package, `__file__` lands in site-packages and the walk below
# finds nothing. `GHOLA_ROOT` is how a deployment says where its configuration
# lives, and the Makefile sets it for every process it starts.
MARKERS = ("settings", "config.yaml")


def root() -> Path:
    """The repository root: `GHOLA_ROOT`, else the nearest directory holding both
    a `settings/` directory and a `config.yaml`."""
    named = os.environ.get("GHOLA_ROOT")
    if named:
        return Path(named).expanduser().resolve()

    for folder in Path(__file__).resolve().parents:
        if all((folder / marker).exists() for marker in MARKERS):
            return folder
    # Not found: the caller gets the current directory and whatever error the
    # missing file produces, which names the file. Guessing a parent here would
    # produce a config-not-found error pointing at a directory nobody chose.
    return Path.cwd()


def settings(name: str) -> Path:
    """One file under `settings/`.

    ghola's own declarative configuration lives there rather than in `config/`,
    which belongs to iii's `configuration` worker: that worker owns its directory
    and rewrites files in it, and a shared directory is a collision waiting for a
    release to happen.
    """
    return root() / "settings" / name
