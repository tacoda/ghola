"""Governance gates: what a machine can prove before something ships.

Three mechanisms sit in front of a call, and confusing them is how a system ends
up with two of them and a gap:

| mechanism | decides | when it is right |
|---|---|---|
| the `ladder` worker | what a **rule** can decide deterministically | a constraint on how code is written |
| `approval-gate` | what a **human** should decide | a judgment nobody wrote down |
| `opengantry` | what a **machine can prove is unsafe** | shipping: merge, deploy, publish |

The third is this module's subject. iii can already run an agent unattended; the
open question is letting one *ship* unattended, and the answer is not more trust.
It is proof: the repository's own build and test commands, run against a declared
edit scope, producing a verdict bound to that exact revision. Edit the work
afterwards and the verdict stops matching.

**A promote-class call is one that changes something outside this machine.** The
suffixes are `opengantry`'s vocabulary rather than ghola's, deliberately: a
second list of what counts as shipping would be a second list to keep in step,
and this design has twice been bitten by exactly that.

Everything here is pure. Whether a verdict exists is somebody else's I/O.
"""

from __future__ import annotations

from dataclasses import dataclass, field

# `opengantry`'s kernel matches on these. A call whose id ends in one of them
# changes the world outside this machine and requires a verdict.
PROMOTE_SUFFIXES = ("::promote", "::deploy", "::merge", "::publish", "::apply",
                    "::push")

# Functions this stack reaches for that ship something without saying so in
# their name. `worktree::land` fast-forwards a target branch, which is a merge
# whatever it is called, and `github::pr::create` publishes to a forge.
#
# Named here because the suffix rule cannot see them, and a governance gate that
# only catches the calls polite enough to be called `::deploy` is theatre.
ALSO_PROMOTE = {
    "worktree::land": "fast-forwards a target branch",
    "github::pr::merge": "merges a pull request",
    "github::release::create": "publishes a release",
}

# Deliberately NOT promote-class, and the distinction is the whole design.
#
# The first real job through this pipeline failed here, and it was right to
# fail and wrong to be asked. `github::pr::create` publishes a PROPOSAL that a
# human then decides on. It is the one thing ghola exists to do, and gating it
# behind a machine proof means a factory whose entire output requires a verdict
# it has no way to mint yet.
#
# **What changes the world is the merge, not the proposal.** A pull request
# nobody merged has changed nothing, which is the same reason ghola never
# merges: the human is the gate, and a gate in front of asking the human is a
# gate in front of the wrong thing.
NOT_PROMOTE = {
    "github::pr::create": "a pull request is a proposal; the human decides",
    "github::pr::comment": "a comment asks; it does not change code",
    "github::issue::create": "an issue asks; it does not change code",
}

ALLOW = "allow"
REQUIRE_VERDICT = "require-verdict"
DENY = "deny"


@dataclass(frozen=True)
class Gate:
    """What governance says about one call."""

    decision: str = ALLOW
    reason: str = ""
    function_id: str = ""
    why_promote: str = ""

    @property
    def allowed(self) -> bool:
        return self.decision == ALLOW


def is_promote(function_id: str) -> tuple[bool, str]:
    """Whether this call ships something, and why it counts as shipping."""
    if function_id in NOT_PROMOTE:
        return False, ""
    if function_id in ALSO_PROMOTE:
        return True, ALSO_PROMOTE[function_id]
    for suffix in PROMOTE_SUFFIXES:
        if function_id.endswith(suffix):
            return True, f"its name ends in `{suffix}`"
    return False, ""


def decide(function_id: str, has_verdict: bool, oversight_level: str = "supervised",
           allowed_functions: tuple[str, ...] = ()) -> Gate:
    """Whether a call may proceed, and what it must prove first.

    `has_verdict` is whether a valid, current verdict token accompanies the call.
    This function does not mint or check one: `gantry::verify` mints and
    `gantry::middleware` checks, and reimplementing either here would be a second
    implementation of one rule.

    **Fail closed.** A promote-class call with no verdict is refused rather than
    allowed with a warning, at every oversight level including `manual`. A person
    watching is not the same as a machine having proved anything, and the two are
    routinely confused: the whole point of this gate is that "somebody clicked
    approve" is weaker evidence than "the repository's own tests passed against
    this exact revision".
    """
    promote, why = is_promote(function_id)
    if not promote:
        return Gate(ALLOW, function_id=function_id)

    if allowed_functions and function_id not in allowed_functions:
        return Gate(DENY, function_id=function_id, why_promote=why, reason=(
            f"`{function_id}` ships something ({why}) and this stage was not "
            "granted it. Rung 1 already stopped this; governance agrees."))

    if has_verdict:
        return Gate(ALLOW, function_id=function_id, why_promote=why)

    return Gate(REQUIRE_VERDICT, function_id=function_id, why_promote=why, reason=(
        f"`{function_id}` ships something ({why}), and nothing has proved this "
        "change is safe. Run the repository's own gates first: a verdict is "
        "bound to the exact revision it was minted against, so editing the work "
        "afterwards invalidates it. Approval by a person is not a substitute, "
        "because it is weaker evidence than the tests passing."))


@dataclass
class Policy:
    """`settings/governance.yaml`, with the convention as the default."""

    require_verdict: bool = True
    extra_promote: dict[str, str] = field(default_factory=dict)
    exempt: tuple[str, ...] = ()

    @classmethod
    def of(cls, config: dict | None) -> "Policy":
        config = config or {}
        return cls(
            # Defaults to on. A governance gate that ships off is a governance
            # gate nobody turns on.
            require_verdict=bool(config.get("require_verdict", True)),
            extra_promote=dict(config.get("also_promote") or {}),
            exempt=tuple(config.get("exempt") or ()),
        )

    def gate(self, function_id: str, has_verdict: bool,
             oversight_level: str = "supervised",
             allowed_functions: tuple[str, ...] = ()) -> Gate:
        """The decision, with this deployment's additions and exemptions.

        An exemption is a deliberate hole and is recorded as one: it appears in
        the audit log with the function it excused, so "why did that ship
        unproven" has an answer that is not a shrug.
        """
        if function_id in self.exempt:
            return Gate(ALLOW, function_id=function_id, reason=(
                f"`{function_id}` is exempt in settings/governance.yaml. This is "
                "a deliberate hole and is recorded as one."))
        if function_id in self.extra_promote and not has_verdict:
            return Gate(REQUIRE_VERDICT, function_id=function_id,
                        why_promote=self.extra_promote[function_id],
                        reason=(f"`{function_id}` ships something "
                                f"({self.extra_promote[function_id]}), declared in "
                                "settings/governance.yaml, and nothing has proved "
                                "this change is safe."))
        if not self.require_verdict:
            promote, why = is_promote(function_id)
            return Gate(ALLOW, function_id=function_id, why_promote=why, reason=(
                "governance.require_verdict is off in settings/governance.yaml"
                if promote else ""))
        return decide(function_id, has_verdict, oversight_level, allowed_functions)
