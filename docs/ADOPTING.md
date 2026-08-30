<!-- voice-register: informational -->
<!-- voice-english: ste -->

# Adopting ghola

Three steps. The shortest honest path runs all three against a repository nobody
else can see. Read [what ghola does not do](LIMITATIONS.md) before you start.

```
git clone tacoda_github:tacoda/ghola.git
git clone tacoda_github:tacoda/ladder.git
git clone tacoda_github:tacoda/audit-log.git
cd ladder && make install && cd ../audit-log && make install && cd ../ghola
make setup
```

Clone all three, side by side. `ladder` carries the rules and `audit-log` keeps
the record. Both run as host processes from their own checkouts, because one has
to see your repository and the other has to outlive the sandbox. `make up`
starts them if they are there.

If a sibling is missing, `make up` says so and keeps going. That is deliberate
for the ladder and dangerous for the record: without `audit-log` nothing is
written down, and `make up` prints `NOTHING WILL BE RECORDED`. Point `AUDITLOG`
or `LADDER` at another directory if you keep them somewhere else.

`make setup` checks your tools, builds the venv, writes `.env` from the example,
and creates an empty `repos.local.toml`. Then it tells you what is left to do.

## Step one: a key and a repository

Put your `ANTHROPIC_API_KEY` in `.env`. The provider workers read credentials
from the engine's own environment. Start the engine without the key and the
router serves no models, so every turn fails at `router::provider::resolve`
and nothing says why. The first time I hit this, the engine had the key in its
shell and not in its environment, and the router's fallback limit then capped a
million-token model at 8192 tokens.

Name a repository in `repos.local.toml`. Git ignores that file, and it beats
`repos.toml`, the tracked template that holds the examples.

Start with a scratch repository and no forge:

```toml
[repos."/Users/you/code/scratch"]
forge = "local"
base  = "main"
```

That needs no GitHub account, no token, and no slug. ghola writes the request
for review into `.ghola/requests/` in the repository itself. Merge the branch to
land it.

```
make up
make doctor      # what is missing, before you spend a turn finding out
make repos       # every target repository, and what is wrong with it
```

## Step two: one job

```
make submit SPEC=specs/document-the-ports.md REPO=/Users/you/code/scratch
make jobs
```

Watch it in the console at `http://127.0.0.1:3133`. The job plans, runs, proves,
reviews, commits through your repository's own hook, and opens the request. Then
it stops. Nothing merges itself.

Write a comment in the request file and ghola reworks the branch. Merge the
branch and ghola lands the job, then releases the worktree.

## Step three: make it yours

Now change something. In the order to reach for them:

1. **A prompt.** `prompts/plan.md` is what the planning turn gets asked. Editing
   it moves more than anything else here, and nothing checks it, so read
   [evals](EVALS.md) first.
2. **The pipeline.** Copy `examples/minimal/settings/pipeline.yaml` into
   `settings/` for one turn per job. Copy `examples/strict/` for every check
   plus a security read.
3. **The oversight dial.** `settings/oversight.yaml` runs from `manual` to
   `dark`, and ships at `supervised`.
4. **A rule.** Write it in the target repository's `CLAUDE.md`. Then read
   [the ladder](LADDER.md) and pick the rung that can see what it is about.

[The customization contract](CUSTOMIZING.md) lists everything that has a home,
and how to override each one.

## Moving to a real repository

Add a GitHub entry to `repos.local.toml`:

```toml
[repos."/Users/you/code/real-repo"]
slug = "you/real-repo"
base = "main"
```

Then check the thing that fails latest and hurts most:

```
make doctor
```

The identity that pushes and the identity that opens a pull request are not the
same thing. Your shell may push over an SSH alias while the `github` worker uses
whatever `GH_TOKEN` the engine started with. That mismatch surfaces at
`pr create`, after a job has already paid for a worktree, a plan, a run and two
checks. So `make doctor` asks the worker which account it is. Asking your shell
would answer a different question.

Put the token in `.env` as `GH_TOKEN`. Git tracks `config/github.yaml`, so that
file holds a reference and never a secret.

## What to expect in the first week

**Most of what goes wrong is a thing your repository wanted and never said.** A
convention that lives in somebody's head is a convention a turn cannot read.
Each one costs you a revision until somebody writes it down. Writing it down is
the work.

**The improve lane needs a record.** `make improve` reads the audit log and the
job records, then proposes what would have prevented whatever cost you
something. On a fresh clone it finds nothing and says so. Come back to it after
a few weeks.

**Budget for the commit hook.** A strict hook produces revisions rather than
failures. Check that `max_revisions` in `repos.toml` is high enough to let the
loop finish.

## When to stop

If your process already works and your team already follows it, ghola will not
make it faster. What it does is make an unattended process auditable, and that
is worth paying for only once some part of your process runs unattended.
