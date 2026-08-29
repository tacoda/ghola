"""The brief a phase is handed.

One markdown file per phase in `prompts/`, rendered with a small context. wipp
kept these as Python string literals, which meant changing how a review is asked
for was a code change; here it is the first file an adopting team edits.

`string.Template` rather than Jinja, deliberately. A prompt template that needs
loops and conditionals is a prompt that should be two prompts, and a template
language is a second thing to learn before you can change what a phase is asked.

A missing prompt file is not an error: the phase falls back to the spec alone,
which is what every phase did before this module existed. What it costs is
visible — `make config` reports which phases have a prompt and which do not —
because a phase running on the bare spec is a phase nobody told what its job is.
"""

from __future__ import annotations

from string import Template

import paths

# Everything a template may name. Anything else stays literal rather than
# raising, because a `$` in a spec is a shell prompt far more often than it is
# a placeholder.
FIELDS = ("spec", "plan", "diff", "brief", "document", "repo", "branch",
          "phase")


def path_for(phase: str, named: str = ""):
    return paths.root() / (named or f"prompts/{phase}.md")


def load(phase: str, named: str = "") -> str:
    """The template for a phase, or an empty string."""
    try:
        return path_for(phase, named).read_text()
    except OSError:
        return ""


def render(template: str, context: dict) -> str:
    """Fill a template, leaving unknown placeholders alone.

    `safe_substitute` rather than `substitute`: a spec containing `$PATH` should
    not blow up the turn that was supposed to read it.
    """
    values = {name: str(context.get(name) or "") for name in FIELDS}
    return Template(template).safe_substitute(values).strip()


def brief(phase: str, context: dict, named: str = "") -> str:
    """What this phase is actually asked, prompt and all.

    A refusal or a reviewer's comment REPLACES the spec rather than joining it:
    re-stating the original alongside a specific complaint is how a turn ends up
    solving the wrong one.
    """
    if context.get("brief"):
        return str(context["brief"])

    template = load(phase, named)
    if not template:
        # No prompt for this phase. The spec alone, which is what every phase
        # got before prompts existed.
        spec = str(context.get("spec") or "")
        plan = str(context.get("plan") or "")
        return f"{spec}\n\n## The plan\n\n{plan}" if plan else spec

    return render(template, context)


def declared() -> dict[str, bool]:
    """Which phases have a prompt, for `make config`.

    A phase running on the bare spec is a phase nobody told what its job is, and
    that is invisible until a turn wastes a step working out what it is for.
    """
    folder = paths.root() / "prompts"
    if not folder.is_dir():
        return {}
    return {path.stem: True for path in sorted(folder.glob("*.md"))}
