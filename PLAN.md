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

### The thesis

A constraint has a **rung**: the mechanism that carries it. Prose that nobody
enforces is rung 0. A tool the phase was never handed is rung 1. The repository's
own hook is rung 2. A callback in front of every call the model makes is rung 3.
The delivery gate over the finished diff is rung 4. CI is rung 5. Each rung puts
the rule further out of reach of the thing it constrains, and the rung a rule
sits on is a number in one line of its frontmatter.

That is the idea worth sharing, and a factory is what proves it. A ladder nobody
runs work through is a diagram.

### Non-goals

- **Not a merge bot.** ghola opens a pull request and stops. A human merges.
- **Not a model.** ghola owns no turn loop, no transcript, no token budget, no
  provider client. Those are iii workers.
- **Not a hosted service.** One operator, one machine, `git` and a forge CLI.
- **Not a replacement for CI.** Rung 5 is the repository's own, and ghola cannot
  reach it. That is the point of rung 5.
- **Not a coding agent.** The agent is `harness`. ghola is what constrains it and
  what carries its output to a pull request.
- **Not multi-tenant.** One namespace, one operator's credentials, one queue.

### License and remote

MIT. Remote is `tacoda_github:tacoda/ghola.git`. Everything in `config/`,
`rules/`, and `prompts/` is tracked; nothing under `state/`, `runs/`, or `.env`
is.

---

## 2. The domain model

Six concepts, carried over from wipp unchanged, because they earned their shape
against real repositories.

| Concept | What it is | Where it lives |
|---|---|---|
| **Spec** | The input of record. Markdown, one file, in git. | `specs/<slug>.md`, media in `specs/media/<slug>/` |
| **Job** | One spec moving through the pipeline against one target repo. | `state/jobs/<id>.json` |
| **Phase** | A kind of turn: what model, what thinking level, what functions. | `config/phases.yaml` |
| **Turn** | One `harness::send` and the `harness::turn-completed` that answers it. | the framework's, not ours |
| **Rule** | A constraint, with a layer, one or more rungs, and a policy. | one markdown file with frontmatter |
| **Proposal** | A staged change to the charter, the harness, or the factory. | `state/proposals/<id>.json` |

### The job lifecycle

A job's states are not a fixed enum in ghola. They are derived from the stage
graph in `config/pipeline.yaml` plus one terminal set the graph declares. The
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

Nothing is applied. Accepting a proposal writes a spec and stops, except a
promotion or demotion, which is one number and becomes a pull request directly.

---

## 3. The three kinds of thing

The test for which is which: **a number or a name is settings, a judgment is a
callback, and everything else belongs to the framework.**

| | What it is | Where |
|---|---|---|
| **the framework** | turn loop, transcript, token budget, provider, sub-agents, queue, HTTP, cron, console | installed iii workers |
| **the settings** | models, thinking levels, turn caps, budgets, tool grants, the stage graph, the layers, the prompts | `config/*.yaml`, `ghola.yaml`, `repos.toml` |
| **our code** | the tools iii does not ship, and four callbacks at the seams the harness offers | `workers/ghola-policy` |

A change that is neither a setting nor a judgment means logic has crept back into
a script, and that is the review question for every pull request on this repo.

### The framework workers ghola composes

Installed, never edited, never wrapped:

`harness` (>= 1.8.7, pinned), `session-manager`, `context-manager`, `llm-router`,
`provider-anthropic`, `provider-openai`, `queue`, `http`, `state`, `cron`,
`configuration`, `console`, `iii-observability`, `iii-worker-manager`, `shell`.

The harness version pin is not cosmetic. On `harness` 1.8.1 the `pre-trigger`
hook fired and its `deny` was ignored: the call ran anyway. A ladder mounted on
1.8.1 looks wired and enforces nothing. **M1 ships a test that asserts a denial
is honored, not merely delivered.**

### The workers ghola writes

Four, and there is no fifth:

| Worker | What it owns |
|---|---|
| `workers/ghola-factory` | The pipeline: HTTP surface, worktrees, git, the forge, the job store. Interprets the stage graph. Starts turns; never runs one. |
| `workers/ghola-policy` | What this repo contributes to a turn: `ghola::tool::*`, and the four callbacks carrying the ladder. Holds no session state. |
| `workers/ghola-core` | The contract between them, plus the pure decision functions: the ladder, the phase settings, the graph interpreter, the cost table, the output parsers. No I/O. |
| `workers/ghola-eval` | Runs a phase against a fixture set and scores it. The only thing here that measures an agent rather than constraining one. See section 4.9. |

`ghola-core` is where the tests live, because every decision in ghola is written
as a pure function of two dicts. wipp proved this is worth doing: its PR gate is
`derive_action(job, pr) -> action`, and every branch is testable without a pull
request.

---

## 4. The customization contract

This is the section that makes ghola different from wipp, and the section most
likely to be wrong on the first attempt.

Three things differ between teams, and each gets its own surface:

| What differs | Surface | Who owns it |
|---|---|---|
| the flow of work in the factory | `config/pipeline.yaml` | the operator running the factory |
| the development process in the harness | `config/phases.yaml`, `config/layers.yaml`, `prompts/` | the team |
| project specifics | the target repo's `CLAUDE.md`, `.claude/`, and its `.ghola/pipeline.yaml` | the project |

Configuration is the preferred surface. A Python script is the escape hatch, and
every escape hatch is a named directory that ghola discovers by convention. There
is no plugin registry and no entry-point mechanism, because a plugin system is a
second framework and iii is already the framework.

### 4.1 The flow of work: `config/pipeline.yaml`

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

### 4.2 The development process: `config/phases.yaml`

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

### 4.4 Layers: `config/layers.yaml`

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

### 4.5 Output contracts: `config/contracts/`

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

### 4.7 The forge: `config/forge.yaml`

wipp assumes `gh`. That is one line of assumption spread over about forty call
sites. ghola names it:

```yaml
forge:
  driver: github            # forges/github.py
  marker: "<!-- ghola -->"  # how ghola tells its own comments from a reviewer's
```

A driver is a module with six functions: `default_branch`, `open_pr`,
`view_pr`, `comment`, `line_comments`, `reply`. GitHub ships. GitLab and a
plain-git no-forge driver are the proof that the seam is real, and they are M8
work, not M0 work.

### 4.8 Evals: `evals/` and the `ghola-eval` worker

A rule decides. An eval measures. They are different instruments and the plan
kept confusing them until this section existed: wipp names `eval` as a kind that
belongs at any layer, "a measurement, for what no rule can decide," and then
ships none.

**Every step where an agent produces something gets an eval.** A test asserts
that `derive_action` returns `rework` for a commented PR. An eval asks whether
the `review` phase actually finds the bug that is in the diff. The first is
deterministic and runs in milliseconds. The second costs tokens, varies between
runs, and is the only way to know that a prompt edit made things worse.

#### The shape of a case

An eval case is a directory. No registration, same convention as everything else:

```
evals/
  review-catches-float-money/
    case.yaml           what to run and what counts as passing
    repo/               a fixture repository, or a git URL and a ref
    spec.md             the spec the phase is handed, when the phase needs one
    diff.patch          the input under test, when the phase reads a diff
    expect.md           prose describing the correct answer, for a judge grader
```

```yaml
# evals/review-catches-float-money/case.yaml
phase: review
runs: 5                      # variance is the measurement, not noise to hide
graders:
  - kind: contract           # did it obey the output contract at all
    contract: verdict
  - kind: expect_value
    field: verdict
    equals: concerns
  - kind: contains
    any: ["float", "rounding", "Decimal"]
  - kind: judge              # a model grades against expect.md
    model: claude-opus-5
    threshold: 0.8
thresholds:
  pass_rate: 0.8             # 4 of 5 runs, and the run-to-run spread is reported
  max_cost_usd: 0.50
```

#### The graders

Four ship, and they are ordered by how much I trust them:

| Grader | What it does | Deterministic |
|---|---|---|
| `contract` | the output parses against `config/contracts/<name>.yaml` | yes |
| `expect_value` | a parsed field equals, or is in, an expected set | yes |
| `contains` / `not_contains` | a regex or literal over the turn's text | yes |
| `judge` | a model scores the output against `expect.md` | no |

`judge` is last on purpose. A model grading a model is the weakest evidence in
the file, so it carries a threshold rather than a verdict, and a case that can be
graded deterministically must not use it. **The eval report states which graders
decided each case**, because a suite that is 90 percent judge is measuring
agreement, not correctness.

#### Extending it

A user's own grader is a Python file, discovered by filename like every other
escape hatch:

```
graders/no_secret_in_output.py   ->   - kind: no_secret_in_output
```

```python
def grade(case: dict, result: dict) -> Score:
    """Return Score(passed: bool, value: float, why: str). Pure, no I/O."""
```

The `ghola-eval` worker registers `ghola::eval::run`, `ghola::eval::list`, and
`ghola::eval::report`. It is a worker rather than a script for one reason: a
team's eval suite is their own, it lives in their own repository, and a worker is
how iii lets a capability be added without editing what is already there. A team
points `config/evals.yaml` at their directory and their graders, and ghola runs
them without knowing anything about the cases.

```yaml
# config/evals.yaml
suites:
  - ./evals                    # ghola's own
  - ~/.ghola/team-evals        # the team's, wherever they keep it
graders: [./graders]
defaults:
  runs: 3
  max_cost_usd: 1.00
report: state/evals/           # one JSON per run, plus a markdown summary
```

#### What evals are for, and what they are not

- **They gate prompt and phase changes, not jobs.** No eval runs inside the
  pipeline. A job that waited on a five-run eval would cost five turns and tell
  the operator nothing about that job.
- **They are the regression test for `prompts/`.** A prompt is the easiest file
  in this repository to change and the only one with no other check on it.
- **They report a rate and a spread, never a pass.** A case that passed 4 of 5
  runs is a case that fails 20 percent of the time, and rounding that to green is
  how a suite stops being evidence.
- **They cost money, so they are opt-in per run.** `make eval` runs everything;
  `make eval CASE=review-catches-float-money` runs one. Nothing runs them on a
  timer until somebody asks for that.

The honest limit: I have not run these yet. Every threshold in this section is a
guess until a suite has run against a real phase, and the first thing M6 should
do is replace the guessed numbers with measured ones.

### 4.9 Everything else

`ghola.yaml` holds ports, paths, and the harness pin. Environment variables
(`GHOLA_*`) override single values for a run and are documented in
`.env.example`. Nothing reads an environment variable that does not also have a
config key, because a setting reachable only through the environment is a setting
nobody can see.

---

## 5. Repository layout

```
ghola.yaml                      ports, paths, the harness pin
worker-compose.yaml             the workers, and the project namespace
repos.toml                      what ghola knows about each target repo
Makefile                        the operator's surface

config/
  pipeline.yaml                 the stage graph            (flow of work)
  phases.yaml                   models, grants, budgets    (development process)
  layers.yaml                   where rules ship from
  forge.yaml                    the forge driver
  contracts/*.yaml              output contracts
  evals.yaml                    where eval suites and graders are found
  <stock-worker>.yaml           one file per iii worker, owned by `configuration`

prompts/*.md                    one per phase
rules/{org,team}/*.md           the rules that travel
predicates/{org,team}/*.py      one pure function each
actions/*.py                    custom stage actions       (escape hatch)
guards/*.py                     custom stage guards        (escape hatch)
parsers/*.py                    custom output parsers      (escape hatch)
graders/*.py                    custom eval graders        (escape hatch)
forges/*.py                     forge drivers

evals/<case>/                   case.yaml, a fixture repo, expect.md

workers/
  ghola-core/                   pure decisions, no I/O. Most tests live here.
  ghola-factory/                the pipeline, the graph interpreter, the store
  ghola-policy/                 tools and the four callbacks
    src/callbacks/
      pre_generate.py           the charter                          (rung 0)
      pre_trigger.py            the ladder                        (rungs 2, 3)
      post_trigger.py           what a call did, on the job's log
      post_generate.py          the verdict guard
  ghola-eval/                   runs a phase against a case, scores it

specs/                          the input of record, in git
scripts/                        operator scripts, each with a --check self-test
state/                          jobs, logs, proposals, evals    (gitignored)
runs/                           worktrees, left after a failure (gitignored)
dashboard/index.html            one file, no build step
tests/
  test_*.py                     pure and worker tests      (make test)
  live/test_*.py                framework contract tests   (make test-live)
docs/                           architecture, adoption, the ladder, evals
```

Convention over wiring: every tool in `tools.TOOLS` registers as
`ghola::tool::<name>`, every module in `callbacks/` binds to the hook point its
filename names, and every module in `actions/`, `guards/`, and `parsers/` is
addressable by its filename. `boot.py` walks all of them, so there is no list to
keep in step.

---

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

**Verify:** `make engine` comes up, `make call FN=router::models::list` returns a
non-empty catalogue, `make stop` frees every port.

### M1. One turn, through the seam

- `ghola-policy` with `boot.py`, the four callbacks as no-ops, and the read-only
  tools.
- `ghola-core`: `phase_settings.py` reads `config/phases.yaml` and merges over
  defaults.
- `make turn PHASE=plan PROMPT="..." WORKSPACE=../repo` runs one turn and prints
  the turn's own words and what it cost.
- `ghola-eval` in its thinnest form: read a case, run its phase, apply the three
  deterministic graders, write a report. The `judge` grader waits for M6, when
  there are contracts worth judging against. One real case ships with it, because
  an eval runner with no case has not been shown to run.

**Verify:**
1. `test_pre_trigger_deny_is_honored` — a `pre-trigger` returning
   `{decision: "deny"}` means the target function is never entered. This is the
   1.8.1 regression test, and it fails loudly on an unpinned harness.
2. A phase given no `read_file` cannot read a file, proving rung 1.
3. Hook trigger types are bound by the **hyphenated** names the worker emits
   (`harness::hook::pre-trigger`). Underscore bindings register without error and
   never fire, which is a ladder that looks wired and is not.

### M2. The charter reaches the turn (rung 0)

- `pre_generate` assembles the target repo's `CLAUDE.md`, `.claude/rules`,
  skills, commands, and sub-agent definitions for the paths this turn has
  touched, and returns them as a system prompt mutation.
- `@path` imports in `CLAUDE.md` are followed.
- `config/layers.yaml` resolves org, team, and project rule directories.

**Verify:** a house rule stated only in a target repo's `CLAUDE.md` changes the
turn's behavior, and a repo with no `.claude` directory still receives the team
and org rules. That last one is what makes them standards rather than suggestions.

### M3. The ladder (rungs 1 through 3, and holds)

- Rule parsing, the three axes, layer resolution, and adaptation by id with
  `locked: true` refusing it.
- `pre_trigger` loads the rules for the touched paths, runs the predicate, and
  refuses in the rule's own words.
- The target repo's `.claude/settings.json` `permissions` honored at two rungs:
  `Bash` names a whole tool and is withheld (rung 1); `Bash(php *)` names an
  argument and is refused (rung 2). `ask` subtracts like `deny`, because an
  unattended factory reading "ask" as "yes" has answered a question nobody put.
- `policy: ask` parks the call. `ghola holds`, `ghola approve`, `ghola deny`.
  `ask` works only at rung 3, because `pre-trigger` is the one hook that may hold.
- The single-writer refusal: a write while a child of this turn is still running
  is refused, because `harness::spawn` is fire-and-forget and a child inherits the
  parent's filesystem root.

**Verify:** each of ghola's own six rules fires at its declared rung against a
fixture; a matcher test proves `make test && php artisan migrate` does **not**
match `php *` and is not refused, because parsing shell to guess would make the
predicate a different rule wearing this one's authority.

### M4. The factory and the graph

- `ghola-factory`: HTTP surface, the job store as JSON files, worktree
  management, prepare and cleanup, the progress log.
- `ghola-core/graph.py`: the stage graph interpreter. `next_stage(job, graph,
  result) -> transition` is a pure function.
- Job state derived from the graph. Every transition a durable queue message.
- The dashboard, driven by the graph rather than a hardcoded rail.

**Job records are files.** wipp used the stock `state` worker until it restarted
mid-run and took a live job with it. A store whose disappearance loses work is
the wrong trade for a factory that runs unattended, and `cat state/jobs/<id>.json`
is a debugging tool.

**Verify:** `test_graph_reaches_every_stage` walks the shipped graph and asserts
every stage is reachable and every terminal state is declared; a job killed
between two stages resumes on restart; a stage delivered twice does the work once.

### M5. Delivery (rung 4, the PR, the gate)

- The commit gate: rung-4 predicates over the finished diff **and over what the
  job is about to publish**, which is neither written by a tool nor part of any
  diff.
- The target repo's own pre-commit hook runs, and its refusal becomes the next
  brief verbatim, bounded by `max`, ending early on an identical refusal.
- `open_pull_request` through the forge driver.
- `watch_pull_request`: merge lands, close closes, comment reworks onto the same
  branch and PR with a reply under it. Line comments read from the endpoint
  `gh pr view` omits.

**Verify:** `derive_action(job, pr) -> action` is pure, and every branch of the
gate is tested without a pull request. Effects live outside it.

### M6. The checks

- `prove`: runs the software against the spec's acceptance criteria, denied every
  editing tool at rung 1. The worktree is checked afterwards and anything a check
  changed is reverted, because a shell can write whatever its tool list says.
- `review`: handed the spec and the diff and nothing else, never the executor's
  summary of its own work. Read-only tools. It never blocks.
- Contracts parsed from `config/contracts/`.
- Interrupts: `INTERRUPT: <question>` as the opening line stops the job, and the
  answer amends the contract. The checks are handed the spec **plus** the question
  and answer, or they grade correct work against a requirement that has been
  withdrawn. That is not hypothetical; prove returned `no` on exactly this in wipp
  before the fix. The authored spec file is never rewritten.

- The `judge` grader, and the six phase eval suites from section 7. This is where
  the guessed thresholds in section 4.8 get replaced with measured ones.

**Verify:** a `PROVEN: yes` with no command under any criterion downgrades to
`unproven`; an unparseable verdict records as `unreadable` and never as a pass.
Each phase suite has a case that passes and a case that fails, and `make eval`
reports a rate and a spread rather than a color.

### M7. The improve lane and the lifecycle

- `POST /improve` hands one turn everything that went wrong recently and asks
  what would have prevented it. Trouble is read broadly: a revision, a block, a
  `concerns` verdict, or a check touching the tree all count.
- Proposals name where, what, and what happens to it, plus the jobs they came
  from. Lanes are charter, harness, factory. Kinds and actions as wipp defines
  them, including `remove`, `promote`, and `demote`.
- The lifecycle CLI: `ghola rules`, `ghola rule ID=`, `ghola promote`,
  `ghola demote`, `ghola carry`, `ghola drop`, `ghola set-policy`,
  `ghola add-rule`, `ghola rm-rule`, `ghola new KIND=`.
- Every rung reachable, not only the promotion chain. Refusing to write rung 1,
  4, or 5 was never a policy in wipp; it sent people to a text editor where the
  generated hook does not follow the number.

What it refuses: a mechanical rung with no predicate, `ask` anywhere but rung 3,
dropping a rule's last rung, and a locked rule without `FORCE=1`.

**Verify:** a promotion to rung 2 writes the hook; a promotion to a mechanical
rung with no predicate produces a spec instead, because the missing half is the
work.

### M8. Adoption

- `ghola init` scaffolds a new factory: `config/`, `prompts/`, an empty rules
  directory, a `worker-compose.yaml`, and a `repos.toml` with one commented entry.
- A second forge driver, to prove the seam is a seam.
- An example directory with two contrasting configurations: a strict one with
  every check on, and a minimal one that is `run` and `publish` only.
- An example team eval suite outside this repository, pointed at by
  `config/evals.yaml`, proving a team's cases and graders need no fork.
- `docs/`: the ladder, the customization contract, adoption, evals, and an honest
  limitations page.

**Verify:** a person who has never seen this repo gets a pull request out of a
target repository, following the README only. If they cannot, the README is the
defect.

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
- **`config/layers.yaml` will meet a team with four layers.** They will have a
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

1. **Does the harness worker's `options.functions.allow` glob syntax cover
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
   worse than none. Ship the fallback table in `config/pricing.yaml`, mark what a
   cost was derived from as `cost_source`, and let the catalogue win whenever it
   is non-zero.
4. **Concurrency.** Nothing in wipp limits how many jobs prepare an environment at
   once, and a Dockerized repo's prepare allocates real ports. `repos.toml`
   carries a `concurrency` key in this plan; the semaphore that honors it is M4
   work and is not designed yet.
5. **Big diffs.** wipp truncates the review's input silently. ghola should refuse
   or chunk, and say which. Truncating a check's input without telling anyone is
   the same failure as a gate that fails open.

---

## 10. The first commit

```
mkdir -p ~/tacoda/ghola && cd ~/tacoda/ghola
git init
git remote add origin tacoda_github:tacoda/ghola.git
```

Then M0. The first pull request on ghola should be opened by ghola, on ghola,
from a spec in `specs/`, because a factory that has never built itself has not
been tested.
