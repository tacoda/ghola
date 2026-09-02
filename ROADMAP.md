<!-- voice-register: informational -->
<!-- voice-english: ste -->

# Roadmap

What ghola does not do yet, and what "done" means for each. [PLAN.md](PLAN.md)
covers the milestones that shipped, M0 through M8. This file covers work that
has no milestone.

Items are ordered by when I want them, not by size. Add new ones at the bottom.
No dates: a date on a side project is a number nobody is holding.

Items 1 through 3 are features. Items 4 through 9 are bugs, and each one is
marked. [docs/LIMITATIONS.md](docs/LIMITATIONS.md) lists the gaps that are
decisions instead, and those are not repeated here.

## How to read an item

Each item states where it stands today, what changes, and the check that says it
is finished. Read the "today" line first. It names files, so you can see whether
an item has gone stale without reading the code.

Adding an item? Keep the four parts. Drop the cost line only when the change has
no cost you can name.

## 1. Sandboxing for other repositories

**Today.** A job gets a worktree and a claim, from the `worktree` worker. That
bounds which checkout the job edits. It bounds nothing else. `prepare` and
`cleanup` in `repos.toml` are shell strings, and they run on the host with the
job's environment. So does the agent's shell, through `shell::*`. The one
sandbox setting in the tree is `sandbox_mode: workspace-write` in
`config/codex.yaml`, and that belongs to the codex worker rather than to ghola.

**What changes.** A job runs against a repository ghola did not write, so the
blast radius has to be a setting rather than a hope. Bound three things: writes
outside the worktree, network reach, and what `prepare` can touch. Put the bound
per repository in `repos.toml`. A scratch directory and your work repository
want different answers.

**Done when.** A repository in `repos.toml` names its isolation level. A turn
that writes outside its worktree is refused, and the refusal reaches the audit
record with the path it tried. `make doctor` reports whether the isolation
mechanism is available on this machine.

**The cost to state.** Isolation breaks `prepare` for any repository whose stack
needs real ports or a real database. That is why the level is per repository and
why one level has to mean "none", named rather than implied.

## 2. Swapping providers, models and keys

**Today.** A phase names a model in `settings/phases.yaml`. Run `make models` to
see what the router can reach. Keys are engine-wide: `ANTHROPIC_API_KEY` and
`OPENAI_API_KEY` in `.env`, read by the provider workers from the **engine's**
environment. `config/llm-router.yaml` carries `value: null`. So changing a key
means editing `.env` and restarting the engine, and an unreachable model fails
at `router::provider::resolve` with nothing saying why.

**What changes.** Three separate swaps, and they are separate on purpose:

| Swap | Where it should live |
|---|---|
| the model a phase uses | `settings/phases.yaml`, which already works |
| the provider behind a model | a setting, not a rebuilt engine |
| the key a provider uses | a reference, resolved per run |

**Done when.** `make models` prints the provider for each model id. A phase can
name a provider and get a clear failure when that provider has no key.
`make doctor` names every provider with a missing key, before a job pays for a
turn.

## 3. The agents standard (fixed)

**What it was.** Support was partial and split across two workers.
`pre_generate.py` looked for `CLAUDE.md` and `AGENTS.md` in a first-match tuple
with `CLAUDE.md` first, so a repository that had migrated and kept the old file
had its `AGENTS.md` ignored by the file it replaced. The charter piece's
`source` was hardcoded to `CLAUDE.md` whichever file it came from. And the
ladder was Claude-shaped: project roots of `{repo}/.ladder` and `{repo}/.claude`,
permissions from `.claude/settings.json`.

**What the fix does.** `AGENTS.md` is the charter file and the only one read.
Every primitive kind is unchanged, so `rules/`, `skills/`, `agents/`,
`commands/`, `mcps/` and `evals/` mean under `.agents/` exactly what they meant
under `.claude/`. Permissions come from `.agents/settings.json`, whose shape is
still Claude Code's `permissions` block because no standard covers that.

**Hooks close the last gap against Claude Code's primitives.** They are declared
in `.agents/settings.json`, which is where Claude Code declares them, so a
repository's existing block works unchanged. `hooks.py` turns that block into
constraints the same way `permissions.py` already does, and `.agents/hooks/`
holds the scripts the entries point at rather than primitives of its own.

`PreToolUse` can refuse a call, so it lands at rung 2. Every other event only
observes, so it lands at prose: putting an observer at rung 2 would have the
ladder claim enforcement nothing performs. ghola runs none of them, and every
synthesized `why` says so. Whichever harness the repository runs them under
carries them, and they sit on the ladder so the mechanism is visible rather
than assumed.

**This repository is now a target of itself.** It tracks `AGENTS.md` and
`.agents/`, with `CLAUDE.md` and `.claude` as symlinks so Claude Code reads the
same files. No code special-cases it, which was the point: the charter here is
the layout ghola reads out of anywhere else. Seven primitives load, including
the hook and two permission entries.

That charter caught its own first overclaim. I wrote `no-ai-attribution`
declaring `rung: delivery`, and `validate` refused it. Rung 4 enforces by
running something, and no predicate here can read a commit message, because
`publishing` reaches a predicate written as a function id on the bus and nothing
else. The rule says rung 2 now, carried by its hook, and it names what carrying
it at 4 would take.

**The charter is everything under `.agents/`.** A repository separates its ideas
by directory and the directory is named after the concept, so
`.agents/architecture/queues.md` arrives as a piece titled `architecture /
queues` and nothing has to declare what it is about. That closes a gap the
kind-directory reading left: a concept the ladder has no kind for, an
architecture note or a domain glossary, used to be ignored entirely.

The charter reader skips the directories the ladder owns. It skips the six kind
directories because `ladder::list` already carries their prose with the rung
attached, and reading them in both places would state every rule twice with the
second copy missing its rung. It skips `hooks/` because a shell script is not
prose. `charter.LADDER_DIRS` mirrors `load.KIND_DIRS` plus `load.SCRIPT_DIRS`,
and a test asserts they agree: a kind added there and missed here is exactly
that double statement.

**No fallback, and no generated files.** ghola reads the repository's agent
files and implements the result itself, at whatever rung the ladder carries each
rule. It does not write a vendor copy, because the same text in two files means
the second one goes stale the first time somebody edits the first. A repository
that also wants Claude Code to see its charter symlinks it, which is what the
standard itself recommends and what keeps one authored file:

```
git mv CLAUDE.md AGENTS.md && ln -s AGENTS.md CLAUDE.md
```

A repository holding only `CLAUDE.md` therefore gets no charter. That is loud
rather than silent: `charter.which` returns the reason with that command in it,
the callback prints it and counts it in `ghola.charter_problems`, and an empty
charter no longer returns early and throws the reason away.

**What is deliberately not built.** Nested `AGENTS.md` files are not read. The
standard says the closest file to the edited one wins, and ghola has no touched
paths at `pre-generate`, so the choice would be between guessing which file
applies and injecting every nested file into every turn. A monorepo gets its
root file, and its subproject instructions belong under `.agents/` where the
directory says what they are about.

**How it stays fixed.** Thirty-one tests. `DEFAULT_ROOTS` and `SETTINGS_FILES`
had none, which is how the whole path swap passed 644 tests without one failure:
every existing ladder test hands `load` an explicit `roots`, so they covered the
mechanism and never the convention. One test now asserts no `.claude` directory
is consulted at all.

**The cost to state.** This is a breaking change for any target repository
already pointed at ghola. A repo with `.claude/rules` loses those primitives
until the directory is renamed, and the rename is the whole migration. The
tracked fixtures moved with it, so `tests/fixtures/permissions-repo` is now
`.agents/settings.json`.

## 4. Cost, which reads zero and cannot be capped

**Two bugs**, and they share one root. The router prices some models at null.

**Today.** `workers/ghola-core/src/turn.py:209` reads `session_cost_usd` off the
harness event and floors a missing value to `0.0`. A real turn on an unpriced
model therefore records `$0.00`. That zero travels into the job record and the
audit log, where nothing tells it apart from a turn that cost nothing.
`settings/pricing.yaml` is the documented fallback. Three files name it, in
`settings/README.md`, `docs/CUSTOMIZING.md` and `docs/LIMITATIONS.md`, and no
code reads it.

The second bug is the cap. `max_cost_usd` sits in `SEND_OPTIONS` in
`workers/ghola-core/src/phase_settings.py`, so a phase can set it and the value
reaches the harness. With null prices the cap never binds. A budget that
silently never fires is worse than no budget, because you stop watching.

**What changes.** Load `settings/pricing.yaml`. Let the catalogue win whenever
its price is non-zero, and record a `cost_source` beside every figure. Report an
unpriced model as unknown rather than as zero.

**Done when.** A turn on an unpriced model records the fallback price and its
`cost_source`. A model with no price and no fallback records `null`, not
`0.00`, and `make models` says which models those are. Setting `max_cost_usd`
on a phase whose model has no price at all is refused at load, with the model
named.

**The cost to state.** A fallback price goes stale, and a stale price is a
confident wrong number. That is why the catalogue wins whenever it has one, and
why each figure in `pricing.yaml` carries the date I wrote it down.

## 5. The review phase was promised a diff and shown nothing (fixed)

**A bug**, and it was not in `docs/LIMITATIONS.md` because nobody had noticed
it.

**What it was.** `prompts/review.md` carried a `## The diff` heading with a
`$diff` placeholder under it, and the prose above said "You are shown this and
the diff." `brief_for` in `workers/ghola-factory/src/factory.py` filled that
placeholder from `job.get("diff")`, and nothing ever wrote `diff` onto a job. A
missing field renders as an empty string, by design, so that a `$PATH` in a spec
cannot break a turn. The reviewer therefore read a heading with nothing under
it, plus a sentence telling it that it had already seen the change.

The phase had `RUNNING` in its grant all along, at
`workers/ghola-core/src/defaults.py:44`, so it could have run `git diff` itself.
Nothing asked it to. A prompt that describes evidence it did not attach is worse
than a prompt that attaches none, because the model has no reason to go looking.

**What the fix does.** The reviewer gets the ref instead of the diff. `diff` is
gone from `prompts.FIELDS` and `base` replaced it, `prompts/review.md` names the
two commands that get the whole change, and `actions.base_ref` is the single
derivation of that ref, read by the delivery gate and by the brief. So a
reviewer cannot grade against a different ref than the gate reads.

Handing over the ref rather than the text also drops the dependency on item 6.
Nothing large goes into the prompt, so nothing has to be bounded first.

**How it stays fixed.** `prompts.FIELDS` is the promise that something fills a
name, and `tests/test_docs.py` now checks every prompt against it. A prompt
naming a field the factory does not supply fails there rather than quietly
deleting a section of its own brief.

## 6. The delivery gate read less than it claimed (fixed)

**Three bugs**, found in one 30-line function while fixing the first. The
truncation is the "big diffs" item in `PLAN.md` section 9.

**What it was.** `rung_four` built its input from two `git diff` calls, joined
them, and cut the result at 200,000 characters with no marker. So the gate
graded a large change on its first 200,000 characters, and its verdict read
exactly like a verdict on the whole thing.

Reading the rest of the function turned up two worse ones, both fail-open. An
unreachable ladder returned `""`, which the caller reads as "not refused", so a
downed worker committed the change. A failed `git diff` produced empty content,
which evaluates as clean, so a broken git call did too. The docstring claimed
the opposite: "A ladder that is unreachable does not wave the commit through
silently." The ladder states the principle in its own predicate runner, at
`workers/ghola-ladder/src/predicate.py`: a predicate that throws is a finding,
not a pass.

The third was the path. Rung 4 passed `path: ""`, and an empty path skips the
filter twice on the way in, at `Loaded.governing` and again at `gate.decide`. So
the gate asked every path-scoped rule about every file in the change, and handed
its predicate `path=""`, which left the findings naming none of them.

**What the fix does.** `diffs.per_file` splits the diff on `diff --git`
boundaries, and the gate makes one `ladder::evaluate` per file, each carrying
its real path. A file is the unit `check(path, content, context)` expects, so
path scoping works and a finding names a file. First refusal wins, matching
`gate.decide`.

`rung_four` now returns `(refusal, problem)`. A refusal is the ladder saying no
and routes to a rework. A problem is the gate unable to answer, and the caller
turns it into `ok: False`, because no rework brings a worker back up. An empty
pair is the only outcome that commits.

The publishing text goes with every file rather than once, because
`gate.escaped` reads an escape hatch out of the commit message and a file
evaluated without it would be refused by a rule the operator had escaped.

Splitting per file removed a bound that the old cut provided by accident: 200,000
characters was however many files it came to. So `MAX_FILES` is 500, and a change
wider than that is a problem rather than 500 calls at a 60-second timeout each.

**How it stays fixed.** Seventeen tests in `tests/test_gate.py`, over a fake
that records what the gate showed the ladder rather than only what it concluded.
The function had none before. Read that fake first if you change the gate. It
pins all three of the old behaviors.

**The cost to state.** For a single file over 200,000 characters of diff, the
gate bounds the patch with the marker from `publishing.trim` and evaluates it
anyway rather than blocking the job. So it can still pass a vendored tree or a
lockfile on a bounded read. It says so on stdout, and the marker sits inside
what the ladder read, which is weaker than a refusal and stronger than the
silence it replaces. Watch for that line if a large change passes and you
expected an argument. One number serves every repository, and it becomes a
setting the first time a real change trips it.

## 7. `concurrency` was parsed and nothing read it (fixed)

**A bug**, and the fix made the setting real rather than deleting it.

**What it was.** `workers/ghola-core/src/repos.py` parsed `concurrency` three
times over: a default of 1, a numeric coercion, a field on the resolved
settings. No code read the value. The one other mention was a comment in
`prepare_workspace` arguing that `worktree::claim` returning `W210` was the
concurrency answer rather than a semaphore.

That argument holds for one checkout and not for one repository. Two jobs on one
repository get two worktrees, so both claims succeed and both run `prepare`.
That is the exact case `docs/LIMITATIONS.md` told you to set `concurrency = 1`
for, and the setting did nothing. A setting nothing reads is worse than no
setting, because it reads as protection.

**What the fix does.** `too_busy` counts the live jobs on the repository before
`prepare` claims anything, and the job store is the semaphore. It already knows
which jobs are live, which beats a lock file that can go stale with nothing to
say so. Over the limit, the job fails naming the holder and the stage it is at,
because "the repository is busy" is not something an operator can act on and
`abc12345 is at run` is.

Three things the count deliberately does not do. It does not count a repository
with no `prepare` command, because nothing was allocated for two jobs to fight
over and the limit would only cost throughput. It does not treat `concurrency =
0` as "allow none", since nobody writes that meaning to stop all work. And it
does not count the asking job against itself: at-least-once delivery hands
`prepare` the same job twice, and a job blocked by its own record would never
start.

`jobs.holding` is pure, so the decision is a list and a number in a test rather
than two live jobs and a port collision on somebody's machine. `jobs.RELEASED`
mirrors `graph.TERMINAL`, and one test asserts the two agree, because a terminal
state missing from that tuple would let a finished job hold a repository
forever.

**How it stays fixed.** Fourteen tests across `tests/test_jobs.py` and
`tests/test_gate.py`, including one asserting the action refuses before it asks
the worktree worker for anything. Start from `jobs.holding` if you change the
rule: the store lookup around it is four lines.

**The cost to state.** The second job fails rather than waiting, which is not
what anybody wants. Waiting needs a stage that can defer itself plus a
reconciler to re-drive it, and `blocked` is not that: it waits on a person.
Failing at `prepare` is cheap because it is the first stage, so no turn has been
paid for yet, and the message names what to wait for.

A job with an open pull request still counts, because `cleanup` runs from
`teardown` on a terminal state only. So the ports are still up while a reviewer
reads. On a repository with `prepare` and the default limit of 1, that means one
open pull request stops new work until it lands or closes. That is the truth
about the environment rather than a policy. Raise `concurrency` if your prepare
can take it, or drop the `prepare` command if the spec does not need the app
running.

The count also races with itself. Two jobs entering `prepare` in the same
instant can both read a store where neither holds yet, because files cannot
compare-and-swap. It closes the case the key exists for, which is a job
submitted while another is already running. Do not read it as a lock.

**Done when.** `make config` and `repos.toml` agree with the code. If the key
survives, two jobs on one repository serialize at `prepare`, and the second one
waits rather than failing. Until then, run one job per repository yourself.

## 8. A squash merge is invisible to the `local` forge

**A bug**, with a manual workaround today.

**Today.** `workers/ghola-core/src/forge.py:292` asks
`git merge-base --is-ancestor`, and reads exit 0 as "somebody merged this". A
squash merge leaves no ancestry, so the branch never reports as merged. The
comment at line 308 says so. The workaround is in the request file itself, at
line 259: set the status to `closed` by hand.

**What changes.** Ask git a second question when the first says no. `git cherry`
against the base, or a patch-id comparison, catches a squashed branch. Keep the
ancestry check first, because it is exact and cheap.

**Done when.** A squashed branch reports as merged without anyone editing the
request file. The driver records which signal answered, so an operator can tell
an exact answer from a heuristic one.

**The cost to state.** A patch-id match is a guess. A rebase that changed the
diff will miss, and that is why the ancestry check stays first and why the
signal is recorded rather than hidden.

## 9. Four of six phases have no eval

**A bug** in the sense that matters here: the least-tested files are the ones
people edit most.

**Today.** `evals/` holds two cases, `prove-cites-evidence.json` and
`review-names-a-place.json`. The built-in pipeline has six phases. So `refine`,
`plan`, `run` and `improve` have no discriminating case, and a prompt edit to
any of them ships with nothing under it.

**What changes.** One discriminating case per phase. Discriminating is the whole
bar: a case that passes on both the old and the new prompt has measured nothing,
which is the failure the first version of this repository's eval suite made. So
weaken the prompt on purpose and check that your case notices.

**Done when.** Every phase in the built-in pipeline has at least one case that
fails on a deliberately weakened prompt. `make eval` reports coverage by phase,
so a phase with no case is visible without counting files.

**The cost to state.** Every case costs real money on every run. `make eval`
stays manual, per `docs/LIMITATIONS.md`, so more cases means a slower and more
expensive gate that people can still afford to skip.

## Non-goals

Not a release plan, and not a promise about order. Not a place for shipped work,
which belongs in [PLAN.md](PLAN.md), and not a place for the gaps that are
decisions, which belong in [docs/LIMITATIONS.md](docs/LIMITATIONS.md).

Found a bug that is not here? Open an issue. Add it here only once you know what
"done" would mean for it.
