# strict

Every check on, plus a security read. For a repository with users on it.

```
cp examples/strict/settings/*.yaml settings/
make pipeline        # read it before submitting
make config          # every effective setting, tagged with where it came from
```

One thing is not copied for you: `prompts/security.md`. The `security` stage
runs on the bare document until you write it, and `make config` reports which
phases have a prompt and which do not. A phase running on the bare spec is a
phase nobody told what its job is.

Add a starting point with `make turn PHASE=security PROMPT="..."` first, or copy
`prompts/review.md` and change the question it asks. The useful version asks one
thing — what does this diff let somebody do that they could not do before — and
names a file and a line for every answer.

## What it costs

Four turns per job, two on a thinking model, plus one more if the job came in as
an idea. Roughly five times `minimal/`, and the difference is entirely in what
gets caught before a person reads it.

## Each stage, and what got through without it

- **plan** — a run turn with no plan picks the first approach that works. A
  two-line change arrives as a refactor of the module around it.
- **prove** — nothing runs the software. "It compiles" is the strongest claim
  anybody can make about the diff.
- **review** — nothing reads the diff against the spec before you do.
- **security** — a general reviewer asked to check everything checks the thing
  it read most recently. The second reader has one question.
- **on_refusal** — the repository's own commit hook refuses and the job dies
  instead of trying again with the hook's own words as the brief.

## Where it is still not strict

`prove` and `review` are `optional: false` here, so a job cannot turn them off.
Nothing stops somebody editing this file, and nothing should: a factory whose
own configuration is unchangeable is a factory somebody works around. What makes
the checks stick is rung 4 and the pull request, not this file.

The `security` stage is `optional: true` on purpose, because a phase with no
prompt should be skippable rather than a wall. Flip it once the prompt is real.
