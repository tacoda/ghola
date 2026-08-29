"""How much of this a person watches. A dial, not a switch.

"Dark factory" is a useful phrase and a bad setting. Nobody actually wants a
system where no human sees anything, and nobody wants to approve every read
either. What they want is to choose, and to move the dial as trust is earned.

Four levels, from a person answering every call to a person answering none:

| level | what a person answers | what refuses without asking |
|---|---|---|
| `manual` | every call | nothing. Every decision is a person's |
| `attended` | every write | reads run |
| `supervised` | only what a rule marks `ask` | the ladder, deterministically |
| `dark` | nothing | the ladder, and `ask` degrades to refuse |

**`supervised` is the default**, and it is the one the rest of this design is
built for: the ladder refuses what it can decide, and a person is asked only
about the calls a rule explicitly could not decide. `manual` and `dark` are the
ends of the dial rather than the sensible positions.

The level maps onto two mechanisms that already exist, which is the point of
having it: `approval-gate`'s per-session mode, and what the ladder does with a
`policy: ask`. Without one name for the pair, an operator has to know that
setting a mode to `full` silently turns every `ask` rule into something else.
"""

from __future__ import annotations

from dataclasses import dataclass

MANUAL = "manual"
ATTENDED = "attended"
SUPERVISED = "supervised"
DARK = "dark"

LEVELS = (MANUAL, ATTENDED, SUPERVISED, DARK)
DEFAULT = SUPERVISED


@dataclass(frozen=True)
class Oversight:
    """What one level means to each mechanism."""

    level: str
    # The mode `approval-gate` is put into for this session.
    approval_mode: str
    # What a rule carrying `policy: ask` does when nobody can be asked. This is
    # the setting that must never quietly become "allow": an unattended factory
    # reading "ask" as "yes" has answered a question nobody put.
    ask_becomes: str
    why: str


SETTINGS = {
    MANUAL: Oversight(
        level=MANUAL, approval_mode="manual", ask_becomes="ask",
        why=("Every call waits for a person. Use it the first time you point this "
             "at a repository, and when you want to watch what it reaches for.")),
    ATTENDED: Oversight(
        level=ATTENDED, approval_mode="auto", ask_becomes="ask",
        why=("Reads run; writes wait for a person. The useful middle when the work "
             "is trusted and the blast radius is not.")),
    SUPERVISED: Oversight(
        level=SUPERVISED, approval_mode="full", ask_becomes="ask",
        why=("The ladder refuses what it can decide, and a person is asked only "
             "about calls a rule explicitly marked `ask`. This is the shape the "
             "rest of the design assumes.")),
    DARK: Oversight(
        level=DARK, approval_mode="full", ask_becomes="refuse",
        why=("Nothing waits for a person, so a rule that wanted one refuses "
             "instead. `ask` becoming `allow` here would be the factory answering "
             "a question nobody put.")),
}


def resolve(level: str | None, stage: str = "") -> Oversight:
    """The oversight for a level name, falling back to the default.

    An unknown name is the default rather than an error, and the caller reports
    it. Failing a job because an operator wrote `oversight: paranoid` would be a
    worse outcome than running it supervised and saying so.
    """
    return SETTINGS.get(str(level or "").strip().lower(), SETTINGS[DEFAULT])


def for_stage(config: dict | None, stage: str = "") -> Oversight:
    """The oversight for one stage, from `settings/oversight.yaml`.

    A stage may name its own, because `run` and `review` genuinely want
    different answers: a review reads and reports, and holding its calls buys
    nothing. Anything a stage does not say falls to the top-level default.

    ```yaml
    default: supervised
    stages:
      run: attended       # writes wait for a person
      review: dark        # it cannot write anyway
    ```
    """
    config = config or {}
    named = (config.get("stages") or {}).get(stage) if stage else None
    return resolve(named or config.get("default"))


def describe(oversight: Oversight) -> str:
    """One line an operator can read before a job runs unattended."""
    return (f"{oversight.level}: approvals {oversight.approval_mode}, "
            f"`ask` rules {oversight.ask_becomes}. {oversight.why}")
