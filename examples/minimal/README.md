# minimal

One turn per job. `run` and `publish`, nothing else.

```
cp examples/minimal/settings/*.yaml settings/
make pipeline        # read it before submitting
```

Pair it with a repository that needs no forge account, which is the rest of the
shortest path:

```toml
# repos.local.toml
[repos."/Users/you/code/scratch"]
forge = "local"
base  = "main"
```

Then:

```
make submit SPEC=specs/x.md REPO=/Users/you/code/scratch
```

The request lands in `.ghola/requests/` in that repository. Merge the branch to
land it, write under the comments marker to ask for a change.

## What it costs

One turn instead of four, and about a fifth of the tokens. What you give up is
in the comments at the top of `settings/pipeline.yaml`, and the one people are
surprised by is the revision loop: with no `on_refusal`, a repository whose
commit hook refuses gets a failed job rather than a second attempt.

## When to stop using it

The moment somebody other than you reads the diffs. `prove` and `review` are
opt-out rather than off in the built-in pipeline, because a factory that quietly
stopped checking is worse than one that never checked — and this configuration
is the "never checked" end on purpose.
