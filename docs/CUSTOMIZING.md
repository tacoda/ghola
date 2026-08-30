<!-- voice-register: informational -->
<!-- voice-english: ste -->

# The customization contract

Everything ghola does has a home, a built-in default, and a way to override it.
This page is the whole list, in the order you should reach for them.

Run `make config` before you change anything. It prints every effective setting
with the source that produced it, so a default is never a magic number you go
looking for in the code.

## The order to reach for things

1. **A key in `settings/*.yaml`.** One value, overriding one default.
2. **A whole block.** A phase, a stage, a contract.
3. **A Python file in a named directory.** For a judgment, not a value.
4. **A function id on the bus.** When Python is the wrong language for it.

Reach for 3 only when 1 and 2 cannot say the thing. A Python file is code you
now maintain, and a key in a YAML file is not.

## What each file owns

| File | Owns | Default when absent |
|---|---|---|
| `settings/phases.yaml` | models, thinking levels, turn caps, tool grants | `defaults.PHASES` |
| `settings/pipeline.yaml` | the stage graph: what happens in what order | `defaults.PIPELINE` |
| `settings/oversight.yaml` | how much a person watches | `supervised` |
| `settings/governance.yaml` | which calls need a verdict before they run | the promote list |
| `settings/contracts/*.yaml` | how a phase's answer parses, and what invalidates it | `contracts.BUILT_IN` |
| `settings/evals.yaml` | eval suites outside this repository | `evals/` alone |
| `settings/pricing.yaml` | fallback prices for models the router prices at null | none |
| `repos.toml` | what ghola knows about a target repository | the built-ins |
| `repos.local.toml` | the same, for this machine, git-ignored | absent |
| `prompts/*.md` | what each phase is actually asked | the bare spec |

`settings/` rather than `config/`, because `config/` belongs to iii's
`configuration` worker, and that worker rewrites files in its own directory.
Point `GHOLA_SETTINGS` somewhere else if you want the settings elsewhere.

## Three merge rules that surprise people

**`phases.yaml` merges one level down.** Set `plan.max_turns` and the `plan`
phase keeps its built-in model and its tool grant. Name a phase the defaults do
not have and ghola simply adds it.

**`functions` replaces, and never merges.** A phase that lists its own tools
means those tools, and not those plus the defaults. Rung 1 read as an accident
of merge order is how a check ends up holding an editor, so this one is
deliberate.

**`optional` and `opt_in` are opposites.** `optional` means the stage runs
unless a job turns it off, which is what `prove` and `review` are. `opt_in`
means it stays off until a job asks, which is what `refine` is. I conflated
them in the first pipeline, and `refine` rewrote the specs of jobs that had
never asked for refining.

## The five extension directories

Drop a file in, and ghola finds it by filename. No registration, and no import
to add anywhere.

| Directory | For | Entry point |
|---|---|---|
| `actions/` | a stage that does something rather than asking a model | `run` |
| `guards/` | a condition on whether a stage runs | `check` |
| `parsers/` | reading a phase's answer your own way | `parse` |
| `predicates/` | what a rule decides, for the ladder to call | `check` |
| `forges/` | a code host other than GitHub | `driver` |

A predicate belongs to the target repository rather than to ghola, and it lives
beside its rule: `team/rules/no-secrets.py` next to `team/rules/no-secrets.md`.
That pairing is what makes the rule and its enforcement one primitive instead of
two things somebody keeps in agreement. See [the ladder](LADDER.md).

Hyphens and underscores are the same name, so a stage written
`deploy-to-staging` finds `deploy_to_staging.py`.

An action receives `(worker, job, settings)` and returns the same shape a turn
does: `{ok, refused, blocked, outcome, error}`. That symmetry is why
`graph.next_stage` does not care which kind of stage it just ran.

**A named extension that resolves to nothing is an error, not a no-op.** ghola
reports it when it reads the pipeline, which is before a job has paid for a
worktree and a plan. Run `make pipeline` to see what it found.

## Naming a function instead of writing a file

Every extension point that takes a module also takes `worker::function`. Write
the extension in Rust, in TypeScript, or in anything that speaks the bus:

```yaml
stages:
  deploy:
    action: acme::deploy::staging
    next: waiting
```

Python is the easy path. A worker is the one that scales, and the one you reach
for when the extension needs state or a connection of its own.

The exception is `forges/`. A driver answers four questions, so one callable
would have to switch on which question it was being asked, and ghola refuses a
function id there rather than pretending.

## What you cannot configure

- **The pull request.** No setting removes it, at any oversight level.
- **`ask` becoming `allow`.** Not at `dark`, not anywhere.
- **The audit log.** It appends, it hash-chains, and one worker owns the chain.
- **Tools.** ghola registers none. Every tool a phase can call belongs to a
  stock iii worker, and rung 1 works the same over a function id whoever
  registered it.

## Where the project's own opinions go

Not here. A target repository's conventions belong in that repository, in its
`CLAUDE.md` and its `.claude/` directory, where they are versioned with the code
they describe and where every other tool can read them too.

That split is the one worth holding. `settings/` says how work gets done.
The repository says what the work must respect.
