"""The stage graph: what happens, in what order, and what decides.

A job moves through stages. Each stage names a phase to run or an action to
take, and says where to go next. The whole thing is declared in
`settings/pipeline.yaml` and interpreted here, so **a team that wants a
different flow of work edits YAML rather than this file**.

Every function is pure. `next_stage` is a function of the job, the graph and the
result, which is what lets every branch of the pipeline be tested without an
engine, a worktree, or a pull request. That property is the whole reason the
factory is worth writing this way: wipp's equivalent decision was spread across
a 3,000-line worker and could only be exercised by sending a real spec.

**Job states are derived from the graph**, not from an enum here. A team that
adds a `threat-model` stage gets a `threat-model` state for free, and one that
deletes `prove` does not leave a dead state behind.
"""

from __future__ import annotations

from dataclasses import dataclass, field

# What a stage can do when it is not running a phase. Each is implemented by the
# factory; a name that is not here and not in `actions/` is a configuration
# error rather than a silent no-op.
BUILTIN_ACTIONS = {
    "prepare_workspace": "claim a worktree and run the repo's prepare command",
    "open_pull_request": "publish the work for a human to decide on",
    "watch_pull_request": "poll the forge and react to what the human did",
    "teardown": "release the worktree and run the repo's cleanup command",
    "stop": "the job ends here",
}

# The states a job can be in that are not stages. `blocked` is a turn waiting on
# a person; the rest are outcomes.
TERMINAL = ("landed", "closed", "failed")
BLOCKED = "blocked"


class GraphError(ValueError):
    """A pipeline that cannot be run as written."""


@dataclass(frozen=True)
class Stage:
    """One step, as declared."""

    name: str
    phase: str = ""
    action: str = ""
    next: str = ""
    # Skip this stage when the job carries one of these reasons. A gate's
    # complaint and a reviewer's comment are already briefs; re-planning would
    # only blur them.
    skip_when: tuple[str, ...] = ()
    optional: bool = False
    # What a refusal from this stage does: where to go, how many times, and when
    # to stop trying.
    on_refusal: str = ""
    max_revisions: int = 2
    # A gate that repeats itself word for word has already proved its complaint
    # is not about the diff, so a second attempt costs a turn and learns nothing.
    stop_when_identical: bool = True
    on_error: str = "fail"
    guard: str = ""
    contract: str = ""
    # What the human did, for a stage that watches a pull request. These are
    # edges too: `rework` is reachable only through one of them, and a walk that
    # follows `next` alone reports it unreachable.
    outcomes: tuple[tuple[str, str], ...] = ()
    isolation: str = ""
    oversight: str = ""
    revert_worktree_changes: bool = False

    @property
    def runs_a_turn(self) -> bool:
        return bool(self.phase)


@dataclass
class Graph:
    """A whole pipeline, and everything wrong with it."""

    stages: dict[str, Stage] = field(default_factory=dict)
    first: str = ""
    terminal: tuple[str, ...] = TERMINAL
    problems: list[str] = field(default_factory=list)

    @property
    def states(self) -> tuple[str, ...]:
        """Every state a job can be in. Derived, so adding a stage adds a state."""
        return tuple(self.stages) + tuple(self.terminal) + (BLOCKED,)

    def phases(self) -> tuple[str, ...]:
        return tuple(dict.fromkeys(s.phase for s in self.stages.values() if s.phase))

    def get(self, name: str) -> Stage | None:
        return self.stages.get(name)


def parse(config: dict | None) -> Graph:
    """Read `settings/pipeline.yaml`. A missing file means the built-in graph.

    Problems are collected rather than raised, so `make config` can show a
    person every mistake at once instead of the first one.
    """
    config = config or {}
    graph = Graph(terminal=tuple(config.get("terminal") or TERMINAL))

    declared = config.get("stages") or {}
    if not declared:
        graph.problems.append("no stages declared, so this pipeline does nothing")
        return graph

    for name, block in declared.items():
        block = block or {}
        graph.stages[name] = Stage(
            name=name,
            phase=str(block.get("phase") or ""),
            action=str(block.get("action") or ""),
            next=str(block.get("next") or block.get("then") or ""),
            skip_when=tuple(block.get("skip_when") or ()),
            optional=bool(block.get("optional")),
            on_refusal=str((block.get("on_refusal") or {}).get("goto") or ""),
            max_revisions=int((block.get("on_refusal") or {}).get("max", 2)),
            stop_when_identical=bool(
                (block.get("on_refusal") or {}).get("stop_when_identical", True)),
            on_error=str(block.get("on_error") or "fail"),
            guard=str(block.get("guard") or ""),
            contract=str(block.get("contract") or ""),
            isolation=str(block.get("isolation") or ""),
            oversight=str(block.get("oversight") or ""),
            revert_worktree_changes=bool(block.get("revert_worktree_changes")),
            outcomes=tuple((k[3:], str(v)) for k, v in sorted(block.items())
                           if k.startswith("on_") and k != "on_refusal"
                           and k != "on_error" and isinstance(v, str)),
        )

    graph.first = str(config.get("first") or next(iter(declared)))
    graph.problems.extend(validate(graph))
    return graph


def validate(graph: Graph) -> list[str]:
    """Everything that would make this pipeline stall, as sentences.

    The checks are the ones that produce a job stuck in a state nobody is
    watching, which is the failure an unattended factory cannot afford: it does
    not crash, it just stops, and nothing says so.
    """
    problems = []
    known = set(graph.stages) | set(graph.terminal) | {BLOCKED, ""}

    if graph.first not in graph.stages:
        problems.append(f"the pipeline starts at `{graph.first}`, which is not a stage")

    for stage in graph.stages.values():
        if not stage.phase and not stage.action:
            problems.append(f"`{stage.name}` names neither a phase nor an action, "
                            "so nothing happens there")
        if stage.phase and stage.action:
            problems.append(f"`{stage.name}` names both a phase and an action. "
                            "One stage does one thing")
        if stage.action and stage.action not in BUILTIN_ACTIONS:
            # Not fatal: it may be a Python file in `actions/`. The factory
            # reports an action it cannot find at load, not here.
            pass
        for field_name, target in ([("next", stage.next),
                                    ("on_refusal.goto", stage.on_refusal)]
                                   + [(f"on_{k}", v) for k, v in stage.outcomes]):
            if target and target not in known:
                problems.append(f"`{stage.name}.{field_name}` points at `{target}`, "
                                "which is not a stage or a terminal state")
        if not stage.next and stage.action not in ("stop", "watch_pull_request"):
            problems.append(f"`{stage.name}` has no `next`, so a job reaching it "
                            "stops without ending. Say `next: failed` if that is "
                            "what you mean")
        if stage.max_revisions < 0:
            problems.append(f"`{stage.name}.on_refusal.max` is negative")

    problems.extend(unreachable(graph))
    return problems


def unreachable(graph: Graph) -> list[str]:
    """Stages nothing can reach.

    A stage nobody arrives at is a stage that was renamed somewhere else and not
    here, and it is silent: the pipeline still runs, just not through it.
    """
    seen, queue = set(), [graph.first]
    while queue:
        name = queue.pop()
        if name in seen or name not in graph.stages:
            continue
        seen.add(name)
        stage = graph.stages[name]
        queue.extend(t for t in (stage.next, stage.on_refusal,
                                 *(target for _, target in stage.outcomes)) if t)

    return [f"`{name}` cannot be reached from `{graph.first}`"
            for name in graph.stages if name not in seen]


@dataclass(frozen=True)
class Transition:
    """Where a job goes next, and why."""

    to: str
    why: str = ""
    # Set when the move is a retry rather than progress, so the record can tell
    # a revision from a stage that simply came next.
    revision: bool = False

    @property
    def terminal(self) -> bool:
        return self.to in TERMINAL


def on_outcome(stage: Stage, outcome: str) -> str:
    """Where a watched pull request sends a job when the human acts.

    Merge lands it, close closes it, a comment is a brief for another turn onto
    the same branch. Nothing is one of them: the card waits.
    """
    return dict(stage.outcomes).get(outcome, "")


def next_stage(job: dict, graph: Graph, result: dict | None = None) -> Transition:
    """The whole state machine, as one pure function of two dicts.

    `job` carries `stage`, `reason`, and `revisions`. `result` is what the stage
    produced: `ok`, `refused`, `refusal`, `blocked`.

    Every branch here is testable without a pull request, which is the point.
    """
    result = result or {}
    stage = graph.get(str(job.get("stage") or ""))
    if stage is None:
        return Transition("failed", f"no stage `{job.get('stage')}` in this pipeline")

    # A turn that stopped to ask a person. The job waits; nothing is retried,
    # because asking the same question twice is not asking.
    if result.get("blocked"):
        return Transition(BLOCKED, "the turn asked a question and is waiting")

    # A stage that watches rather than runs: what happens next is what the
    # person did, and "nothing" is a legitimate answer that means stay put.
    if stage.outcomes:
        outcome = str(result.get("outcome") or "")
        target = on_outcome(stage, outcome)
        if not target:
            return Transition(stage.name, "the card waits")
        return Transition(target, f"the human {outcome}")

    if result.get("refused"):
        return on_refusal(job, stage, result)

    if not result.get("ok", True):
        if stage.on_error == "continue":
            # A failed plan does not fail the job: it hands over an empty plan.
            return Transition(skip_to(job, graph, stage.next),
                              f"`{stage.name}` failed and is allowed to")
        return Transition("failed", f"`{stage.name}` failed: "
                                    f"{str(result.get('error') or '')[:200]}")

    return Transition(skip_to(job, graph, stage.next), f"`{stage.name}` finished")


def on_refusal(job: dict, stage: Stage, result: dict) -> Transition:
    """What a refused stage does. This is where a revision loop lives.

    Bounded twice, and the second bound is the interesting one. An agent that
    cannot satisfy a gate twice will not satisfy it on the ninth try, and finding
    out costs a turn each time. But a gate that comes back **word for word** has
    already proved its complaint is not a function of the diff, so there is
    nothing to learn from another attempt at all.
    """
    if not stage.on_refusal:
        return Transition("failed", f"`{stage.name}` was refused and has nowhere "
                                    "to go. Give it an `on_refusal`")

    revisions = int(job.get("revisions") or 0)
    if revisions >= stage.max_revisions:
        return Transition("failed", f"refused {revisions + 1} times; "
                                    f"`{stage.name}.on_refusal.max` is "
                                    f"{stage.max_revisions}")

    refusal = str(result.get("refusal") or "")
    if stage.stop_when_identical and refusal and refusal == str(job.get("last_refusal") or ""):
        return Transition("failed", "the refusal came back word for word, so it is "
                                    "not about the diff and another turn would "
                                    "learn nothing")

    return Transition(stage.on_refusal, "refused; another attempt with the "
                                        "refusal as the brief", revision=True)


def skip_to(job: dict, graph: Graph, target: str) -> str:
    """Follow `skip_when` and `optional` forward to the first stage that runs.

    Chained, because turning off both `prove` and `review` should reach
    `publish` rather than land on a stage that is also skipped.
    """
    reason = str(job.get("reason") or "")
    seen = set()
    while target in graph.stages and target not in seen:
        seen.add(target)
        stage = graph.stages[target]
        skipped = (reason and reason in stage.skip_when) or (
            stage.optional and not job.get(f"want_{stage.name}", True))
        if not skipped:
            return target
        target = stage.next
    return target
