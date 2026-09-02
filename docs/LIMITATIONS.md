<!-- voice-register: informational -->
<!-- voice-english: ste -->

# What ghola does not do

Read this first. Every item below is something ghola does badly, or not at all,
or only under conditions nobody wrote down until now. A tool with no stated
failure mode reads like a sales page, and you would find these anyway.

None of it is a promise to fix. Some of it is on purpose.

## Decisions, not gaps

**No upgrade path.** You clone this and it is yours. Nothing here tracks a
version, and nothing will migrate you when the built-in pipeline changes,
because a starter kit that owned your configuration would not be yours. Want a
later change? Read the diff and take the parts you want.

**No CLI.** `make` is the whole operator surface. A command you install goes
stale. Every target here is four lines of shell, and you can read all of them.

**No HTTP surface.** The iii console is the interface. A dashboard of ours would
be a second thing to maintain, and a worse trace view than the one already
running on port 3133.

**Nothing merges itself.** No configuration removes the pull request. Want a
factory that lands its own work? Wrong starting point. The gate is not a
setting, so there is nothing here to turn off.

**`ask` never becomes `allow`.** Not at `dark`, not anywhere. An unattended
factory that reads "ask" as "yes" has answered a question nobody put. When a
rule marked `ask` refuses work you want, the rule is what to change.

## Gaps, and how much they cost

**One machine.** The engine, the workers and the worktrees share one box. ghola
has no scheduler, no queue across hosts, and no way to run two factories
against one repository.

**A repository with a `prepare` command runs one job at a time, and the second
one fails rather than waiting.** `concurrency` in `repos.toml` defaults to 1,
and `prepare` counts the live jobs on that repository before it claims
anything. Over the limit, the job fails at its first stage, before any turn is
paid for, naming the job that holds the repository and the stage it is at.
Failing is not what you want; waiting is. Waiting needs a stage that can defer
itself and a reconciler to re-drive it, and neither exists. A repository with no
`prepare` command is not counted at all, because nothing was allocated for two
jobs to fight over.

**Cost reads `$0.00`.** The router prices some models at null, so
`session_cost_usd` comes back zero, which means the number in the job record and
in the audit log is not one you can bill anybody for. `settings/pricing.yaml`
takes fallback prices. Nobody has filled it in.

**Two forges, and one of them is a file.** `github` and `local` ship. GitLab,
Gitea and Bitbucket are each a `forges/<name>.py` away. Nobody has written one.
The seam is real and tested, and a seam with one production driver behind it is
still a seam with one production driver behind it.

**The `local` forge cannot tell you anything.** A file has no notifications, so
ghola says nothing when it reads your comment or finishes with the branch. You
find out by looking.

**A squash merge defeats the `local` forge.** That driver reads a merge as "the
branch is an ancestor of the base", and a squash leaves no ancestry. If you
squash, set the status to `closed` in the request file. Or use GitHub.

**Evals cost money and nothing runs them for you.** `make eval` is manual on
purpose, and nothing hooks it to a commit, to CI, or to a schedule, because a
gate nobody can afford to run is a gate people learn to skip. Run it before a
prompt change.

**The improve lane needs a record to read.** On a fresh clone it has an empty
audit log, so it finds nothing and says so. Give it a few weeks. It is useless
on day one and it will tell you that.

**`AGENTS.md` only, and no `.claude/` fallback.** ghola reads the standard and
the `.agents/` directory beside it. A repository still keeping its charter in
`CLAUDE.md` and its primitives in `.claude/` gets neither, and renaming both is
the whole migration. Symlink `CLAUDE.md -> AGENTS.md` and Claude Code keeps
working from the one file.

**Nested `AGENTS.md` files are not read.** The standard says the closest file to
the edited one wins, and ghola has no touched paths when it assembles the
charter, so it would be guessing which file applies or loading all of them into
every turn. A monorepo gets its root file. Put subproject instructions under
`.agents/` instead, where the directory names the concept.

**Prompts are the least tested thing here.** `prompts/*.md` is the easiest file
to change and the hardest to check. Two evals discriminate. The other four
phases have none, so a prompt edit is the change with the weakest net under it.

## Things that have gone wrong, and now cannot

Kept on purpose. A list of fixed bugs tells you what kind of system this is, and
what to watch for in the parts nobody has exercised yet.

- Harness 1.8.1 ignored a `pre-trigger` `deny`. `worker-compose.yaml` pins 1.8.7.
  A ladder on 1.8.1 looks wired and enforces nothing.
- `shell::exec` spawns a program and is not a shell. `git add -A && git commit`
  failed as a program name, and the commit silently never ran.
- `shell::exec` returns a non-zero exit in the payload rather than raising. A
  refused commit read as a success and disabled the revision loop.
- Two processes appended to the audit log. The chain failed its own
  verification while nothing had tampered with it. One worker owns it now, and
  every other worker asks that one.
- A turn ran with no filesystem scope, read the wrong repository's charter, and
  refused to edit anything because the repository it could see was not the one
  its instructions described.
- The improve lane's request template quoted its own comment heading, and a job
  reworked itself against its own document.
- `prompts/review.md` promised a `$diff` and nothing ever wrote one onto a job.
  A missing field renders empty, so the reviewer read a heading with nothing
  under it and a sentence saying it had seen the change. Every prompt is now
  checked against `prompts.FIELDS`, and the reviewer is handed the base ref
  instead.
- The delivery gate cut its input at 200,000 characters with no marker, read an
  unreachable ladder as "not refused", and read a failed `git diff` as an empty
  change. All three ended in a commit. It now returns a refusal and a problem
  separately, and only an empty pair commits.
- The delivery gate passed no path, and an empty path skips the path filter in
  both `Loaded.governing` and `gate.decide`. So every path-scoped rule was asked
  about every file in the change. It asks once per file now.

## Before you adopt this

If you have a working process and a team that follows it, this will not make it
faster. What it does is make an unattended process auditable, and that is worth
something to you only once some part of your process already runs unattended.

I would keep one part of this: the ladder. Everything else is a pipeline you
could write yourself. The rung is the idea.
