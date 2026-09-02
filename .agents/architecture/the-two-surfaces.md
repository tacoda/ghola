# The harness and the factory

Two things, and knowing which one you are changing decides where the change
goes.

**The harness constrains one turn.** Six phases, each with its own model,
thinking level, turn cap and tool grant. Four callbacks around the turn, in
`workers/ghola-policy/src/callbacks/`. The prompts in `prompts/`. Change it in
`settings/phases.yaml`.

**The factory runs many turns to a diff.** A stage graph where every transition
is a durable queue message, so a crash resumes rather than restarts. A worktree
per job with a claim that stops two jobs racing for one checkout. A delivery
gate over the finished diff, then a pull request nothing can merge for you.
Change it in `settings/pipeline.yaml`.

A harness with no factory is a well-behaved agent you cannot get work through. A
factory with no harness runs unattended and cannot tell you what it was allowed
to do. That split is also how the improve lane sorts its proposals, in
`workers/ghola-core/src/proposals.py`.

## Where a change belongs

| You are changing | It goes in |
|---|---|
| what a phase is asked | `prompts/` |
| which model, or what a phase may call | `settings/phases.yaml` |
| what happens in what order | `settings/pipeline.yaml` |
| how much a person watches | `settings/oversight.yaml` |
| what the work must respect | the target repo's `AGENTS.md` and `.agents/` |

The last row is the one worth holding. `settings/` says how work gets done and
the repository says what the work must respect, so a rule about the code lives
with the code.
