"""What went wrong recently, from the record rather than from memory.

The improve lane needs evidence, and the audit log is where it already is: every
refusal, every hold, every downgrade, every stage transition, hash-chained and
never pruned. This module reads it and the job records and answers one question
— **what cost something** — so a turn can be asked what would have prevented it.

**Trouble is read broadly.** A job that reached a pull request still counts if it
cost a revision, blocked on a question, came back `concerns`, or had a check
touch the tree. A job that went straight through with nothing to say is silent,
and a lane that only looked at outright failures would miss almost everything
worth fixing.

Everything here is pure: jobs and audit entries in, findings out.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field

# What each signal argues for. The improve lane is not "list the failures": a
# count is not an argument, and the useful output names a change.
@dataclass
class Signal:
    """One thing that cost something, and what it suggests."""

    kind: str
    what: str
    argues_for: str
    jobs: tuple[str, ...] = ()
    count: int = 1
    detail: dict = field(default_factory=dict)

    @property
    def recurring(self) -> bool:
        """Once is a coincidence and still worth raising; twice is a pattern.

        One failure is enough to raise a proposal — a suggestion is cheap to
        reject and recurs if it mattered — but the difference is worth carrying
        so a reader can tell them apart.
        """
        return self.count > 1


def of_jobs(jobs: list[dict]) -> list[Signal]:
    """What the job records themselves say went wrong."""
    found: list[Signal] = []

    revised = [j for j in jobs if int(j.get("revisions") or 0) > 0]
    if revised:
        found.append(Signal(
            kind="revision",
            what=f"{len(revised)} job(s) needed a revision",
            argues_for=("the repository's own commit gate refused work the run "
                        "phase thought was finished. Either the gate's rule is "
                        "not in the charter the turn reads, or it is and the "
                        "prose is not carrying it"),
            jobs=tuple(str(j.get("id") or "") for j in revised),
            count=sum(int(j.get("revisions") or 0) for j in revised)))

    failed = [j for j in jobs if j.get("stage") == "failed"]
    for job in failed:
        why = last_why(job)
        found.append(Signal(
            kind="failure",
            what=f"a job failed: {why[:160]}",
            argues_for=("a failure the pipeline could not turn into another "
                        "attempt. If it is a shape that will recur, it wants a "
                        "stage or a guard rather than a person"),
            jobs=(str(job.get("id") or ""),),
            detail={"stage_reached": reached(job)}))

    blocked = [j for j in jobs if j.get("stage") == "blocked"]
    if blocked:
        found.append(Signal(
            kind="interrupt",
            what=f"{len(blocked)} job(s) stopped to ask a question",
            argues_for=("the spec did not answer something the work needed. A "
                        "recurring question belongs in the charter or in the "
                        "spec template, not in a turn"),
            jobs=tuple(str(j.get("id") or "") for j in blocked),
            count=len(blocked)))

    for name in ("verdict", "proven"):
        objected = [j for j in jobs
                    if str(j.get(name) or "") in ("concerns", "blocker", "no",
                                                  "unproven", "unreadable")]
        if objected:
            answers = Counter(str(j.get(name)) for j in objected)
            found.append(Signal(
                kind=f"{name}-objected",
                what=f"{len(objected)} job(s) came back {dict(answers)}",
                argues_for=("a check found something the phase before it did "
                            "not. What the check keeps finding is a candidate "
                            "for a rule carried earlier"),
                jobs=tuple(str(j.get("id") or "") for j in objected),
                count=len(objected),
                detail={"answers": dict(answers)}))

    downgraded = [j for j in jobs
                  if j.get("verdict_downgraded") or j.get("proven_downgraded")]
    if downgraded:
        found.append(Signal(
            kind="downgrade",
            what=f"{len(downgraded)} check(s) claimed more than their output supported",
            argues_for=("a phase whose prompt is drifting: it is answering in a "
                        "shape the contract rejects. This is what an eval on "
                        "that prompt is for"),
            jobs=tuple(str(j.get("id") or "") for j in downgraded),
            count=len(downgraded)))

    return found


def of_audit(entries: list[dict]) -> list[Signal]:
    """What the audit log says, which the job records cannot.

    A refusal is recorded per rung, so this is the only place that can say which
    rung is doing the work — and a backstop that starts catching everything is a
    signal about how turns are writing rather than an argument for tightening.
    """
    found: list[Signal] = []

    refusals = [e for e in entries if e.get("kind") == "ladder.refused"]
    by_rule = Counter(str(e.get("actor") or "?") for e in refusals)
    by_rung = Counter(str((e.get("detail") or {}).get("rung", "?"))
                      for e in refusals)

    for rule, count in by_rule.most_common():
        rungs = {str((e.get("detail") or {}).get("rung", "?"))
                 for e in refusals if e.get("actor") == rule}
        found.append(Signal(
            kind="refusal",
            what=f"`{rule}` refused {count} call(s) at rung {', '.join(sorted(rungs))}",
            argues_for=("a rule the turns keep hitting. If the charter states "
                        "it and they still hit it, the prose is not carrying "
                        "it and the rule wants a higher rung"),
            count=count,
            detail={"rule": rule, "rungs": sorted(rungs)}))

    if len(by_rung) > 1:
        found.append(Signal(
            kind="rung-distribution",
            what=f"catches by rung: {dict(by_rung)}",
            argues_for=("which rung is actually working. A backstop doing all "
                        "the work is a signal about how turns are writing, not "
                        "an argument for tightening anything"),
            detail={"by_rung": dict(by_rung)}))

    held = [e for e in entries if e.get("kind") == "approval.held"]
    if held:
        by_function = Counter(str(e.get("actor") or "?") for e in held)
        found.append(Signal(
            kind="held",
            what=f"{len(held)} call(s) waited for a person: {dict(by_function)}",
            argues_for=("work that could not proceed unattended. A call held "
                        "every time is either a rule that should refuse "
                        "deterministically, or a capability that should be "
                        "granted"),
            count=len(held),
            detail={"by_function": dict(by_function)}))

    warned = [e for e in entries if e.get("kind") == "ladder.warned"]
    if warned:
        found.append(Signal(
            kind="warned",
            what=f"{len(warned)} contract downgrade(s) recorded",
            argues_for=("a check claiming more than its output supports. The "
                        "prompt is the thing to change, and an eval is how you "
                        "would know it worked"),
            count=len(warned)))

    return found


def carried_mechanically(rule: dict) -> bool:
    """Whether anything would record this rule doing its job.

    Rung 0 is prose. A rule carried only there refuses nothing and warns
    nothing, so it cannot produce an audit entry however well it is working.
    """
    return any(int(r.get("number") or 0) > 0 for r in (rule.get("rungs") or []))


def never_fired(rules: list[dict], entries: list[dict]) -> list[Signal]:
    """Rules that could have fired and did not, and rules that could not.

    **A rule that never fires is a demote if it still matters and a remove if
    nobody can say why it is there.** Those are different findings, and the
    difference is whether the `why` survives contact with the evidence — which
    is a judgement, so this reports the fact and lets the turn make it.

    That argument only holds for a rule something could have recorded. **A rule
    carried at prose refuses nothing by construction**, so it appears silent at
    any volume of jobs and no matter how well it is working, and offering it as
    removal evidence is offering an argument that cannot be answered. The
    improve lane's own first live run caught this in this function, and
    proposed the split below against three correct rules it would otherwise
    have argued for deleting.
    """
    fired = {str(e.get("actor") or "") for e in entries
             if e.get("kind") in ("ladder.refused", "ladder.warned")}
    silent = [r for r in rules if str(r.get("id") or "") not in fired]
    if not silent:
        return []

    watched = [r for r in silent if carried_mechanically(r)]
    prose = [r for r in silent if not carried_mechanically(r)]
    found = []

    if watched:
        found.append(Signal(
            kind="never-fired",
            what=f"{len(watched)} rule(s) never fired: {named(watched)}",
            argues_for=("either settled or theatre. A rule that still matters "
                        "wants a demotion; one nobody can say why is there wants "
                        "removing. **Removal is half the work and the one nobody "
                        "does unprompted**: prose accumulates because nothing "
                        "ever fails because of a paragraph"),
            count=len(watched),
            detail={"rules": ids(watched)}))

    if prose:
        found.append(Signal(
            kind="unobservable",
            what=f"{len(prose)} rule(s) are carried at prose: {named(prose)}",
            argues_for=("nothing records whether these fired, so their silence "
                        "is not evidence about them. If one matters, promote it "
                        "to a rung that leaves a trace; if it does not, that is "
                        "a separate argument and this is not the evidence for it"),
            count=len(prose),
            detail={"rules": ids(prose)}))

    return found


def ids(rules: list[dict]) -> list[str]:
    return [str(r.get("id") or "") for r in rules]


def named(rules: list[dict], most: int = 8) -> str:
    return ", ".join(ids(rules)[:most])


def gather(jobs: list[dict], entries: list[dict],
           rules: list[dict] | None = None) -> list[Signal]:
    """Everything worth asking about, newest evidence first."""
    found = of_jobs(jobs) + of_audit(entries) + never_fired(rules or [], entries)
    return sorted(found, key=lambda s: (-s.count, s.kind))


def quiet(jobs: list[dict], signals: list[Signal]) -> bool:
    """Whether there is anything to improve.

    A run with nothing wrong produces no proposals rather than inventing some.
    An improve lane that always finds three things is a lane nobody believes by
    the third time.
    """
    return not signals


def as_brief(signals: list[Signal], jobs: list[dict]) -> str:
    """The evidence, as the turn is handed it."""
    if not signals:
        return "Nothing went wrong in the jobs on record."

    lines = [f"{len(jobs)} job(s) on record. What cost something:", ""]
    for signal in signals:
        lines.append(f"### {signal.what}")
        lines.append("")
        lines.append(f"- **signal**: `{signal.kind}`"
                     + (f", seen {signal.count} times" if signal.recurring else ""))
        lines.append(f"- **suggests**: {signal.argues_for}")
        if signal.jobs:
            lines.append(f"- **jobs**: {', '.join(j[:8] for j in signal.jobs[:6])}")
        if signal.detail:
            lines.append(f"- **detail**: `{signal.detail}`")
        lines.append("")
    return "\n".join(lines)


# ------------------------------------------------------------- helpers

def last_why(job: dict) -> str:
    history = job.get("history") or []
    return str(history[-1].get("why") or "") if history else ""


def reached(job: dict) -> str:
    """The furthest stage a job got to, which is where the trouble is."""
    history = job.get("history") or []
    return str(history[-1].get("from") or "") if history else str(job.get("stage") or "")
