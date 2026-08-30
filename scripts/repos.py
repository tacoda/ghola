"""What ghola knows about each target repository, and what is wrong with it.

    python3 scripts/repos.py            a line per repository
    python3 scripts/repos.py --slugs    just the GitHub slugs, for `make doctor`

Read from `repos.toml` and `repos.local.toml` together, through the same
`repos.merged` the factory uses, so this cannot disagree with what a job will
actually get.
"""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "workers" / "ghola-core" / "src"))

import repos  # noqa: E402


def report() -> int:
    config = repos.merged()
    known = repos.known(config)

    if not known:
        print("  no repositories configured yet.")
        print("  Copy an example out of repos.toml into repos.local.toml,")
        print("  which is git-ignored and is where paths from this machine go.")
        return 1

    for key in known:
        settings = repos.resolve(key, config)
        where = Path(key).expanduser()
        marks = []

        # The commonest configuration error, and it fails at the first stage
        # rather than at submit: a worktree cannot be cut from a directory that
        # is not there.
        if not where.is_dir():
            marks.append("NO SUCH DIRECTORY")
        elif not (where / ".git").exists():
            marks.append("not a git repository")

        if settings.forge == "github" and not settings.slug:
            # ghola will refuse to open a pull request rather than guessing the
            # slug from a remote URL, which is a parse that gets SSH aliases and
            # self-hosted hosts wrong.
            marks.append("no slug, so no pull request can be opened")
        if settings.forge not in ("github", "local"):
            marks.append(f"forge `{settings.forge}` needs forges/{settings.forge}.py")

        detail = f"{settings.forge}"
        if settings.slug:
            detail += f" {settings.slug}"
        if settings.base:
            detail += f" base={settings.base}"

        print(f"  {where}")
        print(f"      {detail}" + ("  <- " + "; ".join(marks) if marks else ""))

    return 0


def slugs() -> int:
    """Only the repositories whose forge needs an account to open anything."""
    config = repos.merged()
    for key in repos.known(config):
        settings = repos.resolve(key, config)
        if settings.forge == "github" and settings.slug:
            print(settings.slug)
    return 0


if __name__ == "__main__":
    raise SystemExit(slugs() if "--slugs" in sys.argv else report())
