<!-- voice-register: informational -->
<!-- voice-english: ste -->

# Evals

A test tells you whether a function returns the right value. An eval tells you
whether a prompt change made the answers better or worse. ghola needs both. Half
of it is code, and the other half asks a model to judge something.

**ghola writes no eval runner.** The stock `eval` worker already runs durable
same-model A/B evaluations, alternates variant order to reduce order bias,
persists its reports, and injects a console page. What it leaves open is the one
thing it cannot know: whether a particular answer was any good.

## Running them

```
make eval                                 every case
make eval CASE=prove-cites-evidence       one case
make eval RESULT=eval_abc123              what it found
```

Evaluations are durable and run in the background. They cost money, so nothing
runs them on a timer. Run them before you ship a prompt change. That is the
moment they earn their price.

## What a case looks like

Each file in `evals/` is an `eval::start` request:

```json
{
  "dimension": "prompt",
  "model": {"model": "claude-sonnet-5", "provider": "anthropic"},
  "control":   {"label": "names a file and line",  "prompt": "..."},
  "treatment": {"label": "objects without naming", "prompt": "..."},
  "evaluator": {
    "function_id": "ghola::eval::verdict-is",
    "arguments": {"contract": "verdict", "equals": "concerns"}
  }
}
```

**One case changes exactly one dimension.** An A/B that changed two things tells
you something moved. It never tells you which thing moved it. The worker
enforces this, and so does `make test`.

## A case that cannot fail is not evidence

Write the failing half first. A suite where every case passes tells you the
suite runs, and nothing else.

Both shipped cases discriminate against a real model. `verdict-is` passes a
review naming `app.py:9`. It fails one that says "something about this feels
wrong", which is the behavior the contract exists to catch. Control scores 1/1,
treatment scores 0/1, and the pass-rate delta is -1.0.

Read the delta before the pass counts, and check the reader agrees with the
console. The first version of `make eval RESULT=` printed "0/0 passed" for an
evaluation that had discriminated perfectly, because I read `report.control.runs`
and the per-run results live under `progress.runs`. A report that looks like a
result is worse than no report.

`eligible` is the worker's own judgment
and it is strict on purpose: every treatment run must pass, and the pass count
must not regress. A candidate that is no worse is not evidence that it is
better.

## The four graders ghola ships

| Name | Asks |
|---|---|
| `contract` | did the answer obey its output contract at all |
| `verdict-is` | did it reach the expected answer, after any downgrade |
| `mentions` | did it name the thing this case is about |
| `cites-evidence` | did a claim of success carry a command under it |

**These are the same checks the pipeline runs.** `contracts.read` grades `prove`
and `review` in production, and the graders reach it rather than reimplementing
it, so an eval measures the thing that ships instead of a second copy that
drifts.

`verdict-is` grades after the contract's downgrades, not before. A `PROVEN: yes`
with no evidence parses as `unproven`, so a case expecting `yes` fails on it.
Grading the raw claim would reward the behavior the contract exists to catch.

`cites-evidence` is the most useful one on a `prove` phase. A model that stops
running things and starts asserting them still produces output that reads
exactly like a proof.

## Your own cases, without a fork

Point `settings/evals.yaml` at a directory anywhere:

```yaml
suites:
  - ~/code/our-harness-evals/cases
```

ghola reads it alongside `evals/` rather than instead of it. Your suite lives in
your repository. It is versioned with the prompts it grades, and it goes through
review like anything else.

A suite that is not where it said it would be gets reported before anything
runs. That matters. A run of no cases prints exactly like a run that passed.

## Your own graders

A grader is fifteen lines on any worker, in any language:

```python
worker.register_function("acme::eval::mentions-a-ticket", grade)
```

It receives `(output, metrics, arguments, role)` and returns
`{passed, score?, reason?, details?}`. Name it in a case file's `evaluator`, and
list it under `graders:` in `settings/evals.yaml` so `make config` can show it.

Two rules, and both come from how the worker delivers:

**It must be deterministic and idempotent.** Durable delivery is at-least-once.
A grader that answered differently on a redelivery would make the report a coin
toss.

**A grader that cannot run must fail, never pass.** An unknown name, a raised
exception, a contract nobody defined: each one is a failed case. Report any of
them as a pass and you have put a green tick on a case nobody graded.

## What is not covered

Six phases produce something. Two of them have cases. `plan`, `run`, `refine`
and `improve` have none, so a change to one of those prompts ships with nothing
here telling you whether you made it worse.
