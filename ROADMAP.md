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

## 3. The agents standard, with a port for harnesses that lack it

**Today.** Support is partial and split across two workers.
`workers/ghola-policy/src/callbacks/pre_generate.py` reads both `CLAUDE.md` and
`AGENTS.md`. The ladder is Claude-shaped: its project roots are `{repo}/.ladder`
and `{repo}/.claude` in `workers/ghola-ladder/src/load.py`, and permissions come
from `.claude/settings.json`.

**What changes.** `AGENTS.md` and `.agents/` become the layout ghola reads
first, and `.claude/` stays as a fallback so no existing target repository
breaks. This repository follows the standard itself.

Then the harder half. Claude Code reads `CLAUDE.md` and `.claude/`, and Cursor
and aider each read their own layout. Keep one standard setup, not three copies
of it. So ghola ports: it generates the harness-specific layout from the
standard files, and the standard files stay the authored ones.

**Done when.** A target repository with only `AGENTS.md` and `.agents/` runs the
whole lifecycle. A repository with only `.claude/` still runs it. Porting is one
command, and every generated file says at the top that it is generated and names
its source.

**The cost to state.** Porting writes files into the target repository. That
needs a rule about what is authored and what is generated, or the next agent
edits the copy and loses the edit on the next port.

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

## 6. The delivery gate truncates its own input silently

**A bug.** It is the "big diffs" item in `PLAN.md` section 9, still open.

**Today.** `workers/ghola-factory/src/actions.py:280` builds the gate's input
from two `git diff` calls and cuts the result at 200,000 characters. No marker,
no refusal, no record. So a large change is graded on its first 200,000
characters and the verdict reads exactly like a verdict on the whole thing.

The pattern for doing this correctly already ships.
`workers/ghola-core/src/publishing.py:140` appends `*(truncated at N
characters)*` to what a reviewer reads, and the docstring two lines above says
that silent truncation of a check's input is the same failure. The gate does
not use it.

**What changes.** Refuse or chunk, and say which. A gate that cannot read the
whole diff has not read the diff, so the honest answers are a refusal naming the
size, or a chunked pass whose record says how many chunks it took. Reuse the
marker in `publishing.py` rather than writing a second one.

**Done when.** A diff over the limit produces a refusal or a chunked verdict.
The audit record names which one happened and the size that triggered it.
Nothing reaches a pull request on a partial read.

## 7. `concurrency` is parsed and nothing reads it

**A bug**, and the cheap fix is a deletion.

**Today.** `workers/ghola-core/src/repos.py` parses `concurrency` three times
over: a default of 1 at line 49, a numeric coercion at line 62, a field on the
resolved settings at line 84. No code reads the value. The one other mention is
a comment at `workers/ghola-factory/src/actions.py:107`, arguing that
`worktree::claim` returning `W210` is the concurrency answer rather than a
semaphore.

That argument holds for one checkout and not for one repository. Two jobs on one
repository get two worktrees, so both claims succeed and both run `prepare`.
That is the exact case `docs/LIMITATIONS.md:38` tells you to set
`concurrency = 1` for, and the setting does nothing.

**What changes.** Two honest endings, and either closes this. Write the
semaphore, keyed on the repository path rather than the worktree. Or delete the
key and correct the sentence in `docs/LIMITATIONS.md`. A setting that nothing
reads is worse than no setting, because it reads as protection.

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
