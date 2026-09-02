<!-- voice-register: informational -->
<!-- voice-english: ste -->

# The ladder

A constraint has a rung: the mechanism that carries it. Write "money is Decimal"
in `AGENTS.md` and you have rung 0, which is prose, and prose is a request. Write
a hook that refuses the write and you have rung 2, which is a guarantee. Same
rule, same words, different thing entirely.

Everything else in ghola is a pipeline you could write yourself. This is the
idea worth taking.

## The six rungs

| Rung | Carried by | What it can see |
|---|---|---|
| 0 | prose in the charter | nothing. It asks |
| 1 | the grant: what the phase may call | function ids, before any call |
| 2 | a hook on the tool call | the arguments, before the write lands |
| 3 | a callback inside the turn | the call, and it may hold it for a person |
| 4 | the delivery gate | the finished diff, before the commit |
| 5 | CI | the merged tree, after everybody left |

Two things follow, and both are the point.

**A rung is a place, not a strictness.** Rung 3 sees a function call, and a
shell command is one call whose contents it does not read. Rung 4 sees the diff
and never sees the call. Neither can see what the other sees, so a rule that
matters names both.

**Climbing costs something.** Rung 0 is free and enforces nothing. Rung 2 needs
a predicate somebody writes and maintains. Rung 5 catches everything, and it
catches it after everybody has gone home. Pick the cheapest rung that can
actually see the thing your rule is about.

## The other ladder

Capability climbs too, and in the opposite direction:

| Rung | Where it lives | Who gets it |
|---|---|---|
| 0 | described in prose | whoever reads it |
| 1 | the project | this repository |
| 2 | the team | every repository the team owns |
| 3 | the org | everybody |
| 4 | a tool | every agent, everywhere, by name |

The two ladders join at rung 1. A constraint withholds a function; a capability
grants one. `ladder::list` returns both, plus `withheld`, which is the list the
factory subtracts from a phase's grant before the turn starts.

## A primitive is two files with one name

`team/rules/no-secrets.md` is the rule. `team/rules/no-secrets.py` is the
predicate. The `.md` alone gives you rung 0. Add the `.py` and the same
primitive turns mechanical, and the ladder works out the rest:

- **kind** comes from the directory. `rules/` is a rule, `skills/` is a skill.
- **side** comes from the kind. A rule constrains; a skill is a capability.
- **layer** is the one thing you declare: `project`, `team`, or `org`.
- **rung** follows from the layer and from whether a script exists beside it.
- **direction** follows too. A rule with a predicate runs before the write and
  is feedforward. One without it can only be read afterwards.

So a primitive declares one field. Where you put the files decides the rest,
which is what stops a rule and its enforcement drifting apart. They are the same
primitive.

## Three mechanisms, three different questions

Do not confuse these. They sit in front of the same call and answer different
things.

- **`ladder`** decides what a rule says. Deterministic, and it refuses in the
  rule's own words.
- **`approval-gate`** decides what a person says. It holds the call and waits.
- **`opengantry`** decides what a machine can prove. It verifies rather than
  judging.

The oversight dial in `settings/oversight.yaml` changes how much of the second
one runs. It never turns the first one off, and `ask` never becomes `allow` at
any level.

## Running it

The ladder is its own worker, and it ships inside this repository at
`workers/ghola-ladder`. `make up` starts it with everything else:

```
make up
make call FN=ladder::list JSON='{"repo":"/path/to/repo"}'
```

It runs as a host process rather than as a sandboxed package worker, which is
what `path://` says in `worker-compose.yaml`. I tried the sandboxed form first,
and it puts a worker in a microVM that mounts only the worker's own source. The target repository does not exist inside that sandbox. So
the ladder read a `.agents/settings.json` that was not there, reported a
repository with no permissions, and looked exactly like a ladder enforcing
nothing. Anything that inspects a target repository has to run where that
repository is.

### It is a copy, and it is meant to be swappable

The ladder is the one idea here worth having without the rest of ghola, so it
also lives on its own at [tacoda/ladder](https://github.com/tacoda/ladder). That
is where it becomes a worker other projects install. The copy in this repository
exists so one clone is the whole thing.

Point `LADDER` at a checkout and that checkout serves instead:

```
git clone https://github.com/tacoda/ladder.git ../ladder
make up LADDER=../ladder
make status                  # names the provider that is serving
```

The seam is the function id rather than an import. Nothing in ghola imports the
ladder package: every caller triggers `ladder::list`, `ladder::evaluate`,
`ladder::move` or `ladder::explain` over the bus, and `ladder::gate` binds itself
to the harness's `pre-trigger` hook. So exactly one provider registers those ids,
and no call site changes when you swap, because there is no call site to change.

Keep that true if you edit either copy. A shortcut that imports the ladder
directly would weld the two together and take the swap away.

## What to ask it

```
make call FN=ladder::list     JSON='{"repo":"..."}'   # everything, both sides
make call FN=ladder::explain  JSON='{"repo":"...","id":"no-secrets"}'
make call FN=ladder::evaluate JSON='{"repo":"...","path":"x.py","content":"...","rung":3}'
make call FN=ladder::move     JSON='{"repo":"...","id":"no-secrets","move":"promote","to":3}'
```

`explain` answers the question people get wrong. Not "is this strict enough" but
"can the mechanism carrying it see the thing it is about".

`move` changes a file and commits nothing. A change to a primitive is a change
to a repository, and it goes through whatever that repository does with changes.

## Reading what it tells you

`ladder::list` reports `measured_share`: the fraction of primitives carried
somewhere a machine records what they caught. That number does not make
feedforward reliable. It makes the gap visible and counted, which is the whole
job.

Two numbers to watch in `make audit`:

- **Refusals per rung.** One rung catching everything is a signal about how your
  turns write, not an argument for tightening anything.
- **Rules that never fire.** A rule carried mechanically that has never fired is
  either settled or theatre. A rule carried at rung 0 cannot fire at all, so its
  silence tells you nothing, and ghola's improve lane reports the two cases
  separately for exactly that reason.
