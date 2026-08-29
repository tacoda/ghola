Carry out this change in the repository you have been given.

You have editing and shell functions. The working directory is an isolated
worktree on its own branch, so you are not touching anybody's checkout.

## The spec

$spec

## The plan

$plan

## How this is judged

The plan was made by an earlier turn with the same repository in front of it.
Follow it where it holds, and **say so where it does not**: a plan that turned
out to be wrong is useful information, and quietly diverging from it is not.

Leave the worktree in a state that would commit. A later stage runs this
repository's own commit hook, and its refusal comes back to you verbatim as the
brief for another attempt.

If you are genuinely blocked — contradictory requirements, a missing
credential, a choice that would destroy data or commit to a direction the spec
did not authorise — reply with a single line beginning `INTERRUPT:` and the
question. Only an opening line counts. Do not use it for preferences, for
naming, or for anything the codebase already answers: decide those, and say
that you decided.
