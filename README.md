# ghola

A constraint ladder you can run. A spec goes in, a pull request comes out,
nothing merges itself.

ghola is an application on [iii](https://iii.dev). It owns no turn loop: a phase
of work is a turn on iii's `harness` worker, the settings say what that phase may
do, and ghola's own contribution is a handful of tools and four callbacks at the
seams the harness offers.

**Status: M0.** The engine boots and the workers are installed. Nothing runs a
job yet. The plan is in [PLAN.md](PLAN.md), and it is phased.

## The idea

A constraint has a **rung**: the mechanism that carries it.

```
0  prose        stated in the rules, and nothing enforces it
1  tool grant   the phase was never handed the tool
2  hook         the repository's own hook refuses
3  in-turn      a callback refuses the call before the target runs
4  stage gate   the delivery gate, over the finished diff
5  CI           on the pull request, out of reach of both agent and factory
```

Each rung puts the rule further out of reach of what it constrains. The rung is
one line of a rule's frontmatter, and moving it is one command.

Everything a team would want to change is configuration:

| What differs between teams | Where |
|---|---|
| the flow of work in the factory | `config/pipeline.yaml` |
| the development process in the harness | `config/phases.yaml`, `config/layers.yaml`, `prompts/` |
| project specifics | the target repo's own `CLAUDE.md` and `.claude/` |

Python is the escape hatch, not the interface. See [PLAN.md](PLAN.md) section 4.

## Running it

```
make engine     # the engine and its workers (foreground)
make status     # what is up
make stop       # all of it down, and wait for the ports to free
make test       # seconds, no engine, no money
```

Copy `.env.example` to `.env` and export it **before starting the engine**:

```
set -a; . ./.env; set +a
```

The provider workers read their credentials from the engine's own environment.
An engine started without them serves a router with no models, and every turn
fails at `router::provider::resolve` with nothing saying why. `make engine`
sources `.env` for exactly this reason.

Ports are 3131 (http), 3133 (console), 3132 (stream) and 49154 (worker manager)
rather than iii's stock 3111/3113/3112/49134, so a ghola engine runs beside
another iii project's.

## Requirements

iii 0.22.1, Python 3.11+, `git`, and an authenticated forge CLI (`gh` today).
`iii.lock` pins `harness` at 1.8.7, and that pin is load-bearing: on 1.8.7 a
`pre-trigger` hook's `deny` is honored, and on 1.8.1 it was ignored and the call
ran anyway. A ladder mounted on 1.8.1 looks wired and enforces nothing.

## License

MIT. See [LICENSE](LICENSE).
