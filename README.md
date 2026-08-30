<!-- voice-register: informational -->

# ghola

*You clone it. You teach it. It remembers.*

**A starter kit for agentic systems on [iii](https://iii.dev).** Clone it,
configure it, point it at a repository. A spec goes in, a pull request comes out,
nothing merges itself.

iii is the framework. It ships the turn loop, the tools, git worktrees, the
GitHub client, the approval gate, durable queues and the console. ghola composes
thirty-one of its workers, and adds the conventions that wire them together.

I moved the constraint ladder out into its own worker,
[ladder](https://github.com/tacoda/ladder). It was the one genuinely general idea
in the pile, and a starter kit whose best idea is locked inside it is a worse
starter kit.

**Status: M8.** The whole lifecycle runs. A spec becomes a plan, a diff, a
proof, a review, a commit through your repository's own hook, and a pull
request. Comment on it and the job reworks. 518 tests, and the phased plan is in
[PLAN.md](PLAN.md).

**Start here:** [docs/ADOPTING.md](docs/ADOPTING.md) gets a pull request out of
a repository today. [docs/LIMITATIONS.md](docs/LIMITATIONS.md) says what this
does badly and what it refuses to do. Read that one first. It costs less.

## Usage

```
1. clone the repo          git clone … && cd ghola && make setup
2. add config and scripts  edit settings/, drop files in actions/
3. tell it to do work      make submit SPEC=specs/x.md REPO=../repo
```

Step 2 is optional. ghola runs on built-in defaults with an empty `settings/`,
which is what `make config` is for: it prints every effective setting tagged
with where it came from, so a default is never a magic number.
[examples/](examples/) holds two worked configurations at opposite ends of the
range.

Step 3 needs a repository named in `repos.local.toml`. The shortest version
needs no GitHub account at all:

```toml
[repos."/Users/you/code/scratch"]
forge = "local"     # no account, no token. The request is a file in the repo
base  = "main"
```

Once you have cloned this, it is yours. No upgrade path, and a starter kit works
that way on purpose rather than because I ran out of time.

## Running it

```
make setup      # checks your tools, makes the venv, writes .env. Run this first
make up         # engine, its workers, the ladder and ghola's callbacks
make status     # what is up
make down       # all of it, and wait for the ports to free

make submit SPEC=specs/x.md REPO=../some-repo SLUG=owner/name
make idea IDEA="a rough sentence" REPO=../some-repo   # refined into a spec first
make jobs       # every job, newest first
make turn PHASE=plan PROMPT="why is the queue slow?" WORKSPACE=../some-repo
make config     # the effective settings, and where each value came from
make models     # what the router can actually reach
make test       # 436 tests, seconds, no engine, no money
make help       # everything else
```

`make setup` writes `.env` for you; put your `ANTHROPIC_API_KEY` in it before
`make up`. The provider workers read their credentials from the **engine's**
environment, so an engine started without them serves a router with no models and
every turn fails at `router::provider::resolve` with nothing saying why.

`make doctor` checks your tools, the harness pin, your key and your `gh` login,
which is where the answer to "why did that fail" usually is.

Ports are 3131 (http), 3133 (console), 3132 (stream) and 49154 (worker manager),
off iii's stock numbers so a ghola engine runs beside another project's.

## What ghola does not write

The rule is that if a worker does it, ghola does not.

| Worker | What ghola therefore does not write |
|---|---|
| `harness` | the turn loop, transcript, retry, sub-agents, token budget |
| `ladder` | rules, layers, rungs, predicates, and the refusal in a rule's own words |
| `shell` | every tool. It owns `coder::*` too: read, search, tree, edit, exec |
| `worktree` | worktree lifecycle, the claim that stops two jobs racing, `land` |
| `github` | the forge: typed `pr`, `issue`, `run`, with read-vs-mutate gating |
| `approval-gate` | the human-in-the-loop hold, and its pending inbox |
| `eval` | A/B evaluation, its durable reports, and its console page |
| `directory` | the charter surfaces: skills, prompts, system prompts |
| `state`, `queue`, `cron`, `http`, `console` | the store, durable topics, scheduling, the surfaces |

**ghola registers no tools of its own.** What is left is the stage graph and the
briefs: which base ref, what happens in what order, when to land, and what the
pull request says.

A *forge* is whoever hosts your code and receives the pull request. Which one
you use is a setting rather than a fork. `github` and `local` ship, and a third
is a file in `forges/`. `local` is no forge at all, and the shortest path to
seeing this work.

## The idea

A constraint has a **rung**: the mechanism that carries it.

```
0  prose        stated in the rules, and nothing enforces it
1  tool grant   the phase was never handed the tool
2  hook         the repository's own hook refuses
3  in-turn      a callback refuses the call before the target runs
4  stage gate   the delivery gate, over the finished diff
5  CI           out of reach of both the agent and the factory
```

Each rung puts the rule further out of reach of what it constrains. It is served
by the `ladder` worker, which also carries capabilities on a second ladder joined
to this one at the grant, and the whole promote/demote/add/remove lifecycle.

```bash
iii trigger ladder::list
iii trigger ladder::move --json '{"id":"no-secrets","move":"carry","at":"delivery"}'
```

Everything a team would want to change is configuration:

| What differs between teams | Where |
|---|---|
| the flow of work in the factory | `settings/pipeline.yaml` |
| the development process in the harness | `settings/phases.yaml`, `prompts/` |
| how much a person watches | `settings/oversight.yaml` |
| project specifics | the target repo's own `CLAUDE.md` and `.claude/` |

## Oversight is a dial, not a switch

"Dark factory" is a useful phrase and a bad setting. Nobody wants a system where
no human sees anything, and nobody wants to approve every read either.

| level | a person answers | refuses without asking |
|---|---|---|
| `manual` | every call | nothing |
| `attended` | every write | reads run |
| `supervised` | only what a rule marks `ask` | the ladder, deterministically |
| `dark` | nothing | the ladder, and `ask` degrades to refuse |

**`ask` never becomes `allow`** at any level. An unattended factory reading "ask"
as "yes" has answered a question nobody put. Default is `supervised`, and a stage
may override it because `run` and `review` want different answers.

Extension is two mechanisms: drop a Python file in `actions/`, `guards/` or
`predicates/` and it is found by filename, or name any function id on the bus and
write it in whatever language you like.

## It reads its own record

```
make improve REPO=../some-repo   # what went wrong, and what would have helped
make proposals                   # what it staged
make accept RUN=abc123 N=0       # one proposal becomes a spec in specs/
```

The evidence is the audit log and the job records, not anyone's memory of the
week: a refusal, a revision, a question the spec did not answer, a check that
objected. Every proposal names the jobs it came from, and **one that cannot be
traced to evidence is dropped rather than repaired**. A clean record produces no
proposals, because a lane that always finds three things is a lane nobody
believes by the third time.

**Nothing is applied.** Accepting writes a spec into `specs/`, and that spec goes
through the same pipeline and the same pull request as any other work. The one
exception is a promotion or a demotion, which is one number in a file, handed to
`ladder::move`. The ladder commits nothing either. Otherwise the lane that
proposes changes to the charter would be the single thing here escaping the gate
everything else goes through.

## Documentation

| Page | Read it when |
|---|---|
| [docs/ADOPTING.md](docs/ADOPTING.md) | you want a pull request out of a repository today |
| [docs/GUIDE.md](docs/GUIDE.md) | you want the walkthrough, part by part |
| [docs/LADDER.md](docs/LADDER.md) | you are deciding where a rule belongs |
| [docs/CUSTOMIZING.md](docs/CUSTOMIZING.md) | you want to change something and need to know where it lives |
| [docs/EVALS.md](docs/EVALS.md) | you are about to edit a prompt |
| [docs/LIMITATIONS.md](docs/LIMITATIONS.md) | before any of it |

## Requirements

iii 0.22.1, Python 3.11+, `git`, and an authenticated `gh`. `iii.lock` pins
`harness` at 1.8.7, and that pin is load-bearing: on 1.8.7 a `pre-trigger` hook's
`deny` is honored, and on 1.8.1 it was ignored and the call ran anyway. A ladder
mounted on 1.8.1 looks wired and enforces nothing.

## License

MIT. See [LICENSE](LICENSE).
