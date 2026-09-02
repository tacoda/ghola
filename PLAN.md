<!-- voice-register: informational -->

# ghola: implementation plan

<!-- voice-register: argument -->

A spec goes in, a pull request comes out, nothing merges itself. ghola is that
factory built as an application on [iii](https://iii.dev), rebuilt from scratch
so a team that is not mine can run it. Every rule, every phase, every stage of
work is configuration first and a Python script second. The cost is one more
indirection between the operator and the behavior, and one more thing to get
wrong in YAML.

ghola is a reimplementation of wipp, a private repository that has run against
three real codebases. wipp works and is not shareable: its flow of work, its
development process, and its project specifics are the same three things, welded
together in about 10,300 lines of Python. This plan separates them.

The name is from Dune. A ghola is regrown from the cells of the dead and then has
to recover what the original knew. That is the exercise.

---

## 1. What this is, and what it is not

### A starter kit. iii is the framework.

**iii is the framework.** It ships the turn loop, the transcript, the token
budget, the providers, the tools, git worktrees, the GitHub client, the approval
gate, durable queues, cron, state and the console. Thirty workers, and every one
of them is somebody else's problem to maintain.

**ghola is a starter kit.** It is an opinionated composition of those workers,
plus the conventions and the one idea iii does not have a worker for: a
constraint ladder. You clone it, configure it, and point it at a repository.

This is the third framing this plan has had, and the first accurate one. It began
as "a factory", then as "Rails for iii", and both overstated ghola's part. What
survived every rewrite is the ladder and the stage graph; everything else turned
out to be a worker that already existed. If a fourth rewrite deletes more, that
is the design working.

What a starter kit owes its user, and what this one owes:

| | |
|---|---|
| **a working thing on day one** | a spec goes in, a pull request comes out |
| **decisions already made** | which of 77 workers, on what ports, wired how |
| **conventions worth keeping** | a directory per extension point, found by filename |
| **an idea you could not assemble yourself in an afternoon** | the ladder |
| **no lock-in** | you own every file the moment you clone it |

### The whole usage, in three steps

```
1. clone the repo          git clone … && make setup
2. add config and scripts  edit settings/, drop files in actions/
3. tell it to do work      make turn, and later make work
```

Step 2 is optional: step 3 runs on built-in defaults. There is no package to
install, no CLI to learn, and no `ghola new`. `make` is the entire operator
surface, and every decision in this plan is answerable to whether it keeps those
three lines true.

### There is no upgrade path

Once you have edited this, it is yours. ghola's later commits are yours to read
and copy by hand. That is not a compromise, it is what a starter kit is: the
alternative is a framework you hold at arm's length, and iii is already the
framework.

The cost is real and worth stating plainly: a fix to the ladder or the graph
interpreter does not reach you for free.

### How you extend it

Two mechanisms, and the first covers most cases.

1. **Drop a Python file in a named directory.** `actions/deploy.py` is
   `action: deploy`. `predicates/no_secrets.py` is a rule's predicate.
   `guards/needs_review.py` is a stage guard. Found by filename, no registration.
2. **Name any function id on the bus.** Every extension point that takes a Python
   module also takes a `function_id`, so an extension can be a worker in Rust,
   TypeScript or anything else iii speaks. Python is the easy path; a worker is
   the escape hatch, and the one that scales.

### The one idea

A constraint has a **rung**: the mechanism that carries it. Prose that nobody
enforces is rung 0. A tool the phase was never handed is rung 1. The repository's
own hook is rung 2. A callback in front of every call the model makes is rung 3.
The delivery gate over the finished diff is rung 4. CI is rung 5. Each rung puts
the rule further out of reach of the thing it constrains, and the rung a rule
sits on is a number in one line of its frontmatter.

That is the idea, and it now ships as its own worker: `iii worker add ladder`.
ghola is what proves it, because a ladder nobody runs work through is a diagram.

The model generalised in the extraction. It carries **capabilities** as well as
constraints on a second ladder joined to the first at the grant, **feedforward
and feedback** derived from whether a script sits beside the file rather than
declared, feedback graded as **deterministic or inferential**, and the whole
**promote, demote, add, remove** lifecycle as one verb over both sides.

### Non-goals

- **Not a framework.** That is iii. ghola composes it.
- **Not a library.** Nothing here is meant to be imported by another project.
- **Not a merge bot.** ghola opens a pull request and stops. A human merges.
- **Not a harness.** ghola owns no turn loop. That is the `harness` worker.
- **Not a replacement for CI.** Rung 5 is the repository's own, out of ghola's
  reach. That is the point of rung 5.
- **Not multi-tenant, not hosted.** One operator, one machine, one namespace.

### License and remote

MIT. Remote is `https://github.com/tacoda/ghola.git`. Everything in `settings/`,
`rules/`, `prompts/` and `iii.lock` is tracked; nothing under `runs/` or `.env`
is.

## 2. The domain model

Six concepts, carried over from wipp unchanged, because they earned their shape
against real repositories.

| Concept | What it is | Where it lives |
|---|---|---|
| **Spec** | The input of record. Markdown, one file, in git. | `specs/<slug>.md`, media in `specs/media/<slug>/` |
| **Job** | One spec moving through the pipeline against one target repo. | `state/jobs/<id>.json` |
| **Phase** | A kind of turn: what model, what thinking level, what functions. | `settings/phases.yaml` |
| **Turn** | One `harness::send` and the `harness::turn-completed` that answers it. | the framework's, not ours |
| **Rule** | A constraint, with a layer, one or more rungs, and a policy. | one markdown file with frontmatter |
| **Proposal** | A staged change to the charter, the harness, or the factory. | `state/proposals/<id>.json` |

### The job lifecycle

A job's states are not a fixed enum in ghola. They are derived from the stage
graph in `settings/pipeline.yaml` plus one terminal set the graph declares. The
shipped default graph produces the states wipp uses today:

```
queued -> preparing -> planning -> running -> proving -> reviewing
       -> publishing -> waiting -> { landed | closed | failed }
                            |
                            +-- blocked   (an interrupt, or a hold)
                            +-- reworking (a reviewer comment)
```

Two properties hold regardless of what graph a team writes:

1. **Every transition is a durable queue message**, so a crash between stages
   resumes rather than restarts.
2. **Every stage guards on the job's own recorded stage**, so at-least-once
   delivery does the work once.

### The rule lifecycle

```
authored (rung 0, prose)
  -> promoted to a mechanical rung, which requires a predicate
  -> carried at a second rung when one mechanism cannot see everything
  -> demoted when it never fires and the "why" still survives
  -> removed when the "why" does not
```

A promotion is a change to a number in a file plus, at rung 2, a generated hook.
It goes through the same pipeline as any other change and lands as a pull
request. **The improve lane may not edit the charter, the harness, or the factory
on its own authority.** That is the one rule keeping ghola from being the single
thing escaping its own gate.

### The proposal lifecycle

```
raised from job evidence -> staged -> accepted -> a spec in specs/ -> a job -> a PR
                                   -> rejected -> recorded with a reason
```

Nothing is applied. Accepting a proposal writes a spec and stops, except a move
on the ladder — promote, demote or carry — which is a rung and becomes a pull
request directly. `drop` and `remove` are ladder verbs this lane may propose in
prose and may not apply, because both take a guarantee away.

---

## 3. The three kinds of thing

The test for which is which: **a number or a name is settings, a judgment is a
callback, and everything else belongs to the framework.**

| | What it is | Where |
|---|---|---|
| **the framework** | turn loop, transcript, token budget, provider, sub-agents, queue, HTTP, cron, console | installed iii workers |
| **the settings** | models, thinking levels, turn caps, budgets, tool grants, the stage graph, the layers, the prompts | `settings/*.yaml`, `repos.toml`, and each iii worker's own entry in `config/` |
| **our code** | the tools iii does not ship, and four callbacks at the seams the harness offers | `workers/ghola-policy` |

A change that is neither a setting nor a judgment means logic has crept back into
a script, and that is the review question for every pull request on this repo.

### The framework workers ghola composes

Installed, never edited, never wrapped. **The rule is that if a worker does it,
ghola does not.** Every row below was something an earlier draft of this plan had
ghola building.

| Worker | What ghola does not write because of it |
|---|---|
| `harness` (1.8.7, pinned) | the turn loop, transcript, retry, sub-agents, token budget |
| `ladder` | the constraint and capability ladder: layers, rungs, predicates, and the refusal that carries a rule's own words. Extracted from this repository into `tacoda/ladder` |
| `audit-log` | the append-only, hash-chained record: one writer, fsynced before it answers, and `audit::recorded` for anyone who wants a copy. Extracted from this repository into `tacoda/audit-log` |
| `shell` | every tool. It owns `coder::*` as well as `shell::*`: `read-file`, `search`, `tree`, `list-folder`, `create-file`, `update-file`, `delete-file`, `move`, `exec`, `exec_bg` |
| `worktree` | worktree lifecycle, the branch convention, the claim that stops two jobs racing, and `land` with its rebase, test gate and atomic compare-and-swap |
| `github` | the forge. Typed `pr::create/view/comment/diff/merge/checks`, `issue::*`, `run::*`, with read-versus-mutate gating and `exec`/`api` as escape hatches |
| `eval` | the A/B evaluation loop, its durable reports, and its console page |
| `directory` | the charter surfaces: `skills::*`, `prompts::*`, `system-prompts::*` |
| `state` | the job store, subject to the durability check in M4 |
| `session-manager`, `context-manager`, `llm-router`, `provider-*` | the transcript, the budget, the model, the credentials |
| `queue`, `http`, `cron`, `console`, `configuration`, `iii-observability`, `iii-worker-manager` | durable topics, the browser surface, scheduling, the console, hot-reloaded settings, traces |

`coder` and `directory` are worth naming twice, because they are the ones an
adopter will not think to look for: `coder::*` is registered by the `shell`
worker rather than by anything called coder, and the charter a repository ships
is served by `directory` rather than read by a tool.

What is left for ghola is **the stage graph and the briefs**: which base ref,
what happens in what order, when to land, and what the pull request says.

The ladder used to be on that list, and so did the audit log. Both were
genuinely general, so both became their own worker, which is the same argument
every other row of this table makes. A starter kit whose best ideas are locked
inside it is a worse starter kit.

The audit log went second and was the easier call, because nothing in it was
ghola's except the vocabulary. That is now `AUDIT_LOG_KINDS`, declared in the
Makefile, and declaring it caught three kinds ghola writes on every improve run
that had never been on the list.

The harness version pin is not cosmetic. On `harness` 1.8.1 the `pre-trigger`
hook fired and its `deny` was ignored: the call ran anyway. A ladder mounted on
1.8.1 looks wired and enforces nothing. **M1 ships a test that asserts a denial
is honored, not merely delivered.**

### The workers ghola writes

Two, and there is no third. An earlier draft of this plan had four; `worktree`,
`github`, `shell` and `eval` took two of them away, and `audit-log` took the
last, which is this plan working rather than this plan being wrong.

| Worker | What it owns |
|---|---|
| `workers/ghola-factory` | The stage graph, the job record, and the briefs. Calls `worktree::*` and `github::*` rather than running git. Starts turns; never runs one. **Serves no HTTP: the console is the UI.** |
| `workers/ghola-policy` | What this repository contributes to a turn: the four callbacks carrying the ladder, and the evaluator functions. **Registers no tools.** Holds no session state. |

`ghola-core` is not a worker. It is a plain Python package both workers import:
the pure decisions, with no I/O and no engine. The graph transition, the gate
action, the rule resolution, the contract parse, the layer precedence and the
phase settings live there, which is what lets nearly the whole test suite run in
milliseconds without an engine. wipp proved this is worth doing: its PR gate is
`derive_action(job, pr) -> action`, and every branch is testable without a pull
request.

wipp's three workers are about 10,300 lines. If ghola's two are not meaningfully
smaller, something here has been reimplemented rather than composed.

---

## 4. The customization contract

This is the section that makes ghola different from wipp, and the section most
likely to be wrong on the first attempt.

### The principle, before the surfaces

**Configuration is optional. Convention is the default. Everything has a home,
and every home can be moved.**

ghola runs with an empty `settings/`, or with no `settings/` at all. Each
file in it *overrides* a default that is stated in code and documented here; none
of them supplies something that was otherwise missing. A team that agrees with
the defaults writes nothing, and the first thing an adopter sees is a working
factory rather than a form.

Three consequences worth stating, because they are what the rule costs:

- **The defaults have to be good**, since most adopters will never change them.
  They are in `ghola-core/defaults.py`, in one place, readable in a sitting.
- **Every default has to be discoverable.** `ghola config` prints the effective
  configuration with each value tagged by where it came from: a built-in, a file,
  or an environment variable. A default nobody can see is a magic number.
- **Slim beats complete.** A knob goes in only when a real team needed it and the
  convention could not be bent. wipp shipped settings nobody ever changed, and
  each one is a thing an adopter has to read past.

Discovery is by convention throughout. A predicate, an action, a guard, a grader
and a forge driver are all *files in a named directory*, found by filename. There
is no registry to keep in step, because this design has twice been bitten by two
lists disagreeing.

Configuration says *where to look* when the convention is wrong. `settings/`
is itself only the default location, overridable with `GHOLA_SETTINGS`.

`settings/` rather than `config/`, incidentally, because `config/` belongs to
iii's `configuration` worker: that worker owns its directory and rewrites files
in it, and a shared directory is a collision waiting for a release to happen.

Three things differ between teams, and each gets its own surface:

| What differs | Surface | Who owns it |
|---|---|---|
| the flow of work in the factory | `settings/pipeline.yaml` | the operator running the factory |
| the development process in the harness | `settings/phases.yaml`, `settings/layers.yaml`, `prompts/` | the team |
| project specifics | the target repo's `CLAUDE.md`, `.claude/`, and its `.ghola/pipeline.yaml` | the project |

Configuration is the preferred surface. A Python script is the escape hatch, and
every escape hatch is a named directory that ghola discovers by convention. There
is no plugin registry and no entry-point mechanism, because a plugin system is a
second framework and iii is already the framework.

### 4.1 The flow of work: `settings/pipeline.yaml`

A stage graph, interpreted by `ghola-core`. Stages name a phase, a guard, and
where to go next.

```yaml
version: 1

terminal: [landed, closed, failed]

stages:
  prepare:
    action: prepare_workspace      # a built-in action
    next: plan

  plan:
    phase: plan                    # a block in phases.yaml
    skip_when: [rework, revision]  # a gate complaint is already a brief
    on_error: continue             # a failed plan hands over an empty plan
    next: run

  run:
    phase: run
    workspace: worktree
    on_refusal:
      goto: run                    # the gate's own words become the next brief
      max: 2                       # an agent that fails a gate twice will fail it again
      stop_when: identical_refusal # a gate repeating itself is not about the diff
    next: prove

  prove:
    phase: prove
    optional: true                 # GHOLA_PROVE=0, or absent from the graph
    contract: proven               # config/contracts/proven.yaml
    revert_worktree_changes: true  # a check may run the software, not repair it
    next: review

  review:
    phase: review
    optional: true
    contract: verdict
    publish: pr_comment            # never blocks; the human decides
    next: publish

  publish:
    action: open_pull_request
    gate: rung4                    # the delivery gate, over the finished diff
    next: waiting

  waiting:
    action: watch_pull_request
    poll: "0 * * * * *"
    on_merge: landed
    on_close: closed
    on_comment: rework

  rework:
    action: prepare_workspace
    then: run                      # same branch, same PR
```

**What a team can do without writing Python:** reorder stages, delete `prove` or
`review`, add a `security-scan` stage that runs an existing phase with a
different prompt, change the revision budget, change what a refusal does, change
which stages a rework re-enters at.

**What needs Python:** a genuinely new `action` or `guard`. Those are discovered
from `actions/` and `guards/` by filename, the same way callbacks are:

```
actions/deploy_to_staging.py   ->  action: deploy_to_staging
guards/needs_design_review.py  ->  guard: needs_design_review
```

Each is one function of `(job, config) -> result`. No base class, no decorator,
no registration.

**The target repo gets a say.** A repo's own `.ghola/pipeline.yaml` may add
stages and tighten guards. It may not remove a stage or loosen a gate, because a
repository that could switch off the checks it is held to is marking its own
homework. What a repo can always do is ask for more. The operator's config wins
on every conflict, and the resolved graph is copied onto the job at submit time
so editing the file mid-job does not change the rules that job is held to.

### 4.2 The development process: `settings/phases.yaml`

One block per phase. Everything that is a number or a name lives here.

```yaml
defaults:
  model: claude-sonnet-5
  thinking_level: medium
  max_turns: 50
  functions:
    allow:
      - "engine::functions::list"    # the agent's discovery loop
      - "engine::functions::info"
      - "ghola::tool::read_file"
      - "ghola::tool::list_files"
      - "ghola::tool::search"
      - "ghola::tool::glob"

phases:
  plan:
    model: claude-opus-5
    thinking_level: high
    prompt: prompts/plan.md

  run:
    thinking_level: xhigh
    max_turns: 80
    prompt: prompts/run.md
    functions:
      allow: ["ghola::tool::*", "harness::spawn"]

  review:
    thinking_level: high
    prompt: prompts/review.md
    functions:
      allow: ["ghola::tool::run"]   # merged over defaults; no editor, ever
```

`functions.allow` is **rung 1**, and it is the harness worker's own
deny-by-default policy rather than a convention. A function absent from the list
does not exist for that phase, so "checks do not repair" needs no predicate:
there is nothing to refuse and nothing to argue past.

Two things a reader trips over once, both learned the expensive way in wipp:

- **The allow list gates discovery as well as use.** The agent's surface is a
  loop of `engine::functions::list`, then `info` for the contract, then the call.
  A phase given tools and not the ability to read their contracts has been given
  nothing. That is how the first live turn on wipp's design failed.
- **A model is named from the router's catalogue** (`router::models::list`), not
  from a provider id we hope resolves. Thinking is a property of the model there,
  so a model that cannot think is never asked to.

Phases are not a fixed set. `plan`, `run`, `prove`, `review`, `draft`, and
`improve` ship as defaults because the default graph names them. A team adding a
`threat-model` stage adds a `threat-model` phase and a prompt, and writes no code.

### 4.3 Prompts: `prompts/`

One markdown file per phase, rendered with a small template context
(`{{spec}}`, `{{plan}}`, `{{diff}}`, `{{brief}}`, `{{repo}}`). wipp keeps its
prompts in Python string literals inside `harness-core`, which means changing how
a review is asked for is a code change. Here it is a file, and the file is the
first thing an adopting team will edit.

Rendering uses `string.Template`, not Jinja. A prompt template needing loops and
conditionals is a prompt that should be two prompts.

### 4.4 Layers: `settings/layers.yaml`

A rule answers three separate questions, and conflating them is how a company
standard ends up indistinguishable from one repository's opinion.

| Field | Question | Values |
|---|---|---|
| `layer:` | whose rule is it, where does it ship from | `project` · `team` · `org` |
| `rung:` | what carries it | 0 prose · 1 grant · 2 hook · 3 in-turn · 4 stage gate · 5 CI |
| `policy:` | what happens when it fires | `refuse` · `ask` · `warn` |

wipp hardcodes where each layer's rules live. ghola declares it:

```yaml
layers:
  org:
    rules: [./rules/org]
    predicates: [./predicates/org]
    locked_by_default: true
  team:
    rules: [./rules/team, ~/.ghola/team-pack/rules]
    predicates: [./predicates/team]
  project:
    rules: ["{repo}/.claude/rules", "{repo}/.ghola/rules"]
    predicates: ["{repo}/.claude/predicates"]
```

A path is a path, so a team's rule pack can be a git submodule, a cloned repo, or
a directory on a shared drive. There are three layers and there is no fourth. A
repository that writes `layer: personal` is describing one person's preference,
which this model does not carry: that rule reads as `project`, governs only its
own repository, **and is told so** in `ghola rules` and on the job record. The
narrow reading is deliberate, and the point of choosing it is that somebody can
see it was chosen.

A rule is one markdown file:

```markdown
---
id: name-the-swallow
description: A broad except says what it is swallowing and why
why: A gate that fails silently on its own bug stops the factory invisibly.
layer: team
rung: [3, 4]
policy: refuse
paths: ["workers/**"]
predicate: predicates/team/name_the_swallow.py
escape: swallow-ok
---
```

**One predicate, mounted at every rung it needs.** The same pure function runs in
the repository's generated hook, in the `pre-trigger` callback, and in the
delivery gate. Two implementations of one rule disagree, and the agent finds the
seam first.

A predicate is a module with one function:

```python
def check(path: str, content: str, context: dict) -> list[Finding]:
    ...
```

No imports from ghola, so a predicate is testable with `python predicate.py file`.

### 4.5 Output contracts: `settings/contracts/`

wipp parses `PROVEN:`, `VERDICT:`, and `INTERRUPT:` in Python with the markers
and the downgrade rules baked in. Those are settings.

```yaml
# config/contracts/verdict.yaml
marker: "VERDICT:"
values: [pass, concerns, blocker]
unparseable: unreadable        # never downgraded to a pass
requires:
  when: [concerns, blocker]
  at_least_one: finding        # an objecting review with no findings is not a review
```

```yaml
# config/contracts/proven.yaml
marker: "PROVEN:"
values: [yes, no]
requires:
  when: [yes]
  evidence: command            # evidence or it did not happen
  otherwise: unproven
```

A parser too odd for this shape goes in `parsers/<name>.py` and the contract
names it. I expect roughly one team in five to need that.

### 4.6 The target repo: `repos.toml`

What ghola knows about a repository. Read fresh on every submit, so adding a repo
does not mean restarting anything.

```toml
[defaults]
base = ""                  # discovered from the forge when empty
branch_prefix = "ghola/"
max_revisions = 2

[repos."/path/to/app"]
branch_prefix = "feature/"    # this repo writes it in CONTRIBUTING
prepare = "make up && make migrate"
cleanup = "make down"
env = { DATABASE_URL = "postgres://localhost/test" }
concurrency = 1               # this repo's prepare allocates real ports
```

Precedence: the repo's own entry, then `[defaults]`, then the environment, then
what is built in. **The resolved settings are copied onto the job**, so a rework
months later rebuilds the environment the job was born in rather than whatever
the file says then.

The base branch is discovered, not assumed. wipp hardcoded `main` and a repo on
`develop` branched from nothing.

### 4.7 The forge and the workspace: two workers, not two driver layers

An earlier draft of this plan had ghola shipping a `forges/` directory with a
six-function driver contract, and managing git worktrees itself. Both are
deleted. The `github` and `worktree` workers do these jobs, and doing them again
behind a ghola-shaped interface would be the exact mistake this repository
exists to argue against.

**The forge is `github`.** Typed `github::pr::create/view/comment/diff/merge/
checks/edit`, `github::issue::*`, `github::run::*`, with read-versus-mutate
permission gating and `github::exec` / `github::api` as the escape hatches. Its
own configuration holds `gh_executable`, `token`, and the timeouts. Supporting
GitLab is somebody publishing a GitLab worker, not ghola growing a driver
directory.

**The workspace is `worktree`.** `worktree::create` mints an isolated, locked
worktree off any base ref and registers it in a cross-agent registry;
`worktree::claim` fails with `W210` when another session holds it;
`worktree::land` rebases onto the target, runs an optional test gate through
`shell::exec`, fast-forwards with an atomic compare-and-swap, and cleans up.
Its configuration holds `worktree_root`, `branch_prefix`, `branch_naming`,
`prune_schedule` and `max_land_retries`.

Three things this bought, each of which was a numbered problem in this plan:

- **Open question 4, concurrency, is answered.** The claim is the semaphore, and
  it is cross-agent rather than per-process.
- **The branch convention is configuration**, in a worker that already
  hot-reloads it.
- **The workspace reaches the tools by itself.** An agent works inside the
  worktree through its turn's `metadata.fs_scope.root`, which is the mechanism
  wipp was injecting a `workspace` argument to simulate.

What stays ghola's is the part above both: which base ref, when to land, and
what the pull request says. Those are the stage graph and the briefs.

**Isolation, when the target repository is not trusted.** `iii-sandbox` spawns
ephemeral microVMs and exposes 16 `sandbox::*` functions, and both `coder::*`
and `shell::*` take a `target: { kind: "sandbox", sandbox_id }`. So the same
tools run either on the host or inside a microVM, chosen per stage rather than
per installation. A stage declares `isolation: sandbox` and nothing else about
it changes.

### 4.8 Evals: the stock `eval` worker, and ghola's evaluators

A rule decides. An eval measures. They are different instruments, and this plan
kept confusing them until this section existed.

**ghola does not write an eval runner.** The `eval` worker already runs durable
same-model A/B evaluations, alternates variant order to reduce order bias,
persists reports, and injects its own console page. It ships two deterministic
evaluators, `eval::assert::exact` and `eval::assert::normalized_text`.

What ghola contributes is **evaluator functions**, because that is the one part
of the contract the worker leaves open:

```
evaluator: { function_id: "ghola::eval::verdict-is", arguments: { equals: "concerns" } }
```

An evaluator receives the output, `harness::metrics`, the run identity, and the
caller's arguments, and returns `{ passed, score?, reason?, details? }`. They
must be deterministic and idempotent, because durable delivery is at-least-once.

ghola registers these on the policy worker:

| Evaluator | What it decides |
|---|---|
| `ghola::eval::contract` | the output parses against a contract in `settings/contracts/` |
| `ghola::eval::verdict-is` | a parsed field equals, or is in, an expected set |
| `ghola::eval::mentions` | a regex or literal over the turn's text |
| `ghola::eval::cites-evidence` | a `PROVEN: yes` carries a command under every criterion |

#### How a user extends it

By registering a function. That is the whole mechanism, and it is the reason
this is better than the grader-directory design it replaces: an evaluator is a
worker's function, so a team writes it in any language, hosts it in their own
repository, and names it by id in an eval request. Nothing has to be installed
into ghola, and nothing has to be discovered from a directory.

`evals/` becomes a directory of `eval::start` request files rather than a
bespoke case format. `make eval` submits them; `eval::result` reads the report.

#### What was given up, and why it is recorded here

The `eval` worker compares 2 to 5 sessions on **one dimension at a time**. It is
an A/B instrument, not a fixture-case regression suite, so the pass-rate-and-
spread reporting an earlier draft of this plan specified is not what comes back.
The reason for accepting that: a regression suite ghola wrote would be a second
eval system beside a working one, and the thing I actually need before changing
a prompt is "is the candidate worse than the control", which is exactly what
`eval::start` answers.

If per-phase regression suites turn out to be necessary, they are built on
`eval::compare-sessions` rather than beside it.

#### What evals are for, and what they are not

- **They gate prompt and phase changes, not jobs.** No eval runs inside the
  pipeline. A job that waited on a five-run eval would cost five turns and tell
  the operator nothing about that job.
- **They are the regression check for `prompts/`.** A prompt is the easiest file
  in this repository to change and the only one with no other check on it.
- **They cost money, so they are opt-in.** Nothing runs them on a timer until
  somebody asks for that.

The honest limit: I have not run one yet. Every claim in this section about what
the worker reports is read from its documentation, not observed.

### 4.8b There is no HTTP surface. The console is the UI.

An earlier draft had ghola serving a browser surface: a job board, a stage rail,
a live log, and endpoints for submitting a spec and answering a hold. All of it
is deleted, because iii's console already does it and does it better.

| what the surface was for | what does it instead |
|---|---|
| submit a spec | invoke `ghola::submit` from the console, or `make submit` |
| watch a job move | the console's turn waterfall, per session |
| tail what a turn is doing | the same waterfall, live, with the model's own calls |
| answer a hold | `approval-gate` injects its own console page |
| queue depth, failures | the console's queue and DLQ views |

**And if ghola ever does need a page of its own, it injects one rather than
serving one.** `console:script` and `console:style` are trigger types: a worker
registers an asset and the console renders it. `harness`, `eval` and `memory`
all do this today. A bespoke dashboard would be a second UI to maintain, a
second port to secure, and a worse trace view than the one already there.

What this costs, stated plainly: there is no remote access and no form. Both
follow from a non-goal this plan already has (one operator, one machine), and a
spec arrives as a file path rather than a drag-and-drop upload.

### 4.8c Entry and exit criteria, and the file between phases

**The interface between phases is a file.** A job starts as a copy of its spec
and each phase appends what it produced, so by the time it reaches a human the
document *is* the account of the work: what was asked, what was planned, what
was built, what was proved, what review found. It becomes the pull request body
unchanged, because nothing has to be summarised into existence.

That is what makes entry and exit criteria expressible:

```yaml
plan:
  phase: plan
  requires: [spec]     # it cannot start without one
  produces: [plan]     # it is not done until it wrote one
```

Both were silent before. **A phase whose entry criteria are unmet would run on
nothing and produce something confident about it**, which costs a turn and reads
like an answer. **A phase that finishes without its exit criteria has returned
something nobody downstream can use**, and the next stage discovers that instead
of the stage that caused it.

The sections are a fixed vocabulary — `spec`, `plan`, `work`, `proof`,
`review`, `answer`, `refusal` — so a `requires: [speck]` is a typo `make
pipeline` catches rather than a criterion that can never be met.

Two properties worth stating, because both were bugs waiting to happen:

- **A rerun replaces its section rather than appending a second one.** A
  revision runs the same phase again, and two `What was built` sections leave a
  reviewer deciding which is current.
- **The authored spec is never rewritten.** It is the input of record and lives
  in `specs/`. The document is a working copy, which is what lets an interrupt's
  answer amend the contract the checks are graded against without editing what a
  person wrote.

### 4.8d Refine: an idea is not a spec

**An optional first phase that turns a vague idea into a spec work can begin
from.** It is opt-in rather than merely optional, and the distinction is one the
first version got wrong:

- **opt-out** (`optional: true`) — the stage runs unless a job turns it off.
  `prove` and `review` are this, because a factory that quietly stopped checking
  would be worse than one that never checked.
- **opt-in** (`opt_in: true`) — the stage runs only when a job asks for it.
  `refine` is this, because most work arrives as a spec somebody wrote, and
  rewriting it would be rewriting their words.

```
make submit SPEC=specs/x.md REPO=../repo    # written carefully, used as-is
make idea IDEA="a rough sentence" REPO=../repo   # refined into a spec first
```

**The idea is kept beside the spec, not replaced by it.** A refinement that
drifted from what was actually wanted is only visible if both are in the
document, and the pull request carries both.

What the phase is told to do, and it is the useful part: read the repository
before writing, because the idea is vague precisely because whoever wrote it did
not have the code in front of them. Narrow it, because a vague idea usually
contains three changes. And **do not invent a requirement the idea did not
contain** — genuine ambiguity goes under `Open questions` rather than being
decided silently, because a spec that quietly answers a question nobody asked is
how the wrong thing gets built confidently.

Verified live: `"the makefile help output is hard to scan"` became a spec naming
three concrete defects with line numbers, having noticed that
`.DEFAULT_GOAL := help` is set on line 1 and therefore that reordering is safe.

### 4.9 Everything else

`ghola.yaml` holds ports, paths, and the harness pin. Environment variables
(`GHOLA_*`) override single values for a run and are documented in
`.env.example`. Nothing reads an environment variable that does not also have a
config key, because a setting reachable only through the environment is a setting
nobody can see.

---

## 5. Repository layout

```
worker-compose.yaml             the whole process surface: the engine, every
                                worker, and the version pins. Tracked, because
                                harness 1.8.7 is load-bearing.
config/<worker>.yaml            one per iii worker, owned by the `configuration`
                                worker. ghola does not write here.

settings/                   ghola's own settings. ALL OPTIONAL — every file
                                overrides a default in ghola-core/defaults.py.
  pipeline.yaml                 the stage graph            (flow of work)
  phases.yaml                   models, grants, budgets    (development process)
  layers.yaml                   where rules ship from
  contracts/*.yaml              output contracts
  pricing.yaml                  fallback prices for models the catalogue nulls

prompts/*.md                    one per phase
rules/{org,team}/*.md           the rules that travel
predicates/{org,team}/*.py      one pure function each
actions/*.py                    custom stage actions       (escape hatch)
guards/*.py                     custom stage guards        (escape hatch)
parsers/*.py                    custom output parsers      (escape hatch)
evals/*.json                    `eval::start` requests

workers/
  ghola-core/                   a package, not a worker. Pure decisions, no I/O.
    src/paths.py                where the repository and its config are
    src/defaults.py             what ghola does when nobody configured it
    src/phase_settings.py       a phase name to send options
    src/turn.py                 phase to harness::send, turn-completed to result
    src/graph.py                the stage transition                     (M4)
    src/rules.py                the ladder                               (M3)
  ghola-factory/                the graph, the job record, the briefs, HTTP
  ghola-policy/                 the four callbacks, and the evaluators
    src/callbacks/
      pre_generate.py           the charter                          (rung 0)
      pre_trigger.py            the ladder                        (rungs 2, 3)
      post_trigger.py           what a call did, on the job's log
      post_generate.py          the verdict guard

specs/                          the input of record, in git
scripts/                        operator scripts, each with a --check self-test
runs/                           worktrees are the `worktree` worker's, under
                                ~/.iii/worktrees. Nothing here.
tests/
  test_*.py                     pure and worker tests      (make test)
  live/test_*.py                framework contract tests   (make test-live)
docs/                           architecture, adoption, the ladder, evals
```

Two directories that are conspicuously absent, because a worker owns them:
`state/` (the `state` worker) and `forges/` (the `github` worker).

Convention over wiring throughout: every module in `callbacks/` binds to the
hook point its filename names, and every module in `actions/`, `guards/` and
`parsers/` is addressable by its filename. `boot.py` walks them, so there is no
list to keep in step. This design has twice been bitten by two lists disagreeing.

## 6. Milestones

Each milestone states what is built and the check that decides it is done. A
milestone with no runnable check is not a milestone.

Section 7 sets the bar every milestone below is held to, and it is not repeated
in each one: pure decisions get tests, framework promises get live contract
tests, agent steps get eval cases, and `make test` is green. Where a milestone
names a check explicitly, that check is *in addition* to the bar, because it is
the one I expect to catch something.

### M0. The skeleton boots

- `iii project init`, `worker-compose.yaml` with namespace `ghola`, the stock
  workers, ports off iii's defaults so a ghola engine runs beside another project.
- MIT license, README stub, `.gitignore`, `.env.example`, remote set.
- `Makefile`: `install`, `engine`, `workers`, `status`, `stop`, `call`.
- Credentials note in the README: **providers read their keys from the engine's
  environment**, so `make engine` sources `.env`. An engine started without them
  serves a router with no models and every turn fails at
  `router::provider::resolve` with nothing saying why. This cost wipp a live run.

**Verify:** `make up` comes up, `make call FN=router::models::list` returns a
non-empty catalogue, `make stop` frees every port.

### M1. One turn, through the seam

- `ghola-policy` with `boot.py`, the four callbacks as no-ops, and the read-only
  tools.
- `ghola-core`: `phase_settings.py` reads `settings/phases.yaml` and merges over
  defaults.
- `make turn PHASE=plan PROMPT="..." WORKSPACE=../repo` runs one turn and prints
  the turn's own words and what it cost.
- The four evaluator functions of section 4.8, and one `eval::start` request
  file that uses them, because an evaluator nothing has called has not been
  shown to run.

**Verify:**
1. `test_pre_trigger_deny_is_honored` — a `pre-trigger` returning
   `{decision: "deny"}` means the target function is never entered. This is the
   1.8.1 regression test, and it fails loudly on an unpinned harness.
2. A phase given no `read_file` cannot read a file, proving rung 1.
3. Hook trigger types are bound by the **hyphenated** names the worker emits
   (`harness::hook::pre-trigger`). Underscore bindings register without error and
   never fire, which is a ladder that looks wired and is not.

### M2. The charter reaches the turn (rung 0) — **done**

Smaller than this plan first said, because three other workers are already on
`pre-generate` and each owns a piece: `directory` serves the repository's skills
and prompts, `memory` injects its banks, and `ladder` owns the rules and their
layers. `settings/layers.yaml` is therefore the ladder's configuration, not
ghola's.

- `ghola-core/charter.py`: assembly, pure. Takes text and a reader, returns text.
- `pre_generate` reads `CLAUDE.md` (or `AGENTS.md`), follows `@path` imports, asks
  `ladder::list` for the constraint prose, and returns a `system_prompt` mutation.
- Only the *prose* is taken from the ladder. A rule's enforcement is the ladder's
  job at whatever rung carries it, and implementing it twice is the seam an agent
  finds first.
- An import is resolved inside the repository only. `@../../../etc/passwd` would
  otherwise put that file into a system prompt, and the target repository is what
  ghola is pointed at rather than what it trusts.
- A missing import, a cycle, and an over-deep chain are each reported and left as
  written. Silently dropping one produces a charter with a missing section, which
  is the harder bug to find.

**Verified live**, against `tests/fixtures/charter-repo`: two arbitrary tokens,
one stated only in `CLAUDE.md` and one reachable only through its `@import`, both
came back in the model's reply. Arbitrary on purpose — a rule the model would
follow anyway proves nothing, because a turn that never saw the charter passes it
too.

**The governed listener is declared** under `engine.workers` in
`worker-compose.yaml` as a second
`iii-worker-manager#governed` instance on 49155, with `gantry::middleware` in
front of every call arriving on it. Nothing connects to it yet: M5 is the first
stage with something to push. It exists now because a governed listener added on
the day you first need it is a governed listener configured in a hurry.

**Not done, and it belongs to M4:** path scoping. `Charter.take(touched=…)` holds
a scoped piece back until the turn goes near what it is about, and is tested, but
nothing tracks touched paths until the factory does. Every scoped piece therefore
waits today and only the always-on ones travel.

### M3. The ladder (rungs 1 through 3, and holds) — **done**

Most of it is the `ladder` worker's, which is what extracting it was for. What
landed here is the join and the dial.

- **In the ladder:** the repository's own `.claude/settings.json` `permissions`,
  read at two rungs. `Bash` names a whole tool and is withheld at rung 1;
  `Bash(php *)` names an argument and is refused at rung 2. `ask` subtracts like
  `deny`, because there is no human inside an unattended turn.
- **In ghola:** rung 1 applied where the grant is actually built. `ladder::list`
  returns what is withheld and `turn.payload_for` subtracts it, putting the names
  in the send's `deny` list. The harness refuses on "no allow-glob match **or** a
  deny-glob match", so a deny beats an allow whatever the glob said.
- **`settings/oversight.yaml`:** the dial above.
- The target repo's `.claude/settings.json` `permissions` honored at two rungs:
  `Bash` names a whole tool and is withheld (rung 1); `Bash(php *)` names an
  argument and is refused (rung 2). `ask` subtracts like `deny`, because an
  unattended factory reading "ask" as "yes" has answered a question nobody put.
- `policy: ask` is the `approval-gate` worker, not ghola code. It binds
  `approval::gate` on `harness::hook::pre-trigger` itself, answers `continue` /
  `deny` / `hold`, and serves the pending inbox as `approval::list-pending` with
  `approval::resolve` to answer one. Confirmed bound on harness 1.8.7 despite its
  README warning about greenfield contracts. ghola's own `pre_trigger` runs
  beside it at a declared `priority`, and carries `refuse` and `warn` only.
- The single-writer refusal: a write while a child of this turn is still running
  is refused, because `harness::spawn` is fire-and-forget and a child inherits the
  parent's filesystem root.

**Verify:** each of ghola's own six rules fires at its declared rung against a
fixture; a matcher test proves `make test && php artisan migrate` does **not**
match `php *` and is not refused, because parsing shell to guess would make the
predicate a different rule wearing this one's authority.

### M4. The factory and the graph

- `ghola-factory`: the job record, the briefs, and the stage dispatch. Worktrees are `worktree::create` / `claim` / `release`; prepare and
  cleanup are `shell::exec`.
- **The state durability check, before anything depends on it.** Kill the `state`
  worker mid-job and assert the record survives. wipp lost a live job exactly
  here and moved to files; if this fails, ghola does the same and this line
  becomes the reason why.
- `ghola-core/graph.py`: the stage graph interpreter. `next_stage(job, graph,
  result) -> transition` is a pure function.
- Job state derived from the graph. Every transition a durable queue message.
- The dashboard, driven by the graph rather than a hardcoded rail.

**The job store is files, and the durability check is why.**

The check ran and the `state` worker passed it once configured. But it passed by
being configured, and that is the finding: `store_method` **defaults to
`in_memory`**, which the worker's own schema calls "volatile, process-lifetime
storage, lost on shutdown — not for production".

The worker is not broken. The failure shape is. A factory on the default adapter
works perfectly until the first restart, nothing announces it, and the first
restart is usually the one during a long job. **For a starter kit somebody clones
and points at their own repository, a store that silently loses every job because
one config key was missed is a worse trade than a store that is obviously a
directory.**

So ghola's own job records are one JSON file per job, written atomically through
`os.replace`. They cannot be misconfigured, `cat state/jobs/<id>.json` is a
debugging tool, and a crash loses at most the write in flight. This is the one
deliberate exception to the prefer-a-worker rule, alongside the audit log, and
for the same reason: a record has to be more durable than the thing recording it.

The `state` worker is still installed and still configured `file_based`, because
`approval-gate`, `worktree` and `memory` all store through it and none of them
should be on the volatile default either. `tests/live/test_state_survives.py`
holds that, and it is about them rather than about jobs.

**Verify:** `test_graph_reaches_every_stage` walks the shipped graph and asserts
every stage is reachable and every terminal state is declared; a job killed
between two stages resumes on restart; a stage delivered twice does the work once.

### M5. Delivery (rung 4, the PR, the gate) — **done, every path exercised**

Three real jobs against `tacoda/fawlty` proved the whole lifecycle:

| path | evidence |
|---|---|
| spec to pull request | PR #1, `README.md` alone, 66 insertions |
| merge to landed | the reconciler noticed on its own in ~20s |
| comment to rework | PR #2: one pull request, two commits, a conversation |
| landed to teardown | worktree off disk and deregistered, said so on the PR |
| an idea to a spec | `refine` narrowed a vague sentence to three defects with line numbers |

**Teardown is called by the factory on every terminal state**, not routed to as
a stage: every terminal state needs it and a stage would need an edge from each
of them. Removal passes `force`, because a squash merge leaves the branch commit
outside the target's ancestry and git cannot see that it landed — without it
every squash-merged job leaks a worktree, which is how three accumulated.



A spec went in and https://github.com/tacoda/fawlty/pull/1 came out, through
prepare, plan, run, prove, review, commit, publish. The diff was `README.md`
alone, 66 insertions, exactly what the spec allowed. The job sits at `waiting`
and nothing merged itself.

What is done: rung 4 over the finished diff and the text about to be published,
the repository's own commit hook, the push, `github::pr::create`, and the
`waiting` state. What is **not** yet exercised: the reconciler that turns a
merge, a close or a comment into the next transition. `derive_outcome` is pure
and fully tested, but no real human has acted on a real pull request yet.

The forge identity is worth its own line, because it cost the first run. **The
identity that pushes and the identity that opens a pull request are not the
same thing.** git authenticated over an ssh host alias as one account while
`gh` used an ambient `GITHUB_TOKEN` belonging to another; the push succeeded
and `pr create` failed with "must be a collaborator" after the job had paid for
a worktree, a plan, a run and two checks. `make doctor` now asks the WORKER
which account it is, not this shell, and checks push permission per configured
slug.

- The commit gate: rung-4 predicates over the finished diff **and over what the
  job is about to publish**, which is neither written by a tool nor part of any
  diff.
- `worktree::land` for the branch, and `github::pr::*` for the pull request. No
  git subprocess in ghola.
- The target repo's own pre-commit hook runs, and its refusal becomes the next
  brief verbatim, bounded by `max`, ending early on an identical refusal.
- `open_pull_request` is `github::pr::create`.
- `watch_pull_request` reads `github::pr::view`, which already returns
  mergeability, review decision and diff stats: merge lands, close closes,
  comment reworks onto the same branch and PR with a reply under it. Line
  comments come from `github::api`, which reaches the endpoint `pr::view` omits.

**Verify:** `derive_action(job, pr) -> action` is pure, and every branch of the
gate is tested without a pull request. Effects live outside it.

### M6. The checks

- `prove`: runs the software against the spec's acceptance criteria, denied every
  editing tool at rung 1. The worktree is checked afterwards and anything a check
  changed is reverted, because a shell can write whatever its tool list says.
- `review`: handed the spec and the diff and nothing else, never the executor's
  summary of its own work. Read-only tools. It never blocks.
- Contracts parsed from `settings/contracts/`.
- Interrupts: `INTERRUPT: <question>` as the opening line stops the job, and the
  answer amends the contract. The checks are handed the spec **plus** the question
  and answer, or they grade correct work against a requirement that has been
  withdrawn. That is not hypothetical; prove returned `no` on exactly this in wipp
  before the fix. The authored spec file is never rewritten.

- Contracts: **done**, and verified live. A real `prove` turn claimed
  `PROVEN: yes` with no command under it, the guard downgraded it to `unproven`,
  and the audit log recorded `claimed: yes -> became: unproven` with the reason.
- Evals: **done**, and both cases discriminate against a real model.
  `ghola::eval::{contract,verdict-is,mentions,cites-evidence}` are registered
  and reachable, `evals/*.json` are `eval::start` requests, and `make eval`
  submits them.

**There is no `judge` grader, and that is now a decision rather than a gap.**
All four evaluators are deterministic, and a case that can be graded
deterministically must not use a model to grade it: a model grading a model is
the weakest evidence available, and every case worth writing so far has had a
checkable answer. If one arrives that genuinely cannot, `judge` is the thing to
add then — with a threshold rather than a verdict, and reported separately, so a
suite that is 90 percent judge is visibly measuring agreement rather than
correctness.

The thresholds section 4.8 guessed at are still guesses. What replaced them is
the `eval` worker's own eligibility rule, which is stricter than anything I
wrote: every treatment run must pass and its pass count must not regress. A
candidate that is merely no worse is not evidence that it is better.

**Verify:** a `PROVEN: yes` with no command under any criterion downgrades to
`unproven`; an unparseable verdict records as `unreadable` and never as a pass.
Each phase suite has a case that passes and a case that fails, and `make eval`
reports a rate and a spread rather than a color.

### M7. The improve lane — **done, and it found a bug in itself**

- `ghola::improve` hands one turn everything that went wrong recently and asks
  what would have prevented it. Not `POST /improve`: there is no HTTP surface,
  and `make improve` is how an operator reaches it.
- Trouble is read broadly. `trouble.py` is pure: job records and audit entries
  in, `Signal` objects out, each naming what cost something **and what it argues
  for**, because a count is not an argument.
- Proposals name where, what, and what happens to it, plus the jobs they came
  from. Lanes are charter, harness, factory; `remove`, `promote` and `demote`
  are first-class. **A proposal that cannot be traced to evidence is dropped
  rather than repaired**, and the reason is kept on the run.
- The lifecycle is the `ladder` worker's, not a CLI here. A promotion or a
  demotion is `ladder::move`, which changes a repository and commits nothing.

**Nothing is applied.** Accepting writes a spec into `specs/` and stops; that
spec goes through the same pipeline and the same pull request as any other work.
A clean record produces no proposals rather than inventing three.

Three things the first live run taught, none of which a test would have:

- **The lane reads two repositories.** A charter proposal is about the target
  repo; a harness or factory one is about ghola's own prompts and pipeline.
  Scoped to one, the turn hit the filesystem boundary on the other, the approval
  hook parked the call for a person, and nothing told that person: it sat in
  `awaiting_functions` for ten minutes. Fixed with
  `harness::filesystem::grant`, the framework's own mechanism, asked for before
  the turn starts.
- **`on_approval_held` passed `kind=` to `record`**, which takes the audit kind
  as its first parameter, so every approval hold this system ever recorded was
  lost to a `TypeError` inside a trigger handler. The log looked like the log of
  a system that never held anything.
- **`never_fired` could not exonerate a rule carried at prose.** Rung 0 refuses
  nothing, so a prose rule appears silent at any volume of jobs however well it
  is working — and the signal's own "removal is half the work" made deleting it
  the likely outcome. The improve lane found this in `trouble.py` on its first
  run and proposed the split, against three correct rules. Now `unobservable` is
  its own signal and says its silence is not evidence.

**Verified live** against `tacoda/fawlty`: five proposals from two jobs and 110
audit entries, all five traceable, none dropped. Accepting one wrote
`specs/give-commits-md-a-scope-for-changes-that-are-not-a-resource.md` and
called nothing on the bus.

### M8. Adoption — **done**

- ~~`ghola init` scaffolds a new factory~~ **Cut.** `state/`, `audit/` and
  `.logs/` are all git-ignored, so a fresh clone is already clean and the files
  *are* the scaffold. Scaffolding a starter kit that ships filled in is
  scaffolding nothing. What was real underneath it: `repos.toml` shipped
  pointing at my home directory. It is now a tracked template of commented
  examples, and `repos.local.toml` is git-ignored and wins over it, which is the
  same split as `.env` for the same reason. `make setup` writes it, and
  `make repos` and `make doctor` report every configured repository through the
  same `repos.merged` the factory uses.
- **A second forge driver.** `forge.py` is pure: a driver returns the calls to
  make and reads the answers, and the factory makes them. `github` is the stock
  worker. `local` is no forge at all, which is the harder and more useful proof:
  the request is a markdown file in `.ghola/requests/`, a merge is a merge, and
  it needs no account, no token and no slug. A third is `forges/<name>.py`
  defining `driver`.
- **Two example configurations**, `minimal` and `strict`, both parsed by the
  same `graph.parse` a live pipeline gets. A broken example is worse than no
  example.
- **`settings/evals.yaml`** names suites outside this repository. Proved with an
  external case that discriminated 1/1 control against 0/1 treatment.
- **`docs/`**: adoption, the ladder, the customization contract, evals, and an
  honest limitations page, plus the guide's missing section on running a job.

What the no-forge run taught, none of which a test would have:

- **The commit stage pushed to `origin` unconditionally.** A repository with no
  forge has no remote, and the branch is already in the checkout the reviewer
  opens. The same assumed ref reached the delivery gate, where `origin/main`
  failing to resolve had quietly reduced rung 4 to reading the staged half of
  the diff.
- **The `local` request template quoted its own comment heading**, so the split
  matched that occurrence, and everything after it came back as one reviewer
  comment. The job reworked itself against its own document. The conversation
  starts at a marker now, because prose gets quoted.
- **`commit_message` did not strip a spec's `#`.** `git commit -m` keeps it, so
  every commit read as a heading.
- **`graph.BUILTIN_ACTIONS` had no entry for `commit_and_push`**, so the
  documented list of built-in actions had drifted from the implemented one.

**Verify:** a person who has never seen this repo gets a pull request out of a
target repository, following the README only. If they cannot, the README is the
defect.

### M9. What reading the record found — **done**

M8 shipped a working lifecycle, so the next thing worth doing was reading it
back. [ROADMAP.md](ROADMAP.md) is where what-comes-next lives now; this section
is the shipped half, moved here because that page is for work with no milestone.

Every item is a defect found by reading code rather than by a failing test, and
three of the four turned out to be more than one bug.

- **The review phase was promised a diff and shown nothing.** `prompts/review.md`
  carried a `$diff` placeholder and told the reviewer it had seen the change.
  `brief_for` filled it from `job.get("diff")` and nothing ever wrote `diff`
  onto a job, and a missing field renders as an empty string on purpose so a
  `$PATH` in a spec cannot break a turn. So the reviewer read a heading with
  nothing under it and no reason to go looking. The phase has `RUNNING` in its
  grant, so it now gets the base ref and the two commands that fetch the whole
  change. `actions.base_ref` is the single derivation of that ref, read by the
  delivery gate and by the brief, because a reviewer grading against a different
  ref than the gate reads is a reviewer whose `pass` means nothing at delivery.
  `prompts.FIELDS` is the promise that something fills a name, so `tests/test_docs.py`
  checks every prompt against it. `9360321`.

- **The delivery gate read less than it claimed**, three ways. It cut its input
  at 200,000 characters with no marker. An unreachable ladder returned `""`,
  which the caller reads as "not refused", so a downed worker committed the
  change; a failed `git diff` did the same through empty content. And it passed
  `path: ""`, which skips the path filter in both `Loaded.governing` and
  `gate.decide`, so every path-scoped rule was asked about every file and its
  predicate got no path to name in a finding. Now `diffs.per_file` splits on
  `diff --git` and the gate asks once per file with the real path, and
  `rung_four` returns `(refusal, problem)` where only an empty pair commits.
  `MAX_FILES` replaces the bound the old cut gave by accident. `d9a0616`.

- **`concurrency` was parsed and nothing read it.** `repos.py` parsed the key
  three times over and no code asked for the value, while `prepare_workspace`
  argued that `worktree::claim` was the answer. That holds for one checkout and
  not for one repository: two jobs get two worktrees, so both claims succeed and
  both run `prepare`. The job store is the semaphore now, because it already
  knows which jobs are live. A job at `waiting` counts, since `teardown` runs
  `cleanup` on a terminal state only and an open pull request still holds the
  ports. `df6cf98`.

- **The agents standard.** `AGENTS.md` is the charter and the only file read,
  and everything under `.agents/` is charter with each directory naming its
  concept. Hooks are read from `.agents/settings.json` where Claude Code
  declares them, and `hooks.py` turns that block into constraints the way
  `permissions.py` already did. `DEFAULT_ROOTS` and `SETTINGS_FILES` had no
  tests, which is how the whole path swap passed 644 of them without one
  failure. This repository is now a target of itself, and that charter caught
  its own first overclaim: `no-ai-attribution` declared `rung: delivery` and
  `validate` refused it, because `publishing` reaches a bus predicate and
  nothing else. `11acbe0`.

**What the four have in common**, and it is the reason to keep them together: in
every case the report was more confident than the mechanism. A gate that could
not read its input said nothing, a prompt described evidence it had not
attached, a setting read as protection while nothing consulted it, and a charter
file claimed a rung nothing carried. None of it would fail a test, because
nothing was asserting the claim.

**Verify:** 675 tests, and `.agents/rules/never-claim-a-rung-you-do-not-carry.md`
is the rule those four wrote.

---

## 7. Testing and evals

**Nothing is done without a check, and the check depends on what the thing is.**
Deterministic code gets a test. A step where an agent produces something gets an
eval. Most of ghola is the first; the six phases are the second; the ladder is
both, because a rule is deterministic and whether the model *adapts* to a refusal
is not.

### The four kinds, in descending count

1. **Pure tests over `ghola-core`.** Every decision is a function of dicts: the
   graph transition, the gate action, the rule resolution, the contract parse,
   the permission match, the cost calculation, the layer precedence. No engine,
   no network, no fixtures beyond dicts. This is where most of the confidence
   lives, and it is the reason `ghola-core` does no I/O.
2. **Worker tests with the engine mocked.** The factory's handlers and the policy
   worker's callbacks are functions of `(payload, context)`. They get called
   directly with a fake trigger client that records what was sent.
3. **Live contract tests against a running engine.** Small, slow, and the only
   thing that catches a framework change. The harness 1.8.1 denial test is the
   model: it asserts a behavior the framework *promises*, and it failed silently
   for wipp before anyone wrote it. Every framework promise ghola leans on gets
   one of these, and there are five: the deny is honored, the hold parks the call,
   `pre-generate` mutations reach the model, `turn-completed` carries the context
   categories, and the allow glob gates discovery.
4. **Evals over the phases.** Section 4.8. One suite per phase, run before any
   prompt or phase-settings change lands.

### The rule

A milestone is not done when the feature works. It is done when:

- every pure decision it added has a test,
- every framework promise it started relying on has a live contract test,
- every agent step it added or changed has an eval case, and
- `make test` is green.

`make test` runs 1 and 2 and takes seconds. `make test-live` runs 3 and needs an
engine. `make eval` runs 4 and costs money. Only the first is a pre-commit gate,
because a gate nobody can afford to run is a gate that gets skipped.

### Coverage of the agent steps

Six phases produce something, so six suites exist by M6. Each one needs at least
a case that passes and a case that *should* fail, because a suite where
everything passes has not been shown to discriminate:

| Phase | The eval asks | The case that must fail |
|---|---|---|
| `draft` | does a sentence become a spec that names real files | a repo the sentence does not match |
| `plan` | does the plan name files that exist and a mechanism that works | a spec whose obvious approach is wrong |
| `run` | does the diff satisfy the spec and pass the repo's gate | a spec with a hidden constraint |
| `prove` | does it run the software and cite commands | work that is broken but looks finished |
| `review` | does it find the defect that is in the diff | a clean diff, which must come back `pass` |
| `improve` | does a proposal trace to real job evidence | a run with nothing wrong, which must be silent |

The ladder gets its own suite, and it is the one I care most about: a turn given
a refusal must adapt rather than argue, retry, or route around. That is a
behavior no predicate can assert about itself, which is the argument for evals
existing at all.

### The invariant underneath

**A gate that fails open on its own bug is a gate that stops the factory
invisibly.** Predicates answer for themselves, which in wipp is a rung-5 rule,
because whether the gates work cannot be asked of the gates. In ghola the same
question is asked twice: a test that every shipped predicate raises nothing on a
malformed input, and an eval that a turn actually meets the rule in practice.

---

## 8. Sequencing and what I expect to get wrong

M0 through M3 are the harness, and they are useful alone. A developer usually
wants that product and not the factory: what does my charter, and my rules, do to
a turn? Ship it as a usable thing at M3 rather than waiting for M8.

M4 and M5 are the factory. M6 and M7 are what makes it worth running unattended.

Three places I expect the first design to be wrong:

- **The stage graph will be under-expressive.** wipp's revision loop, its
  skip-planning-on-rework rule, and its worktree reverting are three special cases
  that I have written as graph fields. At least one of them will need an escape
  hatch, and the honest fix is to name it rather than to grow the schema.
- **`settings/layers.yaml` will meet a team with four layers.** They will have a
  business unit between team and org. The answer is that they map it onto one of
  the three and the record says which, not that ghola grows a layer.
- **The prompt templates will be edited into incoherence.** A prompt is the
  easiest file to change and the hardest to test. M8 should ship a prompt lint
  that asserts each template still names its contract marker.

Two things wipp leaves out that ghola inherits and should state on the front page
rather than in a footnote:

- **A rule carried only at rung 3 is still reachable by a shell.** The callback
  sees every call. What it does not do is read inside a shell command and judge
  the file that command would write. The delivery gate is the backstop, and a rule
  that matters names both rungs.
- **Turns inherit the operator's agent configuration** unless it is pinned. A
  personal skill reached committed code in wipp this way, and the review caught it.

---

## 9. Open questions

0a. ~~**`approval-gate` defaults to holding every call.**~~ **Answered by the
    oversight dial.** Its `mode` defaults to `manual`, so the first live turn
    here parked on `coder::read-file` waiting for a human who was not coming.
    Two workers were both trying to be the human in the loop.

    `settings/oversight.yaml` now names the pair, because setting a mode to
    `full` silently changes what every `ask` rule does and an operator should
    not have to know that:

    | level | a person answers | refuses without asking |
    |---|---|---|
    | `manual` | every call | nothing |
    | `attended` | every write | reads run |
    | `supervised` | only what a rule marks `ask` | the ladder |
    | `dark` | nothing | the ladder, and `ask` degrades to refuse |

    **`ask` never becomes `allow`,** at any level, and that invariant is the
    first test in the file. Default is `supervised`. A stage may override it,
    because `run` and `review` want different answers. **M4 sets it per stage
    when it opens a session.**

1. ~~**Does the harness worker's `options.functions.allow` glob syntax cover
   an explicit deny of one name in the same block?**~~ **Yes**, confirmed on
   1.8.7. `turn.py` builds the deny list and the harness refuses on "no allow
   match OR a deny match", so a deny beats an allow whatever the glob said.
   Rung 1 rests on that and now says so where it is built.

   The original question, kept because the answer is only meaningful with it:

   **Does the harness worker's `options.functions.allow` glob syntax cover
   `ghola::tool::*` and an explicit deny of one name in the same block?** wipp
   relies on this for "checks do not repair." Confirm against 1.8.7 before M1
   closes, because the whole of rung 1 rests on it.
2. **Namespacing.** iii 0.23 routes by namespace. Whether ghola's tools should be
   `ghola::tool::read_file` inside namespace `ghola`, or whether the namespace
   makes the prefix redundant, changes every allow list in `phases.yaml`. Decide
   at M0 and do not revisit.
3. **Cost.** The router's catalogue prices `claude-opus-5` and `claude-sonnet-5`
   at null today, so `max_cost_usd` cannot be set: a budget requires every model
   in the tree to advertise a price, and a budget that silently fails a turn is
   worse than none. Ship the fallback table in `settings/pricing.yaml`, mark what a
   cost was derived from as `cost_source`, and let the catalogue win whenever it
   is non-zero.
4. ~~**Concurrency.**~~ **Answered in M9, and the key shipped dead for four
   milestones first.** `repos.toml` carried `concurrency`, `repos.py` parsed it
   three times, and nothing read the value. The job store is the semaphore:
   `too_busy` counts the live jobs on a repository before `prepare` claims
   anything, and only where a `prepare` command exists, because a repository
   that allocates nothing has nothing for two jobs to fight over.

   The second job fails rather than waiting, and that is the part still worth
   improving. Waiting needs a stage that can defer itself plus a reconciler to
   re-drive it, and `blocked` is not that: it waits on a person.

5. ~~**Big diffs.**~~ **Answered in M9, and the answer was neither refuse nor
   chunk.** The gate splits the diff per file and asks the ladder once per file
   with that file's real path, which is the unit `check(path, content, context)`
   was written for. So the truncation went away and two other bugs went with it:
   the path filter that an empty `path` had been skipping, and the fail-open
   branches that read an unreachable ladder as a clean change.

   A single file over `PER_FILE_LIMIT` is still bounded, with the marker from
   `publishing.trim` inside what the ladder reads, and `MAX_FILES` replaces the
   bound the old whole-diff cut provided by accident.

---

## 10. The first commit

```
mkdir -p ~/tacoda/ghola && cd ~/tacoda/ghola
git init
git remote add origin https://github.com/tacoda/ghola.git
```

Then M0. The first pull request on ghola should be opened by ghola, on ghola,
from a spec in `specs/`, because a factory that has never built itself has not
been tested.
