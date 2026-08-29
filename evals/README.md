# evals

**ghola does not write an eval runner.** The `eval` worker already runs durable
same-model A/B evaluations, alternates variant order to reduce order bias,
persists reports, and injects a console page at `#/ext/eval-benchmarks`.

Each file here is an `eval::start` request. `make eval` submits them all;
`make eval CASE=prove-cites-evidence` submits one.

```bash
make eval CASE=prove-cites-evidence
make call FN=eval::list
make call FN=eval::result JSON='{"evaluation_id":"..."}'
```

## What an eval is for, and what it is not

**They gate prompt changes, not jobs.** No eval runs inside the pipeline. A job
that waited on a five-run eval would cost five turns and tell the operator
nothing about that job.

**They are the regression check for `prompts/`.** A prompt is the easiest file
in this repository to change and the only one with no other check on it. An eval
answers the question a prompt edit actually raises: is the candidate worse than
what we had.

**They cost money, so nothing runs them on a timer** until somebody asks.

## The evaluators

ghola contributes the judgements the worker cannot make. They are the **same
checks the pipeline runs** — `contracts.read` grades `prove` and `review` in
production — so an eval measures the thing that ships rather than a second
implementation that can drift.

| function | asks |
|---|---|
| `ghola::eval::contract` | did the answer obey its output contract at all |
| `ghola::eval::verdict-is` | did it reach the expected answer, after any downgrade |
| `ghola::eval::mentions` | did it name the thing this case is about |
| `ghola::eval::cites-evidence` | did a claim of success carry a command under it |

**A case that can be graded deterministically must not use a model to grade it.**
All four of these are deterministic, which is why there is no judge here yet.

## Writing a case

A case changes **exactly one dimension** — `prompt` or `system_prompt` — and
compares a control against a treatment. That constraint is the worker's, and it
is the right one: an A/B that changed two things tells you something moved and
not which thing moved it.

Each case should have a control that **passes** and a treatment that **fails**,
or the pair proves nothing about the evaluator. A suite where everything passes
has not been shown to discriminate.
