<!-- voice-register: informational -->
<!-- voice-english: ste -->

# ghola

A starter kit for agentic systems on [iii](https://iii.dev). A spec goes in, a
pull request comes out, nothing merges itself. `README.md` is the tour and
`PLAN.md` is the phased plan. This file is what you need before changing
anything.

**This repository is a target repository like any other.** ghola reads
`AGENTS.md` and `.agents/` out of whatever repo you point it at. This is that
layout, applied to itself. `CLAUDE.md` and `.claude` are symlinks, so Claude
Code reads the same files and nothing is duplicated.

## Commands

```bash
make setup      # checks your tools, makes the venv, writes .env. Run this first
make test       # 675 tests, seconds, no engine, no money
make doctor     # what is missing, and which account gh is authenticated as
make config     # every effective setting, tagged with where it came from
make up         # engine, its workers, the ladder and ghola's callbacks
make down       # all of it, and wait for the ports to free
make help       # everything else, with a $ on every target that spends money
```

Run `make test` before every commit. It needs no engine and no key, so there is
no excuse to skip it.

## Layout

| Path | What is in it |
|---|---|
| `workers/ghola-core/` | the pure logic: charter, graph, jobs, prompts, contracts |
| `workers/ghola-factory/` | the stage graph, the actions, the improve lane |
| `workers/ghola-policy/` | the four callbacks around a turn |
| `workers/ghola-ladder/` | the constraint and capability ladder |
| `workers/ghola-audit/` | the append-only record |
| `settings/` | optional overrides. Empty is a working configuration |
| `prompts/` | one markdown file per phase, and the first thing to edit |
| `tests/` | `make test`. No fixtures beyond `tests/fixtures/` |

`config/` belongs to iii's `configuration` worker. That worker rewrites files in
it, so ghola's own settings go in `settings/`.

## Conventions

**Write the reason, not the rule.** Every module here says why it has the shape
it has, usually by naming the bug that gave it that shape. Restating the code in
a comment is noise. Naming what went wrong last time is the only reason the next
person leaves it alone.

**Keep the pure parts pure.** `charter.py`, `graph.py`, `forge.py` and the rest
of `ghola-core` take values and return values. The caller reads the files and
makes the calls. So a test can ask the whole state machine a question with two
dicts, which is why `make test` finishes in under a second.

**A failure says what to do.** An error string names the file, the setting or
the command that fixes it. `docs/LIMITATIONS.md` lists what this does badly, and
adding to it is part of shipping rather than an admission. I keep the fixed bugs
in there too, because a list of them tells you what kind of system this is.

**Never claim a rung you do not carry.** The ladder reports where each rule bites.
A rule sitting at rung 2 with nothing running beats no rule at all, but it is
worse than prose, because the report calls it covered.

## Testing

Name a test as a sentence. Put the bug it prevents in its docstring. Match what
is there: `test_a_non_zero_exit_is_a_failure` beats `test_run_2`, and it beats it
on the day it fails rather than the day you write it.

Leave one runnable check behind for any non-trivial logic: a branch, a parser, a
money path, a gate. A check that cannot fail is not a check, so break the thing
on purpose and watch it go red before you keep it.

## What not to do

Do not add a dependency for what the standard library already does. Do not
register a tool a turn can call: every tool belongs to a stock iii worker, and
that rule is what keeps this repository small. Do not put a target repository's
conventions in `settings/`. That directory says how work gets done.

Read `docs/LIMITATIONS.md` before you propose a fix for anything on it. Some of
that list is deliberate.
