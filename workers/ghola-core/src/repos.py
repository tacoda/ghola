"""What ghola knows about a target repository.

Read fresh on every submit, so adding a repository does not mean restarting
anything. **The resolved settings are copied onto the job**, which is the part
that matters: a rework months later rebuilds the environment the job was born
in, rather than whatever this file says by then.

Precedence, most specific first:

1. the repository's own entry in `repos.local.toml`
2. its entry in `repos.toml`
3. `[defaults]`, from the local file first
4. the environment (`GHOLA_BASE`, `GHOLA_BRANCH_PREFIX`, …)
5. what is built in

**Two files, for the same reason as `.env`.** `repos.toml` is tracked and lists
what a team shares; `repos.local.toml` is git-ignored and lists what is on this
machine. Without the split, the one tracked file names somebody's home directory
and every clone starts with a diff nobody wants to commit.

The base branch is **discovered, not assumed**. wipp hardcoded `main`, and a
repository on `develop` branched from nothing.
"""

from __future__ import annotations

import os
import tomllib
from dataclasses import asdict, dataclass, field
from pathlib import Path

# Built in, and every one of them is overridable. An empty `base` means "ask the
# forge", which is the honest default: this machine does not know.
BUILT_IN = {
    # `owner/name` on the forge. Empty means ghola cannot open a pull request
    # for this repository and will say so rather than guessing from a remote
    # URL, which is a parse that gets SSH aliases and self-hosted hosts wrong.
    "slug": "",
    "base": "",
    # Who hosts this repository and therefore receives the request for review.
    # `local` is no forge at all, and needs no slug and no account.
    "forge": "github",
    "branch_prefix": "ghola/",
    "prepare": "",
    "cleanup": "",
    "max_revisions": 2,
    # A repository whose prepare allocates real ports cannot run two jobs at
    # once. One is the safe default; a repository that knows better says so.
    "concurrency": 1,
    "test_command": "",
}

ENV_KEYS = {
    "forge": "GHOLA_FORGE",
    "base": "GHOLA_BASE",
    "branch_prefix": "GHOLA_BRANCH_PREFIX",
    "prepare": "GHOLA_PREPARE",
    "cleanup": "GHOLA_CLEANUP",
    "max_revisions": "GHOLA_MAX_REVISIONS",
}

NUMERIC = ("max_revisions", "concurrency")

# Tracked, and shared with the team. Git-ignored, and this machine's.
SHARED = Path("repos.toml")
LOCAL = Path("repos.local.toml")


@dataclass
class Repo:
    """The resolved settings for one repository, ready to copy onto a job."""

    path: str
    slug: str = ""
    base: str = ""
    # Who hosts this repository and therefore receives the request for review.
    # `local` is no forge at all: the request is a file in the repository, which
    # is what a repo with no GitHub account behind it needs.
    forge: str = "github"
    branch_prefix: str = "ghola/"
    prepare: str = ""
    cleanup: str = ""
    max_revisions: int = 2
    concurrency: int = 1
    test_command: str = ""
    # Credentials and connection strings a repository's tests need. These reach
    # the prepare and cleanup commands and the agent's own shell.
    env: dict[str, str] = field(default_factory=dict)
    # Where each value came from, so `make config` can show it and an operator
    # is never guessing which layer won.
    source: dict[str, str] = field(default_factory=dict)

    def as_job_fields(self) -> dict:
        """What gets copied onto the job record at submit time."""
        fields = asdict(self)
        fields.pop("source", None)
        return {"repo_settings": fields}


def load(path: str | Path | None = None) -> dict:
    """Read `repos.toml`. Missing or malformed reads as empty.

    Malformed is not fatal on purpose: the built-ins are a working
    configuration, and refusing to start because one repository entry has a
    typo would take every other repository down with it. `make config` is where
    the parse error becomes visible.
    """
    path = Path(path) if path else SHARED
    try:
        return tomllib.loads(path.read_text())
    except (OSError, tomllib.TOMLDecodeError):
        return {}


def merged(path: str | Path | None = None) -> dict:
    """`repos.toml` with `repos.local.toml` on top of it.

    Merged one level deep: a local entry replaces a shared entry for the same
    repository rather than being blended into it, because two half-configurations
    for one repository is the thing nobody could debug.
    """
    shared = load(path)
    if path is not None:
        return shared

    local = load(LOCAL)
    if not local:
        return shared

    out = dict(shared)
    out["defaults"] = {**(shared.get("defaults") or {}), **(local.get("defaults") or {})}
    out["repos"] = {**(shared.get("repos") or {}), **(local.get("repos") or {})}
    return out


def resolve(repo_path: str, config: dict | None = None,
            environ: dict | None = None) -> Repo:
    """The settings for one repository, with precedence applied.

    The repository is keyed by its absolute path, because that is the only name
    ghola reliably has for it: a job names a directory on this machine, not a
    remote or a slug.
    """
    config = merged() if config is None else config
    environ = os.environ if environ is None else environ
    resolved = Path(repo_path).expanduser()
    key = str(resolved)

    values = dict(BUILT_IN)
    source = {name: "built-in" for name in values}

    for name, variable in ENV_KEYS.items():
        if environ.get(variable):
            values[name] = environ[variable]
            source[name] = variable

    for name, value in (config.get("defaults") or {}).items():
        if name in values:
            values[name] = value
            source[name] = "repos.toml [defaults]"

    entry = (config.get("repos") or {}).get(key) or {}
    # A repository may also be keyed by its directory name, which is what people
    # actually type. The absolute path wins when both exist.
    if not entry:
        entry = (config.get("repos") or {}).get(resolved.name) or {}
    for name, value in entry.items():
        if name == "env":
            continue
        values[name] = value
        source[name] = f"repos.toml [{key}]"

    for name in NUMERIC:
        try:
            values[name] = int(values[name])
        except (TypeError, ValueError):
            values[name] = BUILT_IN[name]
            source[name] = "built-in (the configured value was not a number)"

    return Repo(path=key, env=dict(entry.get("env") or {}), source=source,
                **{k: v for k, v in values.items()})


def branch_for(repo: Repo, job_id: str, slug: str = "") -> str:
    """The branch a job works on.

    The prefix is the repository's convention rather than ghola's: `feature/`
    had to be passed by hand for one real repository, and it was written in that
    repository's CONTRIBUTING all along.
    """
    stem = (slug or job_id)[:48].strip("-") or job_id[:8]
    return f"{repo.branch_prefix}{stem}"


def known(config: dict | None = None) -> list[str]:
    config = merged() if config is None else config
    return sorted((config.get("repos") or {}).keys())
