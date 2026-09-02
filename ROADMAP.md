<!-- voice-register: informational -->
<!-- voice-english: ste -->

# Roadmap

What ghola does not do yet, and what "done" means for each. [PLAN.md](PLAN.md)
covers the milestones that shipped, M0 through M9. This file covers work that
has no milestone.

Ordered by when I want them, not by size. Add new ones at the bottom. No dates:
a date on a side project is a number nobody is holding.

Items 1 and 2 are features. Items 3 through 5 are bugs.
[docs/LIMITATIONS.md](docs/LIMITATIONS.md) lists the gaps that are decisions
instead, and those are not repeated here.

**An item leaves this page when it ships.** It becomes a milestone entry in
`PLAN.md`, which is where the four fixed in M9 went, so this file stays a list
of what is open rather than a changelog wearing a roadmap's title. Numbers get
reused, so cite an item by its heading rather than its number.

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

**Done when.** A repository in `repos.toml` names its isolation level. The
sandbox refuses a turn that writes outside its worktree, and the refusal reaches
the audit record with the path it tried. `make doctor` reports whether the isolation
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

## 3. Cost, which reads zero and cannot be capped

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
`0.00`, and `make models` says which models those are. Setting `max_cost_usd` on
a phase whose model has no price at all fails at load, naming the model.

**The cost to state.** A fallback price goes stale, and a stale price is a
confident wrong number. That is why the catalogue wins whenever it has one, and
why each figure in `pricing.yaml` carries the date I wrote it down.

## 4. A squash merge is invisible to the `local` forge

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
diff will miss, so the ancestry check stays first and the driver records which
signal answered rather than hiding it.

## 5. Four of six phases have no eval

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
