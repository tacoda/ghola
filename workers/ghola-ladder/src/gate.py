"""The decision, as a pure function. Rungs 2, 3 and 4 all end up here.

`decide` takes rules and a proposed write and returns what to do about it. It
does no I/O, calls no engine, and knows nothing about the harness. That is what
lets every branch of the ladder be tested without a running agent, and it is why
the hook in `main.py` is fifteen lines.

The three rungs differ in **what they can see**, not in how hard they push:

- rung 2 sees whatever the repository's own hook is given
- rung 3 sees one function call and its arguments, before the target runs
- rung 4 sees the finished diff, and what the job is about to publish

So the same predicate mounted at two rungs is not redundancy. A tool gate never
sees a shell heredoc, and a delivery gate only ever sees the finished file.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from predicate import Finding
from primitive import Primitive

# What the harness understands back from a `pre-trigger` hook.
CONTINUE = "continue"
DENY = "deny"
HOLD = "hold"


@dataclass(frozen=True)
class Write:
    """A proposed change, however it arrived.

    One shape for all three rungs, because the alternative is three shapes and a
    rule that behaves differently depending on which gate asked. `function_id` is
    empty at rung 4, where there is no call, and `content` is empty at rung 3
    when the call is not a write.
    """

    path: str = ""
    content: str = ""
    function_id: str = ""
    arguments: dict = field(default_factory=dict)
    # Text the model wrote that is not a file: a commit message, a pull request
    # body, a summary. Rung 4 sees these and no other rung does, because nothing
    # wrote them through a tool.
    publishing: str = ""


@dataclass(frozen=True)
class Decision:
    """What to do, and the words to say about it."""

    action: str = CONTINUE
    reason: str = ""
    rule_id: str = ""
    rung: int = 0
    findings: tuple[Finding, ...] = ()

    @property
    def allowed(self) -> bool:
        return self.action == CONTINUE

    def as_hook_response(self) -> dict:
        """The shape `harness::hook::pre-trigger` expects."""
        if self.action == CONTINUE:
            return {"decision": CONTINUE}
        response = {"decision": self.action, "reason": self.reason}
        if self.rule_id:
            response["annotations"] = {"ladder.rule": self.rule_id,
                                       "ladder.rung": self.rung}
        return response


def escaped(rule: Primitive, write: Write) -> bool:
    """Whether this write used the rule's escape hatch.

    An escape hatch is a sanctioned path that records why it was taken, which is
    strictly better than an unsanctioned one nobody can count. The hatch has to
    appear in the content itself, so it travels with the code rather than living
    in a decision nobody can find later.
    """
    if not rule.escape:
        return False
    return rule.escape in write.content or rule.escape in write.publishing


def decide(rules: list[Primitive], write: Write, rung: int,
           run) -> Decision:
    """The first rule that refuses, or `continue`.

    `run(rule, write) -> list[Finding]` is handed in rather than imported, so
    this function stays pure and the caller decides whether a predicate is a
    Python file or a function on the bus.

    Rules are asked in order and the first refusal wins. Ordering by severity
    would be a second ranking to keep in step with the rungs, and a refusal is a
    refusal: the model has to solve one of them either way.
    """
    for rule in rules:
        if rung not in rule.rungs:
            continue
        if write.path and not rule.governs_path(write.path):
            continue
        if write.function_id and not rule.governs_function(write.function_id):
            continue
        if escaped(rule, write):
            continue

        findings = run(rule, write)
        if not findings:
            continue

        detail = "; ".join(str(f) for f in findings[:3])
        reason = rule.says(detail)

        if rule.policy == "warn":
            # Allowed and counted. A warn that blocked would be a refuse with a
            # gentler name, and the count is the evidence for promoting it.
            continue
        action = HOLD if rule.policy == "ask" else DENY
        return Decision(action=action, reason=reason, rule_id=rule.id,
                        rung=rung, findings=tuple(findings))

    return Decision()


def warnings(rules: list[Primitive], write: Write, rung: int, run) -> list[Decision]:
    """Every `warn` rule that fired, so the count is real.

    Separate from `decide` because a warning is not a decision: it changes
    nothing about the call, and folding it into the return value would make
    every caller check whether the thing it got back was an answer.
    """
    fired = []
    for rule in rules:
        if rung not in rule.rungs or rule.policy != "warn":
            continue
        if write.path and not rule.governs_path(write.path):
            continue
        if escaped(rule, write):
            continue
        findings = run(rule, write)
        if findings:
            fired.append(Decision(action=CONTINUE, reason=rule.says(str(findings[0])),
                                  rule_id=rule.id, rung=rung, findings=tuple(findings)))
    return fired
