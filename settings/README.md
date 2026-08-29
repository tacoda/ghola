# settings

**This directory is empty on purpose, and ghola runs exactly as well without
it.** Every file below is optional. Each one overrides a default that already
has a value in `workers/ghola-core/src/defaults.py`; none of them supplies
something that was otherwise missing.

Run `make config` to print the effective settings with each value tagged by
where it came from. A default nobody can see is a magic number, so that command
is the point of this design rather than a convenience.

`settings/` rather than `config/`, because `config/` belongs to iii's
`configuration` worker: that worker owns its directory and rewrites files in it.
Override this location with `GHOLA_SETTINGS`.

## The files

| File | Overrides | Arrives in |
|---|---|---|
| `phases.yaml` | models, thinking levels, turn caps, budgets, tool grants | M1 |
| `layers.yaml` | where org, team and project rules ship from | M3 |
| `pipeline.yaml` | the stage graph: what happens, in what order | M4 |
| `contracts/*.yaml` | how a phase's output is parsed and what invalidates it | M6 |
| `pricing.yaml` | fallback prices for models the router's catalogue prices at null | M4 |

## phases.yaml

Merged one level down over the built-ins, so setting one key keeps the rest of
that phase. A phase named here and not built in is simply added.

```yaml
defaults:
  model: claude-sonnet-5      # an id from `make models`, not a provider id
  thinking_level: medium
  max_turns: 50

phases:
  review:
    thinking_level: high      # `plan` keeps its built-in opus + high

  threat-model:               # a phase that does not exist built-in
    model: claude-opus-5
    prompt: prompts/threat-model.md
    functions:
      allow: ["coder::read-file", "coder::search", "engine::functions::info"]
```

Two things worth knowing before editing it.

**`functions.allow` is rung 1**, and it is the harness worker's own
deny-by-default policy rather than a convention. A function absent from the list
does not exist for that phase, so "checks do not repair" needs no predicate:
there is nothing to refuse and nothing to argue past.

**`functions` is replaced wholesale, not merged.** A phase that lists its own
tools means those, and not those plus the defaults. Rung 1 read as an accident
of merge order is how a check ends up holding an editor.

## The tools are not ghola's

The grants above name stock iii functions. `coder::*` and `shell::*` come from
the `shell` worker, the charter surfaces come from `directory`, and rung 1 works
the same over a function id whoever registered it. ghola registers no tools of
its own, which is why there is no tool list to configure here.
